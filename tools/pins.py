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
    return final

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

def main():
    src = open("pins-source.txt").read().strip().splitlines()[0].strip()
    url = resolve(src)
    user, feeds = feeds_for(url)
    pins, used, errors = [], None, []
    for f in feeds:
        try:
            _, body = get(f)
            got = parse(body)
            if got:
                pins, used = got, f
                break
            errors.append(f + ": пустая лента")
        except Exception as e:
            errors.append(f"{f}: {e}")
    out = {"source": src, "resolved": url, "feed": used, "user": user, "count": len(pins), "pins": pins[:60], "errors": errors}
    json.dump(out, open("inspo.json", "w"), ensure_ascii=False, indent=1)
    print(json.dumps({k: v for k, v in out.items() if k != "pins"}, ensure_ascii=False, indent=1))

if __name__ == "__main__":
    main()
