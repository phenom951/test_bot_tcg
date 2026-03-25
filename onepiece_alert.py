"""
One Piece TCG — Stock Alert Bot v3
- 8 sites surveillés
- Filtre prix par type de produit
- Détection restockage
- Résumé quotidien 20h00
- Stock magasins Val d'Oise (Cultura)
"""
import asyncio, re, requests
from datetime import datetime, time as dtime
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

# Installer Chromium si absent

# ─── CONFIG ───────────────────────────────────────────────────────────────────
DISCORD_WEBHOOK = "https://discord.com/api/webhooks/1486098578752536697/BpgUOLAmL2fM5HGyFhYFLEVY20F-TZBXA0B7zCyQbxDV_4A2gjwdlLEs2Is7X1Il0uuw"
CHECK_INTERVAL  = 90   # secondes
DAILY_RECAP_H   = 20   # heure du résumé quotidien

# Seuils prix par type (0 = pas de seuil)
PRICE_LIMITS = {
    "display":  120.0,   # display standard OP-XX
    "premium":   60.0,   # PRB, EB, premium booster
    "booster":    8.0,   # booster à l'unité / blister
}

CULTURA_STORES = [
    {"id": "0095", "name": "Cultura Franconville"},
    {"id": "0064", "name": "Cultura Cergy"},
    {"id": "0082", "name": "Cultura Montigny-lès-Cormeilles"},
]

INCLUDE = [
    "display", "booster", "blister",
    "prb-", "prb 0", "eb-", "eb 0",
    "op-", "op0", "op1", "op2", "op3", "op4", "op5",
    "op6", "op7", "op8", "op9", "op10", "op11", "op12", "op13",
    "premium booster",
]
EXCLUDE = [
    "starter", "deck", "démarrage", "débutant", "apprendre",
    "st-", "st0", "st1", "st2", "st3",
    "portfolio", "protège", "sleeves", "tapis", "playmat",
    "figurine", "manga", "roman", "coffret découverte",
    "lot de deck", "coffret cadeau",
]

SITES = [
    {"name": "Fnac",       "url": "https://www.fnac.com/n564773/Jeux-de-recre-cartes-a-collectionner/Cartes-a-collectionner-One-Piece",         "base": "https://www.fnac.com",          "parser": "fnac"},
    {"name": "Cultura",    "url": "https://www.cultura.com/index/index-des-licences/one-piece/cartes-one-piece.html",                           "base": "https://www.cultura.com",       "parser": "cultura"},
    {"name": "Carrefour",  "url": "https://www.carrefour.fr/s?q=one+piece+carte+booster+display",                                               "base": "https://www.carrefour.fr",      "parser": "carrefour"},
    {"name": "Amazon",     "url": "https://www.amazon.fr/s?k=one+piece+card+game+display+booster&rh=n%3A322086011",                             "base": "https://www.amazon.fr",         "parser": "amazon"},
    {"name": "Philibert",  "url": "https://www.philibertnet.com/fr/recherche?search_query=one+piece+display+booster&submit_search=",            "base": "https://www.philibertnet.com",  "parser": "philibert"},
    {"name": "Otaku",      "url": "https://www.otaku.fr/catalogsearch/result/?q=one+piece+display+booster",                                     "base": "https://www.otaku.fr",          "parser": "generic"},
    {"name": "Magicbazar", "url": "https://www.magicbazar.fr/recherche/?q=one+piece+display",                                                   "base": "https://www.magicbazar.fr",     "parser": "generic"},
    {"name": "Agorajeux",  "url": "https://www.agorajeux.com/fr/recherche?controller=search&s=one+piece+booster+display",                       "base": "https://www.agorajeux.com",     "parser": "generic"},
]

# ─── ÉTAT ─────────────────────────────────────────────────────────────────────
# clé → True si en stock, False si hors stock (pour détecter restockage)
stock_state   = {}   # "site|url" → bool
already_store = set()
daily_found   = []   # produits trouvés dans la journée
recap_sent_today = False

# ─── FILTRE & PRIX ────────────────────────────────────────────────────────────
def is_wanted(name: str) -> bool:
    n = name.lower()
    if any(k in n for k in EXCLUDE):
        return False
    return any(k in n for k in INCLUDE)

def product_type(name: str) -> str:
    n = name.lower()
    if any(k in n for k in ["prb", "eb-", "eb 0", "premium booster", "extra booster"]):
        return "premium"
    if "display" in n:
        return "display"
    return "booster"

