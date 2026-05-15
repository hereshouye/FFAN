# -*- coding: utf-8 -*-
"""每日战报生成器: 数据 → HTML.

两种模式:
  plain — 仅事实, 不调 LLM (零成本, 离线)
  ai    — 调 llm_client.chat() 让模型用鹤哥口吻点评 (需配置 llm_config.json)

用法:
  python tools/daily_report.py                  # 自动选昨天, plain 模式
  python tools/daily_report.py 2026-05-13       # 指定日期
  python tools/daily_report.py 2026-05-13 --ai  # AI 模式
  python tools/daily_report.py --list           # 列出已生成的报告

输出:
  data/reports/daily_<YYYY-MM-DD>.html
"""
from __future__ import annotations
import json
import os
import sys
import re
import datetime as dt
from pathlib import Path

# 让 llm_client 能找到 (作为脚本被 PyInstaller / 直接调用都行)
sys.path.insert(0, str(Path(__file__).resolve().parent))
import llm_client


# ---------------------------------------------------------------------------
# 路径
# ---------------------------------------------------------------------------
def _data_dir() -> Path:
    env = os.environ.get("RANKPROBE_DATA_DIR")
    if env: return Path(env)
    return Path(__file__).resolve().parent.parent / "data"


def _bundle_root() -> Path:
    return Path(__file__).resolve().parent.parent


DATA = _data_dir()
GAMES_DIR    = DATA / "games"
ME_DIR       = DATA / "me"
REPORTS_DIR  = DATA / "reports"
PROFILES_JSON = DATA / "profiles.json"


# ---------------------------------------------------------------------------
# 数据加载
# ---------------------------------------------------------------------------
def _esc(s: str) -> str:
    return (str(s or "")
            .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace('"', "&quot;"))


def load_champion_titles() -> dict:
    """{cid: {name(title), alias}}"""
    candidates = [
        DATA / "_cache" / "assets" / "zh_cn" / "champion-summary.json",
        DATA / "assets" / "zh_cn" / "champion-summary.json",
        _bundle_root() / "bundle_defaults" / "assets" / "zh_cn" / "champion-summary.json",
    ]
    for p in candidates:
        if p.exists():
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                return {c["id"]: {"name": c.get("name",""), "alias": c.get("alias","")}
                        for c in d if c.get("id", -2) >= 0}
            except Exception: pass
    return {}


# 常见中文俗名 (bundle 只有 title, 这里补一层方便阅读)
CHAMP_COMMON_NAME = {
    "Kassadin":"卡萨丁", "Khazix":"卡兹克", "Karma":"卡尔玛", "Senna":"塞纳",
    "Soraka":"索拉卡", "Zyra":"婕拉", "Brand":"布兰德", "Milio":"米利欧",
    "Akali":"阿卡丽", "Zed":"劫", "Yasuo":"亚索", "Yone":"永恩",
    "Ahri":"阿狸", "Lulu":"璐璐", "Nami":"娜美", "Lux":"拉克丝",
    "MissFortune":"厄运小姐", "Ezreal":"伊泽瑞尔", "Caitlyn":"凯特琳",
    "Jinx":"金克丝", "Kaisa":"卡莎", "Vayne":"薇恩", "Aphelios":"厄斐琉斯",
    "Annie":"安妮", "Veigar":"维迦", "Syndra":"辛德拉", "Twisted Fate":"崔斯特",
    "TwistedFate":"崔斯特", "Lillia":"莉莉娅", "Zoe":"佐伊", "Neeko":"妮蔻",
    "Lucian":"卢锡安", "Varus":"维鲁斯", "Sett":"瑟提",
    "Pyke":"派克", "Thresh":"锤石", "Leona":"蕾欧娜", "Braum":"布隆",
    "Maokai":"茂凯", "Sion":"赛恩", "Mundo":"蒙多", "Garen":"盖伦",
    "Darius":"诺手", "Renekton":"鳄鱼", "Ornn":"奥恩",
    "Tahm Kench":"嘴霸", "TahmKench":"嘴霸", "Volibear":"狗熊",
    "Ksante":"卡桑特",
}


