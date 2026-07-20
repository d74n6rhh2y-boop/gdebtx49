#!/usr/bin/env python3
"""hexplay pick bot — posts a random game ("pick for me" style) to Telegram, Bluesky, and X.

Fetches games.json from the live site, picks a game (every game is shown once
before any repeats — see bot_state.json), and posts to whichever platforms have
credentials set.

On the 5th and 20th the bot posts an FAQ question instead — fetched live from
hexplay.games/about (in page order, looping back to #1 after the last;
index kept in bot_state.json as "faq").

Env (a platform is used only if its vars are present):
  TELEGRAM_BOT_TOKEN, TELEGRAM_CHANNEL                     (e.g. @hexplay)
  BLUESKY_HANDLE, BLUESKY_APP_PASSWORD                     (handle e.g. hexplay.bsky.social)
  X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_SECRET (paid pay-per-use; optional)
  DRY_RUN=1   -> print posts instead of sending
  FAQ=1       -> force an FAQ post (useful for manual runs/tests)
"""
import os, json, random, sys, tempfile, html, datetime, calendar, urllib.request

HERE        = os.path.dirname(os.path.abspath(__file__))
STATE       = os.path.join(HERE, "bot_state.json")  # post history: cycle through all before repeating
GAMES_URL   = "https://hexplay.games/games.json"
SITE        = "hexplay.games"
SITE_URL    = "https://hexplay.games"
FAQ_URL     = f"{SITE_URL}/about"
PLAT_LETTER = {"i": "Ⓐ", "a": "Ⓖ", "r": "🅁"}   # App Store / Google Play / Roblox


