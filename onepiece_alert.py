"""
One Piece TCG — Stock Alert Bot v2
- Playwright pour contourner les 403
- Filtre strict : displays, boosters, PRB, EB (pas de starters/decks)
- Stock en ligne ET magasins Val d'Oise
"""
import asyncio, re, requests
from datetime import datetime
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

# ─── CONFIG ───────────────────────────────────────────────────────────────────
DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1486098578752536697/BpgUOLAmL2fM5HGyFhYFLEVY20F-TZBXA0B7zCyQbxDV_4A2gjwdlLEs2Is7X1Il0uuw"
CHECK_INTERVAL  = 90  # secondes

CULTURA_STORES = [
    {"id": "0095", "name": "Cultura Franconville"},
    {"id": "0064", "name": "Cultura Cergy"},
    {"id": "0082", "name": "Cultura Montigny-lès-Cormeilles"},
]

INCLUDE = [
    "display", "booster", "blister",
    "prb-", "prb 0", "eb-", "eb 0",
    "op-", "op0", "op1", "op2", "op3", "op4", "op5",
    "op6", "op7", "op8", "op9", "op1", "premium booster",
]
EXCLUDE = [
    "starter", "deck", "st-", " st0", " st1", " st2",
    "portfolio", "protège", "sleeves", "tapis", "playmat",
    "figurine", "manga", "roman",
]

SITES = [
    {
        "name": "Fnac",
        "url":  "https://www.fnac.com/n564773/Jeux-de-recre-cartes-a-collectionner/Cartes-a-collectionner-One-Piece",
        "base": "https://www.fnac.com",
        "parser": "fnac",
    },
    {
        "name": "Cultura",
        "url":  "https://www.cultura.com/index/index-des-licences/one-piece/cartes-one-piece.html",
        "base": "https://www.cultura.com",
        "parser": "cultura",
    },
    {
        "name": "Carrefour",
        "url":  "https://www.carrefour.fr/s?q=one+piece+carte+booster+display",
        "base": "https://www.carrefour.fr",
        "parser": "carrefour",
    },
]

already_online = set()
already_store  = set()

# ─── FILTRE ───────────────────────────────────────────────────────────────────
def is_wanted(name: str) -> bool:
    n = name.lower()
    if any(k in n for k in EXCLUDE):
        return False
    return any(k in n for k in INCLUDE)

# ─── DISCORD ──────────────────────────────────────────────────────────────────
def discord(title, desc, color=0xFF4500):
    embed = {
        "title": title, "description": desc, "color": color,
        "footer": {"text": f"OP Alert • {datetime.now().strftime('%H:%M:%S')}"},
    }
    try:
        r = requests.post(DISCORD_WEBHOOK, json={"embeds": [embed]}, timeout=10)
        print(f"  {'✅' if r.status_code == 204 else '❌'} Discord : {title}")
    except Exception as e:
        print(f"  ❌ Discord : {e}")

def alert_online(site, name, url, price=""):
    p = f" — **{price}**" if price else ""
    discord(f"🛒 DISPO EN LIGNE — {site}", f"**{name}**{p}\n[👉 Acheter]({url})", 0x00C853)

def alert_store(store, name, url, qty=0):
    q = f" ({qty} en stock)" if qty > 0 else ""
    discord(f"🏪 DISPO EN MAGASIN — {store}", f"**{name}**{q}\n[👉 Voir]({url})", 0x2196F3)