def display_champ(cid: int, titles: dict) -> dict:
    info = titles.get(cid) or {}
    alias = info.get("alias", "")
    title = info.get("name", "")
    common = CHAMP_COMMON_NAME.get(alias, "")
    return {
        "cid":    cid,
        "title":  title,
        "alias":  alias,
        "common": common or title or f"id={cid}",   # 主显示名
    }


def load_games_for_date(date_str: str) -> list[dict]:
    idx = GAMES_DIR / "_index.jsonl"
    if not idx.exists(): return []
    out = []
    with idx.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try:
                d = json.loads(line)
                if (d.get("ts") or "").startswith(date_str):
                    out.append(d)
            except Exception: continue
    out.sort(key=lambda r: r.get("ts",""))
    return out


def load_eog(gid) -> dict | None:
    p = GAMES_DIR / str(gid) / "eog.json"
    if not p.exists(): return None
    try: return json.loads(p.read_text(encoding="utf-8"))
    except Exception: return None


def load_recap(gid) -> dict | None:
    p = GAMES_DIR / str(gid) / "recap.json"
    if not p.exists(): return None
    try: return json.loads(p.read_text(encoding="utf-8"))
    except Exception: return None


def load_profiles() -> dict:
    if not PROFILES_JSON.exists(): return {}
    try: return json.loads(PROFILES_JSON.read_text(encoding="utf-8"))
    except Exception: return {}


def load_me() -> dict:
    p = ME_DIR / "summoner.json"
    if not p.exists(): return {}
    try: return json.loads(p.read_text(encoding="utf-8"))
    except Exception: return {}


# ---------------------------------------------------------------------------
# 加工: 把一局原始 eog → 结构化报告数据
# ---------------------------------------------------------------------------
def enrich_game(idx_row: dict, titles: dict, recap: dict | None) -> dict:
    gid = idx_row.get("game_id")
    eog = load_eog(gid) or {}
    teams = eog.get("teams") or []
    my_team = enemy_team = None
    for t in teams:
        if t.get("isPlayerTeam"): my_team = t
        else:                     enemy_team = t
    def render_team(team):
        rows = []
        max_killer = None
        for p in (team or {}).get("players") or []:
            stats = p.get("stats") or {}
            k = stats.get("CHAMPIONS_KILLED", 0)
            d = stats.get("NUM_DEATHS", 0)
            a = stats.get("ASSISTS", 0)
            ch = display_champ(p.get("championId") or 0, titles)
            row = {
                "is_me":  bool(p.get("isLocalPlayer")),
                "cid":    p.get("championId") or 0,
                "common": ch["common"], "alias": ch["alias"], "title": ch["title"],
                "k": k, "d": d, "a": a,
                "puuid": p.get("puuid",""),
            }
            rows.append(row)
            if (max_killer is None) or (k > max_killer["k"]):
                max_killer = row
        return rows, max_killer
    my_rows,  my_top    = render_team(my_team)
    en_rows,  en_top    = render_team(enemy_team)
    me_row = next((r for r in my_rows if r["is_me"]), None) or {}
    is_winning = bool((my_team or {}).get("isWinningTeam"))
    return {
        "gid":         gid,
        "ts":          idx_row.get("ts") or "",
        "time_hm":     (idx_row.get("ts") or "")[11:16],
        "duration_s":  idx_row.get("duration_s") or eog.get("gameLength") or 0,
        "is_winning":  is_winning,
        "result":      "胜" if is_winning else "负",
        "queue_type":  eog.get("queueType") or idx_row.get("queue_name") or "",
        "me":          me_row,
        "my_team":     my_rows,
        "enemy_team":  en_rows,
        "my_top_killer":  my_top,
        "enemy_top_killer": en_top,
        "recap":       recap,
    }


