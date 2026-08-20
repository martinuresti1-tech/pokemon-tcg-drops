import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlunparse, parse_qsl, urlencode

import httpx
from bs4 import BeautifulSoup

STATE_PATH = Path("state.json")
WEBHOOK = os.getenv("DISCORD_WEBHOOK_URL", "").strip()
MANUAL_RUN = os.getenv("GITHUB_EVENT_NAME", "") == "workflow_dispatch"

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/126.0 Safari/537.36 PokemonTCGDrops/1.0",
    "Accept-Language": "en-US,en;q=0.9",
}

STORES = [
    {
        "key": "walmart",
        "name": "Walmart",
        "domains": ["walmart.com"],
        "search_urls": [
            "https://www.walmart.com/search?q=pokemon+tcg",
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
        ],
        "direct_sellers": ["target"],
    },
    {
        "key": "barnes_noble",
        "name": "Barnes & Noble",
        "domains": ["barnesandnoble.com"],
        "search_urls": [
            "https://www.barnesandnoble.com/s/pokemon%20tcg",
        ],
        "direct_sellers": ["barnes & noble", "barnes and noble"],
    },
    {
        "key": "dicks",
        "name": "DICK'S Sporting Goods",
        "domains": ["dickssportinggoods.com"],
        "search_urls": [
            "https://www.dickssportinggoods.com/search/SearchDisplay?searchTerm=pokemon%20cards",
        ],
        "direct_sellers": ["dick's", "dicks sporting goods"],
    },
    {
        "key": "academy",
        "name": "Academy Sports + Outdoors",
        "domains": ["academy.com"],
        "search_urls": [
            "https://www.academy.com/search?searchTerm=pokemon%20cards",
        ],
        "direct_sellers": ["academy"],
    },
    {
        "key": "scheels",
        "name": "SCHEELS",
        "domains": ["scheels.com"],
        "search_urls": [
            "https://www.scheels.com/search?q=pokemon%20cards",
        ],
        "direct_sellers": ["scheels"],
    },
    {
        "key": "amazon",
        "name": "Amazon",
        "domains": ["amazon.com"],
        "search_urls": [
            "https://www.amazon.com/s?k=pokemon+tcg",
        ],
        "direct_sellers": ["amazon", "amazon.com"],
    },
    {
        "key": "pokemon_center",
        "name": "Pokémon Center",
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
        ],
        "direct_sellers": ["best buy", "bestbuy"],
    },
    {
        "key": "gamestop",
        "name": "GameStop",
        "domains": ["gamestop.com"],
        "search_urls": [
            "https://www.gamestop.com/search/?q=pokemon%20tcg",
        ],
        "direct_sellers": ["gamestop"],
    },
]

