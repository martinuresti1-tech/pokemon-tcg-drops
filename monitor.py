import json
import os
import re
import subprocess
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse, parse_qsl, urlencode

import httpx
from bs4 import BeautifulSoup

STATE_PATH = Path("state.json")
ONLINE_WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
LOCAL_WEBHOOK = os.getenv("LOCAL_DISCORD_WEBHOOK_URL", "").strip()
MANUAL_RUN = os.getenv("GITHUB_EVENT_NAME", "") == "workflow_dispatch"
MAX_OVER_RETAIL = 15.00
LOCAL_CITY = "Greenville"
LOCAL_STATE = "TX"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/126.0 Safari/537.36 PokemonTCGDrops/2.0"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

STORES = [
    {
        "key": "walmart",
        "name": "Walmart",
        "domains": ["walmart.com"],
        "search_urls": [
            "https://www.walmart.com/search?q=pokemon+tcg",
            "https://www.walmart.com/search?q=pokemon+cards",
            "https://www.walmart.com/search?q=pokemon+elite+trainer+box",
            "https://www.walmart.com/search?q=pokemon+booster+bundle",
            "https://www.walmart.com/search?q=pokemon+30th+celebration",
            "https://www.walmart.com/browse/collectibles/pokemon-cards/5967908_9807313_4252400",
        ],
        "direct_sellers": ["walmart", "walmart.com"],
    },
    {
        "key": "target",
        "name": "Target",
        "domains": ["target.com"],
        "search_urls": [
            "https://www.target.com/c/pokemon-trading-cards-card-games-toys/-/N-6llsh",
            "https://www.target.com/s?searchTerm=pokemon+tcg",
            "https://www.target.com/s?searchTerm=pokemon+cards",
            "https://www.target.com/s?searchTerm=pokemon+elite+trainer+box",
            "https://www.target.com/s?searchTerm=pokemon+booster+bundle",
            "https://www.target.com/s?searchTerm=pokemon+30th+celebration",
        ],
        "direct_sellers": ["target"],
    },
    {
        "key": "barnes_noble",
        "name": "Barnes & Noble",
        "domains": ["barnesandnoble.com"],
        "search_urls": [
            "https://www.barnesandnoble.com/s/pokemon%20tcg",
            "https://www.barnesandnoble.com/s/pokemon%20cards",
        ],
        "direct_sellers": ["barnes & noble", "barnes and noble"],
    },
    {
        "key": "dicks",
        "name": "DICK'S Sporting Goods",
        "domains": ["dickssportinggoods.com"],
        "search_urls": [
            "https://www.dickssportinggoods.com/search/SearchDisplay?searchTerm=pokemon%20cards",
            "https://www.dickssportinggoods.com/search/SearchDisplay?searchTerm=pokemon%20tcg",
            "https://www.dickssportinggoods.com/search/SearchDisplay?searchTerm=pokemon%20elite%20trainer%20box",
        ],
        "direct_sellers": ["dick's", "dicks sporting goods"],
    },
    {
        "key": "academy",
        "name": "Academy Sports + Outdoors",
        "domains": ["academy.com"],
        "search_urls": [
            "https://www.academy.com/search?searchTerm=pokemon%20cards",
            "https://www.academy.com/search?searchTerm=pokemon%20tcg",
            "https://www.academy.com/search?searchTerm=pokemon%20elite%20trainer%20box",
        ],
        "direct_sellers": ["academy"],
    },
    {
        "key": "scheels",
        "name": "SCHEELS",
        "domains": ["scheels.com"],
        "search_urls": [
            "https://www.scheels.com/search?q=pokemon%20cards",
            "https://www.scheels.com/search?q=pokemon%20tcg",
        ],
        "direct_sellers": ["scheels"],
    },
    {
        "key": "amazon",
        "name": "Amazon",
        "domains": ["amazon.com"],
        "search_urls": [
            "https://www.amazon.com/s?k=pokemon+tcg",
            "https://www.amazon.com/s?k=pokemon+elite+trainer+box",
            "https://www.amazon.com/s?k=pokemon+booster+bundle",
            "https://www.amazon.com/s?k=pokemon+30th+celebration",
        ],
        "direct_sellers": ["amazon", "amazon.com"],
    },
    {
        "key": "pokemon_center",
        "name": "Pokemon Center",
        "domains": ["pokemoncenter.com"],
        "search_urls": [
            "https://www.pokemoncenter.com/category/trading-card-game",
        ],
        "direct_sellers": ["pokemon center", "pokemoncenter"],
    },
    {
        "key": "best_buy",
        "name": "Best Buy",
        "domains": ["bestbuy.com"],
        "search_urls": [
            "https://www.bestbuy.com/site/searchpage.jsp?st=pokemon+tcg",
            "https://www.bestbuy.com/site/searchpage.jsp?st=pokemon+cards",
            "https://www.bestbuy.com/site/searchpage.jsp?st=pokemon+elite+trainer+box",
            "https://www.bestbuy.com/site/searchpage.jsp?st=pokemon+booster+bundle",
            "https://www.bestbuy.com/site/searchpage.jsp?st=pokemon+30th+celebration",
        ],
        "direct_sellers": ["best buy", "bestbuy"],
    },
    {
        "key": "gamestop",
        "name": "GameStop",
        "domains": ["gamestop.com"],
        "search_urls": [
            "https://www.gamestop.com/search/?q=pokemon%20tcg",
            "https://www.gamestop.com/search/?q=pokemon%20cards",
        ],
        "direct_sellers": ["gamestop"],
    },
]

