# -*- coding: utf-8 -*-
"""一次性生成 mock demo 数据集. 不含任何真实玩家信息.

输出:
    data/profiles.json                       5 个化名朋友 (虚构 puuid)
    data/players/<puuid>/psych_state.json    3 种不同 tilt 状态
    data/players/<puuid>/summoner.json       basic summoner mock
    data/players/<puuid>/ranked.json         basic ranked mock
    data/2026-05-13/basics/champ_select.json LCU session 模拟 (供 --demo)

跑完后:
    python rankprobe_lite.py --demo
或
    FFAN.exe (从 release/)
"""
import json
import sys
import uuid
import datetime as dt
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

# 5 个 "化名" 朋友 (puuid 是随机 v5, 不和真人撞)
def mk_puuid(seed):
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, f"ffan-demo-{seed}"))

MATES = [
    {"key": "me",     "nick": "我",      "tier": "GOLD",     "div": "IV",  "lp": 15, "champion_id": 35,  "role": "assassin"},
    {"key": "buddyA", "nick": "朋友A",   "tier": "GOLD",     "div": "II",  "lp": 78, "champion_id": 141, "role": "fighter"},   # Kayn
    {"key": "buddyB", "nick": "朋友B",   "tier": "PLATINUM", "div": "IV",  "lp": 42, "champion_id": 145, "role": "marksman"},  # Kai'Sa
    {"key": "buddyC", "nick": "朋友C",   "tier": "GOLD",     "div": "III", "lp": 30, "champion_id": 25,  "role": "support"},   # Morgana
    {"key": "stranger", "nick": "路人D", "tier": "SILVER",   "div": "II",  "lp": 60, "champion_id": 104, "role": "fighter"},   # Graves
]

MY_KEY = "me"

PSYCH_STATES = {
    "buddyA": {
        "form": {"l10": ["L"]*6+["W","L"], "wr_l10": 0.15, "wr_l30d": 0.4, "decay_score": 0.12},
        "streak": {"now": -6, "longest_loss_l30d": -6, "longest_win_l30d": 2},
        "tilt": {"score": 0.82, "level": "severe",
                 "components": {"streak_factor": 1.0, "form_factor": 0.85, "decay_factor": 0.88}},
        "mood_inference": "严重 tilt, 建议下机",
        "signals": ["近 6 局连败", "近 10 局胜率 15%", "加权胜率持续下滑", "近 30 天最长 6 连负"],
        "self_efficacy_hint": "low",
        "social_risk": "watch",
    },
    "buddyB": {
        "form": {"l10": ["L","L","W","L","W","W","W","W","W","W"], "wr_l10": 0.7, "wr_l30d": 0.55, "decay_score": 0.48},
        "streak": {"now": -2, "longest_loss_l30d": -3, "longest_win_l30d": 4},
        "tilt": {"score": 0.36, "level": "mild",
                 "components": {"streak_factor": 0.4, "form_factor": 0.3, "decay_factor": 0.4}},
        "mood_inference": "略上头, 留意",
        "signals": ["近 2 局连败", "加权胜率持续下滑"],
        "self_efficacy_hint": "mid",
        "social_risk": "none",
    },
    "buddyC": {
        "form": {"l10": ["W"]*7+["L","W","W"], "wr_l10": 0.85, "wr_l30d": 0.6, "decay_score": 0.92},
        "streak": {"now": 5, "longest_loss_l30d": -2, "longest_win_l30d": 5},
        "tilt": {"score": 0.05, "level": "calm",
                 "components": {"streak_factor": 0.0, "form_factor": 0.0, "decay_factor": 0.0}},
        "mood_inference": "状态稳定, 手感好",
        "signals": ["近 5 局连胜", "近 10 局手感好 (85%)"],
        "self_efficacy_hint": "high",
        "social_risk": "none",
    },
}


