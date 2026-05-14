# -*- coding: utf-8 -*-
"""FFAN — 探针 + 服务 + 工具一体单文件 (Python 3.8+ 标准库, Windows).

启动:   python rankprobe_lite.py
打开:   http://127.0.0.1:6280

数据沿用 ./data/ 目录:
  data/_cache/assets/zh_cn/champion-summary.json    (官方英雄字典)
  data/_cache/assets/official_kiwi/kiwi_augments_official.json  (KIWI 海克斯字典)
  data/_cache/hex_recommendations/apexlol_data.json (apexlol 推荐)

「云朵」按钮 → 调 tools/cache_official_augments.py refresh
            + tools/cache_hex_recommendations.py refresh
            → 重读上述 JSON, 覆盖更新内存字典 (不删除字典本体).
"""

from __future__ import annotations

import base64
import ctypes
import ctypes.wintypes as wt
import datetime as dt
import gzip as _gzip
import json
import os
import queue
import re
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from socketserver import ThreadingMixIn

# ============================================================================
# 配置
# ============================================================================
# 区分开发模式 vs PyInstaller 冻结模式:
#   开发: ROOT = rankprobe_lite.py 所在目录
#   exe : ROOT = exe 所在目录 (data/web/tools 都是 exe 的兄弟目录)
if getattr(sys, "frozen", False):
    ROOT      = Path(sys.executable).resolve().parent
    BUNDLE    = Path(getattr(sys, "_MEIPASS", ROOT))  # 静态资源 (web/tools) 解包目录
else:
    ROOT      = Path(__file__).resolve().parent
    BUNDLE    = ROOT

DATA_DIR      = ROOT / "data"           # 用户数据: 永远在 exe 旁

# v1 (旧) 路径 — 兼容老 data/ 目录, 仅 migrate-v2 + 已迁移前的 fallback 使用
LEGACY_CACHE_DIR  = DATA_DIR / "_cache"
LEGACY_ASSETS_DIR = LEGACY_CACHE_DIR / "assets"
LEGACY_HEX_DIR    = LEGACY_CACHE_DIR / "hex_recommendations"

# v2 (新) 路径 — 按事务分目录, 见 ARCHITECTURE 部分
COACH_DIR       = DATA_DIR / "coach"
COACH_KB_DIR    = COACH_DIR / "kb"
COACH_SEEDS_DIR = COACH_DIR / "training_seeds"
ME_DIR          = DATA_DIR / "me"
GAMES_DIR       = DATA_DIR / "games"
PLAYERS_DIR     = DATA_DIR / "players"
ASSETS_V2_DIR   = DATA_DIR / "assets"
LEGACY_DIR      = DATA_DIR / "legacy"
CONTRIB_DIR     = DATA_DIR / "contributed"   # 用户主动贡献给作者的训练样本 (opt-in)

# 仍兼容老 ASSETS_DIR / HEX_DIR / CACHE_DIR 名字 (load_assets 等老代码用)
# layout 解析后 (_resolve_layout) 会指向 v2 或 v1
CACHE_DIR     = LEGACY_CACHE_DIR        # 老名字, 不再写, 留作 fallback
ASSETS_DIR    = LEGACY_ASSETS_DIR       # 老名字, _resolve_layout 后可指向 ASSETS_V2_DIR
HEX_DIR       = LEGACY_HEX_DIR
TOOLS_DIR     = BUNDLE / "tools"        # 工具: 打包进 bundle, 不变
WEB_DIR       = BUNDLE / "web"          # 前端: 打包进 bundle, 不变

# 数据 layout 版本 (写 data/_VERSION). v1 = 老 _cache + YYYY-MM-DD, v2 = 见迁移设计
DATA_VERSION = 2

# 把 tools/ 加进 sys.path, 让 cache_official_augments / cache_hex_recommendations
# 可以作为模块 import (PyInstaller 友好, 不再用 subprocess)
if TOOLS_DIR.exists() and str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

PORT          = int(os.environ.get("PROBE_PORT", "6280"))
PHASE_POLL    = float(os.environ.get("PROBE_PHASE_POLL", "5"))
CS_POLL       = float(os.environ.get("PROBE_CS_POLL", "3"))
WAIT_CLIENT   = float(os.environ.get("PROBE_WAIT_CLIENT", "8"))

# ============================================================================
# 1. Win32 LCU 进程发现 + HTTP 客户端
# ============================================================================
_TH32CS_SNAPPROCESS = 0x00000002
_PROC_QUERY_LIMITED = 0x1000
_PROC_CMDLINE_INFO  = 60
_INVALID_HANDLE     = wt.HANDLE(-1).value

try:
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _ntdll    = ctypes.WinDLL("ntdll", use_last_error=True)
except OSError:
    _kernel32 = _ntdll = None  # 非 Windows: probe 会一直停在等待客户端


class _PROCENTRY(ctypes.Structure):
    _fields_ = [("dwSize", wt.DWORD), ("cntUsage", wt.DWORD),
                ("th32ProcessID", wt.DWORD), ("th32DefaultHeapID", ctypes.c_void_p),
                ("th32ModuleID", wt.DWORD), ("cntThreads", wt.DWORD),
                ("th32ParentProcessID", wt.DWORD), ("pcPriClassBase", wt.LONG),
                ("dwFlags", wt.DWORD), ("szExeFile", wt.WCHAR * 260)]


class _USTRING(ctypes.Structure):
    _fields_ = [("Length", wt.USHORT), ("MaximumLength", wt.USHORT),
                ("Buffer", wt.LPWSTR)]


def _find_pids(name):
    if _kernel32 is None:
        return []
    snap = _kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if snap == _INVALID_HANDLE:
        return []
    pids = []
    try:
        e = _PROCENTRY(); e.dwSize = ctypes.sizeof(_PROCENTRY)
        if not _kernel32.Process32FirstW(snap, ctypes.byref(e)):
            return pids
        target = name.lower()
        while True:
            if e.szExeFile.lower() == target:
                pids.append(e.th32ProcessID)
            if not _kernel32.Process32NextW(snap, ctypes.byref(e)):
                break
    finally:
        _kernel32.CloseHandle(snap)
    return pids