# ---------------------------------------------------------------------------
# 模板: HTML 框架 (静态)
# ---------------------------------------------------------------------------
CSS = """
:root{--bg:#0d0b1a;--bg2:#161028;--card:#1d1638;--card2:#251b48;--line:#2c2356;
  --pri:#b39dff;--phi:#d8c6ff;--teal:#48d1d1;--gold:#f0c75e;--txt:#e0d9f5;
  --dim:#8a82b0;--ok:#36e8a8;--bad:#ff6b8a;--orange:#ff8a4d}
*{box-sizing:border-box;margin:0;padding:0}
html,body{background:var(--bg);color:var(--txt);font-family:-apple-system,"PingFang SC","Microsoft YaHei UI","Segoe UI",sans-serif;font-size:14px;line-height:1.7}
body{padding:0 20px 60px}
.wrap{max-width:980px;margin:0 auto}
.hero{padding:50px 0 30px;text-align:center;border-bottom:1px solid var(--line);margin-bottom:30px}
.hero .badge{display:inline-block;padding:4px 12px;margin-bottom:14px;background:rgba(72,209,209,.1);color:var(--teal);border-radius:12px;font-size:12px;letter-spacing:1px}
.hero h1{font-size:34px;line-height:1.2;margin-bottom:10px;background:linear-gradient(120deg,var(--pri),var(--teal));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;color:transparent}
.hero .sub{color:var(--dim);font-size:14px}
.stats{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:30px}
.stat{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px;text-align:center}
.stat .num{font-size:28px;font-weight:700;color:var(--phi);line-height:1.1}
.stat .num.ok{color:var(--ok)} .stat .num.bad{color:var(--bad)}
.stat .label{color:var(--dim);font-size:11px;letter-spacing:1px;margin-top:6px}
section{margin:40px 0}
section h2{font-size:20px;margin-bottom:18px;padding-left:12px;border-left:4px solid var(--pri);line-height:1.4}
section h2 small{display:block;font-size:11px;color:var(--dim);font-weight:400;margin-top:3px}
.game{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:16px;margin-bottom:14px}
.game.win{border-left:3px solid var(--ok)} .game.loss{border-left:3px solid var(--bad)}
.game-head{display:flex;align-items:center;gap:14px;flex-wrap:wrap;margin-bottom:10px}
.game-time{color:var(--dim);font-size:13px}
.game-champ{font-size:16px;font-weight:600;color:var(--phi)}
.game-champ small{color:var(--dim);font-weight:400;font-size:12px;margin-left:4px}
.game-result{margin-left:auto;padding:3px 10px;border-radius:10px;font-size:12px;font-weight:700;letter-spacing:1px}
.game-result.win{background:rgba(54,232,168,.15);color:var(--ok)}
.game-result.loss{background:rgba(255,107,138,.15);color:var(--bad)}
.game-kda{color:var(--gold);font-family:Consolas,monospace;font-size:13px}
.game-reflected{background:rgba(72,209,209,.1);color:var(--teal);padding:1px 7px;border-radius:8px;font-size:10px;letter-spacing:.5px}
.game-reflected.frustrated{background:rgba(255,138,77,.15);color:var(--orange)}
.lineup{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:10px 0 0}
.lineup-side{font-size:12px}
.lineup-side .lbl{color:var(--dim);font-size:10px;letter-spacing:1px;margin-bottom:3px}
.lineup-side .row{color:var(--txt);line-height:1.6}
.lineup-side.mine{color:var(--phi)}
.lineup-side .me{color:var(--gold);font-weight:600}
.ai{background:linear-gradient(135deg,rgba(240,199,94,.07),rgba(240,199,94,.02));border-left:3px solid var(--gold);border-radius:0 6px 6px 0;padding:12px 16px;margin-top:12px;font-size:13px}
.ai-head{color:var(--gold);font-weight:600;font-size:12px;letter-spacing:1px;margin-bottom:6px;display:flex;align-items:center;gap:6px}
.ai-body{color:var(--txt);line-height:1.85}
.ai-body b{color:var(--phi);font-weight:600}
.ai-body .hi{color:var(--teal)}
.ai-body .stab{color:var(--orange);font-weight:600}
.placeholder{background:rgba(255,255,255,.02);border:1px dashed var(--line);border-radius:6px;padding:14px;color:var(--dim);font-size:12px;text-align:center;margin-top:12px;line-height:1.8}
.placeholder b{color:var(--phi)}
footer{margin-top:50px;padding-top:20px;border-top:1px solid var(--line);color:var(--dim);font-size:11px;text-align:center}
footer a{color:var(--teal);text-decoration:none}
@media (max-width:720px){.stats{grid-template-columns:repeat(2,1fr)}.lineup{grid-template-columns:1fr}.hero h1{font-size:26px}}
"""