def fetch_games():
    req = urllib.request.Request(GAMES_URL, headers={"User-Agent": "hexplay-bot"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def fetch_faqs():
    """Pull FAQ questions live from hexplay.games/about so edits on the site
    are picked up automatically. Any element text ending in "?" counts as a
    question, tag-agnostic (leading numbering like "01 //" is stripped)."""
    import re
    req = urllib.request.Request(FAQ_URL, headers={"User-Agent": "hexplay-bot"})
    with urllib.request.urlopen(req, timeout=30) as r:
        page = r.read().decode("utf-8", "replace")
    page = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", page, flags=re.S | re.I)
    # keep inline tags from splitting a question (<b>hexplay</b> etc.)
    text = re.sub(r"</?(?:b|i|em|strong|span|a|u|s|small|mark|code)[^>]*>", "", page, flags=re.I)
    text = re.sub(r"<[^>]+>", "\n", text)
    out, seen = [], set()
    for line in html.unescape(text).splitlines():
        q = re.sub(r"^\s*\d+\s*(?://|[.)\u00b7-])?\s*", "", line)
        q = re.sub(r"\s+", " ", q).strip()
        if q.endswith("?") and 8 <= len(q) <= 160 and q not in seen:
            seen.add(q)
            out.append(q)
    return out


def load_state():
    try:
        with open(STATE, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def save_state(posted, last, faq=0):
    with open(STATE, "w", encoding="utf-8") as fh:
        json.dump({"posted": sorted(posted), "last": last, "faq": faq},
                  fh, ensure_ascii=False, indent=0)


def choose(games, posted):
    """Pick a game not yet posted this cycle. Once every game has been posted,
    start a fresh cycle. Newly added games join the current cycle automatically."""
    pool = [g for g in games if g.get("url")]        # must have a link to share
    titles = {g["title"] for g in pool}
    posted = set(posted) & titles                    # forget games no longer listed
    remaining = [g for g in pool if g["title"] not in posted]
    if not remaining:                                # whole list done -> new cycle
        posted, remaining = set(), pool
    g = random.choice(remaining)
    posted.add(g["title"])
    return g, posted


def image_url(g):
    img = g.get("img")
    if not img:
        return None
    return img if img.startswith("http") else f"{SITE_URL}/{img}"


# ---------- formatting ----------
def plat_letters(g):
    order = []
    for c in ("i", "a", "r"):
        if c not in order and any(code == c for code, _ in g.get("p", [])):
            order.append(c)
    return "".join(PLAT_LETTER[c] for c in order)


def years_str(g):
    ys = sorted({y for _, y in g.get("p", [])})
    return "/".join(str(y) for y in ys)


def meta_line(g):
    base = " ".join(x for x in (plat_letters(g), years_str(g)) if x)
    if g.get("pick"):
        base = (base + " #hexplay").strip()
    return base


def hashtag_lines(g):
    """Line 1: gameplay. Line 2: features + modes merged."""
    out = []
    fm = (g.get("features") or []) + (g.get("modes") or [])
    for cat in (g.get("gameplay"), fm):
        if cat:
            out.append(" ".join("#" + t.replace(" ", "") for t in cat))
    return out


def telegram_html(g):
    esc = lambda s: html.escape(s, quote=False)
    lines = [f'<b>{esc(g["title"])}</b>']
    m = meta_line(g)
    if m:
        lines.append(esc(m))
    lines += hashtag_lines(g)
    lines += ["", "keep or skip?", f'more \u2192 <a href="{SITE_URL}">{SITE}</a>']
    return "\n".join(lines)


def tweet_x(g):
    lines = [g["title"]]
    m = meta_line(g)
    if m:
        lines.append(m)
    lines += hashtag_lines(g)
    lines += ["", "keep or skip?", f"more \u2192 {SITE}"]
    return "\n".join(lines)


def telegram_faq(q):
    esc = html.escape(q, quote=False)
    return f'#FAQ {esc}\nanswer \u2192 <a href="{FAQ_URL}">{SITE}/about</a>'


def tweet_faq(q):
    return f"#FAQ {q}\nanswer \u2192 {SITE}/about"


def _bsky_faq(q):
    from atproto import client_utils
    tb = client_utils.TextBuilder()
    tb.tag("#FAQ", "FAQ").text(" " + q + "\nanswer \u2192 ").link(f"{SITE}/about", FAQ_URL)
    return tb


# ---------- senders ----------
def post_telegram(g):
    import requests
    token   = os.environ["TELEGRAM_BOT_TOKEN"]
    channel = os.environ["TELEGRAM_CHANNEL"]
    api     = f"https://api.telegram.org/bot{token}"
    cap     = telegram_html(g)
    photo   = image_url(g)
    if photo:
        r = requests.post(f"{api}/sendPhoto",
            data={"chat_id": channel, "photo": photo, "caption": cap, "parse_mode": "HTML"}, timeout=30)
        if r.ok:
            return "telegram: photo sent"
    r = requests.post(f"{api}/sendMessage",
        data={"chat_id": channel, "text": cap, "parse_mode": "HTML", "disable_web_page_preview": "false"}, timeout=30)
    r.raise_for_status()
    return "telegram: text sent"


def post_x(g):
    import tweepy
    k = (os.environ["X_API_KEY"], os.environ["X_API_SECRET"],
         os.environ["X_ACCESS_TOKEN"], os.environ["X_ACCESS_SECRET"])
    client = tweepy.Client(consumer_key=k[0], consumer_secret=k[1],
                           access_token=k[2], access_token_secret=k[3])
    media_ids = None
    url = image_url(g)
    if url:
        try:
            api_v1 = tweepy.API(tweepy.OAuth1UserHandler(*k))
            ext = os.path.splitext(url.split("?")[0])[1].lower()
            if ext not in (".jpg", ".jpeg", ".png", ".gif", ".webp"):
                ext = ".jpg"
            fn = tempfile.NamedTemporaryFile(suffix=ext, delete=False).name
            urllib.request.urlretrieve(url, fn)
            media_ids = [api_v1.media_upload(fn).media_id]
        except Exception as e:
            print(f"x: media skipped ({e})")
            media_ids = None
    client.create_tweet(text=tweet_x(g), media_ids=media_ids)
    return "x: tweeted" + (" with image" if media_ids else "")


def _bsky_richtext(g):
    """Same layout as the other platforms, with clickable link + hashtags (facets)."""
    from atproto import client_utils
    tb = client_utils.TextBuilder()
    tb.text(g["title"] + "\n")
    meta = " ".join(x for x in (plat_letters(g), years_str(g)) if x)
    tb.text(meta)
    if g.get("pick"):
        tb.text(" ").tag("#hexplay", "hexplay")
    tb.text("\n")
    fm = (g.get("features") or []) + (g.get("modes") or [])
    for cat in (g.get("gameplay"), fm):
        if cat:
            for i, t in enumerate(cat):
                tag = t.replace(" ", "")
                (tb.text(" ") if i else tb).tag("#" + tag, tag)
            tb.text("\n")
    tb.text("\nkeep or skip?\nmore \u2192 ").link(SITE, SITE_URL)
    return tb


def _shrink_image(data, max_dim=1600, quality=90):
    """Bluesky renders previews much faster for small blobs; downscale before upload."""
    try:
        import io
        from PIL import Image
        im = Image.open(io.BytesIO(data)).convert("RGB")
        im.thumbnail((max_dim, max_dim))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=quality, optimize=True)
        out = buf.getvalue()
        return out if len(out) < len(data) else data
    except Exception:
        return data


def _img_dims(data):
    try:
        import io
        from PIL import Image
        return Image.open(io.BytesIO(data)).size          # (width, height)
    except Exception:
        return None


def post_bluesky(g):
    from atproto import Client
    client = Client()
    client.login(os.environ["BLUESKY_HANDLE"], os.environ["BLUESKY_APP_PASSWORD"])
    rt = _bsky_richtext(g)
    url = image_url(g)
    if url:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "hexplay-bot"})
            with urllib.request.urlopen(req, timeout=30) as r:
                img = r.read()
            img = _shrink_image(img)
            if img and len(img) <= 976_000:                 # Bluesky blob limit ~1MB
                kw = {}
                dims = _img_dims(img)
                if dims:
                    try:                                    # real aspect ratio -> no white bars
                        from atproto import models
                        kw["image_aspect_ratio"] = models.AppBskyEmbedDefs.AspectRatio(width=dims[0], height=dims[1])
                    except Exception:
                        pass
                try:
                    client.send_image(text=rt, image=img, image_alt=g["title"], **kw)
                except TypeError:                           # older atproto without the param
                    client.send_image(text=rt, image=img, image_alt=g["title"])
                return "bluesky: image posted"
            print("bluesky: image too large, posting text only")
        except Exception as e:
            print(f"bluesky: image skipped ({e})")
    client.send_post(text=rt)
    return "bluesky: posted"


