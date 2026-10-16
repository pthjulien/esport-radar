#!/usr/bin/env python3
"""Esport Radar Scraper — Breaking News & Vraies photos de presse
Sources : E.SPORT.FR, Dexerto, Charlie INTEL, Dot Esports, Esports Insider, aAa, JV.
Règle stricte : 100% de vraies photos, articles récents (7 jours), vrais paragraphes complets.
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
MAX_ITEMS = 75
MAX_AGE_DAYS = 7  # Focus exclusif sur l'actualité brûlante
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

# Flux spécialisés fournissant des photos officielles et des articles rédigés
FEEDS = [
    # Actu générale & Scène française
    ("https://e.sport.fr/feed/", "E.SPORT.FR"),
    ("https://e.sport.fr/category/league-of-legends/feed/", "E.SPORT.FR"),
    ("https://e.sport.fr/category/valorant/feed/", "E.SPORT.FR"),
    ("https://e.sport.fr/category/counter-strike/feed/", "E.SPORT.FR"),
    ("https://e.sport.fr/category/fortnite/feed/", "E.SPORT.FR"),
    ("https://e.sport.fr/category/call-of-duty/feed/", "E.SPORT.FR"),
    ("https://e.sport.fr/category/rocket-league/feed/", "E.SPORT.FR"),
    ("https://e.sport.fr/category/apex-legends/feed/", "E.SPORT.FR"),
    ("https://www.dexerto.fr/feed/esport/", "Dexerto FR"),
    ("https://www.team-aaa.com/fr/rss/news.xml", "Team-aAa"),
    ("https://www.jeuxvideo.com/rss/rss-esport.xml", "JV Esport"),
    
    # Leaders mondiaux du breaking news & transferts
    ("https://charlieintel.com/feed/", "Charlie INTEL"),
    ("https://dotesports.com/feed", "Dot Esports"),
    ("https://esportsinsider.com/feed", "Esports Insider"),
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

def extract_real_image(item, raw_item_xml: str) -> str:
    """Extrait exclusivement les vraies photos de presse (JPEG/PNG/WEBP)."""
    # 1. Balise enclosure standard
    enc = item.find("enclosure")
    if enc is not None and enc.get("url"):
        u = enc.get("url").strip()
        if re.search(r"\.(jpe?g|png|webp|avif)", u, re.I):
            return u.replace("http://", "https://")

    # 2. Balise media:content / media:thumbnail
    for elem in item.iter():
        if elem.tag.endswith(("content", "thumbnail")):
            u = elem.get("url", "").strip()
            if u and re.search(r"\.(jpe?g|png|webp|avif)", u, re.I):
                return u.replace("http://", "https://")

    # 3. Image insérée dans le corps journalistique
    for tag in ["{http://purl.org/rss/1.0/modules/content/}encoded", "description"]:
        body = item.findtext(tag) or ""
        m = re.search(r'<img[^>]+src=["\']([^"\']+\.(?:jpe?g|png|webp|avif)[^"\']*)["\']', body, re.I)
        if m:
            img = m.group(1).replace("http://", "https://")
            low = img.lower()
            if not any(x in low for x in ["avatar", "logo", "icon", "emoji", "pixel"]):
                return img

    # 4. Scan brut du XML de l'article
    matches = re.findall(r'https?://[^\s"\'><]+\.(?:jpe?g|png|webp|avif)[^\s"\'><]*', raw_item_xml, re.I)
    for m in matches:
        low = m.lower()
        if not any(x in low for x in ["avatar", "logo", "icon", "emoji", "tracking"]):
            return m.replace("http://", "https://")

    return ""

def extract_full_text(item, title: str) -> list:
    """Extrait les véritables paragraphes rédigés par les journalistes."""
    raw_content = item.findtext("{http://purl.org/rss/1.0/modules/content/}encoded") or ""
    raw_desc = item.findtext("description") or ""

    paragraphs = []
    # Découpage des vrais blocs <p> de l'article
    p_tags = re.findall(r'<p[^>]*>(.*?)</p>', raw_content or raw_desc, flags=re.DOTALL | re.IGNORECASE)
    for p in p_tags:
        cleaned = clean_text(p)
        if len(cleaned) > 40:
            low = cleaned.lower()
            if not low.startswith(("à lire aussi", "lire aussi", "source :", "crédit :", "cet article", "the post")):
                paragraphs.append(cleaned)

    # Repli sur la description si pas de balises <p>
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
    cutoff = (now - timedelta(days=MAX_AGE_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    collected = []

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

            pub = parse_date(it.findtext("pubDate") or "")
            # On ignore immédiatement les articles de plus de 7 jours pour garder du direct
            if pub < cutoff:
                continue

            try:
                item_xml_str = ET.tostring(it, encoding="utf-8").decode("utf-8", errors="ignore")
            except Exception:
                item_xml_str = ""

            # FILTRE STRICT : Pas de vraie photo = article rejeté
            img = extract_real_image(it, item_xml_str)
            if not img or "unsplash" in img or "wikimedia" in img:
                continue

            game = detect_game(title + " " + item_xml_str + " " + url)
            category = detect_category(title + " " + item_xml_str)
            paragraphs = extract_full_text(it, title)

            collected.append({
                "title": title,
                "source": src_name,
                "url": link,
                "published": pub,
                "game": game,
                "category": category,
                "image": img,
                "content": "\n\n".join(paragraphs)
            })

    # Dédoublonnage par titre
    unique = {}
    for item in collected:
        k = item["title"].lower().strip()
        if k not in unique:
            unique[k] = item

    # Tri du plus récent au plus ancien
    sorted_items = sorted(
        unique.values(),
        key=lambda x: x.get("published", ""),
        reverse=True
    )

    final = sorted_items[:MAX_ITEMS]
    OUT_FILE.write_text(json.dumps(final, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Extraction réussie : {len(final)} actus chaudes avec vraies photos de presse.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
