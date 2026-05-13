# -*- coding: utf-8 -*-
r"""Cache ARAM hex recommendations from apexlol.info.

This is an optional, manually-run helper. The main probe does not call the
network path; reports only read the cache if it already exists.

Usage:
    python tools/cache_hex_recommendations.py status
    python tools/cache_hex_recommendations.py refresh
    python tools/cache_hex_recommendations.py import D:\path\apexlol_data.json
    python tools/cache_hex_recommendations.py top Zed 5
    python tools/cache_hex_recommendations.py hex 海克斯名
"""

import html
import json
import os
import re
import shutil
import sys
import time
import urllib.error
import urllib.request

BASE_URL = "https://apexlol.info/zh"
REQUEST_DELAY = 0.4
CACHE_TTL_DAYS = 7
PARTIAL_SAVE_EVERY = 5


def project_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def data_root():
    # RANKPROBE_DATA_DIR 优先 (供 PyInstaller exe 使用)
    env = os.environ.get("RANKPROBE_DATA_DIR")
    if env:
        return env
    root = os.path.join(project_root(), "data")
    nested = os.path.join(root, "data")
    return nested if os.path.isdir(nested) else root


def cache_dir():
    return os.path.join(data_root(), "_cache", "hex_recommendations")


def cache_file():
    return os.path.join(cache_dir(), "apexlol_data.json")