def _cmd_line(pid):
    h = _kernel32.OpenProcess(_PROC_QUERY_LIMITED, False, pid)
    if not h:
        return ""
    try:
        size = wt.ULONG(0)
        _ntdll.NtQueryInformationProcess(h, _PROC_CMDLINE_INFO, None, 0, ctypes.byref(size))
        if size.value == 0:
            size.value = 8192
        buf = (ctypes.c_byte * size.value)()
        if _ntdll.NtQueryInformationProcess(h, _PROC_CMDLINE_INFO, buf, size.value,
                                            ctypes.byref(size)) != 0:
            return ""
        ucs = ctypes.cast(buf, ctypes.POINTER(_USTRING)).contents
        if not ucs.Buffer or ucs.Length == 0:
            return ""
        return ctypes.wstring_at(ucs.Buffer, ucs.Length // 2)
    finally:
        _kernel32.CloseHandle(h)


def get_auth():
    """返回 (token, port). 找不到客户端抛 RuntimeError."""
    for pid in _find_pids("LeagueClientUx.exe"):
        cmd = _cmd_line(pid)
        if not cmd:
            continue
        mt = re.search(r"--remoting-auth-token=([\w\-]+)", cmd)
        mp = re.search(r"--app-port=(\d+)", cmd)
        if mt and mp:
            return mt.group(1), mp.group(1)
    raise RuntimeError("LeagueClientUx.exe not running")


_SSL_CTX = ssl.create_default_context()
_SSL_CTX.check_hostname = False
_SSL_CTX.verify_mode = ssl.CERT_NONE


class LCU:
    def __init__(self, token, port):
        self.base = f"https://127.0.0.1:{port}"
        self.auth = "Basic " + base64.b64encode(f"riot:{token}".encode()).decode()

    def get(self, uri, timeout=10):
        req = urllib.request.Request(self.base + uri, method="GET")
        req.add_header("Authorization", self.auth)
        req.add_header("Accept", "application/json")
        try:
            with urllib.request.urlopen(req, context=_SSL_CTX, timeout=timeout) as r:
                raw = r.read()
                if not raw:
                    return None
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    return raw.decode("utf-8", errors="replace")
        except urllib.error.HTTPError:
            return None
        except Exception:
            return None


# ============================================================================
# 2. 全局状态 + 日志环
# ============================================================================
_state_lock = threading.Lock()
STATE = {
    "lcu_online": False,
    "phase": "",            # gameflow phase
    "ts": 0,                # last update
    "me": {                 # 当前召唤师 (LCU 实时)
        "puuid": "", "name": "", "tagLine": "", "level": 0,
        "profileIconId": 0, "tier": "", "division": "", "lp": 0,
        "wins": 0, "losses": 0, "wr": 0,
    },
    "my_champ_history": {},   # cid -> {games, wins, k, d, a}
    "mastery": {},            # cid -> points
    "champ_select": None,     # 见 _build_champ_select_payload
    "last_champ_select": None,  # 离开选人后保留, 用于复盘展示
}

_LOG_RING = deque(maxlen=600)
_log_lock = threading.Lock()

_subs_lock = threading.Lock()
_subs = []  # list of (Event, deque)


def push_log(line):
    line = line.rstrip("\n")
    if not line:
        return
    ts = time.time()
    rec = {"t": ts, "l": line}
    with _log_lock:
        _LOG_RING.append(rec)
    _broadcast("log", json.dumps(rec, ensure_ascii=False))
    try:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()
    except Exception:
        pass


def _broadcast(event, payload):
    msg = (event, payload)
    with _subs_lock:
        dead = []
        for ev, dq in _subs:
            try:
                dq.append(msg); ev.set()
            except Exception:
                dead.append((ev, dq))
        for d in dead:
            _subs.remove(d)


def _set_state(**kv):
    with _state_lock:
        STATE.update(kv)
        STATE["ts"] = time.time()


def _state_snapshot():
    with _state_lock:
        return json.loads(json.dumps(STATE, ensure_ascii=False))


# ============================================================================
# 3. 资产: champion-summary + apex 推荐 + KIWI 字典 (覆盖式刷新)
# ============================================================================
_RATING_SCORE = {"SSS": 6, "SS": 5, "S": 4, "A": 3, "B": 2, "C": 1, "D": 0}

# 这些 dict 是字典本体, 全程不替换, 只 .clear()+.update().
CHAMPIONS_BY_CID   = {}        # cid:int -> {name, alias, roles}
CHAMPIONS_BY_ALIAS = {}        # alias  -> cid:int
APEX_PER_CID       = {}        # str(cid) -> [{combo, tier, rating, tag, analysis}]
HEX_DICT           = {}        # name -> {tier, desc}
AUG_NAME           = {}        # aug_id_str -> name (KIWI)
PROFILES           = {}        # puuid -> {nickname, tags, carry_priority, ...}
PREMADE_SET        = set()     # frozenset({puuid_a, puuid_b}) 形式 (无序对)

_assets_lock = threading.Lock()


def load_profiles():
    """读 data/profiles.json (用户手写) -> PROFILES + PREMADE_SET. 覆盖式."""
    pf_path = DATA_DIR / "profiles.json"
    new_profiles, new_premade = {}, set()
    if pf_path.exists():
        try:
            data = json.loads(pf_path.read_text(encoding="utf-8"))
            for k, v in data.items():
                if k.startswith("_") or not isinstance(v, dict):
                    continue
                new_profiles[k] = v
                for buddy in (v.get("premade_with") or []):
                    if buddy and buddy != k:
                        new_premade.add(frozenset((k, buddy)))
        except Exception as e:
            push_log(f"[profiles] 解析失败: {e}")
    PROFILES.clear();    PROFILES.update(new_profiles)
    PREMADE_SET.clear(); PREMADE_SET.update(new_premade)


def load_assets(verbose=True):
    """覆盖式重读三份 JSON. 不替换 dict 本体, 只 clear+update."""
    with _assets_lock:
        # 1. champion-summary
        new_by_cid, new_by_alias = {}, {}
        cs_path = ASSETS_DIR / "zh_cn" / "champion-summary.json"
        if cs_path.exists():
            try:
                for c in json.loads(cs_path.read_text(encoding="utf-8")):
                    cid = c.get("id")
                    if cid and cid > 0:
                        new_by_cid[cid] = {
                            "name": c.get("name") or "",
                            "alias": c.get("alias") or "",
                            "roles": c.get("roles") or [],
                            "icon": c.get("squarePortraitPath") or "",
                        }
                        if c.get("alias"):
                            new_by_alias[c["alias"]] = cid
            except Exception as e:
                push_log(f"[assets] champion-summary 解析失败: {e}")

        # 2. apex.json
        new_apex, new_hex_dict = {}, {}
        ap_path = HEX_DIR / "apexlol_data.json"
        if ap_path.exists():
            try:
                ax = json.loads(ap_path.read_text(encoding="utf-8"))
                for alias, info in (ax.get("champions") or {}).items():
                    cid = new_by_alias.get(alias)
                    if not cid:
                        continue
                    syn = info.get("synergies") or []
                    ranked = sorted(
                        syn,
                        key=lambda s: _RATING_SCORE.get(
                            (s.get("rating") or "").upper().replace("级", "").strip(), -1),
                        reverse=True)
                    new_apex[str(cid)] = [{
                        "combo":    s.get("hex_names") or [],
                        "tier":     (s.get("hex_tiers") or [None])[0] or "",
                        "rating":   (s.get("rating") or "").upper().replace("级", "").strip(),
                        "tag":      s.get("tag") or "",
                        "analysis": s.get("analysis") or "",
                        "items":    s.get("recommended_items") or [],
                    } for s in ranked]
                for name, meta in (ax.get("hextech_details") or {}).items():
                    if isinstance(meta, dict):
                        new_hex_dict[name] = {
                            "tier": meta.get("tier") or "",
                            "desc": meta.get("description") or "",
                            "mech": meta.get("mechanism") or "",
                        }
            except Exception as e:
                push_log(f"[assets] apex.json 解析失败: {e}")

        # 3. KIWI augments
        new_aug = {}
        kp = ASSETS_DIR / "official_kiwi" / "kiwi_augments_official.json"
        if kp.exists():
            try:
                kd = json.loads(kp.read_text(encoding="utf-8"))
                for aid, row in (kd.get("augments") or {}).items():
                    if isinstance(row, dict) and row.get("name"):
                        new_aug[str(aid)] = row["name"]
            except Exception as e:
                push_log(f"[assets] KIWI 解析失败: {e}")

        # 覆盖式更新 (clear + update, 不替换 dict 本体)
        CHAMPIONS_BY_CID.clear();   CHAMPIONS_BY_CID.update(new_by_cid)
        CHAMPIONS_BY_ALIAS.clear(); CHAMPIONS_BY_ALIAS.update(new_by_alias)
        APEX_PER_CID.clear();       APEX_PER_CID.update(new_apex)
        HEX_DICT.clear();           HEX_DICT.update(new_hex_dict)
        AUG_NAME.clear();           AUG_NAME.update(new_aug)

    if verbose:
        push_log(f"[assets] 英雄 {len(CHAMPIONS_BY_CID)} · 海克斯推荐 {len(APEX_PER_CID)}"
                 f" · 海克斯说明 {len(HEX_DICT)} · KIWI {len(AUG_NAME)}")


# ============================================================================
# 4. 刷新: subprocess 调 tools/ 两个脚本, 完成后重读
# ============================================================================
_refresh_lock = threading.Lock()
_refresh_state = {"running": False, "ok": None, "ts": 0, "lines": []}
_IS_DEMO = False    # 由 main() 写入
_DEMO_OFF = False   # 预留: 真实模式探针接管后置 True


def _refresh_run():
    with _refresh_lock:
        if _refresh_state["running"]:
            return
        _refresh_state["running"] = True
        _refresh_state["ok"] = None
        _refresh_state["lines"] = []

    overall_ok = True

    # 1. KIWI augments (内置, 不依赖外部)
    push_log("[refresh] ▶ KIWI augment 字典")
    try:
        import cache_official_augments as _coa  # type: ignore
        data = _coa.build()
        push_log(f"[refresh] ◀ KIWI {data['meta']['count']} 条")
    except Exception as e:
        push_log(f"[refresh] KIWI 失败: {type(e).__name__}: {e}")
        overall_ok = False

    # 2. apex 海克斯推荐 (可能耗时 5+ 分钟)
    push_log("[refresh] ▶ apex 海克斯推荐 (耗时可达 5 分钟)")
    try:
        import cache_hex_recommendations as _chr  # type: ignore
        _chr.refresh_cache()
        push_log("[refresh] ◀ apex 完成")
    except Exception as e:
        push_log(f"[refresh] apex 失败: {type(e).__name__}: {e}")
        overall_ok = False

    load_assets(verbose=True)
    load_profiles()
    load_coach(verbose=False)
    load_psych_kb(verbose=False)
    push_log(f"[refresh] profiles {len(PROFILES)} · premade {len(PREMADE_SET)} · coach={COACH.get('name','?')} · psych KB {len(PSYCH_KB)}")
    # demo 模式下重建 STATE 以反映 profile 变更
    if STATE.get("lcu_online") and STATE.get("phase") == "ChampSelect" \
            and not _DEMO_OFF and _IS_DEMO:
        try: load_demo_state()
        except Exception as e: push_log(f"[refresh] demo 重建失败: {e}")
    with _refresh_lock:
        _refresh_state["running"] = False
        _refresh_state["ok"] = overall_ok
        _refresh_state["ts"] = time.time()
    _broadcast("refreshed", json.dumps({"ok": overall_ok, "ts": _refresh_state["ts"]}))
    _broadcast("state", json.dumps(_state_snapshot(), ensure_ascii=False))


# ============================================================================
# 5. 极简 AI 阵容分析
# ============================================================================
# 大乱斗模式: 只一条桥 · 持续团战 · 没有 lane/jungle 概念
# 英雄分类只看打架定位
_AD_ROLES   = {"marksman", "fighter", "assassin"}
_AP_ROLES   = {"mage"}
_TANK_ROLES = {"tank"}
_SUP_ROLES  = {"support"}
_ROLE_ZH    = {"marksman": "射手", "fighter": "战士", "assassin": "刺客",
               "mage": "法师", "tank": "坦克", "support": "辅助"}


def _classify(cid):
    roles = (CHAMPIONS_BY_CID.get(cid) or {}).get("roles") or []
    primary = roles[0] if roles else ""
    if primary in _AP_ROLES:   return "ap"
    if primary in _TANK_ROLES: return "tank"
    if primary in _SUP_ROLES:  return "sup"
    if primary in _AD_ROLES:   return "ad"
    return "ad"


def _slot_label(cid):
    """ARAM 卡片用: 单英雄 → 单一定位标签 (代替 lane position)."""
    roles = (CHAMPIONS_BY_CID.get(cid) or {}).get("roles") or []
    if not roles: return "—"
    primary = roles[0]
    return {"marksman": "ADC", "mage": "AP", "assassin": "刺客",
            "fighter": "战士", "tank": "坦克", "support": "辅助"
            }.get(primary, primary.upper())


_DEFAULT_COACH = {
    "name": "鹤哥",
    "voice": "幽默但毒舌, 偶尔骂醒, 关键时刻温柔",
    "style_examples": [
        "兄弟这英雄稳了, 你别上头",
        "心态炸了? 喝口水, 这局我帮你过",
        "你 Kayn 4-0 别浪, 等队友再开团",
    ],
    "do":   ["指出客观问题", "鼓励但不浮夸", "适度调侃", "用真人语气"],
    "dont": ["人身攻击", "无意义吹捧", "讲废话", "重复模板"],
    "templates": {
        "pre_game_with_core":
            "本局指挥棒交给 {core_name} ({core_champ}, {core_score:.0f}分). {advice}",
        "pre_game_no_core":
            "5 个英雄看着都不太硬核, 各打各的吧, 别上头梭哈.",
        "pre_game_me_core":
            "兄弟你是本局 carry, {core_champ} {core_score:.0f}分, {advice} 队友配合你打.",
        "psych_cold":
            "{name} 最近手有点冷 ({recent_wr:.0f}% last10), 让他先 farm 点好处.",
        "psych_no_frontline":
            "无前排阵容, 不要硬冲. 先让 ADC/AP 站后排消耗, 看到敌方先手再反打.",
        "psych_assassin_pile":
            "刺客一堆? 这种阵容拖后期容易散, 速战速决, 见人就秒.",
    },
}


# ============================================================================
# 数据架构 v2 (2026-05): 按事务分目录. 不迁移老 data/, 老目录冻结当参考.
# 详见 README.md > 数据架构 段.
# ============================================================================
CURRENT_PATCH = ""  # gameVersion (短格式 "14.22") — 启动时探针/match 解析时更新


def _data_version():
    p = DATA_DIR / "_VERSION"
    try: return int(p.read_text(encoding="utf-8").strip())
    except Exception: return 0  # 未写过 (新装 或 老 data/)


def _set_data_version(v):
    p = DATA_DIR / "_VERSION"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(str(v) + "\n", encoding="utf-8")


def _set_patch_from_game_version(gv):
    """从 LCU match detail 的 gameVersion (如 '14.22.605.1234') 提取主+次版本."""
    global CURRENT_PATCH
    try:
        if not gv: return
        parts = str(gv).split(".")
        new = f"{parts[0]}.{parts[1]}" if len(parts) >= 2 else str(gv)
        if new and new != CURRENT_PATCH:
            CURRENT_PATCH = new
            push_log(f"[patch] 当前版本识别: {CURRENT_PATCH}")
    except Exception: pass


def _write_jsonl_v2(path, row, schema_version=1):
    """v2 标准 jsonl 写入: 自动加 _v / _ts / _patch tag, atomic append.

    所有新数据 (coach/history, coach/feedback, games/_index, players/events 等)
    走这个 helper. 老 normalized/*.jsonl 暂不动 (regen-profiles 还在读).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    enriched = {
        "_v":     schema_version,
        "_ts":    dt.datetime.now().isoformat(timespec="seconds"),
        "_patch": CURRENT_PATCH or "",
        **row,
    }
    line = json.dumps(enriched, ensure_ascii=False) + "\n"
    # append + flush (fsync 太重, 不上)
    with path.open("a", encoding="utf-8") as f:
        f.write(line)
        f.flush()


# ---------------------------------------------------------------------------
# 训练贡献 (opt-in): 用户在 UI 勾选"贡献"后, 一份脱敏副本写到 data/contributed/
# 永远不上传, 用户点"导出"才打包成单个 JSON. PIPL 第 47 条要求可见/可删/可撤回.
# ---------------------------------------------------------------------------
def _anon_contributor_id():
    """对机器名 + 用户名做 sha256 → 16 hex. 同一机器稳定, 跨机器不可逆推."""
    import hashlib, getpass, socket
    try: who = f"{getpass.getuser()}@{socket.gethostname()}"
    except Exception: who = "unknown"
    return hashlib.sha256(who.encode("utf-8")).hexdigest()[:16]

def _scrub_pii(row):
    """把 puuid / 召唤师名等替换成不可逆 hash, 移除直接 PII."""
    import hashlib, copy
    out = copy.deepcopy(row)
    pu = out.get("my_puuid") or ""
    if pu:
        out["my_puuid_hash"] = hashlib.sha256(pu.encode("utf-8")).hexdigest()[:12]
    out.pop("my_puuid", None)
    # snapshot 里的发言是教练自己说的, 留着; 用户改写的 rewrite 也留着 (是核心训练信号)
    return out

def _capture_contrib_context():
    """从 STATE / COACH 拍一份"训练用上下文"快照.

    这是蒸馏价值的核心: 没有这些字段, 模型不知道"对谁说的", "什么场景".
    选字段原则: 影响教练判断的全收, 个人 PII 一律不收 (puuid 在外层已 hash).
    """
    cs = STATE.get("champ_select") or {}
    mates = cs.get("mates") or []
    me_mate = next((m for m in mates if m.get("is_me")), None) or {}
    arch = cs.get("architecture") or {}
    coach_obj = cs.get("coach") or {}
    ref = coach_obj.get("ref") or ""
    stage = ref.split("|", 1)[-1] if "|" in ref else ""
    team_champs = [m.get("champion") for m in mates if m.get("champion")]
    return {
        # --- 场景 (WHAT) ---
        "phase":         cs.get("phase", ""),
        "stage":         stage,                                # pre_game / psych / ...
        "my_pick":       cs.get("my_pick_name") or "",
        "my_pick_cid":   cs.get("my_pick_cid"),
        "team_champs":   team_champs,
        # --- 玩家画像 (WHO) ---
        "my_axes":       me_mate.get("axes") or {},            # 5轴静态画像
        "my_tilt": {
            "score":     me_mate.get("tilt_score"),
            "level":     me_mate.get("tilt_level"),
            "mood":      me_mate.get("mood"),
        },
        "my_streak":     me_mate.get("streak_now"),
        "my_wr_l10":     me_mate.get("wr_l10"),
        "my_tags":       me_mate.get("tags") or [],
        "my_traps":      me_mate.get("adolescent_traps") or [],
        # --- 团队架构 ---
        "arch_verdict":  arch.get("verdict", ""),
        "arch_score":    arch.get("score"),
        "arch_tags":     arch.get("tags") or [],
        # --- 教练人设 (HOW) ---
        "coach_persona": {
            "name":      COACH.get("name", ""),
            "voice":     (COACH.get("voice") or "")[:160],
        },
    }


def _save_contribution(row):
    """脱敏 + 写入 data/contributed/feedback_<ts>_<short>.json. 返回路径或 None."""
    consent = _load_contrib_consent()
    if (consent or {}).get("action") == "revoke":
        return None
    CONTRIB_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "_v":       2,    # v2: 带 context 字段 (蒸馏可用)
        "_ts":      dt.datetime.now().isoformat(timespec="seconds"),
        "_patch":   CURRENT_PATCH or "",
        "anon_id":  _anon_contributor_id(),
        "context":  _capture_contrib_context(),
        "feedback": _scrub_pii(row),
    }
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    path = CONTRIB_DIR / f"feedback_{ts}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return path

def _load_contrib_consent():
    p = CONTRIB_DIR / "consent.json"
    if not p.exists(): return None
    try: return json.loads(p.read_text(encoding="utf-8"))
    except Exception: return None

def _restore_last_champ_select_view():
    """启动时把 me/last_champ_select_view.json 读回 STATE['last_champ_select'].

    避免重启 FFAN 后界面回到"等待第一次选人"空状态. 加 restored=True 标记.
    """
    p = ME_DIR / "last_champ_select_view.json"
    if not p.exists(): return
    try:
        cs = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(cs, dict): return
        cs["restored"] = True
        # 文件 mtime 作为 ended_at 兜底 (如果原本没记录)
        cs.setdefault("ended_at", p.stat().st_mtime)
        cs.setdefault("ended_phase", "Restored")
        with _state_lock:
            STATE["last_champ_select"] = cs
        push_log(f"[boot] 恢复上次选人快照 (mtime={int(p.stat().st_mtime)})")
    except Exception as e:
        push_log(f"[boot] 恢复 last_champ_select 失败: {e}")


def _read_match_history(limit=30):
    """读 games/_index.jsonl + 增量从 eog.json 提取我的 champion / win.

    返回 [{gid, ts_iso, date, queue_id, queue_name, duration_s, my_champ_id,
           my_champ_name, my_win}], 最新在前.
    """
    idx_path = GAMES_DIR / "_index.jsonl"
    if not idx_path.exists(): return []
    rows = []
    try:
        with idx_path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line: continue
                try: rows.append(json.loads(line))
                except Exception: continue
    except Exception:
        return []
    # 最新在前
    rows.sort(key=lambda r: r.get("_ts") or r.get("ts") or "", reverse=True)
    rows = rows[:max(1, int(limit))]

    me_puuid = (STATE.get("me") or {}).get("puuid", "")
    out = []
    for r in rows:
        gid = r.get("game_id")
        item = {
            "gid":         gid,
            "ts":          r.get("ts") or r.get("_ts") or "",
            "queue_id":    r.get("queue_id"),
            "queue_name":  r.get("queue_name") or "",
            "duration_s":  r.get("duration_s") or 0,
            "win_team":    r.get("win_team") or 0,
            "my_champ_id":   None,
            "my_champ_name": "",
            "my_win":        None,
        }
        # 从 eog.json 找我的参与信息 (best-effort, eog 不存在就跳过)
        eog_path = GAMES_DIR / str(gid) / "eog.json"
        item["has_detail"] = eog_path.exists()
        if eog_path.exists():
            try:
                eog = json.loads(eog_path.read_text(encoding="utf-8"))
                # eog.json 格式: teams[].players[].puuid + championId + isLocalPlayer
                for t in (eog.get("teams") or []):
                    for p in (t.get("players") or []):
                        is_me = (me_puuid and p.get("puuid") == me_puuid) or p.get("isLocalPlayer")
                        if is_me:
                            cid = p.get("championId") or 0
                            item["my_champ_id"]   = cid
                            item["my_champ_name"] = (CHAMPIONS_BY_CID.get(cid) or {}).get("name") or ""
                            item["my_win"]        = bool(t.get("isWinningTeam"))
                            break
                    if item["my_win"] is not None: break
            except Exception:
                pass
        # date string for grouping (优先用 ts, 其次 _ts)
        ts_str = item["ts"]
        try:
            # ts 是 ISO with "Z" or local format
            if ts_str.endswith("Z"):
                d = dt.datetime.fromisoformat(ts_str[:-1])
            else:
                d = dt.datetime.fromisoformat(ts_str[:19])
            item["date"] = d.strftime("%Y-%m-%d")
        except Exception:
            item["date"] = (ts_str or "")[:10]
        out.append(item)
    return out


_RECAP_MOODS = {"happy", "neutral", "frustrated", "tilted"}


def _game_recap_path(gid):
    return GAMES_DIR / str(gid) / "recap.json"


def _load_game_recap(gid):
    p = _game_recap_path(gid)
    if not p.exists(): return None
    try: return json.loads(p.read_text(encoding="utf-8"))
    except Exception: return None


def _save_game_recap(gid, mood, free_text, tags):
    p = _game_recap_path(gid)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "_v":          1,
        "_ts":         dt.datetime.now().isoformat(timespec="seconds"),
        "_patch":      CURRENT_PATCH or "",
        "gid":         int(gid) if str(gid).isdigit() else gid,
        "mood":        mood,
        "free_text":   free_text,
        "tags":        tags,
        "updated_at":  dt.datetime.now().isoformat(timespec="seconds"),
    }
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def _save_game_recap_contribution(gid, mood, free_text, tags):
    """脱敏 + 写到 data/contributed/recap_<gid>_<ts>.json. 不含 puuid/真名."""
    consent = _load_contrib_consent()
    if (consent or {}).get("action") == "revoke":
        return None
    detail = _read_game_detail(gid) or {}
    # 抽取游戏上下文 (训练时模型需要知道 "对什么样的局做的复盘")
    my_mate = next((m for m in (detail.get("mates") or []) if m.get("is_me")), None) or {}
    team_champs = [m.get("champion_name") for m in (detail.get("mates") or [])
                   if m.get("champion_name")]
    context = {
        "gid":            int(gid) if str(gid).isdigit() else gid,
        "queue_type":     detail.get("queue_type", ""),
        "duration_s":     detail.get("duration_s", 0),
        "is_winning":     detail.get("is_winning"),
        "my_champ_name":  my_mate.get("champion_name", ""),
        "team_champs":    team_champs,
    }
    CONTRIB_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "_v":       1,
        "_ts":      dt.datetime.now().isoformat(timespec="seconds"),
        "_patch":   CURRENT_PATCH or "",
        "anon_id":  _anon_contributor_id(),
        "kind":     "game_recap",
        "context":  context,
        "recap": {
            "mood":      mood,
            "free_text": free_text,
            "tags":      tags,
        },
    }
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    path = CONTRIB_DIR / f"recap_{gid}_{ts}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return path


def _read_game_detail(gid):
    """从 games/<gid>/eog.json 构造一份 mate-shaped 列表, 供历史对局编辑使用.

    返回 {gid, ts, queue_name, win, mates: [...]}, 失败返回 None.
    mate 字段与 _build_champ_select 的 mate 兼容, 这样前端可直接复用 openMateModal.
    """
    if not gid: return None
    eog_path = GAMES_DIR / str(gid) / "eog.json"
    if not eog_path.exists(): return None
    try:
        eog = json.loads(eog_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    teams = eog.get("teams") or []
    # 找我所在的 team (isPlayerTeam 优先, 否则 isLocalPlayer 的 player 所在 teamId)
    my_team = None
    for t in teams:
        if t.get("isPlayerTeam"):
            my_team = t; break
    if my_team is None:
        for t in teams:
            for p in (t.get("players") or []):
                if p.get("isLocalPlayer"):
                    my_team = t; break
            if my_team: break
    if my_team is None:
        return None

    mates = []
    for idx, p in enumerate(my_team.get("players") or []):
        puuid = p.get("puuid", "")
        cid   = p.get("championId") or 0
        ch    = CHAMPIONS_BY_CID.get(cid) or {}
        # 真名优先从 PROFILES 的 nickname (用户已经手填的), 其次 LCU 返回的 riotIdGameName
        prof  = PROFILES.get(puuid) or {}
        name  = prof.get("nickname") or p.get("riotIdGameName") or p.get("summonerName") or "?"
        mates.append({
            "cell_id":       idx,                       # drawer 里点击靠 idx
            "puuid":         puuid,
            "is_me":         bool(p.get("isLocalPlayer")),
            "name":          name,
            "champion_id":   cid,
            "champion_name": ch.get("name") or "",      # 修复 eog 里的 mojibake
            "slot_label":    _slot_label(cid),
            "profile": {
                "tags":        prof.get("tags") or [],
                "self_desc":   prof.get("self_desc") or "",
                "peer_review": prof.get("peer_review") or "",
                "habits":      prof.get("habits") or "",
                "skill":       prof.get("skill") or "",
                "persona": {
                    "self_voice":  ((prof.get("persona") or {}).get("self_voice") or ""),
                    "peer_voices": ((prof.get("persona") or {}).get("peer_voices") or []),
                },
            },
        })
    return {
        "gid":         int(gid) if str(gid).isdigit() else gid,
        "ts":          eog.get("endOfGameTimestamp") or "",
        "is_winning":  bool(my_team.get("isWinningTeam")),
        "queue_type":  eog.get("queueType") or "",
        "duration_s":  int(eog.get("gameLength") or 0),
        "mates":       mates,
        "recap":       _load_game_recap(gid),    # 已有复盘随详情一起回前端
    }


def _contrib_upload_target():
    """读 data/contributed/upload_target.json (用户可编辑). 默认 GitHub Issue 模板."""
    p = CONTRIB_DIR / "upload_target.json"
    if p.exists():
        try: return json.loads(p.read_text(encoding="utf-8"))
        except Exception: pass
    return {
        "kind":  "github_issue",
        "url":   "https://github.com/hereshouye/FFAN/issues/new?labels=contribution&title=%5B%E8%AE%AD%E7%BB%83%E8%B4%A1%E7%8C%AE%5D",
        "hint":  "导出 JSON 后, 打开此地址新建 Issue 并把 JSON 文件拖到正文区即可上传.",
    }


def _game_dir(gid):
    return GAMES_DIR / str(gid)


def _player_dir(puuid):
    return PLAYERS_DIR / puuid


def _seed_from_bundle():
    """从 PyInstaller bundle 的 coach_seed/ 把默认 persona + KB 种到 data/coach/.

    候选源 (依次找):
      1. BUNDLE/coach_seed/        ← exe 打包后, PyInstaller datas 落点
      2. ROOT/bundle_defaults/coach/ ← 开发模式, 仓库里的默认资源
      3. ROOT/data/coach/          ← 兼容老仓库布局 (一般不会到这里)
    只在目标不存在时种 (不覆盖用户已有).
    """
    import shutil
    candidates = [
        BUNDLE / "coach_seed",
        ROOT / "bundle_defaults" / "coach",
        ROOT / "data" / "coach",
    ]
    seed_root = None
    for c in candidates:
        if (c / "persona.json").exists() or (c / "kb").exists():
            seed_root = c
            break
    if seed_root is None:
        return  # 真的什么都没有, 跳过

    # persona.json
    seed_persona = seed_root / "persona.json"
    target_persona = COACH_DIR / "persona.json"
    target_persona_v1 = DATA_DIR / "coach.json"
    if seed_persona.exists() and not target_persona.exists() and not target_persona_v1.exists():
        target_persona.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(seed_persona, target_persona)
        push_log(f"[seed] coach/persona.json (default) ← bundle")

    # KB (psychology/)
    seed_kb = seed_root / "kb" / "psychology"
    target_kb = COACH_KB_DIR / "psychology"
    if seed_kb.exists() and not target_kb.exists():
        target_kb.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(seed_kb, target_kb)
        try: n = sum(1 for f in target_kb.rglob("*") if f.is_file())
        except Exception: n = 0
        push_log(f"[seed] coach/kb/psychology/ ({n} 文件) ← bundle")


def _seed_assets_from_bundle():
    """种 _cache/assets/ 和 _cache/hex_recommendations/ 的快照.

    apexlol.info 加了 Cloudflare 403 后, 'refresh' 拉不到了. 内嵌一份快照
    保证新装的 exe 开箱有完整海克斯推荐. 未来手动维护.

    候选源:
      1. BUNDLE/assets_seed/        ← exe 打包后
      2. ROOT/bundle_defaults/assets/ ← 开发模式
    """
    import shutil
    candidates = [
        BUNDLE / "assets_seed",
        ROOT / "bundle_defaults" / "assets",
    ]
    seed_root = None
    for c in candidates:
        if (c / "zh_cn").exists() or (c / "hex_recs").exists():
            seed_root = c; break
    if seed_root is None:
        return

    items = [
        # (bundle 子路径, 目标路径)
        ("zh_cn",         LEGACY_CACHE_DIR / "assets" / "zh_cn",
         "champion 字典"),
        ("official_kiwi", LEGACY_CACHE_DIR / "assets" / "official_kiwi",
         "KIWI augment 字典"),
        ("hex_recs",      LEGACY_CACHE_DIR / "hex_recommendations",
         "海克斯推荐 (apexlol 快照)"),
    ]
    for sub, target, label in items:
        src = seed_root / sub
        if not src.exists(): continue
        if target.exists() and any(target.iterdir()):
            continue  # 用户已有, 不覆盖
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            # 复制目录内容 (不复制目录本身, 让 target 是父级)
            if target.exists():
                target.rmdir()
            shutil.copytree(src, target)
            n = sum(1 for f in target.rglob("*") if f.is_file())
            push_log(f"[seed] {label} ({n} 文件) ← bundle")
        except Exception as e:
            push_log(f"[seed] {label} 失败: {e}")


def _bootstrap_data_dir():
    """首次启动: 建 v2 目录骨架 + 必要默认文件 + 从 bundle 种 KB. 不动已有数据."""
    # 1. 顶级目录骨架
    for d in (COACH_DIR, COACH_KB_DIR, COACH_SEEDS_DIR, ME_DIR,
              GAMES_DIR, PLAYERS_DIR, ASSETS_V2_DIR):
        d.mkdir(parents=True, exist_ok=True)

    # 2. profiles.json (单一真相源, 顶级保留)
    pf = DATA_DIR / "profiles.json"
    if not pf.exists():
        pf.write_text(json.dumps({
            "_meta": {
                "format_version": "1.0",
                "generated_at": "",
                "note": "见 PROFILES.md. 用 python rankprobe_lite.py regen-profiles 重算 auto 字段."
            }
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # 3. 从 bundle 种 coach 资源 (人设 + 心理学 KB)
    _seed_from_bundle()

    # 3b. 从 bundle 种静态资源 (英雄字典 / KIWI augment / apexlol 海克斯快照)
    #     apexlol 加了 Cloudflare 后这是离线兜底
    _seed_assets_from_bundle()

    # 4. 后备: 如果 bundle 也没有 persona, 用内置默认值兜底
    cp_v2  = COACH_DIR / "persona.json"
    cp_old = DATA_DIR / "coach.json"
    if not cp_v2.exists() and not cp_old.exists():
        cp_v2.write_text(json.dumps(_DEFAULT_COACH, ensure_ascii=False, indent=2)
                         + "\n", encoding="utf-8")

    # 5. 标记数据版本 = v2 (仅首次)
    if _data_version() < DATA_VERSION:
        _set_data_version(DATA_VERSION)


# ============================================================================
# AI 教练 — 用 data/coach.json 的人设 + 模板生成自然语气输出
# ============================================================================
COACH = {
    "name": "AI 教练", "voice": "", "style_examples": [],
    "do": [], "dont": [], "templates": {},
}


def _coach_persona_path():
    """v2 优先 coach/persona.json, 回退到老 coach.json (兼容老 data/)."""
    v2 = COACH_DIR / "persona.json"
    if v2.exists(): return v2
    return DATA_DIR / "coach.json"


def load_coach(verbose=True):
    """读教练人设. 覆盖式更新 COACH 字典本体."""
    cp = _coach_persona_path()
    new = dict(COACH); new["templates"] = {}
    if cp.exists():
        try:
            d = json.loads(cp.read_text(encoding="utf-8"))
            for k in ("name", "voice", "style_examples", "do", "dont", "templates"):
                if k in d:
                    new[k] = d[k]
        except Exception as e:
            push_log(f"[coach] {cp.name} 解析失败: {e}")
    COACH.clear(); COACH.update(new)
    if verbose:
        push_log(f"[coach] 已加载 → {COACH['name']} ({len(COACH.get('templates') or {})} 模板)"
                 f" [{cp.relative_to(DATA_DIR)}]")


def _fmt(tpl, ctx):
    """str.format 但缺 key 时静默, 类型错误也不抛."""
    if not tpl: return ""
    class _Safe(dict):
        def __missing__(self, k): return ""
    try:
        return tpl.format_map(_Safe(ctx))
    except Exception:
        return tpl


def coach_say_pre_game(arch, my_puuid=""):
    """根据 architecture (含 core/warnings) 生成一段教练台词."""
    tpls = COACH.get("templates") or {}
    core = arch.get("core") or {}
    ctx = {
        "core_name":     core.get("name", ""),
        "core_champ":    core.get("champion_name", ""),
        "core_score":    float(core.get("score") or 0),
        "core_role_zh":  _ROLE_ZH.get(core.get("role",""), core.get("role","")),
        "advice":        arch.get("advice", ""),
        "verdict":       arch.get("verdict", ""),
        "warning_count": len(arch.get("warnings") or []),
    }
    if not core:
        return _fmt(tpls.get("pre_game_no_core"), ctx) or "未识别本局核心, 各打各的."
    if core.get("is_me") and tpls.get("pre_game_me_core"):
        return _fmt(tpls["pre_game_me_core"], ctx)
    return _fmt(tpls.get("pre_game_with_core"), ctx) or arch.get("advice", "")


# ============================================================================
# 心理学 KB 加载 + 匹配 (runtime 用; 离线训练数据闭环也用同一份 KB)
# ============================================================================
PSYCH_KB = []  # list of entries from coach/kb/psychology/*.jsonl


def load_psych_kb(verbose=True):
    """读 data/coach/kb/psychology/*.jsonl. 覆盖式更新 PSYCH_KB 列表."""
    PSYCH_KB.clear()
    kb_dir = COACH_KB_DIR / "psychology"
    if not kb_dir.exists():
        if verbose: push_log(f"[kb] {kb_dir} 不存在, psych KB 跳过加载")
        return
    by_cat = {}
    for f in sorted(kb_dir.glob("*.jsonl")):
        try:
            with f.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line: continue
                    try:
                        e = json.loads(line)
                        PSYCH_KB.append(e)
                        cat = e.get("category") or "?"
                        by_cat[cat] = by_cat.get(cat, 0) + 1
                    except Exception as ex:
                        push_log(f"[kb] {f.name} line parse: {ex}")
        except Exception as ex:
            push_log(f"[kb] load {f.name} 失败: {ex}")
    if verbose:
        summary = ", ".join(f"{k}={v}" for k, v in by_cat.items())
        push_log(f"[kb] 已加载 psych KB {len(PSYCH_KB)} 条 ({summary})")


def _kb_by_id(entry_id):
    """O(N) 查询. KB 不超过 100 条, 不上索引."""
    for e in PSYCH_KB:
        if e.get("id") == entry_id:
            return e
    return None


def _pick_tilt_intervention_for_mate(mp):
    """根据 mate psych_state 选最匹配的 tilt KB 条目. 返回 entry 或 None.

    决策树 (按 tilt level + streak 综合):
      severe          → desperation (最高优先, 接近危机)
      moderate + 重连负 → running_bad
      moderate        → hate_losing
      mild + 连负     → running_bad (早期介入)
      其它           → None (不打扰)
    """
    level  = mp.get("tilt_level")
    streak = mp.get("streak_now") or 0

    if level == "severe":
        return _kb_by_id("tilt.desperation.01")
    if level == "moderate":
        if streak <= -3:
            return _kb_by_id("tilt.running_bad.01")
        return _kb_by_id("tilt.hate_losing.01")
    if level == "mild" and streak <= -2:
        return _kb_by_id("tilt.running_bad.01")
    return None


def _render_kb_voice(entry, mp):
    """渲染 KB 条目的 intervention.primary_voice. 缺占位符不会炸 (用 _fmt 安全格式化)."""
    if not entry:
        return ""
    iv = entry.get("intervention") or {}
    tpl = iv.get("primary_voice") or ""
    if not tpl:
        return ""
    streak_now = mp.get("streak_now") or 0
    wr_l10 = mp.get("wr_l10") or 0
    ctx = {
        "name":         mp.get("name") or "队友",
        "streak":       streak_now,
        "streak_abs":   abs(streak_now),
        "wr_l10":       wr_l10,
        "wr_l10_pct":   int(wr_l10 * 100),
        "mood":         mp.get("mood") or "",
    }
    return _fmt(tpl, ctx)


def coach_say_psych(mates):
    """心态/状态提醒. 返回字符串列表 (每条独立显示).

    新版优先用 psych_state + KB; 没 state 的玩家回退到老的 auto.recent_form.trend.
    """
    out = []
    matched_ids = []  # for debug / future logging
    tpls = COACH.get("templates") or {}
    for m in mates:
        if m.get("is_me"): continue
        mp = _build_mate_psych(m)
        # 优先: KB-based (有 psych_state 时)
        if mp and mp.get("tilt_level"):
            entry = _pick_tilt_intervention_for_mate(mp)
            voice = _render_kb_voice(entry, mp) if entry else ""
            if voice:
                out.append(voice)
                matched_ids.append(entry.get("id"))
                continue
        # 回退: 老 recent_form.trend (兼容没 psych_state 的玩家)
        prof = m.get("_profile_full") or {}
        rf = (prof.get("auto") or {}).get("recent_form") or {}
        if rf.get("trend") == "cold":
            ln = _fmt(tpls.get("psych_cold"), {
                "name":      m.get("name", "?"),
                "recent_wr": rf.get("wr", 0) * 100,
            })
            if ln: out.append(ln)
    if matched_ids:
        push_log(f"[coach] psych KB matched: {matched_ids}")
    return out[:3]


def coach_say_warnings(arch):
    """阵容警告 → 针对性的教练话术. 不重复 arch.warnings 本身."""
    tpls = COACH.get("templates") or {}
    out = []
    warns = arch.get("warnings") or []
    for w in warns:
        if "无前排" in w:
            ln = _fmt(tpls.get("psych_no_frontline"), {})
            if ln: out.append(ln)
        elif "刺客" in w:
            ln = _fmt(tpls.get("psych_assassin_pile"), {})
            if ln: out.append(ln)
    return out[:2]


# 同 puuid+gid 同阶段去重缓存 (避免轮询期间反复落盘相同发言)
_COACH_LOGGED = set()


def _log_coach_speech(stage, pre, psych, arch, mates, my_puuid="", game_id=None,
                       mates_psych=None):
    """落盘教练发言 → data/coach/history.jsonl. 训练数据源.

    去重: 同 (game_id 或 ts-bucket, stage, voice_hash) 只写一次.
    Demo 模式不落盘 (避免假数据污染训练集).

    mates_psych: 可选, 每个 mate 的 psych 快照 (axes + state + persona 摘录).
                 这是 LLM 替换模板版教练时的核心 ctx, 一定要存进 history.
    """
    if _IS_DEMO:
        return
    voice = (pre or "") + "|" + "|".join(psych or [])
    # 没 game_id 时用选人 session.localPlayerCellId 当短期 token, 不行就 ts 桶
    bucket = str(game_id or "") or f"ts-{int(time.time() // 300)}"
    key = (bucket, stage, hash(voice))
    if key in _COACH_LOGGED:
        return
    _COACH_LOGGED.add(key)
    # ring: 别让 set 无限大
    if len(_COACH_LOGGED) > 500:
        _COACH_LOGGED.clear()

    # 抽 context 关键特征 (省空间, 不存全量 mates)
    core = arch.get("core") or {}
    ctx = {
        "stage":          stage,
        "my_puuid":       my_puuid,
        "game_id":        game_id,
        "core_name":      core.get("name"),
        "core_champ":     core.get("champion_name"),
        "core_score":     core.get("score"),
        "core_is_me":     bool(core.get("is_me")),
        "verdict":        arch.get("verdict"),
        "advice":         arch.get("advice"),
        "warnings":       list(arch.get("warnings") or [])[:5],
        "team_arch":      arch.get("dist"),
        "mates_brief":    [
            {"name": m.get("name"), "champ": m.get("champion_name"),
             "is_me": m.get("is_me", False)}
            for m in (mates or [])
        ],
    }

    row = {
        "context":       ctx,
        "mates_psych":   mates_psych or [],
        "voice_pre":     pre or "",
        "voice_psych":   list(psych or []),
        "coach_name":    COACH.get("name", ""),
        "coach_voice":   COACH.get("voice", ""),
    }
    try:
        _write_jsonl_v2(COACH_DIR / "history.jsonl", row, schema_version=1)
    except Exception as e:
        push_log(f"[coach] history 写入失败: {e}")


def _load_psych_state(puuid):
    """读 players/<puuid>/psych_state.json. 不存在返回 None."""
    if not puuid: return None
    p = _player_dir(puuid) / "psych_state.json"
    if not p.exists(): return None
    try: return json.loads(p.read_text(encoding="utf-8"))
    except Exception: return None


def _build_mate_psych(mate):
    """从 PROFILES + psych_state.json 组装一个 mate 的心理画像快照, 给 LLM ctx 用.

    输出格式精简但信息完整, 任何 LLM 底座都能直接 prompt.
    """
    puuid = mate.get("puuid") or ""
    if not puuid: return None
    prof = PROFILES.get(puuid) or {}
    psych = prof.get("psych") or {}
    state = _load_psych_state(puuid) or {}
    persona = prof.get("persona") or {}

    # 摘录 persona (限长, 避免 prompt 膨胀)
    def _excerpt(text, lim=120):
        if not text: return ""
        text = str(text).strip().replace("\n", " ")
        return text if len(text) <= lim else text[:lim] + "..."

    out = {
        "name":           mate.get("name") or prof.get("nickname"),
        "is_me":          bool(mate.get("is_me")),
        "is_premade":     bool(mate.get("is_premade")),
        "champion":       mate.get("champion_name"),
        # 静态画像 (axes)
        "axes":           psych.get("axes") or {},
        "adolescent_traps": psych.get("adolescent_traps") or [],
        "interventions_ok": psych.get("interventions_ok") or [],
        "interventions_no": psych.get("interventions_no") or [],
        "axes_source":    psych.get("axes_source") or "",
        # 动态状态 (state)
        "tilt_score":     (state.get("tilt") or {}).get("score"),
        "tilt_level":     (state.get("tilt") or {}).get("level"),
        "mood":           state.get("mood_inference"),
        "signals":        state.get("signals") or [],
        "streak_now":     (state.get("streak") or {}).get("now"),
        "wr_l10":         (state.get("form") or {}).get("wr_l10"),
        "self_efficacy":  state.get("self_efficacy_hint"),
        # 自然语言 (语气样本)
        "self_voice_excerpt":  _excerpt(persona.get("self_voice"), 160),
        "peer_voices_excerpts": [_excerpt(v, 80) for v in (persona.get("peer_voices") or [])[:2]],
        # 手填 tags
        "tags":           prof.get("tags") or [],
    }
    return out


def coach_build(arch, mates, my_puuid="", game_id=None):
    """汇总. 返回 dict 直接进 STATE.champ_select.coach.

    顺便把发言落到 coach/history.jsonl (AI 训练样本源).
    """
    pre = coach_say_pre_game(arch)
    psy = coach_say_psych(mates) + coach_say_warnings(arch)
    psy = psy[:3]
    # 给 LLM 后续替换模板用的完整 ctx (rule-engine 暂用不到, 但 history 落盘要存)
    mates_psych = [_build_mate_psych(m) for m in mates]
    mates_psych = [m for m in mates_psych if m]
    _log_coach_speech("champ_select", pre, psy, arch, mates,
                      my_puuid=my_puuid, game_id=game_id,
                      mates_psych=mates_psych)
    return {
        "name":     COACH.get("name", "AI 教练"),
        "voice":    COACH.get("voice", ""),
        "pre_game": pre,
        "psych":    psy,
        # 给前端反馈按钮用的引用 key. 暂用 (game_id, stage) 二元组的字符串
        "ref":      f"{game_id or ''}|champ_select",
    }


# 本局核心 primary role -> 团队建议 (ARAM 团战导向)
ARCH_ADVICE = {
    "marksman":  "围绕 ADC 后排持续输出 · 需 1 坦克扛伤 + 1 奶妈保护 + 1 法师消耗",
    "mage":      "围绕法师爆发清场 · 需前排开团 + 切入位威胁敌后排",
    "assassin":  "刺客切后 + 拉扯节奏 · 需硬控接应 + 视野压制",
    "fighter":   "战士前排冲脸 · 远程消耗 + 减速软控放风筝",
    "tank":      "坦克开团节奏 · 后排带爆发 AD/AP, 辅助选增益型",
    "support":   "保护型阵容 · 真核应在 AD/AP, 持续奶量打消耗",
}


def _champ_wr_from_profile(profile, cid):
    """从 profile.auto.top_champs 找该英雄历史. 返回 (wr_0to1, games) 或 (None, 0)."""
    auto = profile.get("auto") or {}
    for tc in (auto.get("top_champs") or []):
        if tc.get("cid") == cid and tc.get("games", 0) >= 3:
            return tc.get("wr", 0), tc.get("games", 0)
    return None, 0


def _carry_score(mate, profile, my_champ_history):
    """ARAM 版. 客观为主, 自评微调. 范围约 -50 ~ +110.

    客观  = 该 puuid 在该英雄上的历史胜率(±50, 起算 3 局)
          + 整体大乱斗胜率(±10, 起算 30 局, 仅作微调)
          + 熟练度(0~30, 仅自己, LCU 暴露)
    主观  = favorite_champ_ids 命中(+15) + carry_priority(0~10)
    """
    cid = mate.get("champion_id") or 0
    if not cid:
        return 0.0

    # 客观 1: 该英雄历史胜率
    wr, games = _champ_wr_from_profile(profile, cid)
    if wr is None and mate.get("is_me"):
        # 自己: 用 LCU 实时拉的最近 20 局 (STATE.my_champ_history)
        h = my_champ_history.get(cid) or my_champ_history.get(str(cid)) or {}
        if h.get("games", 0) >= 3:
            wr = h["wins"] / h["games"]
            games = h["games"]
    obj_wr = ((wr - 0.5) * 100) if wr is not None else 0

    # 客观 2: 整体胜率微调
    auto = profile.get("auto") or {}
    total_g = auto.get("games_total", 0)
    total_wr = auto.get("wr_total", 0)
    obj_total = ((total_wr - 0.5) * 20) if total_g >= 30 else 0

    # 客观 3: 熟练度 (LCU 只暴露自己的)
    obj_mastery = 0
    if mate.get("is_me"):
        m_pts = STATE.get("mastery", {}).get(cid) or 0
        obj_mastery = min(m_pts / 100000 * 25, 30)

    # 客观 4: 最近状态加成 (热手 +8, 手冷 -8)
    rf = auto.get("recent_form") or {}
    if rf.get("trend") == "hot":   obj_recent = 8
    elif rf.get("trend") == "cold":obj_recent = -8
    else:                           obj_recent = 0

    # 主观
    sub_fav = 15 if cid in (profile.get("favorite_champ_ids") or []) else 0
    sub_pri = float(profile.get("carry_priority") or 0)

    return obj_wr + obj_total + obj_mastery + obj_recent + sub_fav + sub_pri


def _team_warnings(mates):
    """ARAM 阵容风险检查. 返回 1-3 条短句."""
    out = []
    n = len([m for m in mates if m.get("champion_id")])
    if n < 5:
        return out

    # 1. 前排
    tank_count = sum(1 for m in mates
                     if _classify(m.get("champion_id") or 0) == "tank")
    if tank_count == 0:
        out.append("⚠ 全员无前排 · 大乱斗对枪易崩")

    # 2. 状态偏冷: 用每个 puuid 在该英雄的历史胜率
    weak = []
    for m in mates:
        cid = m.get("champion_id") or 0
        if not cid: continue
        profile = m.get("_profile_full") or {}
        wr, g = _champ_wr_from_profile(profile, cid)
        if wr is None and m.get("is_me"):
            h = STATE.get("my_champ_history", {}).get(cid) or {}
            if h.get("games", 0) >= 5:
                wr = h["wins"] / h["games"]; g = h["games"]
        if wr is not None and g >= 5 and wr < 0.4:
            tag = f"{'你' if m.get('is_me') else m.get('name','?')}({m.get('champion_name','?')} {int(wr*100)}%)"
            weak.append(tag)
    if weak:
        out.append("⚠ 状态偏冷: " + " / ".join(weak))

    # 3. 切入位过多 (ARAM 无 peel 容易被分割击破)
    assassin_count = sum(
        1 for m in mates
        if _classify(m.get("champion_id") or 0) == "ad"
        and "assassin" in ((CHAMPIONS_BY_CID.get(m.get("champion_id") or 0) or {}).get("roles") or []))
    if assassin_count >= 3:
        out.append("⚠ 刺客过多 · 缺持续输出, 集火能力弱")

    # 4. 全员脆皮 (无 tank 无 fighter)
    bruiser_count = sum(1 for m in mates
        if "fighter" in ((CHAMPIONS_BY_CID.get(m.get("champion_id") or 0) or {}).get("roles") or []))
    if tank_count == 0 and bruiser_count == 0:
        out.append("⚠ 全员脆皮 · 团战秒散")

    return out[:3]


def analyze_lineup(cids):
    cnt = {"ad": 0, "ap": 0, "tank": 0, "sup": 0}
    for cid in cids:
        if cid:
            cnt[_classify(cid)] += 1
    n = sum(cnt.values())
    parts = []
    if n == 0:
        return {"verdict": "等待全员锁定...", **cnt, "n": 0}
    if cnt["ad"] >= 4:        parts.append("AD 过载")
    elif cnt["ap"] >= 4:      parts.append("AP 过载")
    elif cnt["ad"] == 0:      parts.append("零物理伤害")
    elif cnt["ap"] == 0:      parts.append("零法术伤害")
    else:                     parts.append("AD/AP 均衡")
    if cnt["tank"] == 0:      parts.append("无前排坦克")
    elif cnt["tank"] >= 2:    parts.append("双前排")
    if cnt["sup"] == 0 and n >= 5: parts.append("无辅助")
    return {"verdict": " · ".join(parts), **cnt, "n": n}


# ============================================================================
# 6. 探针主循环 (单线程)
# ============================================================================
def _hex_recs_for_cid(cid, limit=6):
    rows = APEX_PER_CID.get(str(cid), [])[:limit]
    return [{
        "combo": r["combo"], "tier": r["tier"], "rating": r["rating"],
        "tag": r["tag"], "analysis": r["analysis"],
    } for r in rows]


def _build_me(api):
    me = api.get("/lol-summoner/v1/current-summoner") or {}
    rk = api.get("/lol-ranked/v1/current-ranked-stats") or {}
    solo = ((rk.get("queueMap") or {}).get("RANKED_SOLO_5x5") or {})
    wins, losses = solo.get("wins", 0), solo.get("losses", 0)
    gp = wins + losses
    return {
        "puuid": me.get("puuid") or "",
        "name": me.get("gameName") or me.get("displayName") or "",
        "tagLine": me.get("tagLine") or "",
        "level": me.get("summonerLevel") or 0,
        "profileIconId": me.get("profileIconId") or 0,
        "tier": solo.get("tier") or "",
        "division": solo.get("division") or "",
        "lp": solo.get("leaguePoints") or 0,
        "wins": wins, "losses": losses,
        "wr": int(round(wins / gp * 100)) if gp else 0,
    }


def _build_mastery(api):
    arr = api.get("/lol-champion-mastery/v1/local-player/champion-mastery") or []
    out = {}
    for it in arr if isinstance(arr, list) else []:
        cid = it.get("championId")
        if cid:
            out[cid] = it.get("championPoints", 0)
    return out


def _build_champ_history(api, my_puuid, limit=20):
    """从最近 N 局聚合英雄胜率."""
    mh = api.get(f"/lol-match-history/v1/products/lol/{my_puuid}/matches"
                 f"?begIndex=0&endIndex={limit}") or {}
    games = ((mh.get("games") or {}).get("games") or [])
    agg = {}
    for g in games:
        for p in (g.get("participants") or []):
            ident = (g.get("participantIdentities") or [])
            # 直接遍历 g.participants — 个人匹配历史里只有自己
            cid = p.get("championId")
            stats = p.get("stats") or {}
            won = bool(stats.get("win"))
            if not cid:
                continue
            s = agg.setdefault(cid, {"games": 0, "wins": 0, "k": 0, "d": 0, "a": 0})
            s["games"] += 1
            s["wins"] += int(won)
            s["k"] += stats.get("kills", 0)
            s["d"] += stats.get("deaths", 0)
            s["a"] += stats.get("assists", 0)
    return agg


_mate_cache = {}  # puuid -> {tier, wins, losses, wr, name, ts}


def _mate_info(api, puuid):
    if not puuid:
        return {"name": "", "tier": "", "wr": 0, "games": 0}
    c = _mate_cache.get(puuid)
    if c and time.time() - c["ts"] < 300:
        return c
    rk = api.get(f"/lol-ranked/v1/ranked-stats/{puuid}") or {}
    solo = ((rk.get("queueMap") or {}).get("RANKED_SOLO_5x5") or {})
    wins, losses = solo.get("wins", 0), solo.get("losses", 0)
    gp = wins + losses
    sm = api.get(f"/lol-summoner/v2/summoners/puuid/{puuid}") or {}
    info = {
        "puuid": puuid,
        "name": sm.get("gameName") or sm.get("displayName") or "",
        "tier": solo.get("tier") or "",
        "division": solo.get("division") or "",
        "wins": wins, "losses": losses,
        "wr": int(round(wins / gp * 100)) if gp else 0,
        "games": gp,
        "ts": time.time(),
    }
    _mate_cache[puuid] = info
    return info


def _build_champ_select(api, session, my_puuid):
    if not session:
        return None
    my_team = session.get("myTeam") or []
    if not my_team:
        return None

    # 热重载 profiles + coach (用户随时改 JSON, 选人时生效)
    try: load_profiles()
    except Exception: pass
    try: load_coach(verbose=False)
    except Exception: pass

    mates = []
    cids_for_arch = []
    me_pick_cid = 0
    for cell in my_team:
        puuid = cell.get("puuid") or ""
        cid   = cell.get("championId") or cell.get("championPickIntent") or 0
        is_me = (puuid == my_puuid) if my_puuid else False
        if is_me:
            me_pick_cid = cid
        ch = CHAMPIONS_BY_CID.get(cid) or {}
        info = _mate_info(api, puuid) if (puuid and not is_me) else {
            "name": "", "tier": "", "division": "", "wr": 0, "games": 0}
        profile = PROFILES.get(puuid) or {}
        auto = profile.get("auto") or {}
        # 该英雄历史 (ARAM 用)
        c_wr, c_games = _champ_wr_from_profile(profile, cid)
        mates.append({
            "cell_id": cell.get("cellId"),
            "puuid": puuid, "is_me": is_me,
            "name": (info.get("name") or profile.get("nickname")
                     or ("我" if is_me else "队友")),
            "champion_id": cid,
            "champion_name": ch.get("name") or "",
            "slot_label": _slot_label(cid),
            "champ_history": ({"games": c_games, "wr": round(c_wr, 3)}
                              if c_wr is not None else None),
            "total_games": auto.get("games_total", 0),
            "total_wr": auto.get("wr_total", 0),
            "locked": bool(cell.get("championId")),
            "_profile_full": profile,    # 供 warnings 用, 渲染时剥离
            "profile": {
                "tags": profile.get("tags") or [],
                "self_desc": profile.get("self_desc") or "",
                "peer_review": profile.get("peer_review") or "",
                "habits": profile.get("habits") or "",
                "skill": profile.get("skill") or "",
                "persona": {
                    "self_voice": ((profile.get("persona") or {})
                                   .get("self_voice") or ""),
                    "peer_voices": ((profile.get("persona") or {})
                                    .get("peer_voices") or []),
                },
            },
        })
        if cid:
            cids_for_arch.append(cid)

    # premade 标记
    puuids_in_team = [m["puuid"] for m in mates if m["puuid"]]
    for m in mates:
        m["is_premade"] = any(
            frozenset((m["puuid"], other)) in PREMADE_SET
            for other in puuids_in_team if other != m["puuid"]
        ) if m["puuid"] else False

    # carry_score 排序
    for m in mates:
        m["carry_score"] = round(_carry_score(
            m, PROFILES.get(m["puuid"]) or {}, STATE.get("my_champ_history", {})
        ), 1)

    arch = analyze_lineup(cids_for_arch)
    arch.update(_build_core_verdict(mates, cids_for_arch))
    # 选人阶段还没有 game_id, 用 session 自身的 gameId (有时为 0)
    cs_gid = (session.get("gameId") or 0) or None
    coach = coach_build(arch, mates, my_puuid=my_puuid, game_id=cs_gid)
    hex_recs = _hex_recs_for_cid(me_pick_cid) if me_pick_cid else []
    # 剥离仅用于内部传参的 _profile_full
    mates_clean = [{k: v for k, v in m.items() if not k.startswith("_")} for m in mates]
    return {
        "phase": session.get("timer", {}).get("phase") or "",
        "my_pick_cid": me_pick_cid,
        "my_pick_name": (CHAMPIONS_BY_CID.get(me_pick_cid) or {}).get("name") or "",
        "mates": mates_clean,
        "architecture": arch,
        "coach": coach,
        "hex_recs": hex_recs,
        "ts": time.time(),
    }


def _build_core_verdict(mates, cids):
    """选出 carry_score 最高的为本局核心, 输出 advice + warnings."""
    if not cids:
        return {"core": None, "advice": "", "warnings": []}
    sorted_mates = sorted(mates, key=lambda m: m.get("carry_score", 0), reverse=True)
    top = sorted_mates[0] if sorted_mates else None
    core = None
    advice = ""
    if top and top.get("carry_score", 0) > 5 and top.get("champion_id"):
        roles = (CHAMPIONS_BY_CID.get(top["champion_id"]) or {}).get("roles") or []
        primary = roles[0] if roles else ""
        advice = ARCH_ADVICE.get(primary, "围绕其展开节奏, 队友按位置补位")
        core = {
            "puuid": top["puuid"],
            "name": top["name"],
            "champion_id": top["champion_id"],
            "champion_name": top["champion_name"],
            "score": top["carry_score"],
            "tags": top.get("profile", {}).get("tags", [])[:3],
            "is_me": top.get("is_me", False),
            "role": primary,
        }
    warnings = _team_warnings(mates)
    return {"core": core, "advice": advice, "warnings": warnings}


# ============================================================================
# 数据持续采集 (v2 布局: data/games/<gid>/ + data/players/<puuid>/ + data/me/)
# 老 data/YYYY-MM-DD/ + data/_cache/normalized/ 不再写入. regen-profiles 仍能读.
# ============================================================================
def _write_json(path, obj):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _append_jsonl(path, rows):
    """老 jsonl helper (无 _v/_ts tag). 仅用于 regen-profiles 的 normalized 输出.

    新业务数据请用 _write_jsonl_v2()."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _append_ranked_timeline(rk):
    """ranked stats 按日期 append 到 data/me/ranked_timeline.jsonl (情绪曲线源)."""
    if not rk: return
    today = dt.date.today().isoformat()
    path = ME_DIR / "ranked_timeline.jsonl"
    # 同一天只写一次 (读最后一行比对 date)
    try:
        if path.exists():
            with path.open("rb") as f:
                try: f.seek(-2048, 2)
                except OSError: f.seek(0)
                tail = f.read().decode("utf-8", "replace")
            last = tail.rsplit("\n", 2)[-2] if "\n" in tail.strip() else tail.strip()
            if last:
                try:
                    if json.loads(last).get("date") == today:
                        return  # 今日已写
                except Exception: pass
    except Exception: pass
    # 抽取关键字段, 避免每天写 10KB
    queues = []
    for q in (rk.get("queues") or []):
        queues.append({
            "queueType":  q.get("queueType"),
            "tier":       q.get("tier"),
            "division":   q.get("division"),
            "leaguePoints": q.get("leaguePoints"),
            "wins":       q.get("wins"),
            "losses":     q.get("losses"),
        })
    _write_jsonl_v2(path, {"date": today, "queues": queues}, schema_version=1)


def collect_basics(api):
    """闲时采集: summoner / ranked / mastery → data/me/ (覆盖, 最新即真相).

    ranked_stats 额外 append 一条 ranked_timeline (作为情绪曲线的根)."""
    sm = api.get("/lol-summoner/v1/current-summoner")
    if sm: _write_json(ME_DIR / "summoner.json", sm)
    rk = api.get("/lol-ranked/v1/current-ranked-stats")
    if rk:
        _write_json(ME_DIR / "ranked_stats.json", rk)
        _append_ranked_timeline(rk)
    cm = api.get("/lol-champion-mastery/v1/local-player/champion-mastery")
    if cm: _write_json(ME_DIR / "champion_mastery.json", cm)
    # 社交图谱 (友 vs 路人, 训练用)
    fr = api.get("/lol-chat/v1/friends")
    if fr: _write_json(ME_DIR / "friends.json", fr)
    hp = api.get("/lol-honor-v2/v1/profile")
    if hp: _write_json(ME_DIR / "honor_profile.json", hp)


def collect_champ_select_snapshot(session):
    """选人 session 快照. 没 gameId 时写到 me/last_champ_select.json (覆盖).
    局后 collect_match_history 拿到 gid 会把它搬到 games/<gid>/champ_select.json."""
    if not session: return
    gid = session.get("gameId") or 0
    if gid:
        _write_json(_game_dir(gid) / "champ_select.json", session)
    else:
        _write_json(ME_DIR / "last_champ_select.json", session)


def collect_player_cache(api, puuids):
    """选人时把队友 summoner+ranked 缓存到 data/players/<puuid>/."""
    for puuid in puuids:
        if not puuid: continue
        sub = _player_dir(puuid)
        if (sub / "summoner.json").exists() and (sub / "ranked.json").exists():
            # 已有缓存, 24h 之内不重拉
            try:
                age = time.time() - (sub / "summoner.json").stat().st_mtime
                if age < 86400: continue
            except Exception: pass
        sm = api.get(f"/lol-summoner/v2/summoners/puuid/{puuid}")
        if sm: _write_json(sub / "summoner.json", sm)
        rk = api.get(f"/lol-ranked/v1/ranked-stats/{puuid}")
        if rk: _write_json(sub / "ranked.json", rk)


def collect_eog(api, seen_gids):
    """局后抓 eog 结算块 → games/<gid>/eog.json. 返回新 gid 或 None.

    detail.json 才是结算 ground truth (collect_match_history 写); eog 只是 LCU
    实时结算页面的内容, 留作时间戳证据 + 局后立刻可读 (detail 可能滞后)."""
    sess = api.get("/lol-end-of-game/v1/eog-stats-block")
    if not sess: return None
    gid = sess.get("gameId") or 0
    if not gid or gid in seen_gids:
        return None
    _write_json(_game_dir(gid) / "eog.json", sess)
    # 把局前选人快照搬到这个 gid 下 (如果存在的话)
    last_cs = ME_DIR / "last_champ_select.json"
    if last_cs.exists():
        try:
            cs_dst = _game_dir(gid) / "champ_select.json"
            if not cs_dst.exists():
                cs_dst.parent.mkdir(parents=True, exist_ok=True)
                last_cs.replace(cs_dst)
        except Exception as e:
            push_log(f"[collect] champ_select 归位失败: {e}")
    seen_gids.add(gid)
    return gid


# 与老 probe/normalize.py 完全一致的格式映射
_QUEUE_NAMES = {
    420: "单双排位", 430: "匹配", 440: "灵活组排", 450: "极地大乱斗",
    700: "冠军杯", 830: "人机入门", 840: "人机简单", 850: "人机中级",
    900: "无限火力", 1020: "极地乱斗大乱斗", 1700: "斗魂竞技场",
    2700: "云顶之弈",
}  # queue_id 不在表里 → "其它" (兼容老探针的默认值)


def _queue_name(qid):
    return _QUEUE_NAMES.get(int(qid or 0), "其它")


def _stats_to_old_format(stats):
    """LCU camelCase stats → 老探针的 39 字段 snake_case 完整格式."""
    return {
        "champ_level":                   stats.get("champLevel", 0),
        "combat_player_score":           stats.get("combatPlayerScore", 0),
        "cs":                            stats.get("totalMinionsKilled", 0),
        "damage_dealt":                  stats.get("totalDamageDealt", 0),
        "damage_self_mitigated":         stats.get("damageSelfMitigated", 0),
        "damage_taken":                  stats.get("totalDamageTaken", 0),
        "damage_to_champions":           stats.get("totalDamageDealtToChampions", 0),
        "damage_to_objectives":          stats.get("damageDealtToObjectives", 0),
        "damage_to_turrets":             stats.get("damageDealtToTurrets", 0),
        "double_kills":                  stats.get("doubleKills", 0),
        "first_blood_assist":            bool(stats.get("firstBloodAssist", False)),
        "first_blood_kill":              bool(stats.get("firstBloodKill", False)),
        "first_tower_assist":            bool(stats.get("firstTowerAssist", False)),
        "first_tower_kill":              bool(stats.get("firstTowerKill", False)),
        "gold_earned":                   stats.get("goldEarned", 0),
        "gold_spent":                    stats.get("goldSpent", 0),
        "heal":                          stats.get("totalHeal", 0),
        "inhibitor_kills":               stats.get("inhibitorKills", 0),
        "killing_sprees":                stats.get("killingSprees", 0),
        "largest_killing_spree":         stats.get("largestKillingSpree", 0),
        "largest_multi_kill":            stats.get("largestMultiKill", 0),
        "longest_time_living":           stats.get("longestTimeSpentLiving", 0),
        "magic_damage_taken":            stats.get("magicalDamageTaken", 0),
        "magic_damage_to_champions":     stats.get("magicDamageDealtToChampions", 0),
        "neutral_minions":               stats.get("neutralMinionsKilled", 0),
        "objective_player_score":        stats.get("objectivePlayerScore", 0),
        "penta_kills":                   stats.get("pentaKills", 0),
        "physical_damage_taken":         stats.get("physicalDamageTaken", 0),
        "physical_damage_to_champions":  stats.get("physicalDamageDealtToChampions", 0),
        "quadra_kills":                  stats.get("quadraKills", 0),
        "time_ccing_others":             stats.get("timeCCingOthers", 0),
        "total_player_score":            stats.get("totalPlayerScore", 0),
        "triple_kills":                  stats.get("tripleKills", 0),
        "true_damage_taken":             stats.get("trueDamageTaken", 0),
        "true_damage_to_champions":      stats.get("trueDamageDealtToChampions", 0),
        "turret_kills":                  stats.get("turretKills", 0),
        "units_healed":                  stats.get("totalUnitsHealed", 0),
        "vision_score":                  stats.get("visionScore", 0),
        "wards_killed":                  stats.get("wardsKilled", 0),
        "wards_placed":                  stats.get("wardsPlaced", 0),
    }


def _perks_from_stats(stats):
    """LCU stats 中抽 perks → 老格式 {primary_style, sub_style, perks[6], stat_perks[3]}."""
    return {
        "primary_style": stats.get("perkPrimaryStyle", 0),
        "sub_style":     stats.get("perkSubStyle", 0),
        "perks":         [stats.get(f"perk{i}", 0) for i in range(6)],
        "stat_perks":    [stats.get(f"statPerk{i}", 0) for i in range(3)],
    }


def _teams_to_old_format(g, win_team):
    """LCU detail.teams[] → 老格式."""
    out = []
    for t in (g.get("teams") or []):
        tid = t.get("teamId")
        out.append({
            "team_id":          tid,
            "win":              (tid == win_team) if win_team else
                                (str(t.get("win","")).lower() == "win"),
            "tower_kills":      t.get("towerKills", 0),
            "inhibitor_kills":  t.get("inhibitorKills", 0),
            "baron_kills":      t.get("baronKills", 0),
            "dragon_kills":     t.get("dragonKills", 0),
            "first_blood":      bool(t.get("firstBlood", False)),
            "first_tower":      bool(t.get("firstTower", False)),
            "first_inhibitor":  bool(t.get("firstInhibitor", False)),
        })
    return out


def _parse_match_to_normalized(g):
    """把 LCU match detail 拆成 (game_row, participant_rows) 供 normalized 用.

    输出与老 probe/normalize.py 100% 字段一致, 可与老历史数据无缝合并.
    """
    pid_to_player = {p.get("participantId"): (p.get("player") or {})
                     for p in (g.get("participantIdentities") or [])}
    parts = []
    win_team = 0
    for p in (g.get("participants") or []):
        stats = p.get("stats") or {}
        pid = p.get("participantId")
        player = pid_to_player.get(pid) or {}
        cid = p.get("championId", 0)
        won = bool(stats.get("win"))
        if won and not win_team:
            win_team = p.get("teamId") or 0
        augments = [stats.get(f"playerAugment{i}", 0) for i in range(1, 7)]
        augments = [a for a in augments if a]
        items = [stats.get(f"item{i}", 0) for i in range(0, 7)]
        parts.append({
            "game_id":        g.get("gameId"),
            "participant_id": pid,
            "puuid":          player.get("puuid", ""),
            "summoner_id":    p.get("summonerId") or player.get("summonerId") or 0,
            "game_name":      player.get("gameName", ""),
            "tag_line":       player.get("tagLine", ""),
            "team_id":        p.get("teamId"),
            "champion_id":    cid,
            "spell1":         p.get("spell1Id"),
            "spell2":         p.get("spell2Id"),
            "win":            won,
            "kills":          stats.get("kills", 0),
            "deaths":         stats.get("deaths", 0),
            "assists":        stats.get("assists", 0),
            "kda":            round((stats.get("kills",0) + stats.get("assists",0))
                                    / max(1, stats.get("deaths",0)), 2),
            "position":       p.get("timeline", {}).get("lane") or "NONE",
            "items":          items,
            "augments":       augments,
            "perks":          _perks_from_stats(stats),
            "stats":          _stats_to_old_format(stats),
        })
    iso_ts = g.get("gameCreationDate") or ""
    game_row = {
        "game_id":     g.get("gameId"),
        "ts":          iso_ts,
        "duration_s":  g.get("gameDuration", 0),
        "queue_id":    g.get("queueId", 0),
        "queue_name":  _queue_name(g.get("queueId")),
        "map_id":      g.get("mapId", 0),
        "game_mode":   g.get("gameMode", ""),
        "game_type":   g.get("gameType", ""),
        "win_team":    win_team,
        "platform":    g.get("platformId", ""),
        "teams":       _teams_to_old_format(g, win_team),
    }
    return game_row, parts


def _update_players_jsonl(part_rows):
    """从 participants 行更新 _cache/normalized/players.jsonl (覆盖 + 去重).

    老格式: {puuid, summoner_id, game_name, tag_line, last_game_id} 每 puuid 一行.
    """
    path = CACHE_DIR / "normalized" / "players.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    # 1. 读老的
    seen = {}
    if path.exists():
        try:
            with path.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line: continue
                    try:
                        r = json.loads(line)
                        if r.get("puuid"):
                            seen[r["puuid"]] = r
                    except Exception: pass
        except Exception: pass
    # 2. 用新行更新
    updated = 0
    for p in part_rows:
        puuid = p.get("puuid") or ""
        gid   = p.get("game_id")
        if not puuid or not gid: continue
        prev = seen.get(puuid)
        if prev is None or (prev.get("last_game_id") or 0) < gid:
            seen[puuid] = {
                "puuid":          puuid,
                "summoner_id":    p.get("summoner_id"),
                "game_name":      p.get("game_name"),
                "tag_line":       p.get("tag_line"),
                "last_game_id":   gid,
            }
            updated += 1
    # 3. 写回 (覆盖整个文件)
    tmp = path.with_suffix(".jsonl.tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for r in seen.values():
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp.replace(path)
    return updated


def _write_json_gz(path, obj):
    """gzip 写大对象 (timeline 可以压缩 10x). 用 .json.gz 后缀."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with _gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)
    tmp.replace(path)


def _append_games_index(game_row):
    """全局快速索引: data/games/_index.jsonl (每局 1 行, 用于 regen-profiles 扫描)."""
    _write_jsonl_v2(GAMES_DIR / "_index.jsonl", {
        "game_id":    game_row.get("game_id"),
        "ts":         game_row.get("ts"),
        "queue_id":   game_row.get("queue_id"),
        "queue_name": game_row.get("queue_name"),
        "duration_s": game_row.get("duration_s"),
        "win_team":   game_row.get("win_team"),
    }, schema_version=1)


def collect_match_history(api, my_puuid, seen_game_ids, max_pages=2):
    """拉最近对局, 写入 v2 布局:
       - games/<gid>/detail.json         (raw LCU detail)
       - games/<gid>/timeline.json.gz    (raw timeline, gzip, 404 跳过)
       - games/<gid>/normalized.json     (单局聚合: {game, participants})
       - games/_index.jsonl              (全局索引 1 行)

    同时维护老 _cache/normalized/{games,participants,players}.jsonl 让
    regen-profiles + cooccurrence 继续工作 (老逻辑暂未重构, 见 ROADMAP).
    """
    if not my_puuid: return 0
    # 老 normalized 兼容输出 (regen-profiles 还在用)
    nm_dir     = LEGACY_CACHE_DIR / "normalized"
    games_path = nm_dir / "games.jsonl"
    parts_path = nm_dir / "participants.jsonl"

    new_count = 0
    for page in range(max_pages):
        beg, end = page * 20, page * 20 + 19
        mh = api.get(f"/lol-match-history/v1/products/lol/{my_puuid}/matches"
                     f"?begIndex={beg}&endIndex={end}")
        if not mh: break
        games = ((mh.get("games") or {}).get("games") or [])
        if not games: break
        page_new = 0
        for stub in games:
            gid = stub.get("gameId") or 0
            if not gid or gid in seen_game_ids:
                continue
            # 1. 拉详情
            detail = api.get(f"/lol-match-history/v1/games/{gid}")
            if not detail: continue
            _set_patch_from_game_version(detail.get("gameVersion") or "")

            gd = _game_dir(gid)
            try: _write_json(gd / "detail.json", detail)
            except Exception as e: push_log(f"[collect] detail {gid}: {e}")

            game_row, part_rows = _parse_match_to_normalized(detail)
            try: _write_json(gd / "normalized.json",
                             {"game": game_row, "participants": part_rows})
            except Exception as e: push_log(f"[collect] normalized {gid}: {e}")
            try: _append_games_index(game_row)
            except Exception as e: push_log(f"[collect] index {gid}: {e}")

            # 老 normalized (regen-profiles 兼容)
            _append_jsonl(games_path, [game_row])
            _append_jsonl(parts_path, part_rows)
            _update_players_jsonl(part_rows)

            # 2. 拉 timeline → gzip
            tl = api.get(f"/lol-match-history/v1/game-timelines/{gid}")
            if tl:
                try: _write_json_gz(gd / "timeline.json.gz", tl)
                except Exception as e: push_log(f"[collect] timeline {gid}: {e}")

            seen_game_ids.add(gid)
            page_new += 1
            new_count += 1
        if page_new == 0:
            break  # 整页都是老的, 不用再翻
    if new_count:
        push_log(f"[collect] match-history 新增 {new_count} 局 → games/<gid>/")
    return new_count


def _load_seen_game_ids():
    """启动时从 games/_index.jsonl + 老 games.jsonl 合并已采集 gid."""
    out = set()
    # v2: games/_index.jsonl
    idx = GAMES_DIR / "_index.jsonl"
    if idx.exists():
        try:
            with idx.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line: continue
                    try:
                        g = json.loads(line)
                        if g.get("game_id"): out.add(g["game_id"])
                    except Exception: pass
        except Exception: pass
    # 老 normalized (兼容, 让旧 data 的 gid 也不重拉)
    legacy = LEGACY_CACHE_DIR / "normalized" / "games.jsonl"
    if legacy.exists():
        try:
            with legacy.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line: continue
                    try:
                        g = json.loads(line)
                        if g.get("game_id"): out.add(g["game_id"])
                    except Exception: pass
        except Exception: pass
    return out


def recompute_cooccurrence(my_puuid):
    """从 participants.jsonl 重算 my_puuid 的 cooccurrence (premade 关系).
    输出覆盖 _cache/normalized/cooccurrence.jsonl.
    """
    if not my_puuid: return 0
    parts_path = CACHE_DIR / "normalized" / "participants.jsonl"
    if not parts_path.exists(): return 0

    # 1. 找出我所在的每局 + team_id
    my_team_of = {}
    with parts_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try: r = json.loads(line)
            except Exception: continue
            if r.get("puuid") == my_puuid:
                my_team_of[r["game_id"]] = (r.get("team_id"), bool(r.get("win")))

    # 2. 找出每局其他玩家
    from collections import defaultdict
    pair = defaultdict(lambda: {
        "shared": 0, "same_team": 0, "wins_together": 0,
        "first_game": None, "last_game": None,
    })
    with parts_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try: r = json.loads(line)
            except Exception: continue
            puuid = r.get("puuid") or ""
            gid = r.get("game_id")
            if not puuid or puuid == my_puuid or gid not in my_team_of:
                continue
            my_tid, my_won = my_team_of[gid]
            s = pair[puuid]
            s["shared"] += 1
            if r.get("team_id") == my_tid:
                s["same_team"] += 1
                if my_won and r.get("win"):
                    s["wins_together"] += 1
            if s["first_game"] is None or gid < s["first_game"]:
                s["first_game"] = gid
            if s["last_game"] is None or gid > s["last_game"]:
                s["last_game"] = gid

    # 3. 写文件 (覆盖)
    out_path = CACHE_DIR / "normalized" / "cooccurrence.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    rows = []
    for puuid, s in pair.items():
        if s["same_team"] < 1: continue
        team_wr = (s["wins_together"] / s["same_team"]) if s["same_team"] else 0
        # premade_score: same_team 占比 + 高频惩罚 = 简化版
        premade_score = (s["same_team"] / s["shared"]) if s["shared"] else 0
        if s["same_team"] >= 30:
            premade_score = min(1.0, premade_score + 0.1)
        rows.append({
            "puuid_a": my_puuid,
            "puuid_b": puuid,
            "shared_games": s["shared"],
            "same_team":    s["same_team"],
            "wins_together": s["wins_together"],
            "first_game":   s["first_game"],
            "last_game":    s["last_game"],
            "team_wr":      round(team_wr, 3),
            "premade_score": round(premade_score, 3),
        })
    rows.sort(key=lambda r: -r["same_team"])
    with out_path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    return len(rows)


def probe_loop():
    push_log(f"[probe] 启动. 数据目录: {DATA_DIR}")
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    last_phase = None
    last_me_pull = 0
    last_history_pull = 0
    last_mastery_pull = 0
    last_basics_collect = 0       # 闲时 summoner/ranked/mastery 写盘
    last_mh_collect     = 0       # match-history 拉取 + normalized append
    seen_eog_gids: set = set()
    seen_game_ids = _load_seen_game_ids()
    push_log(f"[collect] 启动: 已采集 {len(seen_game_ids)} 局历史")

    while True:
        try:
            token, port = get_auth()
        except RuntimeError:
            if STATE["lcu_online"]:
                _set_state(lcu_online=False, phase="", champ_select=None)
                _broadcast("state", json.dumps(_state_snapshot(), ensure_ascii=False))
                push_log("[probe] 客户端已断开")
            else:
                # 静默轮询
                pass
            time.sleep(WAIT_CLIENT)
            continue

        api = LCU(token, port)
        if not STATE["lcu_online"]:
            push_log(f"[probe] ✓ 已连接客户端 (port={port})")
            _set_state(lcu_online=True)
            # 立即拉一次基础信息
            try:
                STATE["me"].update(_build_me(api))
            except Exception as e:
                push_log(f"[probe] me 拉取失败: {e}")
            last_me_pull = time.time()
            # 立即写盘一次
            try:
                collect_basics(api)
                last_basics_collect = time.time()
                push_log("[collect] 已写当日 summoner/ranked/mastery 快照")
            except Exception as e:
                push_log(f"[collect] basics 失败: {type(e).__name__}: {e}")
            _broadcast("state", json.dumps(_state_snapshot(), ensure_ascii=False))

        # 定期刷新 me/mastery (5 min) - 内存
        now = time.time()
        if now - last_me_pull > 300:
            try:
                STATE["me"].update(_build_me(api))
            except Exception:
                pass
            last_me_pull = now
        if now - last_mastery_pull > 600:
            try:
                m = _build_mastery(api)
                if m:
                    STATE["mastery"].clear(); STATE["mastery"].update(m)
            except Exception:
                pass
            last_mastery_pull = now
        if now - last_history_pull > 600 and STATE["me"]["puuid"]:
            try:
                h = _build_champ_history(api, STATE["me"]["puuid"])
                if h:
                    STATE["my_champ_history"].clear()
                    STATE["my_champ_history"].update(h)
            except Exception:
                pass
            last_history_pull = now

        # 持久化采集: 闲时 (basics 10min, match-history 30min)
        if now - last_basics_collect > 600:
            try: collect_basics(api)
            except Exception as e: push_log(f"[collect] basics: {e}")
            last_basics_collect = now
        if now - last_mh_collect > 1800 and STATE["me"]["puuid"]:
            try:
                new_n = collect_match_history(api, STATE["me"]["puuid"], seen_game_ids)
                if new_n:
                    recompute_cooccurrence(STATE["me"]["puuid"])
                    push_log(f"[collect] cooccurrence 已重算")
                    # 顺便刷新 profile 数据 (供下次选人推荐用)
                    try:
                        regen_profiles()
                    except Exception as e:
                        push_log(f"[collect] regen-profiles: {e}")
            except Exception as e:
                push_log(f"[collect] match-history: {type(e).__name__}: {e}")
            last_mh_collect = now

        # 读 phase
        phase = api.get("/lol-gameflow/v1/gameflow-phase") or ""
        if isinstance(phase, str):
            phase = phase.strip().strip('"')
        else:
            phase = str(phase)

        if phase != last_phase:
            push_log(f"[probe] phase: {last_phase or 'None'} → {phase or 'None'}")
            last_phase = phase
            _set_state(phase=phase)

        if phase == "ChampSelect":
            sess = api.get("/lol-champ-select/v1/session")
            cs = _build_champ_select(api, sess, STATE["me"]["puuid"])
            if cs:
                with _state_lock:
                    STATE["champ_select"] = cs
                    STATE["ts"] = time.time()
                _broadcast("state", json.dumps(_state_snapshot(), ensure_ascii=False))
                # 写盘: 选人 session 快照 + 队友画像缓存 + 处理后的 view 快照 (供 FFAN 重启恢复)
                try:
                    collect_champ_select_snapshot(sess)
                    _write_json(ME_DIR / "last_champ_select_view.json", cs)
                    puuids = [(c.get("puuid") or "") for c in (sess.get("myTeam") or [])]
                    collect_player_cache(api, puuids)
                except Exception as e:
                    push_log(f"[collect] champ_select: {e}")
            time.sleep(CS_POLL)
            continue

        # 离开选人: 不再清空, 改成 "上一局" (issue 2)
        if STATE.get("champ_select"):
            with _state_lock:
                last = dict(STATE["champ_select"])
                last["ended_at"] = time.time()
                last["ended_phase"] = phase or "Idle"
                STATE["last_champ_select"] = last
                STATE["champ_select"] = None
                STATE["ts"] = time.time()
            try:
                _write_json(ME_DIR / "last_champ_select_view.json", last)
            except Exception:
                pass
            _broadcast("state", json.dumps(_state_snapshot(), ensure_ascii=False))
            push_log(f"[probe] 选人结束 → 切到「上一局」展示, phase={phase}")

        # 局后: 抓 EOG 结算块 + 强制再拉一次 match-history
        if phase in ("PreEndOfGame", "EndOfGame", "WaitingForStats"):
            try:
                gid = collect_eog(api, seen_eog_gids)
                if gid:
                    push_log(f"[collect] EOG 已抓: gameId={gid}")
            except Exception as e:
                push_log(f"[collect] eog: {e}")
            # 局后立刻拉 match-history (新一局应该已经入库)
            if STATE["me"]["puuid"]:
                try:
                    new_n = collect_match_history(api, STATE["me"]["puuid"],
                                                  seen_game_ids, max_pages=1)
                    if new_n:
                        recompute_cooccurrence(STATE["me"]["puuid"])
                        last_mh_collect = time.time()
                        try: regen_profiles()
                        except Exception: pass
                except Exception as e:
                    push_log(f"[collect] post-game mh: {e}")

        time.sleep(PHASE_POLL)


# ============================================================================
# 7. HTTP 服务器 (单页 + SSE + API)
# ============================================================================
class _Server(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send(self, status, body, ctype="application/json; charset=utf-8", extra=None):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False)
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        if extra:
            for k, v in extra.items():
                self.send_header(k, v)
        self.end_headers()
        try:
            self.wfile.write(body)
        except Exception:
            pass

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        qs = self.path.split("?", 1)[1] if "?" in self.path else ""
        params = dict(p.split("=", 1) if "=" in p else (p, "")
                      for p in qs.split("&") if p)

        if path == "/" or path == "/index.html":
            return self._serve_static("index.html", "text/html; charset=utf-8")
        if path.startswith("/static/"):
            fname = path[len("/static/"):]
            if "/" in fname or fname.startswith("."):
                self._send(403, {"err":"forbidden"}); return
            ctype = ("text/css; charset=utf-8" if fname.endswith(".css")
                     else "application/javascript; charset=utf-8" if fname.endswith(".js")
                     else "image/png" if fname.endswith(".png")
                     else "image/x-icon" if fname.endswith(".ico")
                     else "image/svg+xml" if fname.endswith(".svg")
                     else "text/plain; charset=utf-8")
            return self._serve_static(fname, ctype)

        if path == "/api/state":
            self._send(200, _state_snapshot()); return

        if path == "/api/hex/champion":
            try: cid = int(params.get("cid", "0"))
            except ValueError: cid = 0
            recs = _hex_recs_for_cid(cid, limit=12)
            name = (CHAMPIONS_BY_CID.get(cid) or {}).get("name") or ""
            self._send(200, {"cid": cid, "name": name, "recs": recs}); return

        if path == "/api/search":
            q = urllib.parse.unquote(params.get("q", "")).strip().lower()
            return self._search(q)

        if path == "/api/log":
            try: n = int(params.get("n", "200"))
            except ValueError: n = 200
            with _log_lock:
                rows = list(_LOG_RING)[-n:]
            self._send(200, rows); return

        if path == "/api/contribute/stats":
            return self._get_contribute_stats()
        if path == "/api/contribute/export":
            return self._get_contribute_export()

        if path == "/api/match_history":
            try: lim = int(params.get("limit", "30"))
            except ValueError: lim = 30
            self._send(200, {"items": _read_match_history(lim)}); return

        if path == "/api/game_detail":
            gid = (params.get("gid") or "").strip()
            detail = _read_game_detail(gid) if gid else None
            if not detail:
                self._send(404, {"err": f"gid={gid} 无记录或 eog.json 缺失"}); return
            self._send(200, detail); return

        if path == "/api/game/recap":
            return self._get_game_recap()

        if path == "/stream":
            return self._stream()

        self._send(404, {"err": "not found"})

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path == "/api/refresh":
            t = threading.Thread(target=_refresh_run, daemon=True); t.start()
            self._send(200, {"ok": True, "msg": "refresh started"}); return

        if path == "/api/profile/persona":
            return self._post_persona()

        if path == "/api/coach/feedback":
            return self._post_coach_feedback()

        if path == "/api/contribute/consent":
            return self._post_contribute_consent()
        if path == "/api/contribute/clear":
            return self._post_contribute_clear()

        if path == "/api/game/recap":
            return self._post_game_recap()

        self._send(404, {"err": "not found"})

    def _post_coach_feedback(self):
        """用户对教练发言的反馈 → data/coach/feedback.jsonl. DPO 偏好对源.

        Body JSON: {"ref": str, "rating": "good"|"bad"|"edit",
                    "rewrite": str?, "comment": str?, "contribute": bool?}
          - ref         = STATE.champ_select.coach.ref ("<gid>|<stage>")
          - rating      = good | bad | edit
          - rewrite     = 用户改写的台词 (rating=edit 时填)
          - comment     = 自由备注
          - contribute  = true 时, 另存一份脱敏副本到 data/contributed/ (opt-in)
        """
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception as e:
            self._send(400, {"err": f"bad json: {e}"}); return
        ref       = (body.get("ref") or "").strip()
        rating    = (body.get("rating") or "").strip().lower()
        rewrite   = (body.get("rewrite") or "").strip()
        comment   = (body.get("comment") or "").strip()
        contribute = bool(body.get("contribute"))
        if rating not in ("good", "bad", "edit"):
            self._send(400, {"err": "rating 必须是 good/bad/edit"}); return
        if rating == "edit" and not rewrite:
            self._send(400, {"err": "rating=edit 必须带 rewrite"}); return

        # 顺手捕获被评价的发言原文 (snapshot, 离线训练时不用反查 history)
        cs = STATE.get("champ_select") or {}
        coach_obj = cs.get("coach") or {}
        snapshot = {
            "pre_game":  coach_obj.get("pre_game", ""),
            "psych":     list(coach_obj.get("psych") or []),
        }

        row = {
            "ref":       ref,
            "rating":    rating,
            "rewrite":   rewrite,
            "comment":   comment,
            "snapshot":  snapshot,
            "my_puuid":  (STATE.get("me") or {}).get("puuid", ""),
        }
        try:
            _write_jsonl_v2(COACH_DIR / "feedback.jsonl", row, schema_version=1)
        except Exception as e:
            self._send(500, {"err": f"写入失败: {e}"}); return
        contributed_path = None
        if contribute:
            try:
                contributed_path = _save_contribution(row)
            except Exception as e:
                push_log(f"[contribute] 保存失败: {e}")
        push_log(f"[coach] feedback ← {rating}"
                 + (" +contrib" if contributed_path else "")
                 + f" ref={ref[:24]}")
        self._send(200, {
            "ok": True, "rating": rating,
            "contributed": bool(contributed_path),
        })

    # ---- 训练贡献 (opt-in, 用户主动) ----
    def _list_contrib_files(self):
        """所有 opt-in 贡献文件: feedback_*.json (教练点评反馈) + recap_*.json (对局复盘)"""
        if not CONTRIB_DIR.exists(): return []
        out = []
        for pat in ("feedback_*.json", "recap_*.json"):
            out.extend(CONTRIB_DIR.glob(pat))
        return sorted(out)

    def _get_contribute_stats(self):
        files = self._list_contrib_files()
        n_feedback = sum(1 for f in files if f.name.startswith("feedback_"))
        n_recap    = sum(1 for f in files if f.name.startswith("recap_"))
        consent = _load_contrib_consent()
        self._send(200, {
            "pending":     len(files),
            "by_kind":     {"feedback": n_feedback, "recap": n_recap},
            "consent":     consent,
            "anon_id":     _anon_contributor_id(),
            "dir":         str(CONTRIB_DIR),
            "upload":      _contrib_upload_target(),
        })

    def _get_contribute_export(self):
        """打包所有待贡献样本成单个 JSON, 直接 download."""
        files = self._list_contrib_files()
        items = []
        for p in files:
            try:
                items.append(json.loads(p.read_text(encoding="utf-8")))
            except Exception:
                continue
        bundle = {
            "bundle_v":  1,
            "bundle_ts": dt.datetime.now().isoformat(timespec="seconds"),
            "anon_id":   _anon_contributor_id(),
            "items":     items,
            "count":     len(items),
        }
        payload = json.dumps(bundle, ensure_ascii=False, indent=2).encode("utf-8")
        ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Disposition",
                         f'attachment; filename="ffan_contrib_{ts}.json"')
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        try: self.wfile.write(payload)
        except Exception: pass

    def _post_contribute_consent(self):
        """记录/撤销用户同意贡献的元信息.

        Body: {"action": "grant"|"revoke", "note": str?}
        """
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception as e:
            self._send(400, {"err": f"bad json: {e}"}); return
        action = (body.get("action") or "").strip().lower()
        if action not in ("grant", "revoke"):
            self._send(400, {"err": "action 必须是 grant/revoke"}); return
        consent = {
            "action":  action,
            "note":    (body.get("note") or "").strip(),
            "ts":      dt.datetime.now().isoformat(timespec="seconds"),
            "anon_id": _anon_contributor_id(),
        }
        try:
            CONTRIB_DIR.mkdir(parents=True, exist_ok=True)
            (CONTRIB_DIR / "consent.json").write_text(
                json.dumps(consent, ensure_ascii=False, indent=2),
                encoding="utf-8")
        except Exception as e:
            self._send(500, {"err": f"写入失败: {e}"}); return
        push_log(f"[contribute] consent {action}")
        self._send(200, {"ok": True, "consent": consent})

    def _post_contribute_clear(self):
        """清空待贡献样本 (用户已上传/不想再保留)."""
        n = 0
        for p in self._list_contrib_files():
            try: p.unlink(); n += 1
            except Exception: pass
        push_log(f"[contribute] 清空 {n} 条")
        self._send(200, {"ok": True, "cleared": n})

    def _post_game_recap(self):
        """保存对局复盘. body: {gid, mood, free_text, tags?, contribute?}"""
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception as e:
            self._send(400, {"err": f"bad json: {e}"}); return
        gid = str(body.get("gid") or "").strip()
        if not gid:
            self._send(400, {"err": "gid 必填"}); return
        mood = (body.get("mood") or "").strip().lower() or None
        if mood and mood not in _RECAP_MOODS:
            self._send(400, {"err": f"mood 须为 {sorted(_RECAP_MOODS)} 之一"}); return
        free_text = (body.get("free_text") or "").strip()
        tags_raw  = body.get("tags") or []
        tags = [str(t).strip() for t in tags_raw if str(t).strip()][:10]
        if not free_text and not mood and not tags:
            self._send(400, {"err": "复盘内容不能完全为空"}); return
        contribute = bool(body.get("contribute"))

        try:
            payload = _save_game_recap(gid, mood, free_text, tags)
        except Exception as e:
            self._send(500, {"err": f"写入失败: {e}"}); return

        contributed_path = None
        if contribute:
            try:
                contributed_path = _save_game_recap_contribution(gid, mood, free_text, tags)
            except Exception as e:
                push_log(f"[contribute] recap 保存失败: {e}")

        push_log(f"[recap] gid={gid} mood={mood or '-'} {len(free_text)}字"
                 + (" +contrib" if contributed_path else ""))
        self._send(200, {
            "ok":          True,
            "recap":       payload,
            "contributed": bool(contributed_path),
        })

    def _get_game_recap(self):
        gid = ""
        if "?" in self.path:
            qs = self.path.split("?", 1)[1]
            for kv in qs.split("&"):
                if kv.startswith("gid="): gid = kv[4:].strip()
        if not gid:
            self._send(400, {"err": "gid 必填"}); return
        r = _load_game_recap(gid)
        self._send(200, {"gid": gid, "recap": r})

    def _post_persona(self):
        """更新一个 puuid 的 persona.

        Body JSON 支持两种 action:
          {"puuid": str, "kind": "self"|"peer", "text": str}            ← 默认: add
              kind=self: 覆盖 persona.self_voice
              kind=peer: 追加到 persona.peer_voices

          {"puuid": str, "action": "delete_peer", "index": int}         ← 删除某条
          {"puuid": str, "action": "clear_self"}                        ← 清空 self_voice
        """
        try:
            length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception as e:
            self._send(400, {"err": f"bad json: {e}"}); return
        puuid  = (body.get("puuid") or "").strip()
        action = (body.get("action") or "add").strip().lower()
        if not puuid:
            self._send(400, {"err": "需要 puuid"}); return

        full = _load_full_profiles()
        if full is None:
            self._send(500, {"err": "profiles.json 读取失败"}); return
        prof = full.get(puuid)
        if not isinstance(prof, dict):
            prof = dict(PROFILE_DEFAULTS); full[puuid] = prof
        persona = _ensure_persona(prof)

        if action == "delete_peer":
            try: idx = int(body.get("index"))
            except (TypeError, ValueError):
                self._send(400, {"err": "index 必须是整数"}); return
            voices = persona.get("peer_voices") or []
            if idx < 0 or idx >= len(voices):
                self._send(400, {"err": f"index 越界 (peer_voices 长 {len(voices)})"}); return
            removed = voices.pop(idx)
            persona["peer_voices"] = voices
            log_tag = f"删 peer[{idx}]={removed[:20]}"
        elif action == "clear_self":
            persona["self_voice"] = ""
            log_tag = "清 self_voice"
        else:  # add
            kind = (body.get("kind") or "").strip()
            text = (body.get("text") or "").strip()
            if kind not in ("self", "peer") or not text:
                self._send(400, {"err": "add: 需要 kind(self|peer) + 非空 text"}); return
            if kind == "self":
                persona["self_voice"] = text
                log_tag = "覆盖 self_voice"
            else:
                persona["peer_voices"].append(text)
                log_tag = f"加 peer (共 {len(persona['peer_voices'])} 条)"

        persona["updated_at"] = dt.datetime.now().isoformat(timespec="seconds")
        try:
            _save_full_profiles(full)
        except Exception as e:
            self._send(500, {"err": f"写入失败: {e}"}); return

        # 热重载内存并广播 state
        load_profiles()
        if _IS_DEMO:
            try: load_demo_state()
            except Exception: pass
        _broadcast("state", json.dumps(_state_snapshot(), ensure_ascii=False))
        push_log(f"[persona] {log_tag} → {prof.get('nickname','?')} ({puuid[:8]})")
        self._send(200, {
            "ok":          True,
            "action":      action,
            "self_voice":  persona.get("self_voice") or "",
            "peer_voices": list(persona.get("peer_voices") or []),
            "peer_count":  len(persona.get("peer_voices") or []),
        })

    # ---- helpers ----
    def _serve_static(self, filename, content_type):
        path = WEB_DIR / filename
        if not path.exists():
            self._send(404, {"err": f"missing web/{filename}"}); return
        try:
            data = path.read_bytes()
        except Exception as e:
            self._send(500, {"err": str(e)}); return
        self._send(200, data, content_type)

    def _search(self, q):
        if not q:
            self._send(200, {"champions": [], "hex": []}); return
        chs = []
        for cid, info in CHAMPIONS_BY_CID.items():
            name = info.get("name") or ""
            alias = info.get("alias") or ""
            if q in name.lower() or q in alias.lower() or q in name:
                roles = info.get("roles") or []
                role_zh = "/".join(_ROLE_ZH.get(r, r) for r in roles[:2]) or "—"
                chs.append({
                    "cid": cid, "name": name, "alias": alias,
                    "role": role_zh,
                    "rec_count": len(APEX_PER_CID.get(str(cid), [])),
                })
            if len(chs) >= 8: break
        hex_rows = []
        for name, meta in HEX_DICT.items():
            if q in name.lower() or q in name:
                hex_rows.append({"name": name, "tier": meta.get("tier", ""),
                                 "desc": (meta.get("desc") or "")[:120]})
                if len(hex_rows) >= 6: break
        self._send(200, {"champions": chs, "hex": hex_rows})

    def _stream(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        ev = threading.Event()
        dq = deque(maxlen=200)
        with _subs_lock:
            _subs.append((ev, dq))
        # 立即推一帧 state
        try:
            self.wfile.write(b": connected\n\n")
            payload = json.dumps(_state_snapshot(), ensure_ascii=False)
            self.wfile.write(f"event: state\ndata: {payload}\n\n".encode("utf-8"))
            self.wfile.flush()
        except Exception:
            self._unsubscribe(ev, dq); return
        last_ping = time.time()
        try:
            while True:
                if ev.wait(timeout=15):
                    ev.clear()
                    while dq:
                        kind, payload = dq.popleft()
                        msg = f"event: {kind}\ndata: {payload}\n\n".encode("utf-8")
                        self.wfile.write(msg); self.wfile.flush()
                else:
                    if time.time() - last_ping > 15:
                        self.wfile.write(b": ping\n\n"); self.wfile.flush()
                        last_ping = time.time()
        except Exception:
            pass
        finally:
            self._unsubscribe(ev, dq)

    def _unsubscribe(self, ev, dq):
        with _subs_lock:
            try: _subs.remove((ev, dq))
            except ValueError: pass


# ============================================================================
# 8. profiles.json 自动生成 (从 normalized 数据聚合, 保留 manual 字段)
# ============================================================================
# 设计:
#   profiles[puuid] = {
#     # ----- manual: 用户手填, regen 永远保留 -----
#     "nickname":       str,    # 显示名 (LCU 拉到会覆盖运行时显示, 不动 JSON)
#     "self_role":      str,    # adc/ap/assassin/tank/support
#     "self_desc":      str,    # 自我描述
#     "tags":           [str],  # 短标签数组, 第一个会展示在卡片
#     "peer_review":    str,    # 他人评价
#     "habits":         str,    # 玩法习惯
#     "skill":          "S/A/B/C/D",
#     "carry_priority": 0~10,   # 围绕他打的优先级
#     "favorite_champ_ids": [int],  # 拿手英雄 cid 列表, 选到时 +15 分
#     # ----- auto: regen 时重算覆盖 -----
#     "auto": {
#       "name_from_history": str,
#       "tag_from_history":  str,
#       "games_total":       int,    # 历史总局数
#       "wins_total":        int,
#       "wr_total":          float,  # 0~1
#       "games_with_me":     int,    # 同队的局数
#       "wins_with_me":      int,
#       "wr_with_me":        float,
#       "premade_score":     float,  # 0~1, 来自 cooccurrence
#       "top_champs": [              # 前 5 个常用英雄
#         {"cid":int, "name":str, "games":int, "wins":int, "wr":float}
#       ],
#       "generated_at":      "ISO-8601 字符串",
#     },
#     # ----- manual but auto-discovered: regen 会自动加, 但保留用户修改 -----
#     "premade_with":   [puuid_str],
#   }
PROFILE_MANUAL_KEYS = (
    "nickname", "self_role", "self_desc", "tags", "peer_review",
    "habits", "skill", "carry_priority", "favorite_champ_ids", "premade_with",
    "persona",
)
PROFILE_DEFAULTS = {
    "nickname": "", "self_role": "", "self_desc": "", "tags": [],
    "peer_review": "", "habits": "", "skill": "", "carry_priority": 0,
    "favorite_champ_ids": [], "premade_with": [],
    "persona": {"self_voice": "", "peer_voices": [], "updated_at": ""},
    "psych": {
        "axes": {
            "competitive_style": "", "comm_style": "", "pressure_response": "",
            "motivation_type": "", "tilt_profile": ""
        },
        "adolescent_traps": [],
        "interventions_ok": [],
        "interventions_no": [],
        "axes_source": "",         # manual / auto_inferred / mixed
        "axes_confidence": 0.0,
        "axes_updated_at": ""
    },
}


# ============================================================================
# psych_state — 玩家动态心理状态 (每次 regen-profiles 重算, 持续监控)
# 输出: data/players/<puuid>/psych_state.json (覆盖最新)
# 历史: data/players/<puuid>/psych_timeline.jsonl (变化时追加, 长期成长曲线)
# ============================================================================
def _compute_streak_now(form_l10):
    """form_l10 = ['W','L','W',...]  newest first. 返回 streak_now (负=连负, 正=连胜).

    例: ['W','W','L','W'] → 1  (W streak from newest)
         ['L','L','L'] → -3
    """
    if not form_l10: return 0
    first = form_l10[0]
    n = 0
    for r in form_l10:
        if r == first: n += 1
        else: break
    return n if first == "W" else -n


def _longest_streak(form_list, kind="L"):
    """form list 里最长连续 kind 的长度. kind in {'W', 'L'}."""
    if not form_list: return 0
    best = cur = 0
    for r in form_list:
        if r == kind:
            cur += 1
            best = max(best, cur)
        else:
            cur = 0
    return best


def _compute_psych_state(puuid, recent_games_30d, form_l10, axes=None):
    """计算玩家心理状态. 见 PSYCH_SCHEMA.md.

    recent_games_30d: list of (ts, won) — 最近 30 天的对局, 任意顺序
    form_l10:         list of 'W'/'L' — 最近 10 局, **newest first**
    axes:             profile.psych.axes (optional, 用于 tilt level 校准)
    """
    axes = axes or {}
    n10 = len(form_l10)
    wins10 = sum(1 for r in form_l10 if r == "W")
    wr_l10 = round(wins10 / n10, 3) if n10 else 0.0

    # 衰减加权 (exp(-i/3)): 越近的局权重越高
    decay_w = [pow(2.718, -i / 3) for i in range(n10)]
    decay_w_total = sum(decay_w) or 1.0
    decay_wins = sum(w for w, r in zip(decay_w, form_l10) if r == "W")
    decay_score = round(decay_wins / decay_w_total, 3)

    # 30 天范围
    wins30d = sum(1 for _, won in recent_games_30d if won)
    n30d = len(recent_games_30d)
    wr_l30d = round(wins30d / n30d, 3) if n30d else 0.0

    # streak
    streak_now = _compute_streak_now(form_l10)

    # 30 天内最长连负/连胜 (按时间排好的 form list)
    # 需要把 30d 按时间排序后取 W/L 列表
    sorted_30d = sorted(recent_games_30d, key=lambda x: x[0])  # oldest → newest
    form_30d = ["W" if won else "L" for _, won in sorted_30d]
    longest_loss = _longest_streak(form_30d, "L")
    longest_win  = _longest_streak(form_30d, "W")

    # tilt score (0-1)
    streak_factor = min(1.0, max(0, -streak_now) / 5.0)
    form_factor   = 0.0 if wr_l10 >= 0.7 else (1.0 if wr_l10 <= 0.3 else (0.7 - wr_l10) / 0.4)
    decay_factor  = 1.0 - decay_score if decay_score < 0.5 else 0.0
    tilt_score = round(streak_factor * 0.5 + form_factor * 0.3 + decay_factor * 0.2, 3)

    # tilt_profile 校准: 易燃型阈值降低 (更早进入 mild)
    tilt_thresh = {
        "易燃":   {"mild": 0.25, "moderate": 0.45, "severe": 0.65},
        "慢热":   {"mild": 0.35, "moderate": 0.55, "severe": 0.75},
        "钝感":   {"mild": 0.45, "moderate": 0.65, "severe": 0.85},
        "自调节": {"mild": 0.35, "moderate": 0.55, "severe": 0.75},
    }.get(axes.get("tilt_profile") or "", {"mild": 0.3, "moderate": 0.5, "severe": 0.75})

    if tilt_score >= tilt_thresh["severe"]:   level = "severe"
    elif tilt_score >= tilt_thresh["moderate"]: level = "moderate"
    elif tilt_score >= tilt_thresh["mild"]:    level = "mild"
    else:                                       level = "calm"

    # signals
    signals = []
    if streak_now <= -3: signals.append(f"近 {-streak_now} 局连败")
    elif streak_now >= 4: signals.append(f"近 {streak_now} 局连胜")
    if wr_l10 <= 0.3 and n10 >= 5: signals.append(f"近 {n10} 局胜率 {int(wr_l10*100)}%")
    elif wr_l10 >= 0.7 and n10 >= 5: signals.append(f"近 {n10} 局手感好 ({int(wr_l10*100)}%)")
    if decay_score < 0.4 and n10 >= 5: signals.append("加权胜率持续下滑")
    if longest_loss >= 5: signals.append(f"近 30 天最长 {longest_loss} 连负")

    # mood 推断 (规则版, 后期可让 LLM 改写)
    if level == "calm":         mood = "状态稳定"
    elif level == "mild":       mood = "略上头, 留意"
    elif level == "moderate":   mood = "上头中, 倾向冲动决策"
    else:                       mood = "严重 tilt, 建议下机"

    # self_efficacy 提示
    if wr_l30d >= 0.6:           self_eff = "high"
    elif wr_l30d <= 0.4 and longest_loss >= 4: self_eff = "low"
    else:                                       self_eff = "mid"

    # 社交风险 (暂时只在严重 tilt 时标 'watch', 真危机检测靠运行时正则)
    social_risk = "watch" if level == "severe" else "none"

    return {
        "_v": 1,
        "puuid": puuid,
        "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "_patch": CURRENT_PATCH or "",
        "form": {
            "l10":           form_l10,
            "wr_l10":        wr_l10,
            "wr_l30d":       wr_l30d,
            "decay_score":   decay_score,
        },
        "streak": {
            "now":             streak_now,
            "longest_loss_l30d": -longest_loss if longest_loss else 0,
            "longest_win_l30d":  longest_win,
        },
        "tilt": {
            "score":      tilt_score,
            "level":      level,
            "components": {
                "streak_factor": round(streak_factor, 3),
                "form_factor":   round(form_factor, 3),
                "decay_factor":  round(decay_factor, 3),
            },
        },
        "mood_inference":      mood,
        "signals":             signals,
        "self_efficacy_hint":  self_eff,
        "social_risk":         social_risk,
    }


def _append_psych_timeline(puuid, new_state, prev_state):
    """状态变化时 append 一条 timeline (持续成长监控). 没变就不写.

    监控维度:
      - tilt.level 变化 (calm/mild/moderate/severe 之间跳转)
      - self_efficacy_hint 变化
      - streak 重大变化 (跨越 0 或超过 ±4)
    """
    if not prev_state:
        # 第一次写: 标记起点
        _write_jsonl_v2(_player_dir(puuid) / "psych_timeline.jsonl", {
            "kind":   "first_seen",
            "level":  new_state["tilt"]["level"],
            "wr_l10": new_state["form"]["wr_l10"],
        })
        return

    changes = []
    pl = prev_state.get("tilt", {}).get("level")
    nl = new_state["tilt"]["level"]
    if pl != nl:
        changes.append({"kind": "tilt_level", "from": pl, "to": nl})

    pe = prev_state.get("self_efficacy_hint")
    ne = new_state["self_efficacy_hint"]
    if pe != ne and pe:
        changes.append({"kind": "self_efficacy", "from": pe, "to": ne})

    ps = prev_state.get("streak", {}).get("now", 0)
    ns = new_state["streak"]["now"]
    if (ps >= 0) != (ns >= 0) and abs(ns - ps) >= 2:
        changes.append({"kind": "streak_flip", "from": ps, "to": ns})

    for c in changes:
        _write_jsonl_v2(_player_dir(puuid) / "psych_timeline.jsonl", {
            **c,
            "context": {
                "wr_l10":  new_state["form"]["wr_l10"],
                "signals": new_state["signals"],
            },
        })


def _save_psych_state(puuid, state):
    """写 psych_state.json (覆盖) + 变化时 timeline append."""
    path = _player_dir(puuid) / "psych_state.json"
    prev = None
    if path.exists():
        try: prev = json.loads(path.read_text(encoding="utf-8"))
        except Exception: pass
    _write_json(path, state)
    try: _append_psych_timeline(puuid, state, prev)
    except Exception as e:
        push_log(f"[psych] timeline append 失败 {puuid[:8]}: {e}")


def regen_profiles(min_games_with_me=3, premade_threshold=0.6):
    """从 data/_cache/normalized 自动重算 profiles.json. 保留 manual 字段.

    only 收录: 和我同队过 >= min_games_with_me 局的 puuid + cooccurrence 里出现的.
    """
    nm_dir = CACHE_DIR / "normalized"
    if not (nm_dir / "participants.jsonl").exists():
        push_log("[regen] 缺 participants.jsonl, 跳过")
        return None

    # 1. 找 my_puuid (最新一天的 summoner/current.json)
    days = sorted([p for p in DATA_DIR.iterdir()
                   if p.is_dir() and re.match(r"\d{4}-\d{2}-\d{2}$", p.name)],
                  reverse=True) if DATA_DIR.exists() else []
    my_puuid = ""
    for d in days:
        cur = d / "summoner" / "current.json"
        if cur.exists():
            try:
                my_puuid = json.loads(cur.read_text(encoding="utf-8")).get("puuid") or ""
                if my_puuid: break
            except Exception: pass
    if not my_puuid:
        push_log("[regen] 找不到 my_puuid, 跳过")
        return None

    # 2. 读 games.jsonl 拿 game_id -> ts (用于 recent_focus / recent_form)
    games_ts = {}    # gid -> unix ts
    gf = nm_dir / "games.jsonl"
    if gf.exists():
        with gf.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line: continue
                try: g = json.loads(line)
                except: continue
                gid = g.get("game_id")
                ts = g.get("ts") or 0
                if not (gid and ts): continue
                # ts 可能是 ISO 字符串 (2026-04-25T...Z) 或 Unix 数字
                if isinstance(ts, (int, float)):
                    games_ts[gid] = float(ts)
                else:
                    try:
                        s = str(ts).replace("Z", "+00:00")
                        games_ts[gid] = dt.datetime.fromisoformat(s).timestamp()
                    except Exception:
                        pass
    now_ts = time.time()
    cutoff_30d = now_ts - 30 * 86400

    # 3. 读 participants -> 聚合每个 puuid 的英雄战绩
    from collections import defaultdict
    per_puuid = defaultdict(lambda: {
        "name": "", "tag": "", "games": 0, "wins": 0,
        "champ": defaultdict(lambda: {"games": 0, "wins": 0}),
        "recent_champ": defaultdict(lambda: {"games": 0, "wins": 0}),
        "recent_games": [],   # 最近时序: (ts, won) 列表
        "games_in_my_team": 0, "wins_in_my_team": 0,
    })
    # 先找出我所有的 (game_id, team_id)
    my_team_in_game = {}
    with (nm_dir / "participants.jsonl").open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try: r = json.loads(line)
            except: continue
            if r.get("puuid") == my_puuid:
                my_team_in_game[r.get("game_id")] = r.get("team_id")
    # 第二遍: 聚合 (包含我自己, 但同队字段单独处理)
    with (nm_dir / "participants.jsonl").open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line: continue
            try: r = json.loads(line)
            except: continue
            puuid = r.get("puuid") or ""
            if not puuid: continue
            s = per_puuid[puuid]
            s["name"] = r.get("game_name") or s["name"]
            s["tag"]  = r.get("tag_line")  or s["tag"]
            s["games"] += 1
            won = bool(r.get("win"))
            if won: s["wins"] += 1
            cid = r.get("champion_id") or 0
            gid = r.get("game_id")
            ts  = games_ts.get(gid, 0)
            if cid:
                c = s["champ"][cid]
                c["games"] += 1
                if won: c["wins"] += 1
                if ts >= cutoff_30d:
                    rc = s["recent_champ"][cid]
                    rc["games"] += 1
                    if won: rc["wins"] += 1
            if ts:
                s["recent_games"].append((ts, won))
            # 同队的 (自己跳过, 否则等于自己的总数)
            if puuid == my_puuid: continue
            gid, tid = r.get("game_id"), r.get("team_id")
            if gid in my_team_in_game and my_team_in_game[gid] == tid:
                s["games_in_my_team"] += 1
                if won: s["wins_in_my_team"] += 1

    # 3. 读 cooccurrence -> premade
    premade_score = {}  # puuid -> score
    cf = nm_dir / "cooccurrence.jsonl"
    if cf.exists():
        with cf.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line: continue
                try: c = json.loads(line)
                except: continue
                if my_puuid not in (c.get("puuid_a"), c.get("puuid_b")):
                    continue
                other = c["puuid_b"] if c["puuid_a"] == my_puuid else c["puuid_a"]
                premade_score[other] = float(c.get("premade_score") or 0)

    # 4. 读旧 profiles, 保留 manual
    pf_path = DATA_DIR / "profiles.json"
    existing = {}
    if pf_path.exists():
        try:
            existing = json.loads(pf_path.read_text(encoding="utf-8"))
        except Exception as e:
            push_log(f"[regen] 旧 profiles 解析失败 (将重建): {e}")

    generated_at = dt.datetime.now().isoformat(timespec="seconds")

    # 5. 输出
    out = {
        "_meta": {
            "format_version": "1.0",
            "generated_at": generated_at,
            "my_puuid": my_puuid,
            "min_games_with_me": min_games_with_me,
            "premade_threshold": premade_threshold,
            "note": "见 PROFILES.md. 删除 auto 字段也行, regen 会重建.",
        }
    }
    kept = sorted(per_puuid.items(),
                  key=lambda kv: kv[1]["games_in_my_team"], reverse=True)
    for puuid, s in kept:
        # 自己始终保留, 其它人需要 >= min_games_with_me
        if puuid != my_puuid and s["games_in_my_team"] < min_games_with_me:
            continue
        # top champs (全期)
        sorted_champs = sorted(s["champ"].items(),
                               key=lambda kv: kv[1]["games"], reverse=True)[:5]
        top_champs = [{
            "cid": cid,
            "name": (CHAMPIONS_BY_CID.get(cid) or {}).get("name") or f"#{cid}",
            "games": c["games"],
            "wins":  c["wins"],
            "wr":    round(c["wins"] / c["games"], 3) if c["games"] else 0,
        } for cid, c in sorted_champs]

        # recent_focus (最近 30 天 top 3)
        recent_sorted = sorted(s["recent_champ"].items(),
                               key=lambda kv: kv[1]["games"], reverse=True)[:3]
        recent_focus = [{
            "cid": cid,
            "name": (CHAMPIONS_BY_CID.get(cid) or {}).get("name") or f"#{cid}",
            "games": c["games"], "wins": c["wins"],
            "wr": round(c["wins"] / c["games"], 3) if c["games"] else 0,
        } for cid, c in recent_sorted]

        # recent_form (最近 10 局)
        recent_games = sorted(s["recent_games"], key=lambda x: x[0], reverse=True)[:10]
        rw = sum(1 for _, w in recent_games if w)
        rg = len(recent_games)
        recent_wr = round(rw / rg, 3) if rg else 0
        if rg >= 5:
            trend = "hot" if recent_wr >= 0.7 else ("cold" if recent_wr <= 0.3 else "normal")
        else:
            trend = "unknown"
        recent_form = {
            "last_n": rg, "wins": rw, "losses": rg - rw,
            "wr": recent_wr, "trend": trend,
        }

        wr_total = s["wins"] / s["games"] if s["games"] else 0
        wr_with_me = (s["wins_in_my_team"] / s["games_in_my_team"]
                      if s["games_in_my_team"] else 0)
        pre_s = premade_score.get(puuid, 0)

        # 保留 manual
        prev = existing.get(puuid) if isinstance(existing.get(puuid), dict) else {}
        merged = dict(PROFILE_DEFAULTS)
        for k in PROFILE_MANUAL_KEYS:
            if k in prev:
                merged[k] = prev[k]
        if not merged["nickname"]:
            merged["nickname"] = s["name"] or ""

        # premade_with 自动更新 (但用户也可手填)
        if pre_s >= premade_threshold:
            buddies = set(merged.get("premade_with") or [])
            buddies.add(my_puuid)
            merged["premade_with"] = sorted(buddies - {puuid})
        merged["auto"] = {
            "name_from_history": s["name"] or "",
            "tag_from_history":  s["tag"] or "",
            "games_total":       s["games"],
            "wins_total":        s["wins"],
            "wr_total":          round(wr_total, 3),
            "games_with_me":     s["games_in_my_team"],
            "wins_with_me":      s["wins_in_my_team"],
            "wr_with_me":        round(wr_with_me, 3),
            "premade_score":     round(pre_s, 3),
            "top_champs":        top_champs,
            "recent_focus":      recent_focus,
            "recent_form":       recent_form,
            "generated_at":      generated_at,
        }
        out[puuid] = merged

        # ---- psych_state (动态状态, 独立文件) ----
        # form_l10: newest first
        recent_sorted_desc = sorted(s["recent_games"], key=lambda x: x[0], reverse=True)
        form_l10 = ["W" if w else "L" for _, w in recent_sorted_desc[:10]]
        # 30 天内 (cutoff_30d 是个 unix ts 或 iso, 取决于调用; 我们重新算)
        cutoff_ts = time.time() - 30 * 86400
        recent_30d = [(t, w) for t, w in s["recent_games"]
                      if (isinstance(t, (int, float)) and t >= cutoff_ts)]
        if not recent_30d and s["recent_games"]:
            recent_30d = list(s["recent_games"])  # 没 ts 时退化用全部

        axes_for_calib = (merged.get("psych") or {}).get("axes") or {}
        psych_state = _compute_psych_state(puuid, recent_30d, form_l10,
                                           axes=axes_for_calib)
        try: _save_psych_state(puuid, psych_state)
        except Exception as e:
            push_log(f"[psych] state 写入失败 {puuid[:8]}: {e}")

    # 也保留旧 profiles 里我没在 normalized 里发现的 puuid (用户手填的)
    for puuid, prev in existing.items():
        if puuid.startswith("_") or not isinstance(prev, dict):
            continue
        if puuid not in out:
            # 保留 manual + 旧 auto
            out[puuid] = prev

    out["_meta"]["count"] = sum(1 for k in out if not k.startswith("_"))

    pf_path.write_text(
        json.dumps(out, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    push_log(f"[regen] ✓ 写入 {pf_path.name}: {out['_meta']['count']} 条 profile")
    return out


# ============================================================================
# 9. AI 辅助: ai-prompt + merge-profile
# ============================================================================
AI_PROMPT_TEMPLATE = """你是英雄联盟大乱斗 (ARAM/KIWI) 玩家画像分析助手。

# 任务
基于下方一个玩家的对局历史数据, 推断他的玩家画像。
**只输出一段 JSON, 不要任何解释/前后文/markdown 围栏**, 格式严格如下:

```json
{{
  "nickname": "<显示名, 通常保留原 nickname 即可>",
  "self_role": "<adc / ap / assassin / tank / support / jungle 之一>",
  "self_desc": "<15-30 字一句话总结此玩家的风格>",
  "tags": ["<2-4 个 2-4 字短标签>"],
  "peer_review": "<20-40 字, 其他人对他可能的评价>",
  "habits": "<15-30 字, 玩法习惯>",
  "skill": "<S/A/B/C/D 之一, 基于胜率和英雄复杂度>",
  "carry_priority": <0-10 整数, 围绕他打的优先级>,
  "favorite_champ_ids": [<3-5 个 championId 数字, 从 top_champs 里挑胜率高/局数多的>]
}}
```

# 评估标准
- carry_priority 综合考虑: 整体胜率 (wr_total) · 英雄池深度 (top_champs 数量) · 高胜率主玩英雄数
  - 8-10: 稳定高胜率 (>55%) + 多个拿手英雄
  - 5-7: 平均胜率 + 有几个拿手
  - 0-4: 胜率偏低 / 英雄池散
- skill 大致对应:
  - S: 总胜率 >= 55% 且 >= 50 局
  - A: 50-54% 且 >= 30 局
  - B: 45-50% 或局数 10-30
  - C: 40-45%
  - D: < 40% 或样本不足
- tags 从风格推断, 例: ["carry","上头"] / ["大核","心态稳"] / ["保护","团队"] / ["新人","求带"] / ["杂食","稳"]

# 玩家数据
"""


AI_PERSONA_TEMPLATE = """你是英雄联盟大乱斗 (ARAM/KIWI) 玩家人设语料生成助手。

# 任务
基于下方一个玩家的对局历史 + 现有简短画像, **生成他的自然语言人设语料**。
**只输出一段 JSON, 不要任何解释/前后文/markdown 围栏**, 格式严格如下:

```json
{
  "self_voice": "<150-300 字, 第一人称, 模拟该玩家自己说自己玩 ARAM 的风格. 要有口语化语气, 例: '我玩 Kayn 就要红色形态啊...看到能切的就切, 不上头不带打.' 基于他的 favorite_champ_ids / recent_focus / habits 推断>",
  "peer_voices": [
    "<队友自然口语评价, 20-60 字>",
    "<另一个视角, 不同语气>",
    "<再来一条简短的>"
  ]
}
```

# 要求
- self_voice 必须像真人在自说自话, 不要列条款, 不要写成第三人称
- peer_voices 至少 3 条, 视角和语气各不同 (可以一个褒一个调侃一个中性)
- 围绕该玩家的 favorite_champ_ids / recent_focus / wr_total 客观数据展开
- 不要编造没数据支撑的剧情 (例如他没有 favorite 含羞蓓蕾就别说他爱含羞蓓蕾)
- 这是给 AI 训练用的语料, **越像真人说话越好**

# 玩家数据
"""


_AI_INFER_PSYCH_TEMPLATE = """# 任务: 推断玩家心理画像 axes (5 维)

你看下面这个玩家的现有资料 (self_desc / persona.self_voice / persona.peer_voices /
tags / habits / auto 数据), 然后**仅输出一段 JSON**, 内容是给他 5 维 axes 标签 +
青春期 traps + 干预偏好.

可选值见 data/coach/kb/psychology/profile_axes.json. 简略:
- competitive_style: 攻击型 | 控制型 | 防守型 | 适应型
- comm_style:        指挥型 | 跟随型 | 独立型 | 协作型
- pressure_response: 冷血 | 高峰 | 崩盘 | 累积
- motivation_type:   胜利 | 表现 | 社交 | 进步
- tilt_profile:      易燃 | 慢热 | 钝感 | 自调节
- adolescent_traps:  T1(自我效能脆弱) | T2(同伴比较) | T3(冲动控制弱) |
                     T4(完美主义) | T5(失败容忍低) | T6(社交焦虑) — 可多选, 也可空

**JSON 格式 (严格按这个结构, 不要加多余字段):**

```json
{
  "axes": {
    "competitive_style": "<4选1>",
    "comm_style":        "<4选1>",
    "pressure_response": "<4选1>",
    "motivation_type":   "<4选1>",
    "tilt_profile":      "<4选1>"
  },
  "adolescent_traps":   ["T1","T3"],
  "interventions_ok":   ["数据展示","具体行为建议","重构 reframe"],
  "interventions_no":   ["讲大道理","和高手比较","归罪"],
  "axes_confidence":    0.7,
  "axes_reasoning":     "<3~5 句话解释为什么这样标>"
}
```

**重要**:
- 只输出 JSON, 不要其他文字 (我会用脚本 parse)
- confidence 0~1, 客观打分 — 资料少就 0.4~0.6, 充足就 0.7+
- reasoning 引用具体的 self_voice / peer_voices 关键短语, 不要空泛
- 没把握时填 "未定" 而不是猜

---

## 玩家资料

"""


def cmd_infer_psych(puuid):
    """生成给 AI 看的 prompt, 用于推断 axes. 用法:
        python rankprobe_lite.py infer-psych <puuid> > prompt.md
        # 把 prompt.md 喂给 Claude/GPT, 拿回 response.json
        python rankprobe_lite.py merge-psych <puuid> response.json
    """
    load_assets(verbose=False)
    load_profiles()
    profile = PROFILES.get(puuid)
    if not profile:
        sys.stderr.write(f"[!] profiles.json 里没有 puuid={puuid}\n")
        return 1
    out = _AI_INFER_PSYCH_TEMPLATE
    # 喂 manual + persona + auto, 不喂当前 psych (我们在推断它)
    snapshot = {
        k: v for k, v in profile.items()
        if k not in ("psych", "auto")
    }
    out += "```json\n" + json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n```\n\n"
    # auto 单独给, 但只挑 axes 相关的: top_champs / recent_form
    auto = profile.get("auto") or {}
    auto_snap = {
        "top_champs":   auto.get("top_champs"),
        "recent_focus": auto.get("recent_focus"),
        "recent_form":  auto.get("recent_form"),
        "wr_with_me":   auto.get("wr_with_me"),
        "games_with_me": auto.get("games_with_me"),
    }
    out += "## 历史 (auto, 仅相关)\n\n```json\n" + json.dumps(
        auto_snap, ensure_ascii=False, indent=2) + "\n```\n\n"
    # 心理状态也喂一份 (如果有)
    state_path = _player_dir(puuid) / "psych_state.json"
    if state_path.exists():
        out += "## 当前 psych_state (动态)\n\n```json\n" + \
               state_path.read_text(encoding="utf-8") + "\n```\n"
    sys.stdout.write(out)
    return 0


def cmd_merge_psych(puuid, file_path):
    """把 AI 返回的 psych axes JSON 合并到 profile. 用法:
        python rankprobe_lite.py merge-psych <puuid> response.json
    """
    p = Path(file_path)
    if not p.exists():
        sys.stderr.write(f"[!] 文件不存在: {file_path}\n"); return 1
    try:
        raw = p.read_text(encoding="utf-8")
        # 兼容 AI 输出含 ```json 包裹的情况
        if "```" in raw:
            raw = raw.split("```json")[-1].split("```")[0] if "```json" in raw \
                  else raw.split("```")[1]
        data = json.loads(raw)
    except Exception as e:
        sys.stderr.write(f"[!] JSON 解析失败: {e}\n"); return 1

    full = _load_full_profiles()
    if full is None: return 1
    prof = full.get(puuid)
    if not isinstance(prof, dict):
        sys.stderr.write(f"[!] profile 不存在: {puuid}\n"); return 1

    psych = prof.get("psych")
    if not isinstance(psych, dict):
        psych = {"axes": {}, "adolescent_traps": [], "interventions_ok": [],
                 "interventions_no": [], "axes_source": "", "axes_confidence": 0.0,
                 "axes_updated_at": ""}
        prof["psych"] = psych

    if "axes" in data and isinstance(data["axes"], dict):
        psych["axes"].update({k: v for k, v in data["axes"].items() if v})
    for k in ("adolescent_traps", "interventions_ok", "interventions_no"):
        if k in data and isinstance(data[k], list):
            psych[k] = data[k]
    psych["axes_confidence"] = float(data.get("axes_confidence") or 0.0)
    # 第一次推断 → auto_inferred; 用户已审过 → mixed
    if not psych.get("axes_source"):
        psych["axes_source"] = "auto_inferred"
    elif psych["axes_source"] == "auto_inferred":
        psych["axes_source"] = "mixed"  # 二次合并算审核过
    psych["axes_updated_at"] = dt.datetime.now().isoformat(timespec="seconds")

    _save_full_profiles(full)
    sys.stdout.write(f"[merge-psych] ✓ {prof.get('nickname','?')} ({puuid[:8]})\n")
    sys.stdout.write(f"  axes:      {psych['axes']}\n")
    sys.stdout.write(f"  traps:     {psych.get('adolescent_traps')}\n")
    sys.stdout.write(f"  source:    {psych['axes_source']}\n")
    sys.stdout.write(f"  reasoning: {data.get('axes_reasoning','')[:200]}\n")
    return 0


def cmd_ai_prompt(puuid, persona=False):
    """输出可粘贴的 markdown prompt (含数据). 用法:
        python rankprobe_lite.py ai-prompt <puuid> > prompt.md          # 短结构化字段
        python rankprobe_lite.py ai-prompt <puuid> --persona > prompt.md  # 自然语言 persona
    """
    load_assets(verbose=False)
    load_profiles()
    profile = PROFILES.get(puuid)
    if not profile:
        sys.stderr.write(f"[!] profiles.json 里没有 puuid={puuid}\n")
        sys.stderr.write(f"    可用 puuid:\n")
        for k, p in PROFILES.items():
            if not k.startswith("_"):
                sys.stderr.write(f"      {k}  ({p.get('nickname','?')})\n")
        return 1
    out = AI_PERSONA_TEMPLATE if persona else AI_PROMPT_TEMPLATE
    out += "\n```json\n" + json.dumps({
        k: v for k, v in profile.items() if k != "auto"
    }, ensure_ascii=False, indent=2) + "\n```\n\n"
    out += "## 历史聚合 (auto)\n\n```json\n" + json.dumps(
        profile.get("auto") or {}, ensure_ascii=False, indent=2) + "\n```\n"
    sys.stdout.write(out)
    return 0


def _load_full_profiles():
    """读取 profiles.json 原始 dict (含 _meta 等), 用于写回."""
    pf_path = DATA_DIR / "profiles.json"
    if pf_path.exists():
        try: return json.loads(pf_path.read_text(encoding="utf-8"))
        except Exception as e:
            sys.stderr.write(f"[!] 读取 profiles.json 失败: {e}\n")
            return None
    return {}


def _save_full_profiles(full):
    pf_path = DATA_DIR / "profiles.json"
    text = json.dumps(full, ensure_ascii=False, indent=2) + "\n"
    # 容错: 替换无效 surrogate (来自 GBK 控制台输入误读)
    text = text.encode("utf-8", errors="replace").decode("utf-8")
    pf_path.write_text(text, encoding="utf-8")


def _ensure_persona(prof):
    p = prof.get("persona")
    if not isinstance(p, dict):
        prof["persona"] = {"self_voice": "", "peer_voices": [], "updated_at": ""}
    else:
        p.setdefault("self_voice", "")
        p.setdefault("peer_voices", [])
        p.setdefault("updated_at", "")
    return prof["persona"]


def cmd_set_self(puuid):
    """从 stdin 读多行作为 persona.self_voice. Ctrl+Z(Win)/Ctrl+D(Unix) 结束."""
    full = _load_full_profiles()
    if full is None: return 1
    if puuid not in full or not isinstance(full[puuid], dict):
        sys.stderr.write(f"[!] puuid={puuid} 不存在. 先跑 regen-profiles 或手工建一条.\n")
        return 1
    sys.stderr.write(
        f"输入 self_voice 内容 (多行, Ctrl+Z 然后 Enter 结束 / Unix Ctrl+D):\n")
    sys.stderr.flush()
    text = sys.stdin.read().strip()
    if not text:
        sys.stderr.write("[!] 空输入, 已取消\n")
        return 1
    persona = _ensure_persona(full[puuid])
    persona["self_voice"] = text
    persona["updated_at"] = dt.datetime.now().isoformat(timespec="seconds")
    _save_full_profiles(full)
    sys.stdout.write(f"[+] 已写入 persona.self_voice ({len(text)} 字)\n")
    sys.stdout.write(f"    puuid: {puuid}\n")
    return 0


def cmd_add_peer(puuid, voice_text):
    """追加一条 persona.peer_voices."""
    full = _load_full_profiles()
    if full is None: return 1
    if puuid not in full or not isinstance(full[puuid], dict):
        sys.stderr.write(f"[!] puuid={puuid} 不存在.\n")
        return 1
    text = (voice_text or "").strip()
    if not text:
        sys.stderr.write("[!] peer voice 不能为空\n")
        return 1
    persona = _ensure_persona(full[puuid])
    persona["peer_voices"].append(text)
    persona["updated_at"] = dt.datetime.now().isoformat(timespec="seconds")
    _save_full_profiles(full)
    sys.stdout.write(f"[+] 已追加 peer_voice (现共 {len(persona['peer_voices'])} 条)\n")
    return 0


def cmd_clear_peers(puuid):
    full = _load_full_profiles()
    if full is None: return 1
    if puuid not in full or not isinstance(full[puuid], dict):
        sys.stderr.write(f"[!] puuid={puuid} 不存在.\n")
        return 1
    persona = _ensure_persona(full[puuid])
    persona["peer_voices"] = []
    persona["updated_at"] = dt.datetime.now().isoformat(timespec="seconds")
    _save_full_profiles(full)
    sys.stdout.write(f"[+] 已清空 peer_voices\n")
    return 0


def cmd_merge_profile(puuid, file_path):
    """从 JSON 文件读取 AI 返回, 合并到 profiles.json 的 manual 字段."""
    load_profiles()
    try:
        new_data = json.loads(Path(file_path).read_text(encoding="utf-8"))
    except Exception as e:
        sys.stderr.write(f"[!] 读取 {file_path} 失败: {e}\n")
        return 1
    if not isinstance(new_data, dict):
        sys.stderr.write("[!] JSON 顶层必须是字典\n")
        return 1

    pf_path = DATA_DIR / "profiles.json"
    full = {}
    if pf_path.exists():
        try: full = json.loads(pf_path.read_text(encoding="utf-8"))
        except Exception as e:
            sys.stderr.write(f"[!] 读取 profiles.json 失败: {e}\n")
            return 1

    existing = full.get(puuid) if isinstance(full.get(puuid), dict) else {}
    merged = dict(PROFILE_DEFAULTS)
    # 1. 保留已有 manual
    for k in PROFILE_MANUAL_KEYS:
        if k in existing:
            merged[k] = existing[k]
    # 2. 用 new_data 覆盖 manual (只允许 PROFILE_MANUAL_KEYS)
    accepted, ignored = [], []
    for k, v in new_data.items():
        if k in PROFILE_MANUAL_KEYS:
            merged[k] = v
            accepted.append(k)
        else:
            ignored.append(k)
    # 3. auto 字段保留旧值
    if "auto" in existing:
        merged["auto"] = existing["auto"]

    full[puuid] = merged
    pf_path.write_text(
        json.dumps(full, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    sys.stdout.write(f"[+] 已合并到 {pf_path}\n")
    sys.stdout.write(f"    puuid: {puuid}\n")
    sys.stdout.write(f"    nickname: {merged.get('nickname','?')}\n")
    sys.stdout.write(f"    accepted: {accepted}\n")
    if ignored:
        sys.stdout.write(f"    ignored (不在白名单): {ignored}\n")
    return 0


# ============================================================================
# 10. Demo 模式: 从 data/ 最新快照构造 STATE, 用于看界面 (不启探针)
# ============================================================================
def _latest_day_dir():
    if not DATA_DIR.exists():
        return None
    days = sorted([p for p in DATA_DIR.iterdir()
                   if p.is_dir() and re.match(r"\d{4}-\d{2}-\d{2}$", p.name)],
                  reverse=True)
    for d in days:
        if (d / "basics" / "champ_select.json").exists():
            return d
    return days[0] if days else None


def _read_json(p):
    try: return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception: return None


def load_demo_state():
    day = _latest_day_dir()
    if not day:
        push_log("[demo] data/ 下无快照, 跳过"); return False
    push_log(f"[demo] 读取最新快照: {day.name}")

    sm = _read_json(day / "summoner" / "current.json") or {}
    rk = _read_json(day / "basics" / "ranked_stats.json") or {}
    cs = _read_json(day / "basics" / "champ_select.json") or {}
    if not cs.get("myTeam"):
        push_log("[demo] champ_select 缺 myTeam"); return False

    solo = ((rk.get("queueMap") or {}).get("RANKED_SOLO_5x5") or {})
    wins, losses = solo.get("wins", 0), solo.get("losses", 0)
    gp = wins + losses
    my_puuid = sm.get("puuid") or ""
    STATE["me"].update({
        "puuid": my_puuid,
        "name": sm.get("gameName") or sm.get("displayName") or "玩家",
        "tagLine": sm.get("tagLine") or "",
        "level": sm.get("summonerLevel") or 0,
        "profileIconId": sm.get("profileIconId") or 0,
        "tier": solo.get("tier") or "",
        "division": solo.get("division") or "",
        "lp": solo.get("leaguePoints") or 0,
        "wins": wins, "losses": losses,
        "wr": int(round(wins / gp * 100)) if gp else 0,
    })

    mates = []
    cids_arch = []
    me_pick_cid = 0
    for i, cell in enumerate(cs.get("myTeam") or []):
        puuid = cell.get("puuid") or ""
        cid = cell.get("championId") or cell.get("championPickIntent") or 0
        is_me = (puuid == my_puuid) if my_puuid else (i == 0)
        if is_me: me_pick_cid = cid

        sub = CACHE_DIR / "players" / puuid
        msm = _read_json(sub / "summoner.json") or {}
        name = (msm.get("gameName") or msm.get("displayName")
                or (sm.get("gameName") if is_me else f"队友{i}"))

        ch = CHAMPIONS_BY_CID.get(cid) or {}
        profile = PROFILES.get(puuid) or {}
        auto = profile.get("auto") or {}
        c_wr, c_games = _champ_wr_from_profile(profile, cid)
        mates.append({
            "cell_id": cell.get("cellId"),
            "puuid": puuid, "is_me": is_me,
            "name": name or profile.get("nickname") or f"队友{i}",
            "champion_id": cid,
            "champion_name": ch.get("name") or "",
            "slot_label": _slot_label(cid),
            "champ_history": ({"games": c_games, "wr": round(c_wr, 3)}
                              if c_wr is not None else None),
            "total_games": auto.get("games_total", 0),
            "total_wr": auto.get("wr_total", 0),
            "locked": True,
            "_profile_full": profile,
            "profile": {
                "tags": profile.get("tags") or [],
                "self_desc": profile.get("self_desc") or "",
                "peer_review": profile.get("peer_review") or "",
                "habits": profile.get("habits") or "",
                "skill": profile.get("skill") or "",
                "persona": {
                    "self_voice": ((profile.get("persona") or {})
                                   .get("self_voice") or ""),
                    "peer_voices": ((profile.get("persona") or {})
                                    .get("peer_voices") or []),
                },
            },
        })
        if cid: cids_arch.append(cid)

    # premade 标记
    puuids_in_team = [m["puuid"] for m in mates if m["puuid"]]
    for m in mates:
        m["is_premade"] = any(
            frozenset((m["puuid"], other)) in PREMADE_SET
            for other in puuids_in_team if other != m["puuid"]
        ) if m["puuid"] else False

    # 给我的英雄编一个近期战绩 (demo 用, 让 carry_score 有客观分)
    if me_pick_cid and not STATE.get("my_champ_history", {}).get(me_pick_cid):
        STATE["my_champ_history"].clear()
        STATE["my_champ_history"][me_pick_cid] = {
            "games": 11, "wins": 7, "k": 84, "d": 52, "a": 103}

    # carry_score
    for m in mates:
        m["carry_score"] = round(_carry_score(
            m, PROFILES.get(m["puuid"]) or {}, STATE.get("my_champ_history", {})
        ), 1)

    arch = analyze_lineup(cids_arch)
    arch.update(_build_core_verdict(mates, cids_arch))
    coach = coach_build(arch, mates, my_puuid=(STATE.get("me") or {}).get("puuid", ""))
    hex_recs = _hex_recs_for_cid(me_pick_cid) if me_pick_cid else []

    # 剥离仅用于内部传参的 _profile_full
    mates_clean = [{k: v for k, v in m.items() if not k.startswith("_")} for m in mates]

    with _state_lock:
        STATE["lcu_online"] = True
        STATE["phase"] = "ChampSelect"
        STATE["champ_select"] = {
            "phase": "FINALIZATION",
            "my_pick_cid": me_pick_cid,
            "my_pick_name": (CHAMPIONS_BY_CID.get(me_pick_cid) or {}).get("name") or "",
            "mates": mates_clean,
            "architecture": arch,
            "coach": coach,
            "hex_recs": hex_recs,
            "ts": time.time(),
        }
        STATE["ts"] = time.time()

    # 灌一些假日志, 看调试抽屉
    for ln in [
        "[probe] phase: None → Lobby",
        "[probe] phase: Lobby → Matchmaking",
        "[probe] phase: Matchmaking → ReadyCheck",
        "[probe] phase: ReadyCheck → ChampSelect",
        f"[advisor] 你 锁定 {(CHAMPIONS_BY_CID.get(me_pick_cid) or {}).get('name','?')}",
        "[advisor] 队友全员锁定, 阵容架构: " + arch.get("verdict", "—"),
    ]:
        push_log(ln)
    push_log(f"[demo] ✓ 已加载演示数据 (英雄 {me_pick_cid} + {len(mates)} 队友)")
    return True


# ============================================================================
# 9. 入口
# ============================================================================
def main():
    # 让 print 中文不乱码 (Windows 默认 GBK 控制台)
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
        # stdin 也得 UTF-8, errors=replace 把不可解码的字节换成 �, 避免炸出
        sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    HEX_DIR.mkdir(parents=True, exist_ok=True)

    # 通知 tools/ 用同一个 DATA_DIR (PyInstaller exe 必须)
    os.environ["RANKPROBE_DATA_DIR"] = str(DATA_DIR)

    # 第一次启动 bootstrap (data/profiles.json, data/coach.json 缺失时建默认)
    _bootstrap_data_dir()

    # 子命令: 不启服务, 跑完退出
    argv = sys.argv[1:]
    if argv and argv[0] in ("regen-profiles", "--regen-profiles"):
        load_assets(verbose=False)
        regen_profiles()
        return
    if argv and argv[0] in ("ai-prompt", "--ai-prompt"):
        if len(argv) < 2:
            sys.stderr.write("用法: python rankprobe_lite.py ai-prompt <puuid> [--persona]\n")
            sys.exit(2)
        persona = "--persona" in argv
        sys.exit(cmd_ai_prompt(argv[1], persona=persona))
    if argv and argv[0] in ("merge-profile", "--merge-profile"):
        if len(argv) < 3:
            sys.stderr.write("用法: python rankprobe_lite.py merge-profile <puuid> <ai_response.json>\n")
            sys.exit(2)
        sys.exit(cmd_merge_profile(argv[1], argv[2]))
    if argv and argv[0] in ("set-self", "--set-self"):
        if len(argv) < 2:
            sys.stderr.write("用法: python rankprobe_lite.py set-self <puuid>  (然后 stdin 输入)\n")
            sys.exit(2)
        sys.exit(cmd_set_self(argv[1]))
    if argv and argv[0] in ("add-peer", "--add-peer"):
        if len(argv) < 3:
            sys.stderr.write('用法: python rankprobe_lite.py add-peer <puuid> "<text>"\n')
            sys.exit(2)
        sys.exit(cmd_add_peer(argv[1], argv[2]))
    if argv and argv[0] in ("clear-peers", "--clear-peers"):
        if len(argv) < 2:
            sys.stderr.write("用法: python rankprobe_lite.py clear-peers <puuid>\n")
            sys.exit(2)
        sys.exit(cmd_clear_peers(argv[1]))
    if argv and argv[0] in ("infer-psych", "--infer-psych"):
        if len(argv) < 2:
            sys.stderr.write("用法: python rankprobe_lite.py infer-psych <puuid> > prompt.md\n")
            sys.exit(2)
        sys.exit(cmd_infer_psych(argv[1]))
    if argv and argv[0] in ("merge-psych", "--merge-psych"):
        if len(argv) < 3:
            sys.stderr.write("用法: python rankprobe_lite.py merge-psych <puuid> <ai_response.json>\n")
            sys.exit(2)
        sys.exit(cmd_merge_psych(argv[1], argv[2]))

    demo = "--demo" in sys.argv or "demo" in sys.argv
    global _IS_DEMO
    _IS_DEMO = demo

    load_assets(verbose=False)
    load_profiles()
    load_coach(verbose=False)
    load_psych_kb(verbose=False)
    # 启动恢复: 上次的 champ_select view (FFAN 重启后不再"等待第一次选人")
    _restore_last_champ_select_view()
    push_log(f"[boot] FFAN, Python {sys.version.split()[0]}"
             + (" [DEMO]" if demo else ""))
    push_log(f"[boot] 数据 {DATA_DIR}")
    push_log(f"[boot] 英雄 {len(CHAMPIONS_BY_CID)} · 海克斯推荐 {len(APEX_PER_CID)}"
             f" · 海克斯说明 {len(HEX_DICT)} · KIWI {len(AUG_NAME)}"
             f" · profiles {len(PROFILES)} · premade对 {len(PREMADE_SET)}"
             f" · coach={COACH.get('name','?')} · psych KB {len(PSYCH_KB)}")

    if demo:
        load_demo_state()
    else:
        # 启动探针线程
        threading.Thread(target=probe_loop, daemon=True, name="probe").start()

    # 启动 HTTP
    srv = _Server(("0.0.0.0", PORT), Handler)
    push_log(f"[boot] HTTP 监听 http://127.0.0.1:{PORT}/"
             + ("  (DEMO 模式, 不连接 LCU)" if demo else ""))
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        push_log("[boot] Ctrl+C, 退出")
        srv.shutdown()


if __name__ == "__main__":
    main()
