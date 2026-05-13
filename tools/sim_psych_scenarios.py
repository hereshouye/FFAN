# -*- coding: utf-8 -*-
"""教练 + psych 模拟测试. 构造 4 个场景, 观察 coach_build() 输出 + ctx 组装.

用法:
    python tools/sim_psych_scenarios.py

会:
  1. 备份现有 players/<puuid>/psych_state.json
  2. 注入 4 个场景的合成 psych_state
  3. 调 coach_build() 看输出 + mates_psych ctx + 模拟 history.jsonl 长啥样
  4. 恢复备份
"""
from __future__ import annotations
import json
import sys
import shutil
import datetime as dt
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# 让 rankprobe_lite 用真实 data/ 目录
import rankprobe_lite as rpl


# ============================================================================
# 4 个场景的合成 psych_state
# ============================================================================
def _state(level, streak, wr_l10, mood, signals, axes_tilt=""):
    return {
        "_v": 1, "puuid": "(填)", "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "_patch": "14.22",
        "form": {"l10": ["L"]*max(0,-streak) + ["W"]*max(0,streak),
                 "wr_l10": wr_l10, "wr_l30d": wr_l10, "decay_score": wr_l10},
        "streak": {"now": streak, "longest_loss_l30d": -5 if streak<0 else 0,
                   "longest_win_l30d": streak if streak>0 else 0},
        "tilt": {"score": {"calm":0.1,"mild":0.35,"moderate":0.55,"severe":0.8}[level],
                 "level": level,
                 "components": {"streak_factor": 0.5, "form_factor": 0.3, "decay_factor": 0.2}},
        "mood_inference": mood,
        "signals": signals,
        "self_efficacy_hint": "low" if level=="severe" else ("high" if level=="calm" else "mid"),
        "social_risk": "watch" if level=="severe" else "none",
    }


SCENARIOS = [
    {
        "name": "S1: 平静开黑 (基线)",
        "desc": "我和朋友B + 朋友A双排, 大家状态都稳, 教练应该轻松调侃式发言.",
        "states": {
            "朋友A":    _state("calm",  +1, 0.6, "状态稳定", []),
            "朋友B":   _state("calm",   0, 0.5, "状态稳定", []),
            "朋友C":     _state("calm",  +2, 0.55,"状态稳定", []),
        },
    },
    {
        "name": "S2: 朋友A连负 3 把 (mild tilt)",
        "desc": "朋友A刚连黑 3 把, axes=易燃, 应触发 early intervention.",
        "states": {
            "朋友A":    _state("mild",  -3, 0.3, "略上头, 留意",
                                 ["近 3 局连败", "加权胜率持续下滑"],
                                 axes_tilt="易燃"),
            "朋友B":   _state("calm",   0, 0.5, "状态稳定", []),
            "朋友C":     _state("calm",  +1, 0.55,"状态稳定", []),
        },
    },
    {
        "name": "S3: 多人状态恶化 (moderate)",
        "desc": "朋友A mild + 朋友B moderate, 教练要同时处理两个心态.",
        "states": {
            "朋友A":    _state("mild",  -2, 0.4, "略上头, 留意",
                                 ["近 2 局连败"], axes_tilt="易燃"),
            "朋友B":   _state("moderate", -4, 0.2, "上头中, 倾向冲动决策",
                                 ["近 4 局连败", "近 10 局胜率 20%", "加权胜率持续下滑"]),
            "朋友C":     _state("calm",   0, 0.5, "状态稳定", []),
        },
    },
    {
        "name": "S4: 紧急 — 严重 tilt (severe, 接近危机)",
        "desc": "朋友A连负 6 把, severe tilt, signals 多. 应触发强干预语气.",
        "states": {
            "朋友A":    _state("severe", -6, 0.15, "严重 tilt, 建议下机",
                                 ["近 6 局连败", "近 10 局胜率 15%",
                                  "加权胜率持续下滑", "近 30 天最长 6 连负"],
                                 axes_tilt="易燃"),
            "朋友B":   _state("calm",    0, 0.5,  "状态稳定", []),
            "朋友C":     _state("calm",   +1, 0.55, "状态稳定", []),
        },
    },
]


# ============================================================================
# 工具
# ============================================================================
def _find_puuid_by_nickname(nick):
    for puuid, prof in rpl.PROFILES.items():
        if puuid.startswith("_"): continue
        if (prof.get("nickname") or "") == nick:
            return puuid
    return None


def _backup_state(puuid):
    p = rpl.PLAYERS_DIR / puuid / "psych_state.json"
    if p.exists():
        bak = p.with_suffix(".json.simbak")
        shutil.copy2(p, bak)
        return bak
    return None


def _restore_state(puuid, bak):
    p = rpl.PLAYERS_DIR / puuid / "psych_state.json"
    if bak and bak.exists():
        shutil.move(bak, p)
    elif p.exists():
        p.unlink()


def _inject_state(puuid, state_template):
    state_template = dict(state_template)
    state_template["puuid"] = puuid
    p = rpl.PLAYERS_DIR / puuid / "psych_state.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state_template, ensure_ascii=False, indent=2),
                 encoding="utf-8")


