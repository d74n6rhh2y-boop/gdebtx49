#!/usr/bin/env python3
"""
Fill games.json `img` with each game's best HORIZONTAL preview art.

PRIORITY (strict):
  1) local file in img/ matched to the game title  (your picture wins)
  2) official website preview (og:image / twitter:image / image_src), landscape
  3) Google Play feature graphic (landscape)        [needs google-play-scraper]
  4) Steam header (460x215, always landscape)        [last resort]
  5) nothing -> card shows "// image soon_"

Steam is last-resort only. Local images (img/) always win and are never
overwritten. Web images are re-resolved by priority on every run, so they
update (or get replaced) when sources change — they never go stale.
Run via GitHub Actions; rewrites games.json in place.
"""
import json
import os
import re
import time
import urllib.request
import urllib.parse
from html.parser import HTMLParser

HERE = os.path.dirname(os.path.abspath(__file__))
GAMES = os.path.join(HERE, "games.json")
IMG_DIR = os.path.join(HERE, "img")
IMG_EXTS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif")

UA = "Mozilla/5.0 (compatible; hexplay-bot/2.0; +https://hexplay.games)"
TIMEOUT = 15

USE_GOOGLE_PLAY = True
USE_STEAM = True
STORE_SLEEP = 1.2
STORE_COUNTRY = "us"
STORE_LANG = "en"
SITE_MIN_RATIO = 1.2
MEASURE_BYTES = 131072

BAD_SUBSTR = (
    "favicon", "apple-touch", "apple_touch", "/ico/", "icon-",
    "logo192", "logo180", "-icon", "_icon", "pfavico", "flaticon",
    "parastorage", "krone.ico", "/favicons/", "webclip", "pwa-icon",
    "android-chrome", "mstile", "safari-pinned", "logo.png",
)
BAD_EXT = (".ico", ".svg")


def is_bad_img(u):
    if not u:
        return True
    s = u.lower().strip()
    if s.startswith("data:"):
        return True
    path = urllib.parse.urlparse(s).path
    for ext in BAD_EXT:
        if path.endswith(ext):
            return True
    for sub in BAD_SUBSTR:
        if sub in s:
            return True
    m = re.search(r"(\d{2,4})x(\d{2,4})", s)
    if m and max(int(m.group(1)), int(m.group(2))) < 200:
        return True
    if re.search(r"/(16|32|48|57|64|72|96|120|128|180|192)(\b|/|$)", path):
        return True
    return False


def looks_like_art(u):
    return bool(u) and not is_bad_img(u)


def is_local_img(u):
    """True if img points to a file in the repo (not an http URL / data URI)."""
    return bool(u) and not u.lower().startswith(("http://", "https://", "data:"))


# ---------- read image dimensions from raw bytes (stdlib only) ----------

_JPEG_SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
             0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def img_dims(data):
    try:
        if data[:8] == b"\x89PNG\r\n\x1a\n" and data[12:16] == b"IHDR":
            return (int.from_bytes(data[16:20], "big"),
                    int.from_bytes(data[20:24], "big"))
        if data[:6] in (b"GIF87a", b"GIF89a"):
            return (int.from_bytes(data[6:8], "little"),
                    int.from_bytes(data[8:10], "little"))
        if data[:2] == b"BM":
            return (abs(int.from_bytes(data[18:22], "little", signed=True)),
                    abs(int.from_bytes(data[22:26], "little", signed=True)))
        if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
            fmt = data[12:16]
            if fmt == b"VP8 ":
                return ((data[26] | data[27] << 8) & 0x3FFF,
                        (data[28] | data[29] << 8) & 0x3FFF)
            if fmt == b"VP8L":
                b = data[21:25]
                return (((b[1] & 0x3F) << 8 | b[0]) + 1,
                        ((b[3] & 0x0F) << 10 | b[2] << 2 | (b[1] & 0xC0) >> 6) + 1)
            if fmt == b"VP8X":
                return ((data[24] | data[25] << 8 | data[26] << 16) + 1,
                        (data[27] | data[28] << 8 | data[29] << 16) + 1)
        if data[:2] == b"\xff\xd8":
            i, n = 2, len(data)
            while i + 9 < n:
                if data[i] != 0xFF:
                    i += 1
                    continue
                marker = data[i + 1]
                if marker == 0xFF:
                    i += 1
                    continue
                if marker in _JPEG_SOF:
                    return (int.from_bytes(data[i + 7:i + 9], "big"),
                            int.from_bytes(data[i + 5:i + 7], "big"))
                if marker == 0xD8 or marker == 0xD9 or 0xD0 <= marker <= 0xD7:
                    i += 2
                    continue
                seg = int.from_bytes(data[i + 2:i + 4], "big")
                if seg <= 0:
                    break
                i += 2 + seg
    except Exception:
        return None
    return None