def extract_price(price_str: str) -> float | None:
    """Extrait un float depuis une chaîne de prix (ex: '89,99 €' → 89.99)"""
    if not price_str:
        return None
    m = re.search(r"(\d+)[,.](\d{2})", price_str.replace("\xa0", ""))
    if m:
        return float(f"{m.group(1)}.{m.group(2)}")
    m2 = re.search(r"(\d+)", price_str)
    return float(m2.group(1)) if m2 else None

def price_ok(name: str, price_str: str) -> bool:
    """Retourne True si le prix est sous le seuil ou si pas de prix trouvé."""
    ptype = product_type(name)
    limit = PRICE_LIMITS.get(ptype, 0)
    if limit == 0:
        return True
    val = extract_price(price_str)
    if val is None:
        return True   # pas de prix → on alerte quand même
    return val <= limit

# ─── DISCORD ──────────────────────────────────────────────────────────────────
def discord_send(title, desc, color=0xFF4500):
    embed = {
        "title": title, "description": desc, "color": color,
        "footer": {"text": f"OP Alert • {datetime.now().strftime('%H:%M:%S')}"},
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

def alert_store(store, name, url, qty=0):
    q = f" ({qty} en stock)" if qty > 0 else ""
    discord_send(f"🏪 DISPO EN MAGASIN — {store}", f"**{name}**{q}\n[👉 Voir]({url})", 0x2196F3)

def alert_price_exceeded(site, name, url, price):
    discord_send(f"💸 DISPO MAIS CHER — {site}", f"**{name}** — ~~{price}~~ (au dessus du seuil)\n[👉 Voir]({url})", 0x9E9E9E)

def send_daily_recap():
    global daily_found, recap_sent_today
    if not daily_found:
        discord_send("📋 Résumé quotidien", "Aucun produit trouvé aujourd'hui.", 0x607D8B)
    else:
        lines = "\n".join(f"• **{p['name']}** — {p['site']} — {p.get('price','?')}" for p in daily_found)
        discord_send(f"📋 Résumé quotidien — {len(daily_found)} produit(s)", lines, 0x607D8B)
    daily_found.clear()
    recap_sent_today = True

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
        n_el = it.select_one("h2 span, h2 a span")
        if not n_el: continue
        name = n_el.get_text(strip=True)
        if not is_wanted(name): continue
        # Exclure si pas de prix (souvent = indisponible sur Amazon)
        price_el = it.select_one(".a-price .a-offscreen, .a-price-whole")
        if not price_el: continue
        price = price_el.get_text(strip=True)
        # Exclure "Actuellement indisponible"
        full_text = it.get_text().lower()
        if any(k in full_text for k in ["indisponible", "currently unavailable", "en rupture"]): continue
        # Reconstruire l'URL proprement (enlever les paramètres de tracking sauf /dp/ASIN)
        link_el = it.select_one("h2 a[href]")
        if not link_el: continue
        raw = link_el["href"]
        # Extraire l'ASIN depuis l'URL Amazon (/dp/XXXXXXXXXX)
        asin_m = re.search(r"/dp/([A-Z0-9]{10})", raw)
        if asin_m:
            url = f"https://www.amazon.fr/dp/{asin_m.group(1)}"
        else:
            url = (base + raw) if raw.startswith("/") else raw
        out.append({"name": name, "url": url, "price": price})
    return out

def parse_philibert(html, base):
    """Parser dédié Philibert (PrestaShop).
    Seuls les produits avec bouton 'Ajouter au panier' sont considérés en stock.
    Les produits en rupture ont un bouton 'Prévenez-moi' et la classe 'out_of_stock'.
    """
    soup = BeautifulSoup(html, "html.parser")
    items = soup.select("li.ajax_block_product, div.ajax_block_product, li[id*='product']")
    if not items:
        # Fallback si structure différente
        items = soup.select("li[class*='product'], div[class*='product_item']")
    out = []
    seen = set()
    for it in items:
        n_el = it.select_one("h5, h3, .product-name, [class*='product_name'], [class*='product-name']")
        if not n_el: continue
        name = n_el.get_text(strip=True)
        if not name or name in seen: continue
        if not is_wanted(name): continue
        # Exclure si classe out_of_stock présente sur le bloc produit
        if it.select_one("[class*='out_of_stock']"): continue
        # Exclure si le bouton est "Prévenez-moi" (= rupture Philibert)
        btn = it.select_one("button, a[class*='button']")
        if btn and any(k in btn.get_text().lower() for k in ["prévenez", "prevenez", "notify", "alerte"]): continue
        # Exclure si "rupture" dans le HTML du bloc
        if "rupture" in it.get_text().lower(): continue
        seen.add(name)
        out.append({"name": name, "url": _link(it, base), "price": _price(it)})
    return out

def parse_generic(html, base):
    """Parser générique pour Otaku, Magicbazar, Agorajeux."""
    soup = BeautifulSoup(html, "html.parser")
    items = soup.select(
        "article, li[class*='product'], div[class*='product-item'], "
        "div[class*='ProductCard'], div[class*='product_item'], "
        "li[class*='item'], div[class*='item-product']"
    )
    out = []
    seen = set()
    for it in items:
        n_el = it.select_one("h2,h3,h4,[class*='title'],[class*='name'],[class*='product-name']")
        if not n_el: continue
        name = n_el.get_text(strip=True)
        if not name or name in seen: continue
        if not is_wanted(name): continue
        text = it.get_text()
        text_low = text.lower()
        if any(k in text_low for k in ["rupture", "indisponible", "out of stock", "currently unavailable", "épuisé", "epuise"]): continue
        if it.select_one("[class*='out_of_stock'],[class*='out-of-stock'],[class*='unavailable'],[class*='rupture']"): continue
        if it.select_one("button[disabled],button[class*='disabled']"): continue
        seen.add(name)
        out.append({"name": name, "url": _link(it, base), "price": _price(it)})
    return out

PARSERS = {
    "fnac":       parse_fnac,
    "cultura":    parse_cultura,
    "carrefour":  parse_carrefour,
    "amazon":     parse_amazon,
    "philibert":  parse_philibert,
    "generic":    parse_generic,
}

# ─── STOCK MAGASIN CULTURA ────────────────────────────────────────────────────
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
    site_name = site["name"]
    parser    = PARSERS[site["parser"]]
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Scan {site_name}...")
    try:
        html  = await fetch(site["url"])
        prods = parser(html, site["base"])
        print(f"  → {len(prods)} produit(s) ciblé(s) sur {site_name}")

        # Marquer tous les produits connus comme hors-stock pour détecter les disparitions
        current_keys = set()

        for p in prods:
            key   = f"{site_name}|{p['url']}"
            name  = p["name"]
            price = p.get("price", "")
            current_keys.add(key)

            was_in_stock = stock_state.get(key)  # None = jamais vu, True = était en stock, False = était hors stock

            # Vérification prix
            if not price_ok(name, price):
                stock_state[key] = True
                if was_in_stock is None:
                    # Premier fois qu'on voit ce produit mais trop cher → alerte grisée
                    alert_price_exceeded(site_name, name, p["url"], price)
                continue

            if was_in_stock is None:
                # Nouveau produit en stock
                stock_state[key] = True
                alert_online(site_name, name, p["url"], price, restock=False)
                daily_found.append({"name": name, "site": site_name, "price": price})
            elif was_in_stock is False:
                # Était hors stock → maintenant en stock = RESTOCKAGE
                stock_state[key] = True
                alert_online(site_name, name, p["url"], price, restock=True)
                daily_found.append({"name": name, "site": site_name, "price": price})
            # Si was_in_stock is True → déjà alerté, rien à faire

            # Stock magasin Cultura
            if site_name == "Cultura" and p["url"]:
                pid = cultura_pid(p["url"])
                if pid:
                    check_stores(pid, name, p["url"])

        # Produits qui étaient en stock mais absents du scan actuel → hors stock
        for key, state in list(stock_state.items()):
            if key.startswith(f"{site_name}|") and state is True and key not in current_keys:
                stock_state[key] = False
                print(f"  ⚠️ Hors stock : {key}")

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
        recap_sent_today = False   # reset à minuit

# ─── MAIN ─────────────────────────────────────────────────────────────────────
async def main():
    print("=" * 60)
    print("  One Piece TCG Stock Alert — v3")
    print(f"  Sites    : {', '.join(s['name'] for s in SITES)}")
    print(f"  Magasins : {', '.join(s['name'] for s in CULTURA_STORES)}")
    print(f"  Prix max : display {PRICE_LIMITS['display']}€ | premium {PRICE_LIMITS['premium']}€ | booster {PRICE_LIMITS['booster']}€")
    print(f"  Résumé quotidien : {DAILY_RECAP_H}h00")
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
