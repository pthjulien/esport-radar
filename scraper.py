import html
import json
import os
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

RSS_URL = "https://news.google.com/rss/search?q=esport+valorant+league+of+legends+cs2&hl=fr&gl=FR&ceid=FR:fr"
DATA_FILE = "data.json"
MAX_ARTICLES = 300
MAX_AGE_DAYS = 30

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 (EsportRadarBot/1.0)"
}

def clean_html(raw_html):
    if not raw_html:
        return ""
    clean = re.sub(r'<[^>]+>', ' ', raw_html)
    return html.unescape(clean).strip()

def detect_game(title):
    t = title.lower()
    if re.search(r'\bleague of legends\b|\blol\b|\blec\b|\blck\b|\blcs\b|\blpl\b|\blfl\b', t):
        return 'lol'
    if re.search(r'\bvalorant\b|\bvct\b', t):
        return 'val'
    if re.search(r'\bcounter-strike\b|\bcs2\b|\bcsgo\b|\bcs:go\b|\bhltv\b', t):
        return 'cs2'
    if re.search(r'\brocket league\b|\brlcs\b', t):
        return 'rl'
    if re.search(r'\bdota\b', t):
        return 'dota'
    return 'other'

def detect_category(title):
    t = title.lower()
    if re.search(r'rumou?rs?|rumeurs?|reportedly|leak|fuite|according to|selon|serait|pourrait|aurait|envisage|piste|sur le point|courtise|set to join', t):
        return 'rumor'
    if re.search(r'\b(joins?|signs?|signed|parts? ways|benched|acquires?|leaves|departs?|roster|transfers?|extends?|re-sign|rejoint|rejoignent|signe|officialise|quitte|quittent|prolonge|recrute|transfert|débarque|s\'engage|change d\'équipe)\b', t):
        return 'official'
    if re.search(r'\bpatch\b|\bmise à jour\b|\bupdate\b', t):
        return 'patch'
    if re.search(r'major|masters|tournoi|tournament|qualif|\biem\b|\bpgl\b|blast|playoff|worlds|mondial|\bmsi\b|\bvct\b|\blec\b|\blck\b|\blfl\b|finale|\bfinal\b|\besl\b|rlcs|champion', t):
        return 'tournament'
    return 'news'

def fetch_rss():
    req = urllib.request.Request(RSS_URL, headers=HEADERS)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                if resp.status == 200:
                    return resp.read()
        except Exception as e:
            print(f"Tentative {attempt + 1}/3 échouée : {e}", file=sys.stderr)
            time.sleep(2)
    return None

def parse_rss(xml_data):
    root = ET.fromstring(xml_data)
    items = []
    now_iso = datetime.now(timezone.utc).isoformat()
    
    for item in root.findall(".//item"):
        title_elem = item.find("title")
        link_elem = item.find("link")
        pubdate_elem = item.find("pubDate")
        desc_elem = item.find("description")
        source_elem = item.find("source")
        
        raw_title = title_elem.text if title_elem is not None else ""
        link = link_elem.text if link_elem is not None else ""
        pubdate = pubdate_elem.text if pubdate_elem is not None else ""
        desc = desc_elem.text if desc_elem is not None else ""
        
        if not raw_title or not link:
            continue
            
        source = source_elem.text if source_elem is not None and source_elem.text else ""
        clean_title = raw_title
        if " - " in raw_title:
            parts = raw_title.rsplit(" - ", 1)
            clean_title = parts[0].strip()
            if not source:
                source = parts[1].strip()
                
        also = []
        if desc:
            fonts = re.findall(r'<font[^>]*>(.*?)</font>', desc)
            for f in fonts:
                f_clean = clean_html(f)
                if f_clean and f_clean != source and f_clean not in also:
                    also.append(f_clean)
                    
        try:
            published_dt = parsedate_to_datetime(pubdate) if pubdate else datetime.now(timezone.utc)
        except Exception:
            published_dt = datetime.now(timezone.utc)
            
        published_iso = published_dt.astimezone(timezone.utc).isoformat()
        
        items.append({
            "title": clean_title,
            "source": source or "Google Actualités",
            "url": link,
            "published": published_iso,
            "game": detect_game(clean_title),
            "category": detect_category(clean_title),
            "also": also[:3],
            "first_seen": now_iso
        })
    return items

def main():
    xml_data = fetch_rss()
    if not xml_data:
        print("Erreur critique : impossible de récupérer le flux RSS.", file=sys.stderr)
        sys.exit(1)
        
    new_items = parse_rss(xml_data)
    if not new_items:
        print("Erreur : aucun article trouvé dans le flux RSS.", file=sys.stderr)
        sys.exit(1)
        
    existing_items = []
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                content = f.read().strip()
                if content:
                    existing_items = json.loads(content)
        except Exception as e:
            print(f"Avertissement : lecture de {DATA_FILE} ({e})", file=sys.stderr)
            existing_items = []

    items_by_url = {item["url"]: item for item in existing_items if "url" in item}

    for item in new_items:
        url = item["url"]
        if url in items_by_url:
            item["first_seen"] = items_by_url[url].get("first_seen", item["first_seen"])
        items_by_url[url] = item

    cutoff = datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS)
    all_items = []
    for item in items_by_url.values():
        try:
            pub_dt = datetime.fromisoformat(item["published"])
            if pub_dt >= cutoff:
                all_items.append(item)
        except Exception:
            all_items.append(item)

    all_items.sort(key=lambda x: x.get("published", ""), reverse=True)
    all_items = all_items[:MAX_ARTICLES]

    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(all_items, f, ensure_ascii=False, indent=2)

    print(f"Succès : {len(all_items)} articles enregistrés dans {DATA_FILE}.")

if __name__ == "__main__":
    main()
