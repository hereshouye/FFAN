# -*- coding: utf-8 -*-
"""下载并缓存 KIWI 海克斯字典 (从 CommunityDragon 官方游戏导出).

零外部依赖, 纯 Python 标准库.

用法:
    python tools/cache_official_augments.py refresh
    python tools/cache_official_augments.py status

输出: data/_cache/assets/official_kiwi/kiwi_augments_official.json
仅采集 AugmentPlatformId 字段, 保证 ID 和游戏内 playerAugment* 完全一致.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import ssl
import sys
import urllib.request


# DATA_DIR 可由 RANKPROBE_DATA_DIR 环境变量覆盖 (供 PyInstaller exe 使用)
ROOT       = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR   = os.environ.get("RANKPROBE_DATA_DIR") or os.path.join(ROOT, "data")
ASSETS_DIR = os.path.join(DATA_DIR, "_cache", "assets")
OUT_DIR    = os.path.join(ASSETS_DIR, "official_kiwi")
OUT_FILE   = os.path.join(OUT_DIR, "kiwi_augments_official.json")

MODE_FILE   = "game_maps_modespecificdata_kiwi.bin.json"
STRING_FILE = "lol.stringtable.zh_cn.json"
MODE_URL    = "https://raw.communitydragon.org/{ver}/game/maps/modespecificdata/kiwi.bin.json"
STRING_URL  = "https://raw.communitydragon.org/{ver}/game/zh_cn/data/menu/en_us/lol.stringtable.json"


def _download(url, path):
    req = urllib.request.Request(url, headers={"User-Agent": "RankProbe-Lite/1.0"})
    with urllib.request.urlopen(req, context=ssl.create_default_context(), timeout=60) as r:
        data = r.read()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)
    return len(data)


def _ensure_sources(version="latest", quiet=False):
    os.makedirs(OUT_DIR, exist_ok=True)
    sources = [
        (MODE_URL.format(ver=version),   os.path.join(OUT_DIR, MODE_FILE)),
        (STRING_URL.format(ver=version), os.path.join(OUT_DIR, STRING_FILE)),
    ]
    for url, path in sources:
        if os.path.exists(path):
            continue
        n = _download(url, path)
        if not quiet:
            print(f"[+] downloaded {os.path.basename(path)} ({n//1024} KB)")


def _text(entries, key):
    if not key:
        return ""
    return entries.get(key) or entries.get(str(key).lower()) or ""


def _clean_text(value):
    value = value or ""
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.I)
    value = re.sub(r"<[^>]+>", "", value)
    value = value.replace("&nbsp;", " ")
    return re.sub(r"[ \t]+", " ", value).strip()


def _iter_augments(obj, path=()):
    if isinstance(obj, dict):
        if obj.get("__type") == "AugmentData" and isinstance(obj.get("AugmentPlatformId"), int):
            yield path, obj
        for key, val in obj.items():
            for row in _iter_augments(val, path + (str(key),)):
                yield row
    elif isinstance(obj, list):
        for idx, val in enumerate(obj):
            for row in _iter_augments(val, path + (str(idx),)):
                yield row


def build(version="latest", quiet=False):
    """从官方文件构建 AugmentPlatformId → 字典. 写入 OUT_FILE."""
    _ensure_sources(version=version, quiet=quiet)
    with open(os.path.join(OUT_DIR, MODE_FILE), encoding="utf-8") as f:
        mode_data = json.load(f)
    with open(os.path.join(OUT_DIR, STRING_FILE), encoding="utf-8") as f:
        raw_strings = json.load(f)
    entries = raw_strings.get("entries", raw_strings)

    by_id, duplicates = {}, []
    for path, aug in _iter_augments(mode_data):
        aid = str(aug.get("AugmentPlatformId"))
        row = {
            "id": int(aid),
            "augment_name_id": aug.get("AugmentNameId", ""),
            "name": _clean_text(_text(entries, aug.get("NameTra"))) or aug.get("AugmentNameId", ""),
            "summary": _clean_text(_text(entries, aug.get("DescriptionTra"))),
            "tooltip": _clean_text(_text(entries, aug.get("AugmentTooltipTra"))),
            "rarity": aug.get("rarity"),
            "name_tra": aug.get("NameTra", ""),
            "description_tra": aug.get("DescriptionTra", ""),
            "tooltip_tra": aug.get("AugmentTooltipTra", ""),
            "large_icon": aug.get("AugmentLargeIconPath", ""),
            "small_icon": aug.get("AugmentSmallIconPath", ""),
            "source_path": "/".join(path),
            "source_field": "AugmentPlatformId",
        }
        if aid in by_id:
            duplicates.append(aid)
        by_id[aid] = row

    data = {
        "meta": {
            "source": "CommunityDragon official game export",
            "mode": "KIWI",
            "queue_id_observed": 2400,
            "version": version,
            "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
            "mode_source_url": MODE_URL.format(ver=version),
            "string_source_url": STRING_URL.format(ver=version),
            "proof": "Each key is copied only when it appears as AugmentPlatformId in game/maps/modespecificdata/kiwi.bin.json.",
            "count": len(by_id),
            "duplicate_ids": sorted(set(duplicates)),
        },
        "augments": by_id,
    }
    with open(OUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, sort_keys=True)
    return data


def status():
    exists = os.path.exists(OUT_FILE)
    if not exists:
        return {"exists": False, "path": OUT_FILE}
    try:
        with open(OUT_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return {"exists": True, "path": OUT_FILE, "parse_error": True}
    meta = data.get("meta") or {}
    return {
        "exists": True,
        "path": OUT_FILE,
        "count": len(data.get("augments") or {}),
        "generated_at": meta.get("generated_at", ""),
        "source": meta.get("source", ""),
        "version": meta.get("version", ""),
    }


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "status":
        st = status()
        print(f"exists: {st['exists']}")
        print(f"path  : {st['path']}")
        if st.get("exists"):
            print(f"count : {st.get('count', 0)}")
            print(f"version: {st.get('version', '-')}")
            print(f"generated_at: {st.get('generated_at', '-')}")
        return 0
    if cmd == "refresh":
        data = build()
        meta = data["meta"]
        print(f"[+] official KIWI augment dictionary cached")
        print(f"    path : {OUT_FILE}")
        print(f"    count: {meta['count']}")
        print(f"    source: {meta['source']}")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
