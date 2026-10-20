"""Fetch pins from a public Pinterest profile or board into inspo.json (stdlib only)."""
import json, re, sys, urllib.request, xml.etree.ElementTree as ET
from urllib.parse import urlparse

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"}

def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.geturl(), r.read()

def resolve(link):
    final, body = get(link)
    host = urlparse(final).netloc
    if "pinterest" not in host:
        # pin.it sometimes answers with an HTML page that carries the target
        m = re.search(rb'https://[a-z.]*pinterest\.[a-z.]+/[^"\'<> ]+', body)
        if m: final = m.group(0).decode()
    return final.split("?")[0]

def feeds_for(url):
    p = urlparse(url)
    parts = [x for x in p.path.split("/") if x]
    base = "https://www.pinterest.com"
    if not parts: raise SystemExit("Ссылка не ведёт на профиль или доску: " + url)
    if parts[0] == "pin":
        raise SystemExit("Это ссылка на отдельный пин, нужна ссылка на профиль или доску: " + url)
    user = parts[0]
    out = []
    if len(parts) >= 2 and parts[1] not in ("_saved", "_created", "pins", "boards"):
        out.append(f"{base}/{user}/{parts[1]}.rss")
    out.append(f"{base}/{user}/feed.rss")
    return user, out

def parse(xml_bytes):
    root = ET.fromstring(xml_bytes)
    pins = []
    for it in root.iter("item"):
        link = (it.findtext("link") or "").strip()
        title = (it.findtext("title") or "").strip()
        desc = it.findtext("description") or ""
        m = re.search(r'src="([^"]+pinimg\.com[^"]+)"', desc)
        if not m: continue
        img = re.sub(r"/\d+x/", "/736x/", m.group(1))
        pid = re.search(r"/pin/(\d+)", link)
        pins.append({"id": pid.group(1) if pid else img, "img": img, "title": title, "link": link})
    return pins

def board_api(user, board, errors, board_id=None):
    """All pins of a public board via Pinterest's web endpoint (cookie + csrf like a browser)."""
    import json as J, http.cookiejar
    from urllib.parse import quote
    jar = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    src = f"/{user}/{board}/"
    try:
        html = op.open(urllib.request.Request("https://www.pinterest.com" + src, headers=UA), timeout=30).read().decode("utf8", "ignore")
    except Exception as e:
        errors.append(f"board page: {e}"); return [], None
    if not board_id:
        m = re.search(r'"board_id"\s*:\s*"?(\d+)', html) or re.search(r'"id"\s*:\s*"(\d{10,})"\s*,\s*"[^"]*"\s*:\s*[^,]*,\s*"url"\s*:\s*"/' + re.escape(user), html)
        board_id = m and m.group(1)
    if not board_id:
        errors.append("board id not found"); return [], None
    csrf = next((c.value for c in jar if c.name == "csrftoken"), "")
    pins, bookmark = [], None
    for _ in range(30):
        opts = {"board_id": board_id, "board_url": src, "page_size": 100, "field_set_key": "react_grid_pin"}
        if bookmark: opts["bookmarks"] = [bookmark]
        u = f"https://www.pinterest.com/resource/BoardFeedResource/get/?source_url={quote(src)}&data={quote(J.dumps({'options': opts, 'context': {}}))}"
        h = {**UA, "Accept": "application/json, text/javascript, */*; q=0.01", "X-Requested-With": "XMLHttpRequest", "X-Pinterest-AppState": "active", "X-CSRFToken": csrf, "Referer": "https://www.pinterest.com" + src, "X-Pinterest-Source-Url": src}
        try:
            r = J.loads(op.open(urllib.request.Request(u, headers=h), timeout=30).read())["resource_response"]
        except Exception as e:
            errors.append(f"BoardFeedResource: {e}"); break
        for it in r.get("data") or []:
            if not isinstance(it, dict) or it.get("type") != "pin": continue
            imgs = it.get("images") or {}
            im = imgs.get("736x") or imgs.get("564x") or imgs.get("orig") or {}
            if im.get("url"):
                pins.append({"id": str(it.get("id")), "img": im["url"], "title": (it.get("grid_title") or it.get("title") or "").strip(), "link": f"https://www.pinterest.com/pin/{it.get('id')}/"})
        bookmark = r.get("bookmark")
        if not bookmark or bookmark == "-end-": break
    return pins, None

def widget_api(user, board, errors):
    try:
        _, body = get(f"https://widgets.pinterest.com/v3/pidgets/boards/{user}/{board}/pins/")
        d = json.loads(body)["data"]; data = d["pins"]; widget_api.board_id = str((d.get("board") or {}).get("id") or "")
        out = []
        for it in data:
            im = (it.get("images") or {}).get("564x") or (it.get("images") or {}).get("237x") or {}
            if im.get("url"): out.append({"id": str(it.get("id")), "img": re.sub(r"/\d+x/", "/736x/", im["url"]), "title": (it.get("description") or "").strip()[:120], "link": f"https://www.pinterest.com/pin/{it.get('id')}/"})
        return out
    except Exception as e:
        errors.append(f"widgets: {e}"); return []

def main():
    src = open("pins-source.txt").read().strip().splitlines()[0].strip()
    url = resolve(src)
    user, feeds = feeds_for(url)
    pins, used, errors, total = [], None, [], None
    parts = [x for x in urlparse(url).path.split("/") if x]
    if len(parts) >= 2:
        wp = widget_api(parts[0], parts[1], errors)
        full, total = board_api(parts[0], parts[1], errors, getattr(widget_api, "board_id", None))
        seen, pins = set(), []
        for p in full + wp:
            if p["id"] not in seen: seen.add(p["id"]); pins.append(p)
        used = "board-api" if full else ("widgets" if wp else None)
    for f in ([] if pins else feeds):
        try:
            _, body = get(f)
            got = parse(body)
            if got:
                pins, used = got, f
                break
            errors.append(f + ": пустая лента")
        except Exception as e:
            errors.append(f"{f}: {e}")
    # keep pins seen on earlier runs so the collection grows past the 50 the feed returns
    try:
        old = json.load(open("inspo.json")).get("pins", [])
        ids = {p["id"] for p in pins}
        pins += [p for p in old if p["id"] not in ids]
    except Exception:
        pass
    out = {"source": src, "resolved": url, "feed": used, "user": user, "count": len(pins), "board_total": total, "pins": pins[:400], "errors": errors}
    json.dump(out, open("inspo.json", "w"), ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in out.items() if k != "pins"}, ensure_ascii=False, indent=1))

if __name__ == "__main__":
    main()
