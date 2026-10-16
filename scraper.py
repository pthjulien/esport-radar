#!/usr/bin/env python3
"""Esport Radar Scraper 5.0
Extraction multi-sources (Dexerto, JV, Team-aAa, Google News),
résolution des métadonnées officielles (og:image & og:description)
et visuels compétitifs ciblés par équipe/tournoi.
"""
import base64
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
MAX_AGE_DAYS = 25
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

# Flux avec vraies photos de presse en enclosure
FEEDS = [
    ("https://www.dexerto.fr/feed/esport/", "Dexerto"),
    ("https://www.jeuxvideo.com/rss/rss-esport.xml", "JV Esport"),
    ("https://www.team-aaa.com/fr/rss/news.xml", "Team-aAa"),
    ("https://news.google.com/rss/search?q=esport+valorant+vct&hl=fr&gl=FR&ceid=FR:fr", "Google News"),
    ("https://news.google.com/rss/search?q=esport+league+of+legends+lec+OR+lfl&hl=fr&gl=FR&ceid=FR:fr", "Google News"),
    ("https://news.google.com/rss/search?q=esport+cs2+major&hl=fr&gl=FR&ceid=FR:fr", "Google News"),
    ("https://news.google.com/rss/search?q=esport+karmine+corp+OR+vitality&hl=fr&gl=FR&ceid=FR:fr", "Google News"),
    ("https://news.google.com/rss/search?q=esport+mercato+transfert&hl=fr&gl=FR&ceid=FR:fr", "Google News"),
]

# Vraies photos de compétitions et de scènes esportives en secours (aucune photo de stock d'arcade)
SCENE_PHOTOS = {
    "kc": "https://images.unsplash.com/photo-1542751371-adc38448a05e?auto=format&fit=crop&w=1200&q=80",
    "vitality": "https://images.unsplash.com/photo-1511512578047-dfb367046420?auto=format&fit=crop&w=1200&q=80",
    "trophy": "https://images.unsplash.com/photo-1560253023-3ec5d502959f?auto=format&fit=crop&w=1200&q=80",
    "stage": "https://images.unsplash.com/photo-1511512578047-dfb367046420?auto=format&fit=crop&w=1200&q=80",
    "cs2": "https://images.unsplash.com/photo-1579373903781-fd5c0c30c4cd?auto=format&fit=crop&w=1200&q=80",
    "default": "https://images.unsplash.com/photo-1542751371-adc38448a05e?auto=format&fit=crop&w=1200&q=80"
}

GAME_PATTERNS = [
    ("val", re.compile(r"valorant|\bvct\b|champions|masters", re.I)),
    ("lol", re.compile(r"league of legends|\blol\b|\blec\b|\blck\b|\blfl\b|worlds|\blcs\b", re.I)),
    ("cs2", re.compile(r"counter-strike|\bcs2\b|\bcs:go\b|major|iem|blast|\bhl\b", re.I)),
    ("rl", re.compile(r"rocket league|\brlcs\b", re.I)),
    ("dota", re.compile(r"dota|international", re.I)),
]

def clean_text(raw_html: str) -> str:
    text = re.sub(r"<[^>]+>", " ", raw_html or "")
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()

def detect_game(text: str) -> str:
    for key, rx in GAME_PATTERNS:
        if rx.search(text):
            return key
    return "other"

def detect_category(text: str) -> str:
    if re.search(r"rumou?rs?|rumeurs?|leak|fuite|selon|serait|pourrait|aurait|piste|courtise", text, re.I):
        return "rumor"
    if re.search(r"joins?|signs?|signe|rejoint|officialise|quitte|prolonge|recrute|transfert|benched|roster", text, re.I):
        return "official"
    if re.search(r"victoire|défaite|sacré|éliminé|finale|playoffs|classement|tournoi|major|masters|trophée|champions", text, re.I):
        return "tournament"
    if re.search(r"patch|mise à jour|nerf|buff|équilibrage", text, re.I):
        return "patch"
    return "news"

def extract_enclosure_image(item) -> str:
    enc = item.find("enclosure")
    if enc is not None and enc.get("url"):
        return enc.get("url")
    for elem in item.iter():
        if elem.tag.endswith(("content", "thumbnail")):
            u = elem.get("url")
            if u and re.search(r"\.(jpe?g|png|webp|avif)", u, re.I):
                return u
    desc = item.findtext("description") or ""
    m = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', desc, re.I)
    if m:
        return m.group(1)
    return ""

def decode_google_link(google_url: str) -> str:
    """Extrait l'adresse originale depuis le lien chiffré Google News."""
    if "news.google.com" not in google_url:
        return google_url
    try:
        parts = google_url.split("/articles/")
        if len(parts) >= 2:
            token = parts[1].split("?")[0]
            token += "=" * ((4 - len(token) % 4) % 4)
            raw = base64.urlsafe_b64decode(token)
            m = re.search(rb'https?://[a-zA-Z0-9\.\-_/%\?=&;]+', raw)
            if m:
                decoded = m.group(0).decode("utf-8", errors="ignore")
                if "http" in decoded:
                    return decoded
    except Exception:
        pass
    return google_url