def render_lineup_row(rows: list[dict], mine: bool) -> str:
    """渲染单边阵容. 我方高亮自己 (gold), 对方高亮 top killer (bad)."""
    parts = []
    top_k = max((r["k"] for r in rows), default=0)
    for r in rows:
        kda = f"({r['k']}/{r['d']}/{r['a']})"
        name = _esc(r["common"])
        if mine and r["is_me"]:
            parts.append(f'<span class="me">{name}{kda}</span>')
        elif (not mine) and r["k"] == top_k and top_k > 0:
            parts.append(f'<b style="color:var(--bad)">{name}{kda}</b>')
        elif mine:
            # 队友里有突出 carry
            if r["k"] == top_k and not r["is_me"] and top_k > 0:
                parts.append(f'<b style="color:var(--ok)">{name}{kda}</b>')
            else:
                parts.append(f"{name}{kda}")
        else:
            parts.append(f"{name}{kda}")
    return " · ".join(parts)


def render_game_card(g: dict, commentary_html: str = "") -> str:
    me = g["me"]
    champ = me.get("common", "?")
    title = me.get("title", "")
    alias = me.get("alias", "")
    sub = " · ".join(filter(None, [title, alias]))
    kda = f"{me.get('k',0)} / {me.get('d',0)} / {me.get('a',0)}"
    klass = "win" if g["is_winning"] else "loss"
    dur = g["duration_s"]
    dur_str = f"{dur//60}m{dur%60:02d}s"
    reflected = ""
    if g.get("recap"):
        mood = (g["recap"].get("mood") or "").lower()
        emoji = {"happy":"😊","frustrated":"😤","tilted":"🤯","neutral":"😐"}.get(mood, "📝")
        extra_cls = " frustrated" if mood in ("frustrated","tilted") else ""
        reflected = f'<span class="game-reflected{extra_cls}">{emoji} 已复盘</span>'
    cmnt = commentary_html or ""
    return f"""
    <div class="game {klass}">
      <div class="game-head">
        <span class="game-time">{_esc(g['time_hm'])}</span>
        <span class="game-champ">{_esc(champ)} <small>{_esc(sub)}</small></span>
        <span class="game-kda">{_esc(kda)}</span>
        {reflected}
        <span class="game-result {klass}">{g['result']} · {dur_str}</span>
      </div>
      <div class="lineup">
        <div class="lineup-side mine">
          <div class="lbl">我方</div>
          <div class="row">{render_lineup_row(g['my_team'], True)}</div>
        </div>
        <div class="lineup-side">
          <div class="lbl">对面</div>
          <div class="row">{render_lineup_row(g['enemy_team'], False)}</div>
        </div>
      </div>
      {cmnt}
    </div>
    """


