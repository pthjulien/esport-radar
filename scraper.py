#!/usr/bin/env python3
"""Scraper esport multi-flux : interroge les flux spécialisés (Dexerto, Google News ciblés),
extrait les images de presse réelles et maintient data.json à jour.
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

OUT_FILE = Path(__file__).resolve().parent / "data.json"
MAX_ITEMS = 150
MAX_AGE_DAYS = 30
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 (EsportRadarBot/3.0)"

# Flux RSS riches en données et requêtes ciblées par jeu (évite le filtre restrictif)
FEEDS = [
    "https://www.dexerto.fr/feed/esport/",
    "https://news.google.com/rss/search?q=esport+valorant&hl=fr&gl=FR&ceid=FR:fr",
    "https://news.google.com/rss/search?q=esport+league+of+legends+OR+lec+OR+lfl&hl=fr&gl=FR&ceid=FR:fr",
    "https://news.google.com/rss/search?q=esport+counter-strike+OR+cs2&hl=fr&gl=FR&ceid=FR:fr",
    "https://news.google.com/rss/search?q=esport+mercato+OR+transfert&hl=fr&gl=FR&ceid=FR:fr",
    "https://news.google.com/rss/search?q=esport+rocket+league&hl=fr&gl=FR&ceid=FR:fr",
]

# Banques de visuels de secours HD (scènes réelles de tournois majeurs et trophées)
DEFAULT_IMAGES = {
    "lol": "https://images.unsplash.com/photo-1542751371-adc38448a05e?auto=format&fit=crop&w=800&q=80",
    "val": "https://images.unsplash.com/photo-1511512578047-dfb367046420?auto=format&fit=crop&w=800&q=80",
    "cs2": "https://images.unsplash.com/photo-1579373903781-fd5c0c30c4cd?auto=format&fit=crop&w=800&q=80",
    "rl": "https://images.unsplash.com/photo-1563089145-599997674d42?auto=format&fit=crop&w=800&q=80",
    "dota": "https://images.unsplash.com/photo-1550745165-9bc0b252726f?auto=format&fit=crop&w=800&q=80",
    "other": "https://images.unsplash.com/photo-1511512578047-dfb367046420?auto=format&fit=crop&w=800&q=80",
}

GAME_RX = [
    ("lol", re.compile(r"league of legends|\blol\b|\blec\b|\blck\b|\blcs\b|\blpl\b|\blfl\b|worlds", re.I)),
    ("val", re.compile(r"valorant|\bvct\b|champions", re.I)),
    ("cs2", re.compile(r"counter-strike|\bcs2\b|\bcsgo\b|\bcs:go\b|\bhltv\b|major", re.I)),
    ("rl", re.compile(r"rocket league|\brlcs\b", re.I)),
    ("dota", re.compile(r"dota|international", re.I)),
]

RUMOR_RX = re.compile(r"rumou?rs?|rumeurs?|reportedly|leak|fuite|according to|selon|serait|pourrait|aurait|envisage|piste|sur le point|courtise|set to join", re.I)
OFFICIAL_RX = re.compile(r"\b(joins?|signs?|signed|parts? ways|benched|acquires?|leaves|departs?|roster|transfers?|extends?|re-sign|rejoint|rejoignent|signe|officialise|quitte|quittent|prolonge|recrute|transfert|débarque|s'engage|change d'équipe)\b", re.I)
PATCH_RX = re.compile(r"\bpatch\b|mise à jour|\bupdate\b", re.I)
TOURNAMENT_RX = re.compile(r"major|masters|tournoi|tournament|qualif|\biem\b|\bpgl\b|blast|playoff|worlds|mondial|\bmsi\b|\bvct\b|\blec\b|\blck\b|\blfl\b|finale|\bfinal\b|\besl\b|rlcs|champion", re.I)

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
    except Exception:
        return datetime.now(timezone.utc)

def iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

def extract_image_from_item(item) -> str:
    # 1. Balise enclosure standard RSS
    enc = item.find("enclosure")
    if enc is not None and enc.get("url"):
        return enc.get("url")
    # 2. Balises media:content ou media:thumbnail (Yahoo / Media RSS)
    for elem in item.iter():
        if elem.tag.endswith("content") or elem.tag.endswith("thumbnail"):
            u = elem.get("url")
            if u and re.search(r"\.(jpe?g|png|webp|avif)", u, re.I):
                return u
    # 3. Balise <img> dans la description HTML
    desc = item.findtext("description") or ""
    m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', desc, re.I)
    if m:
        return m.group(1)
    return ""

def fetch_feed(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.8"})
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            return resp.read()
    except Exception as e:
        print(f"Erreur sur le flux {url} : {e}", file=sys.stderr)
        return b""

def main() -> int:
    now = datetime.now(timezone.utc)
    seen_at = iso(now)

    existing = {}
    if OUT_FILE.exists():
        try:
            data = json.loads(OUT_FILE.read_text(encoding="utf-8"))
            if isinstance(data, list):
                existing = {a["title"].strip().lower(): a for a in data if isinstance(a, dict) and a.get("title")}
        except Exception:
            pass

    collected = []
    for feed_url in FEEDS:
        xml_data = fetch_feed(feed_url)
        if not xml_data:
            continue
        try:
            root = ET.fromstring(xml_data)
        except Exception:
            continue

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

            if not source:
                if "dexerto" in feed_url:
                    source = "Dexerto"
                else:
                    source = "Actualités Esport"

            game = detect_game(title)
            cat = detect_category(title)
            img = extract_image_from_item(item)
            if not img:
                img = DEFAULT_IMAGES.get(game, DEFAULT_IMAGES["other"])

            pub_iso = iso(parse_date(item.findtext("pubDate") or ""))
            key = title.strip().lower()

            collected.append({
                "title": title,
                "source": source,
                "url": link,
                "published": pub_iso,
                "game": game,
                "category": cat,
                "image": img,
                "first_seen": existing.get(key, {}).get("first_seen", seen_at)
            })

    # Fusion et dédoublonnage par titre
    all_articles = {**existing, **{a["title"].strip().lower(): a for a in collected}}

    cutoff = iso(now - timedelta(days=MAX_AGE_DAYS))
    sorted_items = sorted(
        [a for a in all_articles.values() if a.get("published", "") >= cutoff],
        key=lambda x: x.get("published", ""),
        reverse=True
    )
    final_list = sorted_items[:MAX_ITEMS]

    OUT_FILE.write_text(json.dumps(final_list, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Terminé : {len(final_list)} articles enregistrés avec images.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