def heartbeat():
    requests.post(DISCORD_WEBHOOK,
                  json={"content": f"💓 Bot actif — {datetime.now().strftime('%d/%m %H:%M')}"},
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
    if not a:
        return ""
    h = a["href"]
    return (base + h) if h.startswith("/") else h

def _price(el):
    p = el.select_one("[class*='price'],[class*='prix'],[class*='Price']")
    return p.get_text(strip=True) if p else ""

def parse_fnac(html, base):
    soup = BeautifulSoup(html, "html.parser")
    items = soup.select("article.Article, li.Article, div.Article") or \
            soup.select("[data-ref]")
    out = []
    for it in items:
        n_el = it.select_one("h2,h3,[class*='title'],[class*='Title']")
        if not n_el: continue
        name = n_el.get_text(strip=True)
        if not is_wanted(name): continue
        if it.select_one("[class*='unavailable'],[class*='rupture'],[class*='indisponible']"):
            continue
        out.append({"name": name, "url": _link(it, base), "price": _price(it)})
    return out

def parse_cultura(html, base):
    soup = BeautifulSoup(html, "html.parser")
    items = (soup.select("div[class*='ProductCard'],div[class*='product-item'],li[class*='product']")
             or soup.select("li.product-item, div.product-item"))
    out = []
    for it in items:
        n_el = it.select_one("h2,h3,[class*='ProductName'],[class*='product-name'],[class*='title']")
        if not n_el: continue
        name = n_el.get_text(strip=True)
        if not is_wanted(name): continue
        # En stock si bouton "ajouter" présent OU pas de badge rupture
        rupture = it.select_one("[class*='rupture'],[class*='unavailable'],[class*='out-of-stock']")
        add_btn = it.select_one("button[class*='add'],button[class*='cart'],[class*='AddToCart']")
        if rupture and not add_btn:
            continue
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
        if it.select_one("[class*='rupture'],[class*='unavailable'],[class*='indisponible']"):
            continue
        out.append({"name": name, "url": _link(it, base), "price": _price(it)})
    return out

PARSERS = {"fnac": parse_fnac, "cultura": parse_cultura, "carrefour": parse_carrefour}

# ─── STOCK MAGASIN CULTURA ───────────────────────────────────────────────────
def cultura_pid(url):
    m = re.search(r"-(\d{7,})\.html", url)
    return m.group(1) if m else None

def check_stores(pid, name, url):
    for store in CULTURA_STORES:
        try:
            r = requests.get(
                f"https://www.cultura.com/api/stores/stock?productId={pid}&storeId={store['id']}",
                headers={"Accept": "application/json"}, timeout=8
            )
            if r.status_code != 200: continue
            data = r.json()
            qty = data.get("quantity") or data.get("stock") or data.get("qty") or 0
            if data.get("inStock") or data.get("available") or int(qty) > 0:
                key = f"{store['id']}|{url}"
                if key not in already_store:
                    already_store.add(key)
                    alert_store(store["name"], name, url, int(qty))
        except Exception as e:
            print(f"  Store API ({store['name']}) : {e}")

# ─── SCAN ─────────────────────────────────────────────────────────────────────
async def scan(site):
    name   = site["name"]
    parser = PARSERS[site["parser"]]
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Scan {name}...")
    try:
        html  = await fetch(site["url"])
        prods = parser(html, site["base"])
        print(f"  → {len(prods)} produit(s) ciblé(s) sur {name}")
        for p in prods:
            key = f"{name}|{p['url']}"
            if key not in already_online:
                already_online.add(key)
                alert_online(name, p["name"], p["url"], p.get("price", ""))
            if name == "Cultura" and p["url"]:
                pid = cultura_pid(p["url"])
                if pid:
                    check_stores(pid, p["name"], p["url"])
    except Exception as e:
        print(f"  ❌ {name} : {e}")

# ─── MAIN ─────────────────────────────────────────────────────────────────────
async def main():
    print("=" * 55)
    print("  One Piece TCG Stock Alert — v2")
    print(f"  Sites    : {', '.join(s['name'] for s in SITES)}")
    print(f"  Magasins : {', '.join(s['name'] for s in CULTURA_STORES)}")
    print(f"  Intervalle : {CHECK_INTERVAL}s")
    print("=" * 55)
    heartbeat()

    cycle = 0
    while True:
        cycle += 1
        print(f"\n── Cycle #{cycle} {'─'*38}")
        for site in SITES:
            await scan(site)
            await asyncio.sleep(4)
        if cycle % 40 == 0:
            heartbeat()
        print(f"  ⏳ Prochaine vérif dans {CHECK_INTERVAL}s")
        await asyncio.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    asyncio.run(main())