PRIORITY_WATCHLIST = [
    {"name": "Prismatic Evolutions Super-Premium Collection", "url": "https://www.target.com/p/pok-233-mon-sv-8-5-prismatic-evolutions-super-premium-collection/-/A-1012055696"},
    {"name": "30th Celebration Tech Sticker Collection", "url": "https://www.target.com/p/pok-233-mon-trading-card-game-30th-celebration-tech-sticker-collection-lucario-or-alolan-exeggutor-styles-may-vary/-/A-1010892078"},
    {"name": "30th Celebration Elite Trainer Box", "url": "https://www.target.com/p/pok-233-mon-trading-card-game-30th-celebration-elite-trainer-box/-/A-1010892076"},
    {"name": "30th Celebration Sylveon ex Box", "url": "https://www.target.com/p/pok-233-mon-trading-card-game-30th-celebration-sylveon-ex-box/-/A-1010892068"},
    {"name": "30th Celebration Binder Collection", "url": "https://howl.link/afhbvkd4js8cf"},
    {"name": "30th Celebration Battle Deck", "url": "https://howl.link/6zz6jbrsf2lxj"},
    {"name": "30th Celebration Booster Bundle", "url": "https://howl.link/vhesqt7wh1d7e"},
    {"name": "30th Celebration Sylveon ex Box", "url": "https://howl.link/uqfo6d938thay"},
    {"name": "30th Celebration Greninja ex Box", "url": "https://howl.link/cbeplu5wxmz6w"},
    {"name": "30th Celebration Knock Out Collection", "url": "https://howl.link/53go48dzfoe7i"},
    {"name": "30th Celebration Collection Tin", "url": "https://howl.link/qi8oes4322sux"},
    {"name": "Ascended Heroes Mega Emboar ex Box", "url": "https://howl.link/ggc1pk3oit7zn"},
    {"name": "Ascended Heroes Mega Meganium ex Box", "url": "https://howl.link/bw6mjaw832qzz"},
    {"name": "30th Celebration Ultra-Premium Collection", "url": "https://buff.ly/5EuL04P"},
    {"name": "30th Celebration ETB", "url": "https://buff.ly/m7kC347"},
    {"name": "30th Celebration Ditto Premium Collection", "url": "https://buff.ly/nNHplnW"},
    {"name": "30th Celebration Mew & Mewtwo Figure Collection", "url": "https://buff.ly/DMOr6NC"},
    {"name": "30th Celebration Binder Collection", "url": "https://buff.ly/y1954AM"},
    {"name": "30th Celebration Poster Collection", "url": "https://buff.ly/fqEdoMZ"},
    {"name": "30th Celebration Greninja & Sylveon Tins", "url": "https://buff.ly/nixm6fC"},
    {"name": "30th Celebration Greninja & Sylveon ex Boxes", "url": "https://buff.ly/zKFjSnR"},
    {"name": "30th Celebration Umbreon & Espeon Battle Decks", "url": "https://buff.ly/fyd2pqv"},
]