def render_stats_block(games: list[dict]) -> tuple[str, dict]:
    wins   = sum(1 for g in games if g["is_winning"])
    losses = len(games) - wins
    wr = (wins * 100 // len(games)) if games else 0
    unique_champs = len({g["me"].get("cid") for g in games if g["me"]})
    stats = {"total": len(games), "wins": wins, "losses": losses,
             "wr": wr, "unique_champs": unique_champs}
    html = f"""
    <div class="stats">
      <div class="stat"><div class="num ok">{wins}</div><div class="label">胜</div></div>
      <div class="stat"><div class="num bad">{losses}</div><div class="label">负</div></div>
      <div class="stat"><div class="num">{wr}%</div><div class="label">胜率</div></div>
      <div class="stat"><div class="num">{unique_champs}</div><div class="label">不同英雄</div></div>
    </div>
    """
    return html, stats


# ---------------------------------------------------------------------------
# AI commentary 生成
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """你是鹤哥, 一个跟玩家开黑过 500 把的老哥.
你不是教练, 不是心理咨询师, 不是分析师, 不是 ChatGPT 客服.

## 1. 鹤哥怎么说话 (5 条样本, 模仿这个语感)

- "3 连了, 这把别 1v3, 心态再撑两把就裂"
- "0/20/3 还能赢, 你这把是脑子赢的, 数据是表象"
- "看出来你上头了, 关电脑, 下一把不会更好"
- "数据像保洁阿姨, 但你蹲草丛一波带走主 c, 不亏"
- "凌晨 1 点你还在打, 我对你的承诺保留态度"

## 2. 死亡禁令 (违反 = 输出无效)

- 不准用内部标签作为口语: "short_fuse" "carry_seeker" "tilt_profile" 这些是数据库字段, 不是话
- 不准用学术词: "认知资源" "教科书级" "情绪曲线" "心理资源耗尽" 这是论文不是聊天
- 不准戏剧化标题: "这不只是X，这是Y" "教科书级的崩塌" "致命信号" 鹤哥不写标题
- 不准超过 60 字一段. 鹤哥说话短, 一句话讲完一件事
- 不准说教结尾: "下次当你..." "请记住..." "这就是停手信号"
- 不准 emoji
- 不准客套: "辛苦了" "加油" "你能行"
- 不准说"你这把 0/20/3" — KDA 卡片上已经显示, 鹤哥不要重复数据

## 3. axes 内部标签 → 鹤哥人话翻译表

跟玩家说话时必须用右边, 不准用左边:

| 内部 | 人话 |
|---|---|
| short_fuse | 输了就急 |
| slow_burn | 慢慢憋着 |
| compartmentalized | 一局一重置 |
| immune | 心态稳 |
| carry_seeker | 想 carry |
| team_player | 跟团型 |
| supporter | 当辅助型 |
| challenger | 爱玩冷门 |
| aggressive | 压力下硬冲 |
| analytical | 输了想原因 |
| calm | 稳得住 |
| avoidance | 想跑 |
| caller | 爱指挥 |
| chatty | 话多 |
| silent | 闷头打 |
| reactive | 听指挥 |
| competitive | 上分型 |
| social | 跟朋友玩型 |
| mastery | 钻研型 |
| escape | 解压型 |

## 4. 输出格式 (必须合法 JSON)

字段及**上限**字数 (短为美, 不强制下限):

- intro: 开场 1 句, ≤ 60 字
- games: { "<gid>": "对该局点评 HTML 片段" } 每局 1-3 句, ≤ 80 字
- champ_portrait: 英雄池 1 段, ≤ 100 字
- mate_portrait: 队友 1 段, ≤ 100 字
- mind_portrait: 心态 1 段, ≤ 100 字
- summary: 总评分 3 个小段 "<b>做对了:</b>...<br><b>做错了:</b>...<br><b>下次:</b>..." 每段 ≤ 60 字

## 5. 允许的 HTML 标签 (只能用这几个)

- `<b>加粗</b>`
- `<br>换行`
- `<span class="hi">青色高亮</span>`
- `<span class="stab">橙色尖锐</span>`

不准用任何其他 class 或 HTML 元素. 不准发明 `.hege` `.jg` `.bd` 这种新 class.

## 6. 写作心法

1. 短 > 长. 长是论文, 短是聊天
2. 具体 > 抽象. "蹲下半野草丛" > "注意位置"
3. 调侃 > 说教. "你又上头了" > "建议保持冷静"
4. 站玩家这边. 数据烂可以说但底色支持: "数据像保洁但脑子在线"
5. 不重复用户已知信息. KDA / 胜负卡片上有, 不要复述

记住: 鹤哥是开黑老哥, 不是 ChatGPT 化妆版. 收到指令时默念这条三遍.
"""


def build_user_prompt(date_str: str, me: dict, games: list[dict],
                       profiles: dict, stats: dict) -> str:
    """凝练把所有数据塞给模型 (尽量短, 避免 token 浪费)."""
    payload = {
        "date":     date_str,
        "player":   me.get("gameName") or me.get("displayName") or "?",
        "stats":    stats,
        "games": [
            {
                "gid":         g["gid"],
                "time":        g["time_hm"],
                "champ":       g["me"].get("common"),
                "champ_title": g["me"].get("title"),
                "result":      g["result"],
                "duration_s":  g["duration_s"],
                "my_kda":      f"{g['me'].get('k')}/{g['me'].get('d')}/{g['me'].get('a')}",
                "my_team":     [{"c": r["common"], "kda": f"{r['k']}/{r['d']}/{r['a']}",
                                 "is_me": r["is_me"]}
                                for r in g["my_team"]],
                "enemy_team":  [{"c": r["common"], "kda": f"{r['k']}/{r['d']}/{r['a']}"}
                                for r in g["enemy_team"]],
                "recap":       (g.get("recap") or {}).get("free_text",""),
                "recap_mood":  (g.get("recap") or {}).get("mood",""),
                "recap_tags":  (g.get("recap") or {}).get("tags",[]),
            }
            for g in games
        ],
        "profiles": [
            {
                "puuid_head": pid[:12],
                "is_me":      pid == me.get("puuid"),
                "self_voice": (p.get("persona") or {}).get("self_voice",""),
                "peer_voices": (p.get("persona") or {}).get("peer_voices",[]),
            }
            for pid, p in profiles.items() if not pid.startswith("_")
        ],
    }
    return f"""请根据以下战报数据, 用鹤哥口吻输出 JSON 点评.

数据如下:
{json.dumps(payload, ensure_ascii=False, indent=2)}

输出要求:
1. games 字段里 key 必须是上面每局的 gid (字符串形式)
2. 在 recap 字段有内容的局, 点评要结合用户的复盘 (但不直接复述原文)
3. 鼓励多于批评, 但发现实质问题要直说
4. summary 部分必须包含: 真强项 / 真弱点 / 训练数据价值 / 接下来 30 局建议
"""


def parse_ai_response(raw: str) -> dict:
    """容错解析: 优先 JSON, 失败试找 JSON 块."""
    raw = raw.strip()
    # 去 markdown 代码围栏
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        return json.loads(raw)
    except Exception:
        # 找第一个 { ... } 块
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            try: return json.loads(m.group(0))
            except Exception: pass
    raise ValueError(f"AI 返回不是合法 JSON: {raw[:300]}")


def gen_ai_commentary(date_str, me, games, profiles, stats, cfg) -> dict:
    user = build_user_prompt(date_str, me, games, profiles, stats)
    raw = llm_client.chat(SYSTEM_PROMPT, user, json_mode=True,
                          max_tokens=8192, cfg=cfg)
    return parse_ai_response(raw)


# ---------------------------------------------------------------------------
# 渲染整体 HTML
# ---------------------------------------------------------------------------
def wrap_ai_block(head: str, body_html: str) -> str:
    return f"""
    <div class="ai">
      <div class="ai-head">🎙️ <span style="color:var(--gold)">鹤哥</span> · {_esc(head)}</div>
      <div class="ai-body">{body_html}</div>
    </div>
    """


PLACEHOLDER_AI = """
<div class="placeholder">
  <b>本节需 AI 模式才能生成专业点评</b><br>
  右下角 📊 → 选"AI 模式" → 配置 LLM endpoint + key → 重新生成
</div>
"""


def render_html(date_str: str, me: dict, games: list[dict], profiles: dict,
                ai: dict | None, mode: str) -> str:
    stats_html, stats = render_stats_block(games)
    player_name = me.get("gameName") or me.get("displayName") or "?"

    # 1. Hero
    hero = f"""
    <header class="hero">
      <div class="badge">FFAN 战报 · 大乱斗 ARAM/KIWI · 鹤哥 {'AI 智写' if mode=='ai' else '模板版'}</div>
      <h1>{_esc(date_str)} · {_esc(player_name)}</h1>
      <div class="sub">{stats['total']} 局 · {stats['wins']}胜{stats['losses']}负 · 胜率 {stats['wr']}% · {stats['unique_champs']} 个不重复英雄</div>
    </header>
    """

    # 2. 开篇总评
    intro_block = (wrap_ai_block("开局白话", ai["intro"])
                   if (ai and ai.get("intro")) else PLACEHOLDER_AI)

    # 3. 每局
    game_cards = []
    for g in games:
        cmt = ""
        if ai and ai.get("games"):
            v = ai["games"].get(str(g["gid"])) or ai["games"].get(g["gid"])
            if v:
                cmt = wrap_ai_block("这局白话", v)
        if not cmt and mode == "ai":
            cmt = wrap_ai_block("这局白话", "(AI 未返回该局点评)")
        game_cards.append(render_game_card(g, cmt))
    games_section = f"""
    <section>
      <h2>{stats['total']} 局详情 <small>从早到晚, 时间顺序</small></h2>
      {''.join(game_cards)}
    </section>
    """

    # 4. 英雄画像
    champ_section = f"""
    <section>
      <h2>英雄画像 <small>你昨天用的英雄揭示了什么</small></h2>
      <div class="lineup-side"><div class="row">"""
    for g in games:
        c = g["me"]
        champ_section += f'<div style="display:inline-block;margin:0 8px 8px 0;padding:6px 10px;background:var(--card);border:1px solid var(--line);border-radius:6px;font-size:12px"><b style="color:var(--phi)">{_esc(c.get("common","?"))}</b> <span style="color:var(--gold);font-family:Consolas,monospace">{c.get("k",0)}/{c.get("d",0)}/{c.get("a",0)}</span> <span class="{("game-result win" if g["is_winning"] else "game-result loss")}" style="padding:1px 5px;font-size:10px">{g["result"]}</span></div>'
    champ_section += "</div></div>"
    if ai and ai.get("champ_portrait"):
        champ_section += wrap_ai_block("英雄池白话", ai["champ_portrait"])
    else:
        champ_section += PLACEHOLDER_AI
    champ_section += "</section>"

    # 5. 队友画像
    mate_section = '<section><h2>队友画像 <small>你 + 常队友 + 路人</small></h2>'
    for pid, p in profiles.items():
        if pid.startswith("_"): continue
        persona = p.get("persona") or {}
        sv = persona.get("self_voice") or ""
        pv = persona.get("peer_voices") or []
        is_me = (pid == me.get("puuid"))
        tag_cls = "me" if is_me else "frequent"
        tag_txt = "你自己" if is_me else "队友"
        # 不展示 self_voice/peer_voices 原文 (尊重"去掉我写的内容"原则) — 这里给 AI 处理
        mate_section += f"""
        <div class="game" style="padding:12px 14px">
          <div style="display:flex;align-items:center;gap:8px;margin-bottom:6px">
            <span style="color:var(--dim);font-size:11px;font-family:Consolas,monospace">{_esc(pid[:12])}...</span>
            <span style="background:rgba({'240,199,94' if is_me else '72,209,209'},.12);color:var({'--gold' if is_me else '--teal'});padding:2px 8px;border-radius:10px;font-size:11px">{tag_txt}</span>
            <span style="color:var(--dim);font-size:11px;margin-left:auto">备注 {len(pv)} 条 + 自评 {'有' if sv else '无'}</span>
          </div>
        </div>
        """
    if ai and ai.get("mate_portrait"):
        mate_section += wrap_ai_block("4 人车队白话", ai["mate_portrait"])
    else:
        mate_section += PLACEHOLDER_AI
    mate_section += "</section>"

    # 6. 心态画像
    moods = {}
    for g in games:
        m = ((g.get("recap") or {}).get("mood") or "").lower()
        if m: moods[m] = moods.get(m, 0) + 1
    n_recap = sum(moods.values())
    mind_section = f"""
    <section>
      <h2>心态画像 <small>{n_recap} 份本地复盘的情绪信号</small></h2>
      <div style="display:flex;gap:14px;flex-wrap:wrap;margin-bottom:14px">
    """
    for m, label, color in [
        ("happy","😊 happy","var(--ok)"),
        ("neutral","😐 neutral","var(--dim)"),
        ("frustrated","😤 frustrated","var(--orange)"),
        ("tilted","🤯 tilted","var(--bad)"),
    ]:
        n = moods.get(m, 0)
        pct = (n * 100 // stats["total"]) if stats["total"] else 0
        mind_section += f"""
        <div style="flex:1 1 200px;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px">
          <h4 style="color:var(--phi);font-size:13px;margin-bottom:8px">{label} ({n} 份)</h4>
          <div style="height:8px;background:rgba(255,255,255,.05);border-radius:4px;overflow:hidden">
            <div style="height:100%;width:{pct}%;background:{color}"></div>
          </div>
        </div>
        """
    mind_section += "</div>"
    if ai and ai.get("mind_portrait"):
        mind_section += wrap_ai_block("情绪白话", ai["mind_portrait"])
    else:
        mind_section += PLACEHOLDER_AI
    mind_section += "</section>"

    # 7. 总评
    summary_section = "<section><h2>🎙️ 鹤哥总评 <small>白话诊断 · 训练价值 · 接下来怎么打</small></h2>"
    if ai and ai.get("summary"):
        summary_section += f'<div class="ai" style="background:linear-gradient(135deg,rgba(240,199,94,.12),rgba(240,199,94,.04));padding:18px 22px"><div class="ai-body" style="font-size:14px;line-height:1.95">{ai["summary"]}</div></div>'
    else:
        summary_section += PLACEHOLDER_AI
    summary_section += "</section>"

    # Footer
    now_iso = dt.datetime.now().isoformat(timespec="seconds")
    mode_label = "AI 智写 (你的本地 LLM)" if mode == "ai" else "模板版 (无 AI 点评)"
    footer = f"""
    <footer>
      模式: {mode_label} · 生成于 {_esc(now_iso)} · 数据全部在本地, 不上传 ·
      <a href="https://github.com/hereshouye/FFAN">github.com/hereshouye/FFAN</a>
    </footer>
    """

    return f"""<!doctype html>
<html lang="zh"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>FFAN 战报 · {_esc(date_str)} · {_esc(player_name)}</title>
<style>{CSS}</style>
</head><body>
<div class="wrap">
{hero}
{stats_html}
{wrap_ai_block("开局白话", ai["intro"]) if (ai and ai.get("intro")) else (PLACEHOLDER_AI if mode != 'ai' else wrap_ai_block("开局白话", "(AI 未返回)"))}
{games_section}
{champ_section}
{mate_section}
{mind_section}
{summary_section}
{footer}
</div></body></html>
"""


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------
def generate(date_str: str, mode: str = "plain") -> Path:
    titles = load_champion_titles()
    me = load_me()
    profiles = load_profiles()
    idx_rows = load_games_for_date(date_str)
    if not idx_rows:
        raise ValueError(f"{date_str} 没有对局数据")

    games = []
    for r in idx_rows:
        recap = load_recap(r["game_id"])
        games.append(enrich_game(r, titles, recap))

    ai = None
    if mode == "ai":
        cfg = llm_client.load_config()
        if not cfg or not cfg.get("api_key"):
            raise RuntimeError("AI 模式但未配置 llm_config.json. 先在 UI 配置.")
        stats_html, stats = render_stats_block(games)
        try:
            ai = gen_ai_commentary(date_str, me, games, profiles, stats, cfg)
        except Exception as e:
            raise RuntimeError(f"AI 调用失败: {e}")

    html = render_html(date_str, me, games, profiles, ai, mode)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    out = REPORTS_DIR / f"daily_{date_str}.html"
    out.write_text(html, encoding="utf-8")
    return out


if __name__ == "__main__":
    import sys
    args = sys.argv[1:]
    if "--list" in args:
        if REPORTS_DIR.exists():
            for p in sorted(REPORTS_DIR.glob("daily_*.html")):
                print(p.name)
        sys.exit(0)
    date_str = None
    mode = "plain"
    for a in args:
        if a == "--ai":
            mode = "ai"
        elif re.match(r"^\d{4}-\d{2}-\d{2}$", a):
            date_str = a
    if not date_str:
        date_str = (dt.date.today() - dt.timedelta(days=1)).isoformat()
    try:
        out = generate(date_str, mode)
        # 用 sys.stdout.buffer 避免 Windows GBK 编码问题
        sys.stdout.buffer.write(f"[OK] 已生成: {out}\n".encode("utf-8"))
    except Exception as e:
        sys.stderr.buffer.write(f"[FAIL] {e}\n".encode("utf-8"))
        sys.exit(1)
