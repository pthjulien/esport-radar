#!/usr/bin/env python3
"""Esport Radar Scraper — Multi-catégories & Cumul d'historique
Interroge les flux par jeu pour multiplier les articles récents,
exige 100% de vraies photos de presse, et conserve l'historique sur 30 jours.
"""
import html
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path

OUT_FILE = Path(__file__).resolve().parent / "data.json"
MAX_ITEMS = 150
MAX_AGE_DAYS = 30
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

# Flux spécialisés et flux thématiques par jeu (chacun apporte ses 10 derniers articles avec photo)
FEEDS = [
    # E.SPORT.FR (Général + Flux dédiés par jeu)
    ("https://e.sport.fr/feed/", "E.SPORT.FR"),
    ("https://e.sport.fr/category/league-of-legends/feed/", "E.SPORT.FR"),
    ("https://e.sport.fr/category/valorant/feed/", "E.SPORT.FR"),
    ("https://e.sport.fr/category/counter-strike/feed/", "E.SPORT.FR"),
    ("https://e.sport.fr/category/fortnite/feed/", "E.SPORT.FR"),
    ("https://e.sport.fr/category/call-of-duty/feed/", "E.SPORT.FR"),
    ("https://e.sport.fr/category/rocket-league/feed/", "E.SPORT.FR"),
    ("https://e.sport.fr/category/apex-legends/feed/", "E.SPORT.FR"),
    
    # Autres médias spécialisés avec vraies photos
    ("https://www.dexerto.fr/feed/esport/", "Dexerto FR"),
    ("https://www.team-aaa.com/fr/rss/news.xml", "Team-aAa"),
    ("https://www.jeuxvideo.com/rss/rss-esport.xml", "JV Esport"),
    ("https://dotesports.com/feed", "Dot Esports"),
    ("https://www.eclypsia.com/feed/", "Eclypsia"),
]

GAME_PATTERNS = [
    ("fortnite", re.compile(r"fortnite|\bfncs\b", re.I)),
    ("cod", re.compile(r"call of duty|\bcod\b|\bcdl\b|warzone|black ops|modern warfare", re.I)),
    ("apex", re.compile(r"apex legends|\balgs\b|\bapex\b", re.I)),
    ("val", re.compile(r"valorant|\bvct\b|champions|masters", re.I)),
    ("lol", re.compile(r"league of legends|\blol\b|\blec\b|\blck\b|\blfl\b|worlds|\blcs\b|\blpl\b", re.I)),
    ("cs2", re.compile(r"counter-strike|\bcs2\b|\bcs:go\b|\bcsgo\b|major|iem|blast|\bhl\b", re.I)),
    ("rl", re.compile(r"rocket league|\brlcs\b", re.I)),
    ("dota", re.compile(r"dota|international", re.I)),
]

def clean_text(raw_html: str) -> str:
    text = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', raw_html or "", flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = html.unescape(text)
    return re.sub(r'\s+', ' ', text).strip()

def detect_game(text: str) -> str:
    for key, rx in GAME_PATTERNS:
        if rx.search(text):
            return key
    return "other"

def detect_category(text: str) -> str:
    if re.search(r"rumou?rs?|rumeurs?|leak|fuite|selon|serait|pourrait|aurait|piste|courtise", text, re.I):
        return "rumor"
    if re.search(r"joins?|signs?|signe|rejoint|officialise|quitte|prolonge|recrute|transfert|benched|roster|départ|rejoindre", text, re.I):
        return "official"
    if re.search(r"victoire|défaite|sacré|éliminé|finale|playoffs|classement|tournoi|major|masters|trophée|champions|direct|match|score", text, re.I):
        return "tournament"
    if re.search(r"patch|mise à jour|nerf|buff|équilibrage|update", text, re.I):
        return "patch"
    return "news"