# Local-stock channel checks. These are conservative:
# a local alert is only sent when the public page itself contains
# Greenville/TX plus pickup/in-stock language.
LOCAL_STORES = [
    ("Walmart", ["walmart.com"], [
        "https://www.walmart.com/search?q=pokemon+cards",
        "https://www.walmart.com/search?q=pokemon+tcg",
    ]),
    ("Target", ["target.com"], [
        "https://www.target.com/s?searchTerm=pokemon+cards",
        "https://www.target.com/s?searchTerm=pokemon+tcg",
    ]),
    ("Best Buy", ["bestbuy.com"], [
        "https://www.bestbuy.com/site/searchpage.jsp?st=pokemon+cards",
    ]),
    ("Academy Sports + Outdoors", ["academy.com"], [
        "https://www.academy.com/search?searchTerm=pokemon%20cards",
    ]),
    ("DICK'S Sporting Goods", ["dickssportinggoods.com"], [
        "https://www.dickssportinggoods.com/search/SearchDisplay?searchTerm=pokemon%20cards",
    ]),
    ("Dollar General", ["dollargeneral.com"], [
        "https://www.dollargeneral.com/search-results?query=pokemon",
    ]),
    ("Dollar Tree", ["dollartree.com"], [
        "https://www.dollartree.com/searchresults?Ntt=pokemon",
    ]),
    ("Family Dollar", ["familydollar.com"], [
        "https://www.familydollar.com/searchresults?Ntt=pokemon",
    ]),
    ("Walgreens", ["walgreens.com"], [
        "https://www.walgreens.com/search/results.jsp?Ntt=pokemon%20cards",
    ]),
    ("CVS", ["cvs.com"], [
        "https://www.cvs.com/search?searchTerm=pokemon%20cards",
    ]),
]

LOCAL_STOCK_WORDS = (
    "pickup", "pick up", "ready for pickup", "store pickup",
    "in stock at", "available at", "pick-up",
)

PRODUCT_WORDS = (
    "booster", "elite trainer", " etb", "ultra-premium", "ultra premium",
    "collection", "tin", "blister", "display", "trainer box",
    "premium collection", "pokemon tcg", "pokÃ©mon tcg", "trading card game",
)
EXCLUDE_WORDS = (
    "single card", "graded", "psa ", "cgc ", "binder sleeve", "portfolio",
    "playmat", "toploader", "card holder", "deck box", "plush", "shirt",
    "hoodie", "figure only", "book", "guide", "mystery pack", "mystery box",
)
OUT_WORDS = (
    "out of stock", "sold out", "currently unavailable",
    "temporarily unavailable", "unavailable for shipping",
)
PREORDER_WORDS = ("preorder", "pre-order", "pre order", "coming soon")
IN_STOCK_WORDS = (
    "add to cart", "add to bag", "buy now", "in stock",
    "available for shipping", "ship it",
)
TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "tag", "srsltid", "athbdg", "athancid",
}

RETAILER_DOMAIN_MAP = {
    "amazon.com": "Amazon",
    "www.amazon.com": "Amazon",
    "target.com": "Target",
    "www.target.com": "Target",
    "walmart.com": "Walmart",
    "www.walmart.com": "Walmart",
    "bestbuy.com": "Best Buy",
    "www.bestbuy.com": "Best Buy",
    "academy.com": "Academy Sports + Outdoors",
    "www.academy.com": "Academy Sports + Outdoors",
    "dickssportinggoods.com": "DICK'S Sporting Goods",
    "www.dickssportinggoods.com": "DICK'S Sporting Goods",
    "scheels.com": "SCHEELS",
    "www.scheels.com": "SCHEELS",
    "gamestop.com": "GameStop",
    "www.gamestop.com": "GameStop",
    "barnesandnoble.com": "Barnes & Noble",
    "www.barnesandnoble.com": "Barnes & Noble",
    "pokemoncenter.com": "Pokemon Center",
    "www.pokemoncenter.com": "Pokemon Center",
}



