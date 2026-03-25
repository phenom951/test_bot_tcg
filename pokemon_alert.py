"""
Pokémon TCG — Stock Alert Bot v1
- Même architecture que le bot One Piece
- Displays, boosters, ETB, UPC, Tins
- Tous sets récents (EV, SV, Écarlate & Violet...)
- Alertes prix + restockage + résumé 20h00
"""
import asyncio, re, requests
from datetime import datetime
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

# ─── CONFIG ───────────────────────────────────────────────────────────────────
DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1486469899743133856/akZLWkcJbUPcyCF-evPLfzGV0nUv7Xr9Ln0Pb8p-0Fy2CDrYaix_K2Rk0RnYRxfkryJC"
CHECK_INTERVAL  = 90
DAILY_RECAP_H   = 20

PRICE_LIMITS = {
    "display": 160.0,   # display 36 boosters
    "etb":      60.0,   # coffret dresseur d'élite
    "upc":      90.0,   # coffret premium
    "tin":      30.0,   # tin
    "booster":   8.0,   # booster à l'unité
}

INCLUDE = [
    "display", "booster", "coffret dresseur", "etb", "elite trainer",
    "coffret premium", "upc", "ultra premium", "tin",
    "écarlate", "ecarlate", "violet", "ev0", "ev1", "ev2", "ev3",
    "ev4", "ev5", "ev6", "ev7", "ev8", "ev9",
    "scarlet", "sv0", "sv1", "sv2", "sv3", "sv4", "sv5", "sv6", "sv7",
    "foudre noire", "destinées de paldea", "forces temporelles",
    "mascarade crépusculaire", "couronne stellaire", "étincelles déferlantes",
    "flammes obsidiennes", "évolutions primastiques", "rivalités destinées",
    "aventures ensemble", "méga-évolution",
]
EXCLUDE = [
    "sleeve", "protège", "portfolio", "classeur", "tapis", "playmat",
    "figurine", "peluche", "stylo", "pin", "cahier", "deck", "starter",
    "promo card", "carte promo", "carte seule", "lot de cartes",
    "accessoire", "binder",
]

SITES = [
    {"name": "Fnac",       "url": "https://www.fnac.com/Pokemon-Cartes-a-collectionner/n564770/w-4",                          "base": "https://www.fnac.com",         "parser": "fnac"},
    {"name": "Cultura",    "url": "https://www.cultura.com/index/index-des-licences/pokemon/cartes-pokemon.html",             "base": "https://www.cultura.com",      "parser": "cultura"},
    {"name": "Carrefour",  "url": "https://www.carrefour.fr/s?q=pokemon+display+booster+coffret",                             "base": "https://www.carrefour.fr",     "parser": "carrefour"},
    {"name": "Amazon",     "url": "https://www.amazon.fr/s?k=pokemon+display+booster+coffret&rh=n%3A322086011",              "base": "https://www.amazon.fr",        "parser": "amazon"},
    {"name": "Philibert",  "url": "https://www.philibertnet.com/fr/recherche?search_query=pokemon+display+booster",          "base": "https://www.philibertnet.com", "parser": "generic"},
    {"name": "Otaku",      "url": "https://www.otaku.fr/catalogsearch/result/?q=pokemon+display+booster",                    "base": "https://www.otaku.fr",         "parser": "generic"},
    {"name": "Magicbazar", "url": "https://www.magicbazar.fr/recherche/?q=pokemon+display",                                  "base": "https://www.magicbazar.fr",    "parser": "generic"},
    {"name": "Agorajeux",  "url": "https://www.agorajeux.com/fr/recherche?controller=search&s=pokemon+booster+display",      "base": "https://www.agorajeux.com",    "parser": "generic"},
]

# ─── ÉTAT ─────────────────────────────────────────────────────────────────────
stock_state      = {}
daily_found      = []
recap_sent_today = False

# ─── FILTRE & PRIX ────────────────────────────────────────────────────────────
def is_wanted(name: str) -> bool:
    n = name.lower()
    if any(k in n for k in EXCLUDE):
        return False
    return any(k in n for k in INCLUDE)

def product_type(name: str) -> str:
    n = name.lower()
    if any(k in n for k in ["ultra premium", "upc", "coffret premium"]): return "upc"
    if any(k in n for k in ["elite trainer", "etb", "dresseur d'élite", "dresseur d elite"]): return "etb"
    if "tin" in n: return "tin"
    if "display" in n: return "display"
    return "booster"

def extract_price(s: str):
    if not s: return None
    m = re.search(r"(\d+)[,.](\d{2})", s.replace("\xa0", ""))
    if m: return float(f"{m.group(1)}.{m.group(2)}")
    m2 = re.search(r"(\d+)", s)
    return float(m2.group(1)) if m2 else None