def _synthetic_mates(my_puuid, mate_puuids_named):
    """构造一个假的 mates 列表 (champ_select 后的样子), 供 coach_build 用."""
    # me
    me_pick = 35  # 恶魔小丑
    mates = [{
        "puuid":         my_puuid,
        "is_me":         True,
        "name":          "我",
        "champion_id":   me_pick,
        "champion_name": (rpl.CHAMPIONS_BY_CID.get(me_pick) or {}).get("name") or "?",
        "champion_role": ((rpl.CHAMPIONS_BY_CID.get(me_pick) or {}).get("roles") or ["?"])[0],
        "is_premade":    False,
        "tier":          "GOLD",
        "carry_score":   50,
    }]
    # mates
    fake_champs = {"朋友A": 141, "朋友B": 145, "朋友C": 222}
    for nick, puuid in mate_puuids_named.items():
        cid = fake_champs.get(nick, 7)
        prof = rpl.PROFILES.get(puuid) or {}
        mates.append({
            "puuid":         puuid,
            "is_me":         False,
            "name":          nick,
            "champion_id":   cid,
            "champion_name": (rpl.CHAMPIONS_BY_CID.get(cid) or {}).get("name") or f"#{cid}",
            "champion_role": ((rpl.CHAMPIONS_BY_CID.get(cid) or {}).get("roles") or ["?"])[0],
            "is_premade":    True,
            "tier":          "GOLD",
            "carry_score":   60,
            "_profile_full": prof,
        })
    return mates, me_pick


def _run_scenario(sc, my_puuid):
    print(f"\n{'='*70}")
    print(f"## {sc['name']}")
    print(f"   {sc['desc']}")
    print(f"{'='*70}")

    # 1. 注入 psych_state
    backups = {}
    for nick, state in sc["states"].items():
        puuid = _find_puuid_by_nickname(nick)
        if not puuid:
            print(f"  [skip] 找不到 {nick}")
            continue
        backups[puuid] = _backup_state(puuid)
        _inject_state(puuid, state)

    try:
        # 2. 构造 mates 调 coach_build
        mate_named = {n: _find_puuid_by_nickname(n) for n in sc["states"].keys()
                      if _find_puuid_by_nickname(n)}
        mates, me_pick_cid = _synthetic_mates(my_puuid, mate_named)
        cids = [m["champion_id"] for m in mates]
        arch = rpl.analyze_lineup(cids)
        arch.update(rpl._build_core_verdict(mates, cids))

        # 教练发言 + history 落盘
        coach = rpl.coach_build(arch, mates, my_puuid=my_puuid, game_id=None)

        # 3. 输出观察
        print(f"\n[阵容架构]")
        print(f"  verdict: {arch.get('verdict')}")
        print(f"  core:    {(arch.get('core') or {}).get('name')} "
              f"({(arch.get('core') or {}).get('champion_name')})  "
              f"score={(arch.get('core') or {}).get('score')}")
        print(f"  advice:  {arch.get('advice')}")
        print(f"  warnings: {arch.get('warnings')}")

        print(f"\n[教练 voice — 当前模板版]")
        print(f"  pre_game: {coach.get('pre_game')}")
        for i, p in enumerate(coach.get("psych") or []):
            print(f"  psych[{i}]: {p}")

        print(f"\n[mates_psych ctx — 给未来 LLM 看的快照]")
        for m in mates:
            mp = rpl._build_mate_psych(m)
            if not mp: continue
            print(f"  — {mp['name']} ({mp['champion']}) is_me={mp['is_me']}")
            print(f"      tilt:  level={mp['tilt_level']}  score={mp['tilt_score']}  mood='{mp['mood']}'")
            print(f"      signals: {mp['signals']}")
            print(f"      axes: {mp['axes']}  traps: {mp['adolescent_traps']}")
            print(f"      ok:  {mp['interventions_ok']}")
            print(f"      no:  {mp['interventions_no']}")
            if mp['self_voice_excerpt']:
                print(f"      self: {mp['self_voice_excerpt']}")

    finally:
        # 4. 恢复
        for puuid, bak in backups.items():
            _restore_state(puuid, bak)


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    rpl.load_assets(verbose=False)
    rpl.load_profiles()
    rpl.load_coach(verbose=False)
    rpl.load_psych_kb(verbose=True)

    # 找我自己 puuid
    my_puuid = None
    for puuid, prof in rpl.PROFILES.items():
        if puuid.startswith("_"): continue
        nick = prof.get("nickname") or ""
        # 找 my_puuid (从 profiles.json _meta 取, 失败用第一个)
        if puuid == (rpl.PROFILES.get("_meta") or {}).get("my_puuid"):
            my_puuid = puuid; break
    if not my_puuid:
        # 退化: 用任意一个
        for puuid in rpl.PROFILES:
            if not puuid.startswith("_"):
                my_puuid = puuid; break
    print(f"使用我的 puuid: {my_puuid[:8]} ({(rpl.PROFILES.get(my_puuid) or {}).get('nickname','?')})")

    # 落盘前打个标记 (本次是模拟, history 行会带 sim=True 方便后期过滤)
    # 教练 history 不带 sim 字段, 但我们可以在 _ts 之后 grep '模拟' 关键词
    # 这里只是提示用户
    print("注意: 4 个场景会落 4 行到 coach/history.jsonl. 跑完想清理就 truncate.\n")

    history_path = rpl.COACH_DIR / "history.jsonl"
    before = history_path.read_text(encoding="utf-8").count("\n") if history_path.exists() else 0

    for sc in SCENARIOS:
        _run_scenario(sc, my_puuid)

    after = history_path.read_text(encoding="utf-8").count("\n") if history_path.exists() else 0
    print(f"\n{'='*70}")
    print(f"完成. coach/history.jsonl 行数: {before} → {after}  (+{after-before})")
    print(f"模拟时构造的 psych_state 已恢复 (来源是 regen-profiles 算的真实值).")
    print(f"想清理这 {after-before} 条模拟 history, 删 coach/history.jsonl 最后 {after-before} 行即可.")


if __name__ == "__main__":
    main()