def clean_text(value):
    if value is None:
        return ""
    s = str(value)

    # Try to repair common UTF-8 mojibake.
    if any(token in s for token in ("Ã", "Ã¢", "Ã°", "Ã")):
        try:
            s = s.encode("latin1", errors="ignore").decode("utf-8", errors="ignore")
        except Exception:
            pass

    # Output ASCII-safe Discord text so mobile clients never display mojibake.
    s = unicodedata.normalize("NFKD", s)
    s = s.encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def load_state():
    if not STATE_PATH.exists():
        return {"initialized": False, "products": {}, "priority_watchlist": {}}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        data.setdefault("initialized", False)
        data.setdefault("products", {})
        data.setdefault("priority_watchlist", {})
        return data
    except Exception:
        return {"initialized": False, "products": {}, "priority_watchlist": {}}


def save_state(state):
    STATE_PATH.write_text(
        json.dumps(state, indent=2, ensure_ascii=True, sort_keys=True),
        encoding="utf-8",
    )


def canonicalize(url):
    p = urlparse(url)
    query = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
             if k.lower() not in TRACKING_PARAMS]
    return urlunparse((
        p.scheme or "https",
        p.netloc.lower(),
        p.path.rstrip("/") or "/",
        "",
        urlencode(query),
        "",
    ))


def same_domain(url, domains):
    host = urlparse(url).netloc.lower()
    return any(host == d or host.endswith("." + d) for d in domains)


def retailer_from_url(url):
    return RETAILER_DOMAIN_MAP.get(urlparse(url).netloc.lower())


def resolve_short_url(client, url):
    try:
        r = client.get(url, headers=HEADERS, timeout=18, follow_redirects=True)
        return str(r.url) if r.url else url
    except Exception:
        return url


def extract_amazon_asin(url):
    if urlparse(url).netloc.lower() not in ("amazon.com", "www.amazon.com"):
        return None
    upper = url.upper()
    for pattern in (
        r"/DP/([A-Z0-9]{10})(?:[/?]|$)",
        r"/GP/PRODUCT/([A-Z0-9]{10})(?:[/?]|$)",
        r"/GP/OFFER-LISTING/([A-Z0-9]{10})(?:[/?]|$)",
        r"/OFFER-LISTING/([A-Z0-9]{10})(?:[/?]|$)",
        r"/PRODUCT/([A-Z0-9]{10})(?:[/?]|$)",
    ):
        m = re.search(pattern, upper)
        if m:
            return m.group(1)
    return None


def normalize_amazon_url(url):
    asin = extract_amazon_asin(url)
    if not asin:
        return None
    return f"https://www.amazon.com/dp/{asin}"


def normalize_candidate_url(store, url):
    if store["key"] == "amazon":
        return normalize_amazon_url(url)
    return canonicalize(url)


def looks_like_product(title, url):
    hay = f"{title} {url}".lower()
    if "pokemon" not in hay and "pokÃ©mon" not in hay:
        return False
    if any(word in hay for word in EXCLUDE_WORDS):
        return False
    return any(word in hay for word in PRODUCT_WORDS)


def infer_title_from_url(url):
    part = urlparse(url).path.rstrip("/").split("/")[-1]
    part = re.sub(r"[-_]+", " ", part)
    return part[:220].strip().title() or "Pokemon TCG product"


def infer_status(text):
    t = re.sub(r"\s+", " ", text.lower())
    if any(word in t for word in OUT_WORDS):
        return "out_of_stock"
    if any(word in t for word in PREORDER_WORDS):
        return "preorder"
    if any(word in t for word in IN_STOCK_WORDS):
        return "in_stock"
    return "unknown"


