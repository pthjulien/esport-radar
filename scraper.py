#!/usr/bin/env python3
"""Télécharge les flux d'actualités esport, récupère la vraie photo de chaque article
via les métadonnées OpenGraph (og:image) et met à jour data.json.
"""
import html
import json
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

FEED_URL = (
    "https://news.google.com/rss/search"
    "?q=esport+valorant+league+of+legends+cs2&hl=fr&gl=FR&ceid=FR:fr"
)
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 (EsportRadarBot/2.0)"
OUT_FILE = Path(__file__).resolve().parent / "data.json"
MAX_ITEMS = 150
MAX_AGE_DAYS = 30

GAME_RX = [
    ("lol", re.compile(r"league of legends|\blol\b|\blec\b|\blck\b|\blcs\b|\blpl\b|\blfl\b", re.I)),
    ("val", re.compile(r"valorant|\bvct\b", re.I)),
    ("cs2", re.compile(r"counter-strike|\bcs2\b|\bcsgo\b|\bcs:go\b|\bhltv\b", re.I)),
    ("rl", re.compile(r"rocket league|\brlcs\b", re.I)),
    ("dota", re.compile(r"dota", re.I)),
]

RUMOR_RX = re.compile(
    r"rumou?rs?|rumeurs?|reportedly|leak|fuite|according to|selon|serait|pourrait|"
    r"aurait|envisage|piste|sur le point|courtise|set to join",
    re.I,
)
OFFICIAL_RX = re.compile(
    r"\b(joins?|signs?|signed|parts? ways|benched|acquires?|leaves|departs?|roster|"
    r"transfers?|extends?|re-sign|rejoint|rejoignent|signe|officialise|quitte|quittent|"
    r"prolonge|recrute|transfert|débarque|s'engage|change d'équipe)\b",
    re.I,
)
PATCH_RX = re.compile(r"\bpatch\b|mise à jour|\bupdate\b", re.I)
TOURNAMENT_RX = re.compile(
    r"major|masters|tournoi|tournament|qualif|\biem\b|\bpgl\b|blast|playoff|worlds|"
    r"mondial|\bmsi\b|\bvct\b|\blec\b|\blck\b|\blfl\b|finale|\bfinal\b|\besl\b|rlcs|champion",
    re.I,
)

def detect_game(title: str) -> str:
    for key, rx in GAME_RX:
        if rx.search(title):
            return key
    return "other"

def detect_category(title: str) -> str:
    if RUMOR_RX.search(title):
        return "rumor"
    if OFFICIAL_RX.search(title):
        return "official"
    if PATCH_RX.search(title):
        return "patch"
    if TOURNAMENT_RX.search(title):
        return "tournament"
    return "news"

def parse_date(text: str) -> datetime:
    try:
        dt = parsedate_to_datetime(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)

def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

def fetch_real_image(url: str) -> str:
    """Récupère l'image officielle (og:image) de la source de l'article."""
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
            }
        )
        with urllib.request.urlopen(req, timeout=4) as response:
            html_content = response.read(65536).decode("utf-8", errors="ignore")
            m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', html_content, re.I)
            if not m:
                m = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', html_content, re.I)
            if m:
                img_url = m.group(1).strip()
                if img_url.startswith("http"):
                    return img_url
    except Exception:
        pass
    return ""

def download() -> bytes:
    req = urllib.request.Request(
        FEED_URL,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9",
        },
    )
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(req, timeout=25) as response:
                return response.read()
        except Exception as err:
            print(f"Tentative {attempt}/3 échouée : {err}", file=sys.stderr)
            time.sleep(2 * attempt)
    raise RuntimeError("Impossible de contacter le flux RSS.")

def load_existing() -> dict:
    if not OUT_FILE.exists():
        return {}
    try:
        data = json.loads(OUT_FILE.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return {a["url"]: a for a in data if isinstance(a, dict) and a.get("url")}
    except Exception:
        pass
    return {}

def main() -> int:
    now = datetime.now(timezone.utc)
    seen_at = iso(now)

    try:
        xml_bytes = download()
        root = ET.fromstring(xml_bytes)
    except Exception as e:
        print(f"Erreur de téléchargement : {e}", file=sys.stderr)
        return 1

    existing_articles = load_existing()
    fresh_items = []

    for item in root.iter("item"):
        raw_title = html.unescape((item.findtext("title") or "").strip())
        link = (item.findtext("link") or "").strip()
        if not raw_title or not link.startswith("http"):
            continue

        source_el = item.find("source")
        source = (source_el.text or "").strip() if source_el is not None else ""
        title = raw_title
        if " - " in raw_title:
            parts = raw_title.rsplit(" - ", 1)
            title = parts[0].strip()
            if not source:
                source = parts[1].strip()

        pub_iso = iso(parse_date(item.findtext("pubDate") or ""))

        # Si l'article existe déjà et a déjà une photo, on la garde sans refaire de requête
        cached = existing_articles.get(link)
        img_url = cached.get("image", "") if cached else ""
        first_seen = cached.get("first_seen", seen_at) if cached else seen_at

        fresh_items.append({
            "title": title,
            "source": source or "Actualités Esport",
            "url": link,
            "published": pub_iso,
            "game": detect_game(title),
            "category": detect_category(title),
            "image": img_url,
            "first_seen": first_seen
        })

    # On récupère les vraies images pour les 15 premiers articles s'ils n'en ont pas encore
    for art in fresh_items[:15]:
        if not art["image"]:
            print(f"Extraction image pour : {art['title'][:40]}...")
            art["image"] = fetch_real_image(art["url"])

    merged = {**existing_articles, **{a["url"]: a for a in fresh_items}}

    cutoff = iso(now - timedelta(days=MAX_AGE_DAYS))
    sorted_articles = sorted(
        [a for a in merged.values() if a.get("published", "") >= cutoff],
        key=lambda x: x["published"],
        reverse=True
    )

    # Dédoublonnage sur les titres
    seen_titles, final_list = set(), []
    for a in sorted_articles:
        k = a["title"].lower()
        if k not in seen_titles:
            seen_titles.add(k)
            final_list.append(a)

    final_list = final_list[:MAX_ITEMS]
    OUT_FILE.write_text(json.dumps(final_list, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Succès : {len(final_list)} articles enregistrés avec images réelles.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