def price_ok(name: str, price_str: str) -> bool:
    limit = PRICE_LIMITS.get(product_type(name), 0)
    if limit == 0: return True
    val = extract_price(price_str)
    if val is None: return True
    return val <= limit

# ─── DISCORD ──────────────────────────────────────────────────────────────────
def discord_send(title, desc, color=0xFF4500):
    embed = {
        "title": title, "description": desc, "color": color,
        "footer": {"text": f"Pokémon Alert • {datetime.now().strftime('%H:%M:%S')}"},
    }
    try:
        r = requests.post(DISCORD_WEBHOOK, json={"embeds": [embed]}, timeout=10)
        print(f"  {'✅' if r.status_code == 204 else '❌'} Discord : {title}")
    except Exception as e:
        print(f"  ❌ Discord : {e}")

def alert_online(site, name, url, price="", restock=False):
    emoji = "🔄" if restock else "🛒"
    label = "RESTOCKAGE" if restock else "DISPO EN LIGNE"
    p = f" — **{price}**" if price else ""
    discord_send(f"{emoji} {label} — {site}", f"**{name}**{p}\n[👉 Acheter]({url})", 0x00C853 if not restock else 0xFF9800)

def alert_price_exceeded(site, name, url, price):
    discord_send(f"💸 DISPO MAIS CHER — {site}", f"**{name}** — ~~{price}~~ (au dessus du seuil)\n[👉 Voir]({url})", 0x9E9E9E)

def send_daily_recap():
    global daily_found, recap_sent_today
    if not daily_found:
        discord_send("📋 Résumé quotidien Pokémon", "Aucun produit trouvé aujourd'hui.", 0x607D8B)
    else:
        lines = "\n".join(f"• **{p['name']}** — {p['site']} — {p.get('price','?')}" for p in daily_found)
        discord_send(f"📋 Résumé quotidien — {len(daily_found)} produit(s)", lines, 0x607D8B)
    daily_found.clear()
    recap_sent_today = True

def heartbeat():
    requests.post(DISCORD_WEBHOOK,
                  json={"content": f"💓 Pokémon Bot actif — {datetime.now().strftime('%d/%m %H:%M')}"},
                  timeout=10)

# ─── PLAYWRIGHT ───────────────────────────────────────────────────────────────
async def fetch(url: str) -> str:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(
            locale="fr-FR",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
        )
        page = await ctx.new_page()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(3000)
            html = await page.content()
        finally:
            await browser.close()
    return html

# ─── PARSERS ──────────────────────────────────────────────────────────────────
def _link(el, base):
    a = el.select_one("a[href]")
    if not a: return ""
    h = a["href"]
    return (base + h) if h.startswith("/") else h

def _price(el):
    p = el.select_one("[class*='price'],[class*='prix'],[class*='Price']")
    return p.get_text(strip=True) if p else ""

def parse_fnac(html, base):
    soup = BeautifulSoup(html, "html.parser")
    items = soup.select("article.Article,li.Article,div.Article") or soup.select("[data-ref]")
    out = []
    for it in items:
        n_el = it.select_one("h2,h3,[class*='title'],[class*='Title']")
        if not n_el: continue
        name = n_el.get_text(strip=True)
        if not is_wanted(name): continue
        if it.select_one("[class*='unavailable'],[class*='rupture'],[class*='indisponible']"): continue
        out.append({"name": name, "url": _link(it, base), "price": _price(it)})
    return out

def parse_cultura(html, base):
    soup = BeautifulSoup(html, "html.parser")
    items = (soup.select("div[class*='ProductCard'],div[class*='product-item'],li[class*='product']")
             or soup.select("li.product-item,div.product-item"))
    out = []
    for it in items:
        n_el = it.select_one("h2,h3,[class*='ProductName'],[class*='product-name'],[class*='title']")
        if not n_el: continue
        name = n_el.get_text(strip=True)
        if not is_wanted(name): continue
        rupture = it.select_one("[class*='rupture'],[class*='unavailable'],[class*='out-of-stock']")
        add_btn = it.select_one("button[class*='add'],button[class*='cart'],[class*='AddToCart']")
        if rupture and not add_btn: continue
        out.append({"name": name, "url": _link(it, base), "price": _price(it)})
    return out

def parse_carrefour(html, base):
    soup = BeautifulSoup(html, "html.parser")
    items = soup.select("div[class*='ProductCard'],article[class*='product'],div[class*='product-card']")
    out = []
    for it in items:
        n_el = it.select_one("h2,h3,[class*='title'],[class*='name']")
        if not n_el: continue
        name = n_el.get_text(strip=True)
        if not is_wanted(name): continue
        if it.select_one("[class*='rupture'],[class*='unavailable'],[class*='indisponible']"): continue
        out.append({"name": name, "url": _link(it, base), "price": _price(it)})
    return out