def find_price(text):
    m = re.search(r"\$\s?(\d{1,4}(?:,\d{3})*(?:\.\d{2}))", text)
    return f"${m.group(1)}" if m else None


def parse_price(price_text):
    if not price_text:
        return None
    try:
        return float(str(price_text).replace("$", "").replace(",", "").strip())
    except Exception:
        return None


def estimate_msrp(title):
    t = title.lower()
    if "pokemon center elite trainer box" in t or "pokÃ©mon center elite trainer box" in t:
        return 59.99
    if "elite trainer box" in t or re.search(r"\betb\b", t):
        return 49.99
    if "booster bundle" in t:
        return 26.94
    if ("booster display" in t or "booster box" in t) and (
        "36 pack" in t or "36-pack" in t or "36 packs" in t
    ):
        return 161.64
    if "ultra-premium collection" in t or "ultra premium collection" in t:
        return 119.99
    if "build & battle box" in t or "build and battle box" in t:
        return 21.99
    if "3 pack blister" in t or "3-pack blister" in t:
        return 14.99
    if "sleeved booster pack" in t:
        return 4.49
    return None


def msrp_comparison(price_text, title):
    price = parse_price(price_text)
    msrp = estimate_msrp(title)
    if msrp is None:
        return None, "âª MSRP UNKNOWN"
    if price is None:
        return msrp, "âª PRICE NOT DETECTED"
    diff = round(price - msrp, 2)
    if abs(diff) < 0.01:
        return msrp, "ð¡ AT MSRP"
    if diff < 0:
        return msrp, f"ð¢ ${abs(diff):.2f} BELOW MSRP"
    return msrp, f"ð´ ${diff:.2f} ABOVE MSRP"