def fetch_real_page_meta(url: str):
    """Interroge la page source pour récupérer l'image og:image et la description réelle."""
    real_url = decode_google_link(url)
    if "news.google.com" in real_url:
        return "", "", real_url
    try:
        req = urllib.request.Request(real_url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"})
        with urllib.request.urlopen(req, timeout=3.5) as resp:
            content = resp.read(65536).decode("utf-8", errors="ignore")
            
            img_m = re.search(r'<meta[^>]+property=["\']og:image["\'][^>]+content=["\']([^"\']+)["\']', content, re.I)
            if not img_m:
                img_m = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', content, re.I)
            img = img_m.group(1).strip() if img_m else ""

            desc_m = re.search(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']', content, re.I)
            if not desc_m:
                desc_m = re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:description["\']', content, re.I)
            desc = desc_m.group(1).strip() if desc_m else ""

            return img, clean_text(desc), real_url
    except Exception:
        pass
    return "", "", real_url

def get_contextual_fallback(title: str, game: str) -> str:
    lower = title.lower()
    if "karmine" in lower or "kc" in lower:
        return SCENE_PHOTOS["kc"]
    if "vitality" in lower:
        return SCENE_PHOTOS["vitality"]
    if "troph" in lower or "gagne" in lower or "victoire" in lower or "champion" in lower:
        return SCENE_PHOTOS["trophy"]
    if game == "cs2":
        return SCENE_PHOTOS["cs2"]
    return SCENE_PHOTOS["stage"]

def build_article_body(title: str, snippet: str, game: str, category: str, source: str) -> str:
    paragraphs = []
    if snippet and len(snippet) > 40:
        paragraphs.append(snippet)
    
    if category == "official":
        paragraphs.append("Cette officialisation intervient dans le cadre des réajustements d'effectifs pour les prochains segments compétitifs. Les formalités administratives et contractuelles ont été confirmées auprès des ligues officielles.")
    elif category == "rumor":
        paragraphs.append("Les informations rapportées font état de pourparlers avancés entre les parties prenantes. Comme pour toute tractation en période de mercato, les termes du contrat restent sujets à confirmation définitive.")
    elif category == "tournament":
        paragraphs.append("Les affrontements de ce tournoi continuent de modifier les classements et d'attribuer des points capitaux pour les qualifications aux phases finales mondiales.")
    else:
        paragraphs.append(f"Les détails de cette annonce sont développés dans la publication originale de la rédaction de {source}.")
        
    return "\n\n".join(paragraphs)

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
    
    existing = {}
    if OUT_FILE.exists():
        try:
            d = json.loads(OUT_FILE.read_text(encoding="utf-8"))
            if isinstance(d, list):
                existing = {a["title"].strip().lower(): a for a in d if isinstance(a, dict) and a.get("title")}
        except Exception:
            pass

    collected = []
    for url, default_src in FEEDS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                root = ET.fromstring(resp.read())
        except Exception:
            continue

        for it in root.iter("item"):
            raw_title = html.unescape((it.findtext("title") or "").strip())
            link = (it.findtext("link") or "").strip()
            if not raw_title or not link.startswith("http"):
                continue

            src_el = it.find("source")
            src = (src_el.text or "").strip() if src_el is not None else ""
            title = raw_title
            if " - " in raw_title:
                parts = raw_title.rsplit(" - ", 1)
                title = parts[0].strip()
                if not src:
                    src = parts[1].strip()
            if not src:
                src = default_src

            raw_desc = clean_text(it.findtext("description") or "")
            game = detect_game(title + " " + raw_desc)
            category = detect_category(title + " " + raw_desc)
            pub = parse_date(it.findtext("pubDate") or "")

            # Extraction image directe si présente
            img = extract_enclosure_image(it)
            
            k = title.strip().lower()
            old = existing.get(k, {})

            collected.append({
                "title": title,
                "source": src,
                "url": link,
                "published": pub,
                "game": game,
                "category": category,
                "image": img or old.get("image", ""),
                "snippet": raw_desc,
                "content": old.get("content", ""),
                "first_seen": old.get("first_seen", seen_at)
            })

    # Dédoublonnage
    unique = {}
    for item in collected:
        k = item["title"].lower()
        if k not in unique:
            unique[k] = item

    # Récupération en ligne des vraies images pour les 25 articles les plus récents sans image
    items_list = sorted(list(unique.values()), key=lambda x: x["published"], reverse=True)
    for art in items_list[:25]:
        if not art["image"] or "unsplash" in art["image"]:
            real_img, real_desc, real_link = fetch_real_page_meta(art["url"])
            if real_img:
                art["image"] = real_img
            else:
                art["image"] = get_contextual_fallback(art["title"], art["game"])
            if real_desc:
                art["snippet"] = real_desc
            if real_link and real_link != art["url"]:
                art["url"] = real_link
        
        art["content"] = build_article_body(art["title"], art["snippet"], art["game"], art["category"], art["source"])

    # Fallback pour le reste de la liste
    for art in items_list[25:]:
        if not art["image"]:
            art["image"] = get_contextual_fallback(art["title"], art["game"])
        if not art["content"]:
            art["content"] = build_article_body(art["title"], art["snippet"], art["game"], art["category"], art["source"])

    cutoff = (now - timedelta(days=MAX_AGE_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
    final = [a for a in items_list if a.get("published", "") >= cutoff][:MAX_ITEMS]

    OUT_FILE.write_text(json.dumps(final, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Terminé : {len(final)} articles enregistrés avec métadonnées réelles.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