PRODUCT_WORDS = (
    "booster", "elite trainer", " etb", "ultra-premium", "ultra premium",
    "collection", "tin", "blister", "display", "trainer box",
    "premium collection", "pokemon tcg", "pokémon tcg", "trading card game",
)
EXCLUDE_WORDS = (
    "single card", "graded", "psa ", "cgc ", "binder", "portfolio", "sleeve",
    "playmat", "toploader", "card holder", "deck box", "plush", "shirt",
    "hoodie", "figure", "book", "guide", "mystery pack", "mystery box",
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


def utcnow():
    return datetime.now(timezone.utc).isoformat()


def load_state():
    if not STATE_PATH.exists():
        return {"initialized": False, "products": {}}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError
        data.setdefault("initialized", False)
        data.setdefault("products", {})
        return data
    except Exception:
        return {"initialized": False, "products": {}}


def save_state(state):
    STATE_PATH.write_text(
        json.dumps(state, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )


def canonicalize(url):
    p = urlparse(url)
    query = [
        (k, v) for k, v in parse_qsl(p.query, keep_blank_values=True)
        if k.lower() not in TRACKING_PARAMS
    ]
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


def looks_like_product(title, url):
    hay = f"{title} {url}".lower()
    if "pokemon" not in hay and "pokémon" not in hay:
        return False
    if any(word in hay for word in EXCLUDE_WORDS):
        return False
    return any(word in hay for word in PRODUCT_WORDS)


def infer_title_from_url(url):
    part = urlparse(url).path.rstrip("/").split("/")[-1]
    part = re.sub(r"[-_]+", " ", part)
    return part[:220].strip().title() or "Pokémon TCG product"


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
            t = item.get("@type")
            types = t if isinstance(t, list) else [t]
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

    avail = str(offers.get("availability", "")).lower()
    if "instock" in avail or "in_stock" in avail:
        return "in_stock", price
    if "preorder" in avail or "pre-order" in avail:
        return "preorder", price
    if "outofstock" in avail or "soldout" in avail:
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
    patterns = (
        r"sold and shipped by\s+([a-z0-9&' .\-]{2,70})",
        r"sold by\s+([a-z0-9&' .\-]{2,70})",
        r"seller\s*:\s*([a-z0-9&' .\-]{2,70})",
    )
    for pat in patterns:
        m = re.search(pat, compact)
        if not m:
            continue
        seller = m.group(1).strip(" .-|")
        seller = re.split(r"\||returns|shipping|delivery", seller)[0].strip()
        if seller and not any(name in seller for name in direct):
            return True, seller[:80]
    return False, None


def special_tag(title):
    t = title.lower()
    if "30th" in t or "30th anniversary" in t or "anniversary" in t:
        return "🔥 30TH ANNIVERSARY"
    return None


def send_discord(title, lines, url=None, color=3447003):
    if not WEBHOOK:
        raise RuntimeError("DISCORD_WEBHOOK_URL is missing")

    embed = {
        "title": title[:256],
        "description": "\n".join(lines)[:4000],
        "color": color,
        "timestamp": utcnow(),
        "footer": {"text": "Pokémon TCG Drop Monitor"},
    }
    if url:
        embed["url"] = url

    payload = json.dumps({"embeds": [embed]}, ensure_ascii=False)
    result = subprocess.run(
        [
            "curl", "--silent", "--show-error", "--fail-with-body",
            "-H", "Content-Type: application/json",
            "-H", "User-Agent: PokemonTCGDrops/1.0",
            "-d", payload,
            WEBHOOK,
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
        url = canonicalize(urljoin(page_url, a["href"]))
        if not same_domain(url, store["domains"]):
            continue

        title = " ".join(a.stripped_strings).strip()
        if not title:
            title = (a.get("aria-label") or a.get("title") or "").strip()
        if not title:
            title = infer_title_from_url(url)

        if looks_like_product(title, url):
            found[url] = title[:240]
    return found


def inspect_product(client, store, url, fallback_title):
    html, body = fetch(client, url)
    if not html:
        return None

    soup = BeautifulSoup(html, "html.parser")
    product = next(jsonld_products(html), None)

    title = None
    if product:
        title = product.get("name")
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

    is_third_party, seller = third_party_seller(store, body, product)

    return {
        "store": store["name"],
        "store_key": store["key"],
        "title": title,
        "price": price,
        "status": status,
        "third_party": is_third_party,
        "seller": seller,
        "last_checked": utcnow(),
    }


def status_label(status):
    return {
        "in_stock": "🟢 IN STOCK",
        "preorder": "🟣 PREORDER",
        "out_of_stock": "🔴 OUT OF STOCK",
        "unknown": "🔵 NEW LISTING",
    }.get(status, status.upper())


def alert_for_item(kind, store, item, url):
    tag = special_tag(item["title"])
    lines = []
    if tag:
        lines.append(f"**{tag}**")
    lines += [
        f"**{item['title']}**",
        f"Retailer: **{store['name']}**",
        f"Status: **{status_label(item['status'])}**",
        f"Price: **{item.get('price') or 'Not detected'}**",
        "",
        f"🛒 **Direct product link:** {url}",
    ]

    if kind == "restock":
        title = f"🚨 RESTOCK — {store['name']}"
        color = 15158332
    elif kind == "preorder":
        title = f"🟣 PREORDER OPEN — {store['name']}"
        color = 10181046
    else:
        title = f"🆕 NEW LISTING — {store['name']}"
        color = 3447003

    send_discord(title, lines, url=url, color=color)


def main():
    state = load_state()
    initialized = bool(state.get("initialized"))
    products = state.setdefault("products", {})

    if MANUAL_RUN:
        send_discord(
            "✅ Live Pokémon TCG monitor started",
            [
                "Discord alerts are connected.",
                f"Watching **{len(STORES)} major U.S. retailers**.",
                "The first live scan builds a baseline so old listings do not spam the channel.",
                "Scheduled checks are requested every **5 minutes**.",
            ],
            color=5763719,
        )

    with httpx.Client() as client:
        for store in STORES:
            discovered = {}
            for search_url in store["search_urls"]:
                html, _ = fetch(client, search_url)
                if html:
                    discovered.update(extract_links(store, search_url, html))

            # Inspect new product links. Cap per run to keep Actions quick.
            new_items = [(u, t) for u, t in discovered.items() if u not in products][:12]
            for url, fallback_title in new_items:
                item = inspect_product(client, store, url, fallback_title)
                if item is None:
                    item = {
                        "store": store["name"],
                        "store_key": store["key"],
                        "title": fallback_title,
                        "price": None,
                        "status": "unknown",
                        "third_party": False,
                        "seller": None,
                        "last_checked": utcnow(),
                    }

                products[url] = item

                if initialized and not item.get("third_party"):
                    kind = "preorder" if item["status"] == "preorder" else "new"
                    alert_for_item(kind, store, item, url)

            # Recheck the oldest-known products from this store to detect restocks.
            known = [
                (url, item)
                for url, item in products.items()
                if item.get("store_key") == store["key"]
            ]
            known.sort(key=lambda pair: pair[1].get("last_checked", ""))

            for url, old in known[:5]:
                fresh = inspect_product(
                    client, store, url, old.get("title", "Pokémon TCG product")
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

    # Prevent unbounded state growth while preserving the most recently checked items.
    if len(products) > 1500:
        newest = sorted(
            products.items(),
            key=lambda pair: pair[1].get("last_checked", ""),
            reverse=True,
        )[:1500]
        state["products"] = dict(newest)

    state["initialized"] = True
    state["last_run"] = utcnow()
    save_state(state)


if __name__ == "__main__":
    main()
