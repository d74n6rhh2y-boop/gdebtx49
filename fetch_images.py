#!/usr/bin/env python3
"""
Fill / refresh games.json `img` fields with each game's best preview art.

HORIZONTAL-ONLY MODE (no API keys needed):
  - Re-checks EVERY game (not only empty ones).
  - Rejects junk: favicons, .ico, apple-touch-icon, logo192, data:-URIs,
    svg, tiny/placeholder icons, parastorage/flaticon stubs.
  - Site art first: og:image -> twitter:image -> image_src, BUT only if the
    image is clearly landscape (width >= 1.2 x height). Square / vertical
    site images are skipped. Shape is read from og:image:width/height meta,
    or measured straight from the image bytes (PNG/JPEG/WebP/GIF/BMP).
  - Landscape fallbacks, looked up by game title:
      1) Google Play feature graphic  1024x500 landscape   [optional]
      2) Steam capsule (header.jpg)   460x215  landscape
    No square icons, no vertical screenshots, no portrait box art.
  - Keeps an existing img ONLY if it already looks like real art.

Run via GitHub Actions; rewrites games.json in place.

Google Play needs:  pip install google-play-scraper
(if missing, Play is skipped automatically; Steam still works).
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

UA = "Mozilla/5.0 (compatible; hexplay-bot/1.8; +https://hexplay.games)"
TIMEOUT = 15

# --- config ---
USE_GOOGLE_PLAY = True        # needs: pip install google-play-scraper
STORE_SLEEP = 1.2             # polite delay between lookups (seconds)
STORE_COUNTRY = "us"
STORE_LANG = "en"
SITE_MIN_RATIO = 1.2          # site image must be at least this wide vs tall
MEASURE_BYTES = 131072        # how many bytes to pull to read image size

STEAM_SEARCH = "https://store.steampowered.com/api/storesearch/"
STEAM_CDN = "https://cdn.akamai.steamstatic.com/steam/apps/{}/header.jpg"

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
    if m:
        w, h = int(m.group(1)), int(m.group(2))
        if max(w, h) < 200:
            return True
    if re.search(r"/(16|32|48|57|64|72|96|120|128|180|192)(\b|/|$)", path):
        return True
    return False


def looks_like_art(u):
    return bool(u) and not is_bad_img(u)


# ---------- read image dimensions from raw bytes (stdlib only) ----------

_JPEG_SOF = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
             0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}


def img_dims(data):
    """Return (w, h) for PNG/JPEG/WebP/GIF/BMP from a header chunk, else None."""
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
                w = ((b[1] & 0x3F) << 8 | b[0]) + 1
                h = ((b[3] & 0x0F) << 10 | b[2] << 2 | (b[1] & 0xC0) >> 6) + 1
                return (w, h)
            if fmt == b"VP8X":
                return ((data[24] | data[25] << 8 | data[26] << 16) + 1,
                        (data[27] | data[28] << 8 | data[29] << 16) + 1)
        if data[:2] == b"\xff\xd8":            # JPEG
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
            data = r.read(MEASURE_BYTES)
    except Exception:
        return None
    return img_dims(data)


def is_landscape(url, w=None, h=None):
    """True if clearly wider than tall. Uses meta dims if given, else measures.
    Lenient (True) only when the size genuinely can't be determined."""
    try:
        w = int(w) if w else 0
        h = int(h) if h else 0
    except Exception:
        w = h = 0
    if not (w and h):
        dims = measure_url(url)
        if not dims:
            return True          # couldn't measure -> don't over-reject
        w, h = dims
    if not (w and h):
        return True
    return w >= h * SITE_MIN_RATIO


class MetaParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.og = None
        self.tw = None
        self.img_src = None
        self.og_w = None
        self.og_h = None

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
            if not href:
                return
            if "image_src" in rel and not self.img_src:
                self.img_src = href


def absolutize(base, url):
    if not url:
        return None
    return urllib.parse.urljoin(base, url)