def jsonld_products(html):
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = tag.get_text(strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except Exception:
            continue
        stack = data if isinstance(data, list) else [data]
        expanded = []
        for item in stack:
            if isinstance(item, dict) and isinstance(item.get("@graph"), list):
                expanded.extend(item["@graph"])
            else:
                expanded.append(item)
        for item in expanded:
            if not isinstance(item, dict):
                continue
            types = item.get("@type")
            types = types if isinstance(types, list) else [types]
            if "Product" in types:
                yield item


def availability_from_jsonld(product):
    offers = product.get("offers")
    if isinstance(offers, list):
        offers = offers[0] if offers else None
    if not isinstance(offers, dict):
        return None, None
    price = offers.get("price")
    if price is not None:
        try:
            price = f"${float(str(price).replace(',', '')):.2f}"
        except Exception:
            price = f"${price}"
    availability = str(offers.get("availability", "")).lower()
    if "instock" in availability or "in_stock" in availability:
        return "in_stock", price
    if "preorder" in availability:
        return "preorder", price
    if "outofstock" in availability or "soldout" in availability:
        return "out_of_stock", price
    return None, price


def third_party_seller(store, text, product=None):
    direct = store["direct_sellers"]
    if isinstance(product, dict):
        offers = product.get("offers")
        if isinstance(offers, list):
            offers = offers[0] if offers else None
        seller = offers.get("seller") if isinstance(offers, dict) else None
        if isinstance(seller, dict):
            seller = seller.get("name")
        if isinstance(seller, str) and seller.strip():
            s = seller.strip().lower()
            if not any(name in s for name in direct):
                return True, seller.strip()[:80]

    compact = re.sub(r"\s+", " ", text.lower())
    for pat in (
        r"sold and shipped by\s+([a-z0-9&' .\-]{2,70})",
        r"sold by\s+([a-z0-9&' .\-]{2,70})",
        r"seller\s*:\s*([a-z0-9&' .\-]{2,70})",
    ):
        m = re.search(pat, compact)
        if not m:
            continue
        seller = m.group(1).strip(" .-|")
        seller = re.split(r"\||returns|shipping|delivery", seller)[0].strip()
        if seller and not any(name in seller for name in direct):
            return True, seller[:80]
    return False, None


def send_discord(title, lines, url=None, color=3447003, webhook=None):
    webhook = webhook or ONLINE_WEBHOOK
    if not webhook:
        return

    title = clean_text(title)
    cleaned_lines = []
    for line in lines:
        if "http://" in line or "https://" in line:
            cleaned_lines.append(line)
        else:
            cleaned_lines.append(clean_text(line))
    lines = cleaned_lines

    embed = {
        "title": title[:256],
        "description": "\n".join(lines)[:4000],
        "color": color,
        "timestamp": utcnow(),
        "footer": {"text": "Pokemon TCG Drop Monitor"},
    }
    if url:
        embed["url"] = url

    payload = json.dumps({"embeds": [embed]}, ensure_ascii=True)
    result = subprocess.run(
        [
            "curl", "--silent", "--show-error", "--fail-with-body",
            "-H", "Content-Type: application/json",
            "-H", "User-Agent: PokemonTCGDrops/2.0",
            "-d", payload,
            webhook,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"Discord webhook failed: {result.stderr.strip()} {result.stdout.strip()}"
        )


def fetch(client, url):
    try:
        r = client.get(url, headers=HEADERS, timeout=18, follow_redirects=True)
        if r.status_code >= 400:
            return "", ""
        html = r.text
        text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
        return html, text
    except Exception:
        return "", ""


def extract_links(store, page_url, html):
    soup = BeautifulSoup(html, "html.parser")
    found = {}
    for a in soup.find_all("a", href=True):
        raw = urljoin(page_url, a["href"])
        if not same_domain(raw, store["domains"]):
            continue

        title = " ".join(a.stripped_strings).strip()
        if not title:
            title = (a.get("aria-label") or a.get("title") or "").strip()
        if not title:
            title = infer_title_from_url(raw)

        if not looks_like_product(title, raw):
            continue

        cleaned = normalize_candidate_url(store, raw)
        if not cleaned:
            continue

        found[cleaned] = clean_text(title)[:240]
    return found


def inspect_product(client, store, url, fallback_title):
    html, body = fetch(client, url)
    if not html:
        return None

    soup = BeautifulSoup(html, "html.parser")
    product = next(jsonld_products(html), None)

    title = product.get("name") if product else None
    if not title:
        og = soup.find("meta", attrs={"property": "og:title"})
        if og:
            title = og.get("content")
    title = (title or fallback_title or infer_title_from_url(url)).strip()[:240]

    status = None
    price = None
    if product:
        status, price = availability_from_jsonld(product)
    if not status:
        status = infer_status(body)
    if not price:
        price = find_price(body)

    third_party, seller = third_party_seller(store, body, product)

    return {
        "store": store["name"],
        "store_key": store["key"],
        "title": title,
        "price": price,
        "status": status,
        "third_party": third_party,
        "seller": seller,
        "last_checked": utcnow(),
    }


def status_label(status):
    return {
        "in_stock": "IN STOCK",
        "preorder": "PREORDER",
        "out_of_stock": "OUT OF STOCK",
        "unknown": "NEW LISTING",
    }.get(status, status.upper())


def quick_links(retailer, product_url):
    # Product-page links only. Retailer cart deep links are session-dependent
    # and were unreliable, so they are intentionally omitted.
    if retailer == "Amazon":
        clean = normalize_amazon_url(product_url)
        return [("OPEN AMAZON PRODUCT", clean)] if clean else []

    if retailer == "Target":
        return [("OPEN TARGET PRODUCT", product_url)]

    if retailer == "Walmart":
        return [("OPEN WALMART PRODUCT", product_url)]

    if retailer == "Best Buy":
        return [("OPEN BEST BUY PRODUCT", product_url)]

    return [("OPEN PRODUCT", product_url)]


def alert_for_item(kind, store, item, url, priority=False):
    msrp, value = msrp_comparison(item.get("price"), item["title"])

    lines = []
    if priority:
        lines.append("PRIORITY WATCHLIST HIT")
    if "30th" in item["title"].lower():
        lines.append("30TH CELEBRATION")

    lines += [
        f"Product: {clean_text(item['title'])}",
        f"Retailer: {store['name']}",
        f"Status: {status_label(item['status'])}",
        f"Price: {item.get('price') or 'Not detected'}",
        f"Retail/MSRP: ${msrp:.2f}" if msrp is not None else "Retail/MSRP: Unknown",
        f"Value: {value}",
        "",
    ]

    for label, link in quick_links(store["name"], url):
        lines.append(f"{label}: {link}")

    if priority:
        title = f"PRIORITY DROP - {store['name']}"
        color = 15158332
    elif kind == "restock":
        title = f"RESTOCK - {store['name']}"
        color = 15158332
    elif kind == "preorder":
        title = f"PREORDER OPEN - {store['name']}"
        color = 10181046
    else:
        title = f"NEW LISTING - {store['name']}"
        color = 3447003

    send_discord(title, lines, url=url, color=color)


def store_for_retailer_name(name):
    for store in STORES:
        if store["name"] == name:
            return store
    return None


def scan_priority_watchlist(client, state):
    watch_state = state.setdefault("priority_watchlist", {})

    for entry in PRIORITY_WATCHLIST:
        resolved = resolve_short_url(client, entry["url"])
        retailer = retailer_from_url(resolved)

        if retailer == "Amazon":
            resolved = normalize_amazon_url(resolved)
            if not resolved:
                continue

        if not retailer or not resolved:
            continue

        store = store_for_retailer_name(retailer)
        if not store:
            continue

        item = inspect_product(client, store, resolved, entry["name"])
        if not item:
            continue

        key = canonicalize(resolved)
        previous = watch_state.get(key, {})
        previous_status = previous.get("status", "unknown")

        watch_state[key] = {
            "name": item["title"],
            "status": item["status"],
            "price": item["price"],
            "resolved_url": resolved,
            "source_url": entry["url"],
            "last_checked": utcnow(),
        }

        if not state.get("initialized"):
            continue

        if item.get("third_party"):
            continue

        if (
            previous_status in ("unknown", "out_of_stock")
            and item["status"] in ("in_stock", "preorder")
        ):
            kind = "preorder" if item["status"] == "preorder" else "restock"
            alert_for_item(kind, store, item, resolved, priority=True)



def local_page_has_stock(text):
    compact = re.sub(r"\s+", " ", text.lower())
    has_city = LOCAL_CITY.lower() in compact
    has_state = " texas" in compact or " tx" in compact
    has_pickup = any(word in compact for word in LOCAL_STOCK_WORDS)
    has_stock = any(word in compact for word in IN_STOCK_WORDS)
    return has_city and has_state and has_pickup and has_stock


def send_local_alert(store_name, title, price, url):
    msrp, value_label = msrp_comparison(price, title)
    detected_price = parse_price(price)

    if (
        msrp is not None
        and detected_price is not None
        and detected_price > msrp + MAX_OVER_RETAIL
    ):
        return

    lines = [
        f"{title}",
        f"Retailer: {store_name}",
        f"Area: {LOCAL_CITY}, {LOCAL_STATE}",
        "Status: ð¢ LOCAL/PICKUP SIGNAL DETECTED",
        f"Price: {price or 'Not detected'}",
        f"Retail/MSRP: ${msrp:.2f}" if msrp is not None else "Retail/MSRP: Unknown",
        f"Value: {clean_text(value_label)}",
        "",
        f"ð Product link: {url}",
        "",
        "â ï¸ Verify pickup quantity in the retailer app/site before driving.",
    ]

    send_discord(
        f"LOCAL STOCK - {store_name}",
        lines,
        url=url,
        color=3066993,
        webhook=LOCAL_WEBHOOK,
    )


def scan_local_stock(client, state):
    if not LOCAL_WEBHOOK:
        return

    local_state = state.setdefault("local_products", {})

    for store_name, domains, search_urls in LOCAL_STORES:
        for search_url in search_urls:
            html, search_text = fetch(client, search_url)
            if not html:
                continue

            soup = BeautifulSoup(html, "html.parser")
            candidates = {}

            for a in soup.find_all("a", href=True):
                product_url = canonicalize(urljoin(search_url, a["href"]))
                if not same_domain(product_url, domains):
                    continue

                title = " ".join(a.stripped_strings).strip()
                if not title:
                    title = (a.get("aria-label") or a.get("title") or "").strip()

                if title and looks_like_product(title, product_url):
                    candidates[product_url] = title[:240]

            for product_url, title in list(candidates.items())[:8]:
                product_html, product_text = fetch(client, product_url)
                if not product_html or not local_page_has_stock(product_text):
                    continue

                price = find_price(product_text)
                key = f"{store_name}|{product_url}"
                old = local_state.get(key, {})
                already_available = old.get("available", False)

                local_state[key] = {
                    "available": True,
                    "title": title,
                    "price": price,
                    "last_checked": utcnow(),
                }

                if state.get("initialized") and not already_available:
                    send_local_alert(store_name, title, price, product_url)


def main():
    state = load_state()
    initialized = bool(state.get("initialized"))
    products = state.setdefault("products", {})
    state.setdefault("local_products", {})

    if MANUAL_RUN:
        send_discord(
            "Pokemon TCG monitor v2 started",
            [
                "Priority exact-link watchlist is enabled.",
                "Amazon links are U.S.-only and cleaned to direct /dp/ASIN URLs.",
                "Walmart, Target, Academy, DICK'S, Best Buy and other retailer discovery is expanded.",
                "Retail/MSRP comparison is enabled.",
                f"Products more than ${MAX_OVER_RETAIL:.0f} over known retail/MSRP are filtered out.",
                "Scheduled checks are requested every 5 minutes.",
            ],
            color=5763719,
        )

    if MANUAL_RUN and LOCAL_WEBHOOK:
        send_discord(
            "Local Pokemon stock channel connected",
            [
                f"Watching conservative public pickup/local signals around {LOCAL_CITY}, {LOCAL_STATE}.",
                "Includes Walmart, Target, Best Buy, Academy, DICK'S, Dollar General, Dollar Tree, Family Dollar, Walgreens and CVS.",
                f"Products more than ${MAX_OVER_RETAIL:.0f} over known retail/MSRP are filtered out.",
                "Dollar-store websites may not expose reliable SKU-level store inventory.",
            ],
            color=5763719,
            webhook=LOCAL_WEBHOOK,
        )

    with httpx.Client() as client:
        scan_priority_watchlist(client, state)
        scan_local_stock(client, state)

        for store in STORES:
            discovered = {}

            for search_url in store["search_urls"]:
                html, _ = fetch(client, search_url)
                if html:
                    discovered.update(extract_links(store, search_url, html))

            new_items = [(u, t) for u, t in discovered.items() if u not in products][:15]

            for url, fallback_title in new_items:
                item = inspect_product(client, store, url, fallback_title)
                if item is None:
                    continue

                products[url] = item

                if initialized and not item.get("third_party"):
                    kind = "preorder" if item["status"] == "preorder" else "new"
                    alert_for_item(kind, store, item, url)

            known = [
                (url, item)
                for url, item in products.items()
                if item.get("store_key") == store["key"]
            ]
            known.sort(key=lambda pair: pair[1].get("last_checked", ""))

            for url, old in known[:6]:
                fresh = inspect_product(
                    client, store, url, old.get("title", "Pokemon TCG product")
                )
                if fresh is None:
                    continue

                old_status = old.get("status", "unknown")
                products[url] = fresh

                if not initialized or fresh.get("third_party"):
                    continue

                if (
                    old_status in ("out_of_stock", "unknown")
                    and fresh["status"] in ("in_stock", "preorder")
                ):
                    kind = "preorder" if fresh["status"] == "preorder" else "restock"
                    alert_for_item(kind, store, fresh, url)

    if len(products) > 1800:
        newest = sorted(
            products.items(),
            key=lambda pair: pair[1].get("last_checked", ""),
            reverse=True,
        )[:1800]
        state["products"] = dict(newest)

    state["initialized"] = True
    state["last_run"] = utcnow()
    save_state(state)


if __name__ == "__main__":
    main()