def extract_native_image(item, raw_item_xml: str) -> str:
    # 1. Enclosure
    enc = item.find("enclosure")
    if enc is not None and enc.get("url"):
        u = enc.get("url").strip()
        if re.search(r"\.(jpe?g|png|webp|avif)", u, re.I):
            return u.replace("http://", "https://")

    # 2. Media content / thumbnail
    for elem in item.iter():
        if elem.tag.endswith(("content", "thumbnail")):
            u = elem.get("url", "").strip()
            if u and re.search(r"\.(jpe?g|png|webp|avif)", u, re.I):
                return u.replace("http://", "https://")

    # 3. Première balise <img> dans content:encoded ou description
    for tag_name in ["{http://purl.org/rss/1.0/modules/content/}encoded", "description"]:
        body = item.findtext(tag_name) or ""
        m = re.search(r'<img[^>]+src=["\']([^"\']+\.(?:jpe?g|png|webp|avif)[^"\']*)["\']', body, re.I)
        if m:
            img_url = m.group(1).replace("http://", "https://")
            low = img_url.lower()
            if "avatar" not in low and "logo" not in low and "icon" not in low and "emoji" not in low:
                return img_url

    # 4. Scan brut du XML de l'article
    matches = re.findall(r'https?://[^\s"\'><]+\.(?:jpe?g|png|webp|avif)[^\s"\'><]*', raw_item_xml, re.I)
    for m in matches:
        low = m.lower()
        if "avatar" not in low and "logo" not in low and "icon" not in low and "emoji" not in low and "tracking" not in low:
            return m.replace("http://", "https://")

    return ""

def extract_article_body(item, title: str) -> list:
    raw_content = item.findtext("{http://purl.org/rss/1.0/modules/content/}encoded") or ""
    raw_desc = item.findtext("description") or ""

    paragraphs = []
    p_tags = re.findall(r'<p[^>]*>(.*?)</p>', raw_content or raw_desc, flags=re.DOTALL | re.IGNORECASE)
    for p in p_tags:
        cleaned = clean_text(p)
        if len(cleaned) > 40 and not cleaned.lower().startswith(("à lire aussi", "lire aussi", "source :", "crédit :", "cet article")):
            paragraphs.append(cleaned)

    if not paragraphs:
        cleaned_desc = clean_text(raw_desc)
        if len(cleaned_desc) > 30 and cleaned_desc.lower() not in title.lower():
            paragraphs.append(cleaned_desc)

    return paragraphs

def parse_date(date_str: str) -> str:
    try:
        dt = parsedate_to_datetime(date_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

def main() -> int:
    now = datetime.now(timezone.utc)
    seen_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    # 1. Chargement de l'historique existant (pour CUMULER et ne pas écraser)
    existing = {}
    if OUT_FILE.exists():
        try:
            d = json.loads(OUT_FILE.read_text(encoding="utf-8"))
            if isinstance(d, list):
                for a in d:
                    if isinstance(a, dict) and a.get("title") and a.get("image"):
                        k = a["title"].strip().lower()
                        # Purge des anciennes images de stock si présentes
                        if "unsplash" not in a.get("image", ""):
                            existing[k] = a
        except Exception:
            pass

    collected = []

    # 2. Récupération des articles sur l'ensemble des flux
    for url, src_name in FEEDS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                xml_raw = resp.read()
                root = ET.fromstring(xml_raw)
        except Exception:
            continue

        for it in root.iter("item"):
            title = html.unescape((it.findtext("title") or "").strip())
            link = (it.findtext("link") or "").strip()
            if not title or not link.startswith("http"):
                continue

            try:
                item_xml_str = ET.tostring(it, encoding="utf-8").decode("utf-8", errors="ignore")
            except Exception:
                item_xml_str = ""

            img = extract_native_image(it, item_xml_str)
            # RÈGLE STRICTE : Uniquement les vraies photos
            if not img or "unsplash" in img:
                continue

            game = detect_game(title + " " + item_xml_str + " " + url)
            category = detect_category(title + " " + item_xml_str)
            pub = parse_date(it.findtext("pubDate") or "")
            paragraphs = extract_article_body(it, title)

            k = title.strip().lower()
            collected.append({
                "title": title,
                "source": src_name,
                "url": link,
                "published": pub,
                "game": game,
                "category": category,
                "image": img,
                "content": "\n\n".join(paragraphs),
                "first_seen": existing.get(k, {}).get("first_seen", seen_at)
            })

    # 3. Fusion des nouveaux articles avec l'historique
    merged = {**existing}
    for item in collected:
        k = item["title"].lower().strip()
        merged[k] = item

    # 4. Tri chronologique et conservation sur 30 jours
    cutoff = (now - timedelta(days=MAX_AGE_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    sorted_articles = sorted(
        [a for a in merged.values() if a.get("published", "") >= cutoff],
        key=lambda x: x.get("published", ""),
        reverse=True
    )

    final = sorted_articles[:MAX_ITEMS]
    OUT_FILE.write_text(json.dumps(final, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Extraction terminée : {len(final)} articles avec photos réelles enregistrés.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