def fetch_html(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        ctype = r.headers.get("Content-Type", "")
        if "html" not in ctype.lower():
            return None
        raw = r.read(600_000)
    for enc in ("utf-8", "latin-1"):
        try:
            return raw.decode(enc, errors="ignore")
        except Exception:
            continue
    return None


def best_image(url):
    try:
        html = fetch_html(url)
    except Exception as e:
        print(f"   fetch fail: {e}")
        return None
    if not html:
        return None
    p = MetaParser()
    try:
        p.feed(html)
    except Exception:
        pass
    # (url, meta_w, meta_h) — only og carries reliable meta dims
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
    """Title with the trailing subtitle dropped (after the last separator)."""
    if not t:
        return None
    seps = list(_SUBTITLE_SEP.finditer(t))
    if not seps:
        return None
    base = t[:seps[-1].start()].strip()
    return base if len(base) >= 3 else None


# ---------- Steam (capsule header, landscape) ----------

def steam_image(title):
    """Steam store capsule (header.jpg) via the storefront search API."""
    if not title:
        return None
    q = urllib.parse.urlencode({"term": title, "cc": STORE_COUNTRY,
                                "l": STORE_LANG})
    try:
        req = urllib.request.Request(STEAM_SEARCH + "?" + q,
                                     headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            data = json.loads(r.read().decode("utf-8", "ignore"))
    except Exception as e:
        print(f"   steam fail: {e}")
        return None
    for it in data.get("items", []):
        if _title_matches(title, it.get("name")):
            appid = it.get("id")
            if appid:
                return STEAM_CDN.format(appid)
    return None


# ---------- Google Play (feature graphic, landscape) ----------

def play_image(title):
    """Wide feature graphic only (no vertical screenshot). Needs the scraper lib."""
    if not title:
        return None
    try:
        from google_play_scraper import search as gp_search, app as gp_app
    except ImportError:
        return None
    try:
        results = gp_search(title, n_hits=5, lang=STORE_LANG,
                            country=STORE_COUNTRY)
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
            return d.get("headerImage")   # 1024x500 banner; landscape only
    return None


def store_image(title):
    """Landscape art: Google Play banner -> Steam capsule.
    Tries the full title first, then the base title (subtitle stripped)."""
    terms = [title]
    base = _base_title(title)
    if base and _norm(base) != _norm(title):
        terms.append(base)
    sources = [(play_image, "play")] if USE_GOOGLE_PLAY else []
    sources.append((steam_image, "steam"))
    attempts = [(fn, tag, term) for term in terms for fn, tag in sources]
    for idx, (fn, tag, term) in enumerate(attempts):
        if idx:
            time.sleep(STORE_SLEEP)      # space calls; none wasted on a miss
        img = fn(term)
        if img:
            print(f"   -> [{tag}] {img[:80]}")
            return img
    return None


def main():
    with open(GAMES, encoding="utf-8") as fh:
        games = json.load(fh)
    refreshed = 0
    kept = 0
    from_store = 0
    failed = []
    for i, g in enumerate(games, 1):
        url = g.get("url")
        cur = g.get("img")
        title = g.get("title", "?")

        if cur and looks_like_art(cur):
            kept += 1
            continue

        print(f"[{i}/{len(games)}] {title}"
              + ("  (replacing junk)" if cur else ""))

        img = best_image(url) if url else None
        if img:
            print(f"   -> {img[:90]}")
        else:
            img = store_image(title)
            if img:
                from_store += 1

        if img:
            g["img"] = img
            refreshed += 1
        else:
            g.pop("img", None)
            failed.append(title)
            print("   -> none (cleared; card shows // image soon_)")

    with open(GAMES, "w", encoding="utf-8") as fh:
        json.dump(games, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"\nDone. Kept good: {kept}. Refreshed: {refreshed} "
          f"(of which {from_store} from stores). No art: {len(failed)}.")
    if failed:
        print("No art for:", ", ".join(failed[:60]),
              ("..." if len(failed) > 60 else ""))


if __name__ == "__main__":
    main()