def parse_amazon(html, base):
    soup = BeautifulSoup(html, "html.parser")
    items = soup.select("div[data-component-type='s-search-result']")
    out = []
    for it in items:
        n_el = it.select_one("h2 span,h2 a span")
        if not n_el: continue
        name = n_el.get_text(strip=True)
        if not is_wanted(name): continue
        unavail = it.select_one("[class*='a-color-price']")
        if unavail and "indisponible" in unavail.get_text().lower(): continue
        link_el = it.select_one("h2 a[href]")
        url = (base + link_el["href"]) if link_el and link_el["href"].startswith("/") else (link_el["href"] if link_el else "")
        price_el = it.select_one(".a-price .a-offscreen,.a-price-whole")
        price = price_el.get_text(strip=True) if price_el else ""
        out.append({"name": name, "url": url, "price": price})
    return out

def parse_generic(html, base):
    soup = BeautifulSoup(html, "html.parser")
    items = soup.select(
        "article,li[class*='product'],div[class*='product-item'],"
        "div[class*='ProductCard'],div[class*='product_item'],"
        "li[class*='item'],div[class*='item-product']"
    )
    out = []
    seen = set()
    for it in items:
        n_el = it.select_one("h2,h3,h4,[class*='title'],[class*='name'],[class*='product-name']")
        if not n_el: continue
        name = n_el.get_text(strip=True)
        if not name or name in seen: continue
        if not is_wanted(name): continue
        text = it.get_text().lower()
        if any(k in text for k in ["rupture", "indisponible", "out of stock", "épuisé"]): continue
        seen.add(name)
        out.append({"name": name, "url": _link(it, base), "price": _price(it)})
    return out

PARSERS = {
    "fnac": parse_fnac, "cultura": parse_cultura, "carrefour": parse_carrefour,
    "amazon": parse_amazon, "generic": parse_generic,
}

# ─── SCAN ─────────────────────────────────────────────────────────────────────
async def scan(site):
    site_name = site["name"]
    parser    = PARSERS[site["parser"]]
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Scan {site_name}...")
    try:
        html  = await fetch(site["url"])
        prods = parser(html, site["base"])
        print(f"  → {len(prods)} produit(s) sur {site_name}")
        current_keys = set()

        for p in prods:
            key  = f"{site_name}|{p['url']}"
            name = p["name"]
            price = p.get("price", "")
            current_keys.add(key)
            was = stock_state.get(key)

            if not price_ok(name, price):
                stock_state[key] = True
                if was is None:
                    alert_price_exceeded(site_name, name, p["url"], price)
                continue

            if was is None:
                stock_state[key] = True
                alert_online(site_name, name, p["url"], price, restock=False)
                daily_found.append({"name": name, "site": site_name, "price": price})
            elif was is False:
                stock_state[key] = True
                alert_online(site_name, name, p["url"], price, restock=True)
                daily_found.append({"name": name, "site": site_name, "price": price})

        for key, state in list(stock_state.items()):
            if key.startswith(f"{site_name}|") and state is True and key not in current_keys:
                stock_state[key] = False
                print(f"  ⚠️  Hors stock : {key}")

    except Exception as e:
        print(f"  ❌ {site_name} : {e}")

# ─── RÉSUMÉ QUOTIDIEN ─────────────────────────────────────────────────────────
def check_daily_recap():
    global recap_sent_today
    now = datetime.now()
    if now.hour == DAILY_RECAP_H and now.minute < 2:
        if not recap_sent_today:
            send_daily_recap()
    elif now.hour == 0:
        recap_sent_today = False

# ─── MAIN ─────────────────────────────────────────────────────────────────────
async def main():
    print("=" * 60)
    print("  Pokémon TCG Stock Alert — v1")
    print(f"  Sites : {', '.join(s['name'] for s in SITES)}")
    print(f"  Prix max : display {PRICE_LIMITS['display']}€ | ETB {PRICE_LIMITS['etb']}€ | UPC {PRICE_LIMITS['upc']}€ | tin {PRICE_LIMITS['tin']}€ | booster {PRICE_LIMITS['booster']}€")
    print(f"  Résumé : {DAILY_RECAP_H}h00")
    print("=" * 60)
    heartbeat()

    cycle = 0
    while True:
        cycle += 1
        print(f"\n── Cycle #{cycle} {'─'*40}")
        for site in SITES:
            await scan(site)
            await asyncio.sleep(4)
        check_daily_recap()
        if cycle % 40 == 0:
            heartbeat()
        print(f"  ⏳ Prochaine vérif dans {CHECK_INTERVAL}s")
        await asyncio.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    asyncio.run(main())
