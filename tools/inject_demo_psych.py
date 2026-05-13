# -*- coding: utf-8 -*-
"""为 demo 模式注入合成 psych_state, 让 UI 上能看到教练 KB 触发. 可逆.

用法:
    python tools/inject_demo_psych.py             # 自动检测前 3 个 puuid 注入
    python tools/inject_demo_psych.py --restore   # 恢复原 psych_state

注入场景:
    队友 #1 → severe tilt (-6 连负)  → 触发 desperation
    队友 #2 → mild tilt   (-2 连负)  → 触发 running_bad 早期
    队友 #3 → calm + 连胜             → 不打扰 (无 psych 提醒)

脚本不绑定具体 puuid — 自动读 data/profiles.json 取前 3 个非 _meta 的 puuid 用.
"""
import json
import sys
import shutil
from pathlib import Path
import datetime as dt

ROOT = Path(__file__).resolve().parent.parent
PLAYERS_DIR = ROOT / "data" / "players"
PROFILES_PATH = ROOT / "data" / "profiles.json"

# 场景模板 (puuid 由 runtime 自动选)
SCENARIOS = [
    {  # severe
        "form": {"l10": ["L"]*7+["W"], "wr_l10": 0.15, "wr_l30d": 0.4, "decay_score": 0.12},
        "streak": {"now": -6, "longest_loss_l30d": -6, "longest_win_l30d": 2},
        "tilt": {"score": 0.82, "level": "severe",
                 "components": {"streak_factor": 1.0, "form_factor": 0.85, "decay_factor": 0.88}},
        "mood_inference": "严重 tilt, 建议下机",
        "signals": ["近 6 局连败", "近 10 局胜率 15%", "加权胜率持续下滑", "近 30 天最长 6 连负"],
        "self_efficacy_hint": "low",
        "social_risk": "watch",
    },
    {  # mild
        "form": {"l10": ["L","L","W","L","W","W","W","W"], "wr_l10": 0.55, "wr_l30d": 0.5, "decay_score": 0.42},
        "streak": {"now": -2, "longest_loss_l30d": -3, "longest_win_l30d": 4},
        "tilt": {"score": 0.36, "level": "mild",
                 "components": {"streak_factor": 0.4, "form_factor": 0.3, "decay_factor": 0.4}},
        "mood_inference": "略上头, 留意",
        "signals": ["近 2 局连败", "加权胜率持续下滑"],
        "self_efficacy_hint": "mid",
        "social_risk": "none",
    },
    {  # calm + hot streak
        "form": {"l10": ["W"]*7+["L"], "wr_l10": 0.85, "wr_l30d": 0.6, "decay_score": 0.92},
        "streak": {"now": 5, "longest_loss_l30d": -2, "longest_win_l30d": 5},
        "tilt": {"score": 0.05, "level": "calm",
                 "components": {"streak_factor": 0.0, "form_factor": 0.0, "decay_factor": 0.0}},
        "mood_inference": "状态稳定, 手感好",
        "signals": ["近 5 局连胜", "近 10 局手感好 (85%)"],
        "self_efficacy_hint": "high",
        "social_risk": "none",
    },
]


def _load_puuids():
    """从 profiles.json 读前 N 个非 _meta puuid (按 games_with_me 排序如果有)."""
    if not PROFILES_PATH.exists():
        return []
    try:
        d = json.loads(PROFILES_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    # 过滤 my_puuid + _meta + 取前 3
    my_puuid = (d.get("_meta") or {}).get("my_puuid", "")
    puuids = []
    for k, v in d.items():
        if k.startswith("_") or not isinstance(v, dict): continue
        if k == my_puuid: continue
        # 按 games_with_me 排, 大的先 (更稳的样本)
        games = ((v.get("auto") or {}).get("games_with_me") or 0)
        puuids.append((games, k, v.get("nickname") or k[:8]))
    puuids.sort(reverse=True)
    return [(p[1], p[2]) for p in puuids]


def main():
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass

    restore = "--restore" in sys.argv
    bak_suffix = ".democeache"

    targets = _load_puuids()
    if not targets:
        sys.stderr.write("[!] data/profiles.json 里没找到队友 puuid, 先跑 'FFAN regen-profiles' 或玩几局\n")
        sys.exit(1)

    # 取前 3 (或不够 3 就有几个用几个)
    selected = targets[:3]

    if restore:
        n = 0
        for puuid, nick in selected:
            p = PLAYERS_DIR / puuid / "psych_state.json"
            bak = p.with_suffix(".json" + bak_suffix)
            if bak.exists():
                shutil.move(bak, p)
                print(f"  ✓ 恢复 {nick} ({puuid[:8]})")
                n += 1
            elif p.exists():
                p.unlink()
                print(f"  ✓ 删除注入的 {nick} ({puuid[:8]}) — 原本无 psych_state")
        print(f"\n恢复 {n} 个 psych_state.")
        return

    now = dt.datetime.now().isoformat(timespec="seconds")
    print(f"注入 demo psych_state ({len(selected)} 个队友):\n")
    for (puuid, nick), state in zip(selected, SCENARIOS):
        p = PLAYERS_DIR / puuid / "psych_state.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        bak = p.with_suffix(".json" + bak_suffix)
        if p.exists() and not bak.exists():
            shutil.copy2(p, bak)
        full = {"_v": 1, "puuid": puuid, "updated_at": now, "_patch": "14.22", **state}
        p.write_text(json.dumps(full, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  ✓ {nick:12s} ({puuid[:8]})  level={state['tilt']['level']:8s}  streak={state['streak']['now']:+d}  mood={state['mood_inference']}")

    print(f"\n完成. 启动 demo 模式看效果:")
    print(f"  python rankprobe_lite.py --demo")
    print(f"\n恢复:")
    print(f"  python tools/inject_demo_psych.py --restore")


if __name__ == "__main__":
    main()