def measure_url(url):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return img_dims(r.read(MEASURE_BYTES))
    except Exception:
        return None


def is_landscape(url, w=None, h=None):
    try:
        w = int(w) if w else 0
        h = int(h) if h else 0
    except Exception:
        w = h = 0
    if not (w and h):
        dims = measure_url(url)
        if not dims:
            return True
        w, h = dims
    if not (w and h):
        return True
    return w >= h * SITE_MIN_RATIO


class MetaParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.og = self.tw = self.img_src = self.og_w = self.og_h = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta":
            prop = (a.get("property") or a.get("name") or "").lower()
            content = a.get("content")
            if not content:
                return
            if prop == "og:image" and not self.og:
                self.og = content
            elif prop == "og:image:width" and not self.og_w:
                self.og_w = content
            elif prop == "og:image:height" and not self.og_h:
                self.og_h = content
            elif prop in ("twitter:image", "twitter:image:src") and not self.tw:
                self.tw = content
        elif tag == "link":
            rel = (a.get("rel") or "").lower()
            href = a.get("href")
            if href and "image_src" in rel and not self.img_src:
                self.img_src = href


def absolutize(base, url):
    return urllib.parse.urljoin(base, url) if url else None


def fetch_html(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        if "html" not in r.headers.get("Content-Type", "").lower():
            return None
        raw = r.read(600_000)
    for enc in ("utf-8", "latin-1"):
        try:
            return raw.decode(enc, errors="ignore")
        except Exception:
            continue
    return None


def best_image(url):
    """Official website preview, landscape only."""
    try:
        html = fetch_html(url)
    except Exception as e:
        print(f"   site fail: {e}")
        return None
    if not html:
        return None
    p = MetaParser()
    try:
        p.feed(html)
    except Exception:
        pass
    cands = []
    if p.og:
        cands.append((absolutize(url, p.og), p.og_w, p.og_h))
    if p.tw:
        cands.append((absolutize(url, p.tw), None, None))
    if p.img_src:
        cands.append((absolutize(url, p.img_src), None, None))
    seen = set()
    for full, w, h in cands:
        if not full or full in seen:
            continue
        seen.add(full)
        if not looks_like_art(full):
            continue
        if not is_landscape(full, w, h):
            print(f"   site img skipped (not landscape): {full[:70]}")
            continue
        return full
    return None


# ---------- title matching ----------

def _norm(s):
    return re.sub(r"[^a-z0-9]", "", (s or "").lower())


def _words(s):
    return set(re.findall(r"[a-z0-9]+", (s or "").lower()))


def _title_matches(want, cand):
    nw, nc = _norm(want), _norm(cand)
    if not nw or not nc:
        return False
    if nw in nc or nc in nw:
        return True
    a, b = _words(want), _words(cand)
    return bool(a and b) and len(a & b) / len(a | b) >= 0.5


_SUBTITLE_SEP = re.compile(r":\s+|\s+[-–—]\s+")


def _base_title(t):
    if not t:
        return None
    seps = list(_SUBTITLE_SEP.finditer(t))
    if not seps:
        return None
    base = t[:seps[-1].start()].strip()
    return base if len(base) >= 3 else None


# ---------- local files in img/ ----------

def load_local_images():
    out = []
    if not os.path.isdir(IMG_DIR):
        return out
    for fn in sorted(os.listdir(IMG_DIR)):
        stem, ext = os.path.splitext(fn)
        if ext.lower() not in IMG_EXTS:
            continue
        out.append((_norm(stem), _words(stem), "img/" + urllib.parse.quote(fn), fn))
    return out


def match_local(title, local_imgs):
    nt, wt = _norm(title), _words(title)
    if not nt:
        return None, None
    for ns, ws, rel, fn in local_imgs:              # exact normalized
        if ns and ns == nt:
            return rel, fn
    best, best_s = None, 0.0                          # strong word overlap
    for ns, ws, rel, fn in local_imgs:
        if not ws or not wt:
            continue
        s = len(wt & ws) / len(wt | ws)
        if s > best_s:
            best, best_s = (rel, fn), s
    if best and best_s >= 0.7:
        return best
    return None, None


# ---------- Google Play (feature graphic, landscape) ----------

def play_image(title):
    if not title:
        return None
    try:
        from google_play_scraper import search as gp_search, app as gp_app
    except ImportError:
        return None
    try:
        results = gp_search(title, n_hits=5, lang=STORE_LANG, country=STORE_COUNTRY)
    except Exception as e:
        print(f"   play fail: {e}")
        return None
    for r in results:
        if _title_matches(title, r.get("title")):
            try:
                d = gp_app(r["appId"], lang=STORE_LANG, country=STORE_COUNTRY)
            except Exception as e:
                print(f"   play app fail: {e}")
                return None
            return d.get("headerImage")
    return None


def play_lookup(title):
    """Google Play, full title then base title."""
    if not USE_GOOGLE_PLAY:
        return None
    terms = [title]
    base = _base_title(title)
    if base and _norm(base) != _norm(title):
        terms.append(base)
    for idx, term in enumerate(terms):
        if idx:
            time.sleep(STORE_SLEEP)
        img = play_image(term)
        if img:
            print(f"   -> [play] {img[:80]}")
            return img
    return None


# ---------- Steam (header image, always 460x215 landscape) ----------

def _steam_search(term):
    """Return list of (appid, name) from Steam store search."""
    q = urllib.parse.urlencode({"term": term, "cc": STORE_COUNTRY, "l": STORE_LANG})
    api = "https://store.steampowered.com/api/storesearch/?" + q
    try:
        req = urllib.request.Request(api, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            data = json.loads(r.read().decode("utf-8", "ignore"))
    except Exception as e:
        print(f"   steam fail: {e}")
        return []
    out = []
    for it in data.get("items", []):
        appid, name = it.get("id"), it.get("name")
        if appid and name:
            out.append((appid, name))
    return out


def steam_image(title):
    if not title:
        return None
    for appid, name in _steam_search(title):
        if _title_matches(title, name):
            url = f"https://cdn.akamai.steamstatic.com/steam/apps/{appid}/header.jpg"
            if measure_url(url):          # confirm the header exists
                return url
    return None


def steam_lookup(title):
    """Steam header, full title then base title."""
    if not USE_STEAM:
        return None
    terms = [title]
    base = _base_title(title)
    if base and _norm(base) != _norm(title):
        terms.append(base)
    for idx, term in enumerate(terms):
        if idx:
            time.sleep(STORE_SLEEP)
        img = steam_image(term)
        if img:
            print(f"   -> [steam] {img[:80]}")
            return img
    return None


def main():
    with open(GAMES, encoding="utf-8") as fh:
        games = json.load(fh)
    local_imgs = load_local_images()
    if local_imgs:
        print(f"Local img/ files: {len(local_imgs)}")
    used_local = set()
    from_local = kept = from_site = from_play = from_steam = 0
    failed = []

    for i, g in enumerate(games, 1):
        url = g.get("url")
        cur = g.get("img")
        title = g.get("title", "?")

        # 1) local file matches this game -> your picture wins
        rel, fn = match_local(title, local_imgs)
        if rel:
            used_local.add(fn)
            if cur != rel:
                g["img"] = rel
                print(f"[{i}/{len(games)}] {title}  -> [local] {rel}")
            from_local += 1
            continue

        # 2) a local path is already set -> never overwrite
        if is_local_img(cur):
            used_local.add(os.path.basename(urllib.parse.unquote(cur)))
            kept += 1
            continue

        # always re-resolve web art every run, by priority (replace stale)
        print(f"[{i}/{len(games)}] {title}" + ("  (refreshing)" if cur else ""))

        # 3) official website preview
        img = best_image(url) if url else None
        if img:
            print(f"   -> [site] {img[:90]}")
            from_site += 1
        else:
            # 4) Google Play
            img = play_lookup(title)
            if img:
                from_play += 1
            else:
                # 5) Steam (last resort)
                img = steam_lookup(title)
                if img:
                    from_steam += 1

        if img:
            g["img"] = img
        else:
            g.pop("img", None)
            failed.append(title)
            print("   -> none (cleared; card shows // image soon_)")

    with open(GAMES, "w", encoding="utf-8") as fh:
        json.dump(games, fh, ensure_ascii=False, separators=(",", ":"))

    print(f"\nDone. Local: {from_local}. Kept: {kept}. "
          f"Site: {from_site}. Play: {from_play}. Steam: {from_steam}. "
          f"No art: {len(failed)}.")
    unused = [fn for (_, _, _, fn) in local_imgs if fn not in used_local]
    if unused:
        print("\nLocal files NOT matched to any game "
              "(rename them closer to a game title):")
        print("  " + ", ".join(unused))
    if failed:
        print("No art for:", ", ".join(failed[:60]),
              ("..." if len(failed) > 60 else ""))


if __name__ == "__main__":
    main()