def post_telegram_faq(q):
    import requests
    token   = os.environ["TELEGRAM_BOT_TOKEN"]
    channel = os.environ["TELEGRAM_CHANNEL"]
    r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
        data={"chat_id": channel, "text": telegram_faq(q), "parse_mode": "HTML",
              "disable_web_page_preview": "false"}, timeout=30)
    r.raise_for_status()
    return "telegram: faq sent"


def post_x_faq(q):
    import tweepy
    client = tweepy.Client(
        consumer_key=os.environ["X_API_KEY"], consumer_secret=os.environ["X_API_SECRET"],
        access_token=os.environ["X_ACCESS_TOKEN"], access_token_secret=os.environ["X_ACCESS_SECRET"])
    client.create_tweet(text=tweet_faq(q))
    return "x: faq tweeted"


def post_bluesky_faq(q):
    from atproto import Client
    client = Client()
    client.login(os.environ["BLUESKY_HANDLE"], os.environ["BLUESKY_APP_PASSWORD"])
    client.send_post(text=_bsky_faq(q))
    return "bluesky: faq posted"


# ---------- main ----------
def is_rest_day(d):
    """No post on the 10th/15th/25th/30th (the 5th and 20th are FAQ days).
    February has no 30th, so its last day (28 or 29) stands in for it."""
    if d.day in (10, 15, 25, 30):
        return True
    return d.month == 2 and d.day == calendar.monthrange(d.year, 2)[1]


def pick_targets(tg, x, bsky):
    targets = []
    if os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHANNEL"):
        targets.append(tg)
    if all(os.environ.get(v) for v in ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET")):
        targets.append(x)
    if os.environ.get("BLUESKY_HANDLE") and os.environ.get("BLUESKY_APP_PASSWORD"):
        targets.append(bsky)
    if not targets:
        sys.exit("no credentials set for any platform")
    return targets


def send_all(targets, arg, on_success):
    posted_ok = failed = False
    for send in targets:
        try:
            print(send(arg))
            posted_ok = True
        except Exception as e:
            failed = True
            print(f"ERROR in {send.__name__}: {e}")
    if posted_ok:
        on_success()
    if failed:
        sys.exit(1)


def main():
    dry = os.environ.get("DRY_RUN") == "1"
    faq_mode = os.environ.get("FAQ") == "1"
    if os.environ.get("EVENT") == "schedule":          # FAQ/rest days apply to the schedule only
        today = datetime.date.today()                  # runner is UTC (cron fires 17:00 UTC)
        if today.day in (5, 20):
            faq_mode = True
        elif is_rest_day(today):
            print(f"{today} is a rest day (10/15/25/30) — no post")
            return
    state = load_state()
    today_str = str(datetime.date.today())
    if os.environ.get("EVENT") == "schedule" and state.get("last") == today_str:
        print(f"already posted today ({today_str}) — skipping duplicate scheduled run")
        return

    if faq_mode:
        faqs = fetch_faqs()
        if not faqs:
            sys.exit("no FAQ questions parsed from /about — check the page markup")
        i = state.get("faq", 0) % len(faqs)
        q = faqs[i]
        print(f"faq: {i + 1}/{len(faqs)} — {q}")
        if dry:
            print("\n--- TELEGRAM (HTML) ---\n" + telegram_faq(q))
            print("\n--- X ---\n" + tweet_faq(q))
            print("\n--- BLUESKY ---\n" + _bsky_faq(q).build_text())
            return                              # dry run: do not advance the FAQ index
        targets = pick_targets(post_telegram_faq, post_x_faq, post_bluesky_faq)
        send_all(targets, q, lambda: save_state(
            set(state.get("posted", [])), today_str, (i + 1) % len(faqs)))
        return

    games = fetch_games()
    posted = set(state.get("posted", []))
    g, posted = choose(games, posted)
    total = sum(1 for x in games if x.get("url"))
    print(f"picked: {g['title']}  ({len(posted)}/{total} this cycle)")

    if dry:
        print("\n--- TELEGRAM (HTML) ---\n" + telegram_html(g))
        print("\n--- X ---\n" + tweet_x(g))
        print("\n--- BLUESKY ---\n" + _bsky_richtext(g).build_text())
        print(f"\nimage: {image_url(g)}")
        return                                  # dry run: do not consume the game

    targets = pick_targets(post_telegram, post_x, post_bluesky)
    send_all(targets, g, lambda: save_state(posted, today_str, state.get("faq", 0)))


if __name__ == "__main__":
    main()