def main():
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass
    print("=== mock demo seed ===")
    DATA.mkdir(exist_ok=True)
    (DATA / "_VERSION").write_text("2\n", encoding="utf-8")

    # 1. profiles.json
    now_iso = dt.datetime.now().isoformat(timespec="seconds")
    my_puuid = mk_puuid(MY_KEY)
    profiles = {
        "_meta": {
            "format_version": "1.0",
            "generated_at": now_iso,
            "my_puuid": my_puuid,
            "min_games_with_me": 3,
            "premade_threshold": 0.6,
            "note": "mock demo data — fake puuids, fake names",
            "count": len(MATES),
        }
    }
    for m in MATES:
        puuid = mk_puuid(m["key"])
        is_me = m["key"] == MY_KEY
        profiles[puuid] = {
            "nickname": m["nick"],
            "self_role": m["role"],
            "self_desc": f"{m['nick']} 的虚拟自评" if not is_me else "",
            "tags": ["上头"] if m["key"] == "buddyA" else (["心态稳"] if m["key"] == "buddyC" else []),
            "peer_review": "",
            "habits": "",
            "skill": "A",
            "carry_priority": 7 if m["key"] in ("buddyA", "buddyB") else 5,
            "favorite_champ_ids": [m["champion_id"]],
            "premade_with": [my_puuid] if m["key"] in ("buddyA","buddyB","buddyC") and not is_me else [],
            "persona": {
                "self_voice": f"虚构的 {m['nick']} 自评. 这是 demo 用 mock 数据.",
                "peer_voices": [],
                "updated_at": now_iso,
            },
            "psych": {
                "axes": {
                    "competitive_style": ("攻击型" if m["key"]=="buddyA" else "防守型" if m["key"]=="buddyC" else "适应型"),
                    "comm_style":        "协作型",
                    "pressure_response": ("崩盘" if m["key"]=="buddyA" else "冷血" if m["key"]=="buddyC" else "高峰"),
                    "motivation_type":   "胜利",
                    "tilt_profile":      ("易燃" if m["key"]=="buddyA" else "钝感" if m["key"]=="buddyC" else "慢热"),
                },
                "adolescent_traps": ["T1","T3"] if m["key"]=="buddyA" else [],
                "interventions_ok": ["数据展示","具体行为建议"],
                "interventions_no": ["讲大道理","归罪"],
                "axes_source": "auto_inferred",
                "axes_confidence": 0.7,
                "axes_updated_at": now_iso,
            },
            "auto": {
                "name_from_history": m["nick"],
                "tag_from_history":  "demo",
                "games_total":       80 if not is_me else 200,
                "wins_total":        45 if not is_me else 105,
                "wr_total":          0.56,
                "games_with_me":     0 if is_me else 60,
                "wins_with_me":      0 if is_me else 34,
                "wr_with_me":        0.0 if is_me else 0.57,
                "premade_score":     0.0 if is_me else 0.9,
                "top_champs":        [{"cid": m["champion_id"], "name": "?", "games": 12, "wins": 7, "wr": 0.58}],
                "recent_focus":      [],
                "recent_form":       {"last_n": 10, "wins": 5, "losses": 5, "wr": 0.5, "trend": "normal"},
                "generated_at":      now_iso,
            },
        }
    (DATA / "profiles.json").write_text(json.dumps(profiles, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  ✓ profiles.json ({len(MATES)} 人, 含 mock psych axes)")

    # 2. psych_state.json (动态 tilt 状态) + 老 _cache/players 的 summoner (demo 代码读这里取名字)
    for m in MATES:
        puuid = mk_puuid(m["key"])
        # v2 psych_state
        d_v2 = DATA / "players" / puuid
        d_v2.mkdir(parents=True, exist_ok=True)
        if m["key"] in PSYCH_STATES:
            state_data = PSYCH_STATES[m["key"]]
            full = {"_v": 1, "puuid": puuid, "updated_at": now_iso, "_patch": "14.22", **state_data}
            (d_v2 / "psych_state.json").write_text(json.dumps(full, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"  ✓ players/{puuid[:8]}/psych_state.json  ({state_data['tilt']['level']})")
        # v1 _cache/players summoner (demo 模式读这里, 决定 mate.name 显示)
        d_v1 = DATA / "_cache" / "players" / puuid
        d_v1.mkdir(parents=True, exist_ok=True)
        (d_v1 / "summoner.json").write_text(json.dumps({
            "puuid": puuid, "gameName": m["nick"], "tagLine": "demo",
            "displayName": m["nick"], "summonerLevel": 100, "profileIconId": 0,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        (d_v1 / "ranked.json").write_text(json.dumps({
            "queues": [{"queueType":"RANKED_SOLO_5x5","tier":m["tier"],"division":m["div"],
                        "leaguePoints":m["lp"],"wins":50,"losses":40}]
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    # 3. 给 demo 模式的 champ_select 快照
    today = dt.date.today().isoformat()
    day_dir = DATA / today
    cs_dir = day_dir / "basics"
    cs_dir.mkdir(parents=True, exist_ok=True)
    summ_dir = day_dir / "summoner"
    summ_dir.mkdir(parents=True, exist_ok=True)

    # current summoner (我自己)
    me = {
        "puuid": my_puuid,
        "gameName": "我",
        "tagLine": "demo",
        "profileIconId": 0,
        "summonerLevel": 100,
        "displayName": "我",
        "internalName": "demo",
    }
    (summ_dir / "current.json").write_text(json.dumps(me, ensure_ascii=False, indent=2), encoding="utf-8")

    # ranked stats
    (cs_dir / "ranked_stats.json").write_text(json.dumps({
        "queues": [{"queueType":"RANKED_SOLO_5x5","tier":"GOLD","division":"IV","leaguePoints":15,"wins":105,"losses":95}]
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    # champ_select (LCU 格式)
    my_team = []
    for i, m in enumerate(MATES):
        my_team.append({
            "cellId":      i,
            "puuid":       mk_puuid(m["key"]),
            "summonerId":  1000 + i,
            "championId":  m["champion_id"],
            "championPickIntent": m["champion_id"],
            "assignedPosition": "",
            "team":        1,
            "gameName":    m["nick"],
            "tagLine":     "demo",
            "summonerInternalName": m["nick"],
            "displayName": m["nick"],
        })

    cs_session = {
        "gameId":           0,
        "localPlayerCellId": 0,
        "timer":            {"phase": "FINALIZATION", "adjustedTimeLeftInPhase": 30000},
        "myTeam":           my_team,
        "theirTeam":        [],
        "actions":          [],
        "queueId":          450,
        "isCustomGame":     False,
    }
    (cs_dir / "champ_select.json").write_text(json.dumps(cs_session, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  ✓ {today}/basics/champ_select.json + summoner")

    # 4. 最小英雄字典 (5 个 demo 英雄)
    cs_assets = DATA / "_cache" / "assets" / "zh_cn"
    cs_assets.mkdir(parents=True, exist_ok=True)
    champ_dict = [
        {"id": 35,  "name": "恶魔小丑",  "alias": "Shaco",   "roles": ["assassin"]},
        {"id": 141, "name": "影流之镰",  "alias": "Kayn",    "roles": ["fighter","assassin"]},
        {"id": 145, "name": "虚空之女",  "alias": "Kaisa",   "roles": ["marksman"]},
        {"id": 25,  "name": "堕落天使",  "alias": "Morgana", "roles": ["mage","support"]},
        {"id": 104, "name": "法外狂徒",  "alias": "Graves",  "roles": ["fighter","marksman"]},
    ]
    (cs_assets / "champion-summary.json").write_text(
        json.dumps(champ_dict, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  ✓ _cache/assets/zh_cn/champion-summary.json (5 个 demo 英雄)")

    print(f"\n=== 完成 ===")
    print(f"启动 demo:")
    print(f"  python rankprobe_lite.py --demo")
    print(f"  # 或 cd release && ./FFAN.exe --demo")
    print(f"\n浏览器开: http://127.0.0.1:6280/")


if __name__ == "__main__":
    main()