def _strip_tags(text):
    text = re.sub(r"<script\b.*?</script>", "", text, flags=re.I | re.S)
    text = re.sub(r"<style\b.*?</style>", "", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _class_blocks(page, class_name):
    marker = class_name
    out = []
    pos = 0
    while True:
        m = re.search(r"<([a-zA-Z0-9]+)[^>]*class=[\"'][^\"']*"
                      + re.escape(marker)
                      + r"[^\"']*[\"'][^>]*>", page[pos:], flags=re.I)
        if not m:
            break
        start = pos + m.start()
        open_end = pos + m.end()
        tag = m.group(1).lower()
        depth = 1
        scan = open_end
        pat = re.compile(r"</?%s\b[^>]*>" % re.escape(tag), flags=re.I)
        while True:
            tm = pat.search(page, scan)
            if not tm:
                out.append(page[start:])
                pos = len(page)
                break
            token = tm.group(0)
            if token.startswith("</"):
                depth -= 1
                if depth == 0:
                    end = tm.end()
                    out.append(page[start:end])
                    pos = end
                    break
            else:
                depth += 1
            scan = tm.end()
    return out


def _class_texts(page, class_name):
    return [_strip_tags(b) for b in _class_blocks(page, class_name)]


def _fetch(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": "RankProbe-HexCache/1.0",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            raw = r.read()
            enc = r.headers.get_content_charset() or "utf-8"
            return raw.decode(enc, errors="replace")
    except (urllib.error.URLError, TimeoutError) as e:
        print(f"[!] 请求失败 {url}: {e}")
        return ""


def load_cache():
    try:
        with open(cache_file(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_cache(data):
    os.makedirs(cache_dir(), exist_ok=True)
    with open(cache_file(), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def cache_valid():
    path = cache_file()
    if not os.path.exists(path):
        return False
    age_days = (time.time() - os.path.getmtime(path)) / 86400
    return age_days < CACHE_TTL_DAYS


def cache_status():
    path = cache_file()
    if not os.path.exists(path):
        return {"exists": False, "path": path}
    data = load_cache()
    return {
        "exists": True,
        "path": path,
        "valid": cache_valid(),
        "age_hours": round((time.time() - os.path.getmtime(path)) / 3600, 1),
        "size_mb": round(os.path.getsize(path) / 1024 / 1024, 2),
        "champion_count": len(data.get("champions", {}) or {}),
        "hextech_count": len(data.get("hextech_details", {}) or {}),
        "scraped_at": (data.get("meta") or {}).get("scraped_at", ""),
    }


def scrape_champion_list():
    page = _fetch(f"{BASE_URL}/champions/")
    rows = []
    seen = set()
    for href, text in re.findall(r"<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>",
                                 page, flags=re.I | re.S):
        href = html.unescape(href)
        m = re.search(r"/champions/([A-Za-z0-9]+)/*$", href)
        if not m:
            continue
        cid = m.group(1)
        title = _strip_tags(text).lstrip("S").strip()
        if cid and cid not in seen:
            seen.add(cid)
            rows.append({"id": cid, "cn_title": title})
    return rows


def scrape_champion(champion_id):
    page = _fetch(f"{BASE_URL}/champions/{champion_id}")
    if not page:
        return {"id": champion_id, "cn_name": "", "synergies": []}

    h1 = _strip_tags((re.search(r"<h1\b[^>]*>(.*?)</h1>", page, flags=re.I | re.S)
                     or ["", ""])[1])
    parts = h1.split()
    cn_name = parts[-1] if parts else ""
    synergies = []
    for card in _class_blocks(page, "interaction-card"):
        hex_names = _class_texts(card, "hex-name")
        analysis = "\n".join(t for t in _class_texts(card, "note") if t)
        if not hex_names or not analysis:
            continue
        items = []
        for item in re.findall(r"data-item-name=[\"']([^\"']+)[\"']", card, flags=re.I):
            item = html.unescape(item).strip()
            if item:
                items.append(item)
        synergies.append({
            "hex_names": hex_names,
            "hex_tiers": _class_texts(card, "hex-tier"),
            "rating": (_class_texts(card, "rating-badge") or [""])[0].replace("级", "").strip(),
            "tag": (_class_texts(card, "tag-badge") or [""])[0],
            "analysis": analysis,
            "recommended_items": items,
        })
    return {"id": champion_id, "cn_name": cn_name, "synergies": synergies}


def scrape_hextech_list():
    page = _fetch(f"{BASE_URL}/hextech/")
    rows = []
    seen = set()
    for href, text in re.findall(r"<a\b[^>]*href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>",
                                 page, flags=re.I | re.S):
        href = html.unescape(href)
        m = re.search(r"/zh/hextech/([^/]+)/*$", href)
        if not m:
            continue
        hid = m.group(1)
        name = _strip_tags(text)
        if hid and name and hid not in seen:
            seen.add(hid)
            rows.append({"id": hid, "name": name})
    return rows


def scrape_hextech_detail(hex_id):
    page = _fetch(f"{BASE_URL}/hextech/{hex_id}")
    if not page:
        return {}
    name = (_class_texts(page, "title-section") or [""])[0]
    header = (_class_blocks(page, "header-card") or [""])[0]
    tier = ""
    for css, label in [("prismatic", "棱彩阶"), ("gold", "黄金阶"), ("silver", "白银阶")]:
        if css in header:
            tier = label
            break
    desc = (_class_texts(page, "description-box") or [""])[0]
    mech = (_class_texts(page, "mechanism-box") or [""])[0]
    out = {"name": name, "tier": tier, "description": desc}
    if mech and "暂无" not in mech:
        out["mechanism"] = mech
    return out


def refresh_cache():
    champs = scrape_champion_list()
    if not champs:
        print("[!] 没拿到英雄列表，缓存未更新")
        return {}
    old = load_cache()
    data = {
        "meta": {
            "source": "https://apexlol.info",
            "scraped_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "note": "Optional ARAM hex recommendation cache for RankProbe reports.",
        },
        "champion_list": champs,
        "champions": old.get("champions", {}) if isinstance(old, dict) else {},
        "hextech_details": old.get("hextech_details", {}) if isinstance(old, dict) else {},
    }
    total = len(champs)
    for i, champ in enumerate(champs, 1):
        if champ["id"] in data["champions"] and data["champions"][champ["id"]].get("synergies"):
            continue
        print(f"[{i}/{total}] {champ.get('cn_title') or champ['id']} ({champ['id']})")
        info = scrape_champion(champ["id"])
        data["champions"][champ["id"]] = {
            "cn_title": champ.get("cn_title", ""),
            "cn_name": info.get("cn_name", ""),
            "synergies": info.get("synergies", []),
        }
        if i % PARTIAL_SAVE_EVERY == 0:
            save_cache(data)
        time.sleep(REQUEST_DELAY)

    hex_rows = scrape_hextech_list()
    for i, row in enumerate(hex_rows, 1):
        if row.get("name") in data["hextech_details"]:
            continue
        if i == 1 or i % 20 == 0:
            print(f"[hex {i}/{len(hex_rows)}]")
        detail = scrape_hextech_detail(row["id"])
        name = detail.get("name") or row.get("name", "")
        for prefix in ("棱彩阶", "黄金阶", "白银阶"):
            if name.startswith(prefix):
                name = name[len(prefix):]
        if name and detail.get("description"):
            data["hextech_details"][name] = {
                "tier": detail.get("tier", ""),
                "description": detail.get("description", ""),
            }
            if detail.get("mechanism"):
                data["hextech_details"][name]["mechanism"] = detail["mechanism"]
        if i % 20 == 0:
            save_cache(data)
        time.sleep(REQUEST_DELAY * 0.5)

    save_cache(data)
    print(f"[+] 已缓存 {len(data['champions'])} 英雄, {len(data['hextech_details'])} 个海克斯说明")
    print(f"    {cache_file()}")
    return data


def _rating_key(row):
    order = {"sss": 0, "ss": 1, "s": 2, "a": 3, "b": 4, "c": 5, "d": 6}
    rating = (row.get("rating", "") or "").lower().replace("级", "").strip()
    for k, v in order.items():
        if rating.startswith(k):
            return v
    return 99


def query_top(champion, n=8):
    data = load_cache()
    champ = (data.get("champions") or {}).get(champion)
    if not champ:
        low = champion.lower()
        for key, value in (data.get("champions") or {}).items():
            if key.lower() == low or champion in (value.get("cn_title", ""), value.get("cn_name", "")):
                champ = value
                champion = key
                break
    if not champ:
        return f"未找到英雄: {champion}"
    rows = sorted(champ.get("synergies", []), key=_rating_key)[:n]
    lines = [f"### {champ.get('cn_title') or champion}({champion}) 海克斯推荐"]
    for row in rows:
        line = f"- [{row.get('rating') or '-'}] {' + '.join(row.get('hex_names', []))}"
        if row.get("tag"):
            line += f" [{row['tag']}]"
        if row.get("recommended_items"):
            line += " | 出装: " + " -> ".join(row["recommended_items"])
        if row.get("analysis"):
            line += " | " + row["analysis"]
        lines.append(line)
    return "\n".join(lines)


def query_hex(name):
    data = load_cache()
    details = data.get("hextech_details") or {}
    if name in details:
        d = details[name]
        return f"【{name}】{d.get('tier', '')}\n{d.get('description', '')}\n{d.get('mechanism', '')}".strip()
    for key, d in details.items():
        if name in key or key in name:
            return f"【{key}】{d.get('tier', '')}\n{d.get('description', '')}\n{d.get('mechanism', '')}".strip()
    return f"未找到海克斯: {name}"


def import_cache(source_path):
    with open(source_path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or "champions" not in data:
        raise ValueError("缓存格式不兼容: 缺少 champions")
    os.makedirs(cache_dir(), exist_ok=True)
    shutil.copyfile(source_path, cache_file())
    print(f"[+] 已导入缓存: {source_path}")
    print(f"    -> {cache_file()}")
    print(f"    英雄 {len(data.get('champions', {}) or {})}, 海克斯 {len(data.get('hextech_details', {}) or {})}")


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    if cmd == "status":
        print(json.dumps(cache_status(), ensure_ascii=False, indent=2))
    elif cmd == "refresh":
        refresh_cache()
    elif cmd == "top":
        if len(sys.argv) < 3:
            print("用法: python tools/cache_hex_recommendations.py top <英雄英文ID/中文名> [N]")
            return 1
        n = int(sys.argv[3]) if len(sys.argv) > 3 else 8
        print(query_top(sys.argv[2], n))
    elif cmd == "hex":
        if len(sys.argv) < 3:
            print("用法: python tools/cache_hex_recommendations.py hex <海克斯名>")
            return 1
        print(query_hex(sys.argv[2]))
    elif cmd == "import":
        if len(sys.argv) < 3:
            print("用法: python tools/cache_hex_recommendations.py import <apexlol_data.json>")
            return 1
        import_cache(sys.argv[2])
    else:
        print(__doc__)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
