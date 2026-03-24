import requests
import time
import json
import re
from datetime import datetime
from bs4 import BeautifulSoup

# ─────────────────────────────────────────────
#  CONFIG
# ─────────────────────────────────────────────
DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1486098578752536697/BpgUOLAmL2fM5HGyFhYFLEVY20F-TZBXA0B7zCyQbxDV_4A2gjwdlLEs2Is7X1Il0uuw"
CHECK_INTERVAL  = 60   # secondes entre chaque scan complet
KEYWORDS        = ["one piece", "op-", "op0", "op1", "prb-", "eb-"]  # mots-clés produits ciblés

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

# ─────────────────────────────────────────────
#  SITES À SURVEILLER
#  Chaque entrée : nom, url de la page listing/recherche, fonction de parsing
# ─────────────────────────────────────────────
SITES = [
    {
        "name": "Fnac",
        "url": "https://www.fnac.com/n564773/Jeux-de-recre-cartes-a-collectionner/Cartes-a-collectionner-One-Piece",
        "parser": "fnac",
    },
    {
        "name": "Cultura",
        "url": "https://www.cultura.com/index/index-des-licences/one-piece/cartes-one-piece.html",
        "parser": "cultura",
    },
    {
        "name": "Carrefour",
        "url": "https://www.carrefour.fr/s?q=one+piece+display+booster&filters=eyJjYXRlZ29yeSI6WyJKb3VldCJdfQ%3D%3D",
        "parser": "carrefour",
    },
]

# ─────────────────────────────────────────────
#  ÉTAT  (pour éviter les alertes en double)
# ─────────────────────────────────────────────
already_alerted = set()

# ─────────────────────────────────────────────
#  DISCORD
# ─────────────────────────────────────────────
def send_discord_alert(site_name: str, product_name: str, url: str, price: str = ""):
    price_str = f" — **{price}**" if price else ""
    embed = {
        "title": f"🚨 STOCK DISPO — {site_name}",
        "description": f"**{product_name}**{price_str}\n[👉 Acheter maintenant]({url})",
        "color": 0xFF4500,
        "footer": {"text": f"One Piece Stock Alert • {datetime.now().strftime('%H:%M:%S')}"},
    }
    payload = {"embeds": [embed]}
    try:
        r = requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)
        if r.status_code == 204:
            print(f"  [Discord] Alerte envoyée : {product_name}")
        else:
            print(f"  [Discord] Erreur {r.status_code} : {r.text[:200]}")
    except Exception as e:
        print(f"  [Discord] Exception : {e}")


def send_discord_heartbeat():
    payload = {"content": f"💓 One Piece Alert actif — {datetime.now().strftime('%d/%m %H:%M')}"}
    try:
        requests.post(DISCORD_WEBHOOK, json=payload, timeout=10)
    except Exception:
        pass

# ─────────────────────────────────────────────
#  PARSERS PAR SITE
# ─────────────────────────────────────────────
def is_one_piece_tcg(name: str) -> bool:
    n = name.lower()
    return any(k in n for k in KEYWORDS)


def parse_fnac(html: str, base_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    results = []
    for article in soup.select("article.Article, li.Article, div[class*='Article']"):
        name_el = article.select_one("h2, h3, .Article-title, [class*='title']")
        if not name_el:
            continue
        name = name_el.get_text(strip=True)
        if not is_one_piece_tcg(name):
            continue

        # Vérifier disponibilité
        unavail = article.select_one("[class*='unavailable'], [class*='rupture'], [class*='indisponible']")
        avail   = article.select_one("[class*='available'], [class*='stock'], [class*='panier'], button[data-add]")
        if unavail and not avail:
            continue

        link_el = article.select_one("a[href]")
        url = link_el["href"] if link_el else base_url
        if url.startswith("/"):
            url = "https://www.fnac.com" + url

        price_el = article.select_one("[class*='price'], [class*='prix']")
        price = price_el.get_text(strip=True) if price_el else ""

        results.append({"name": name, "url": url, "price": price})
    return results


def parse_cultura(html: str, base_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    results = []
    for item in soup.select("div.product-item, li.product-item, article, div[class*='product']"):
        name_el = item.select_one("h2, h3, .product-name, [class*='name'], [class*='title']")
        if not name_el:
            continue
        name = name_el.get_text(strip=True)
        if not is_one_piece_tcg(name):
            continue

        unavail = item.select_one("[class*='unavailable'], [class*='rupture'], [class*='indisponible'], [class*='out-of-stock']")
        if unavail:
            continue

        link_el = item.select_one("a[href]")
        url = link_el["href"] if link_el else base_url
        if url.startswith("/"):
            url = "https://www.cultura.com" + url

        price_el = item.select_one("[class*='price'], [class*='prix']")
        price = price_el.get_text(strip=True) if price_el else ""

        results.append({"name": name, "url": url, "price": price})
    return results


def parse_carrefour(html: str, base_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    results = []
    for item in soup.select("div[class*='product'], article, li[class*='product']"):
        name_el = item.select_one("h2, h3, p[class*='name'], [class*='title']")
        if not name_el:
            continue
        name = name_el.get_text(strip=True)
        if not is_one_piece_tcg(name):
            continue

        unavail = item.select_one("[class*='unavailable'], [class*='rupture'], [class*='indisponible']")
        if unavail:
            continue

        link_el = item.select_one("a[href]")
        url = link_el["href"] if link_el else base_url
        if url.startswith("/"):
            url = "https://www.carrefour.fr" + url

        price_el = item.select_one("[class*='price'], [class*='prix']")
        price = price_el.get_text(strip=True) if price_el else ""

        results.append({"name": name, "url": url, "price": price})
    return results


PARSERS = {
    "fnac":      parse_fnac,
    "cultura":   parse_cultura,
    "carrefour": parse_carrefour,
}

# ─────────────────────────────────────────────
#  SCAN
# ─────────────────────────────────────────────
def scan_site(site: dict):
    name    = site["name"]
    url     = site["url"]
    parser  = PARSERS[site["parser"]]
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Scan {name}...")
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        if r.status_code != 200:
            print(f"  HTTP {r.status_code} sur {name}")
            return
        products = parser(r.text, url)
        print(f"  {len(products)} produit(s) One Piece détecté(s) en stock sur {name}")
        for p in products:
            key = f"{name}|{p['url']}"
            if key not in already_alerted:
                already_alerted.add(key)
                send_discord_alert(name, p["name"], p["url"], p.get("price", ""))
    except Exception as e:
        print(f"  Erreur sur {name} : {e}")


# ─────────────────────────────────────────────
#  MAIN LOOP
# ─────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 50)
    print("  One Piece TCG — Stock Alert Bot")
    print(f"  Intervalle : {CHECK_INTERVAL}s")
    print(f"  Sites : {', '.join(s['name'] for s in SITES)}")
    print("=" * 50)
    send_discord_heartbeat()

    cycle = 0
    while True:
        cycle += 1
        print(f"\n── Cycle #{cycle} ──────────────────────")
        for site in SITES:
            scan_site(site)
            time.sleep(3)   # petit délai entre sites pour ne pas flood
        print(f"  Prochaine vérification dans {CHECK_INTERVAL}s...")
        # Heartbeat toutes les heures (60 cycles de 60s)
        if cycle % 60 == 0:
            send_discord_heartbeat()
        time.sleep(CHECK_INTERVAL)
