import argparse
import csv
import json
import sys
import time
import base64
import re
from urllib.parse import urljoin, urlparse

from selenium import webdriver
from selenium.webdriver.chrome.options import Options


DEFAULT_CATEGORY_URL = "https://goldapple.ru/makiyazh/lice/tonal-nye-sredstva"

DEFAULT_HINTS = (
    "catalog",
    "products",
    "plp",
    "category",
    "search",
)


def build_driver(headless: bool) -> webdriver.Chrome:
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")

    opts.add_argument("--start-maximized")
    opts.add_argument("--disable-blink-features=AutomationControlled")

    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)

    # Needed for driver.get_log('performance')
    opts.set_capability("goog:loggingPrefs", {"performance": "ALL"})

    driver = webdriver.Chrome(options=opts)
    driver.set_page_load_timeout(90)

    # Enable CDP network events
    driver.execute_cdp_cmd("Network.enable", {})
    return driver


def normalize_url(u: str) -> str | None:
    if not u or not isinstance(u, str):
        return None

    u = u.strip()
    if u.startswith("//"):
        u = "https:" + u
    if u.startswith("/"):
        u = urljoin("https://goldapple.ru", u)

    if not u.startswith("http"):
        return None

    host = urlparse(u).netloc.lower()
    if "goldapple" not in host:
        return None

    return u


def is_likely_product_url(u: str, include_prefixes: tuple[str, ...], exclude_prefixes: tuple[str, ...]) -> bool:
    p = urlparse(u)
    path = (p.path or "/").rstrip("/")

    # GoldApple product pages often look like: /19000472181-make-up-care-matte
    if re.match(r"^/\d{6,}-", path):
        return True

    if exclude_prefixes:
        for pref in exclude_prefixes:
            if not pref:
                continue
            if path == pref.rstrip("/") or path.startswith(pref.rstrip("/") + "/"):
                return False

    if include_prefixes:
        for pref in include_prefixes:
            if not pref:
                continue
            pref_n = pref.rstrip("/")
            if path == pref_n or path.startswith(pref_n + "/"):
                return True
        return False

    # Fallback heuristic if include list is empty
    return "/product/" in path or "/products/" in path


def extract_links(payload, include_prefixes: tuple[str, ...], exclude_prefixes: tuple[str, ...]) -> set[str]:
    found: set[str] = set()

    def walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                lk = str(k).lower()
                if lk in ("url", "href", "link", "producturl", "product_url") and isinstance(v, str):
                    nu = normalize_url(v)
                    if nu:
                        found.add(nu)
                if lk in ("slug", "productslug", "product_slug") and isinstance(v, str):
                    # Common pattern: build product URL from slug
                    cand = normalize_url("/product/" + v.lstrip("/"))
                    if cand:
                        found.add(cand)
                walk(v)
        elif isinstance(obj, list):
            for x in obj:
                walk(x)

    walk(payload)

    out = set()
    for u in found:
        if is_likely_product_url(u, include_prefixes=include_prefixes, exclude_prefixes=exclude_prefixes):
            out.add(u)
    return out


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--url", default=DEFAULT_CATEGORY_URL, help="Category URL")
    p.add_argument("--out", default="product_links.csv", help="Output CSV")
    p.add_argument("--debug-urls", default="debug_network_urls.txt", help="Write all network URLs here")
    p.add_argument(
        "--debug-jsonl",
        default="debug_catalog_responses.jsonl",
        help="Write stats about parsed catalog-like responses",
    )
    p.add_argument("--headless", action="store_true", help="Run Chrome headless")
    p.add_argument("--scrolls", type=int, default=14, help="How many scroll steps (used if --scroll-until-stable is off)")
    p.add_argument("--scroll-pause", type=float, default=1.0, help="Pause between scrolls")
    p.add_argument(
        "--scroll-until-stable",
        action="store_true",
        help="Scroll until no new product links appear for several rounds (better for infinite scroll).",
    )
    p.add_argument(
        "--max-scrolls",
        type=int,
        default=200,
        help="Max scroll steps when --scroll-until-stable is enabled.",
    )
    p.add_argument(
        "--stable-rounds",
        type=int,
        default=6,
        help="How many consecutive rounds with 0 new links until we stop (when --scroll-until-stable).",
    )
    p.add_argument(
        "--hints",
        default=",".join(DEFAULT_HINTS),
        help="Comma-separated substrings to detect catalog responses",
    )

    p.add_argument(
        "--include-prefixes",
        default="/product,/products",
        help="Comma-separated URL path prefixes to keep (default: product pages).",
    )
    p.add_argument(
        "--exclude-prefixes",
        default="/brands,/cards,/contacts,/detjam,/delivery,/help,/login,/profile,/shops",
        help="Comma-separated URL path prefixes to drop.",
    )

    p.add_argument(
        "--dump-bodies",
        action="store_true",
        help="Dump raw response bodies (truncated) for matched endpoints to help tuning extraction.",
    )
    p.add_argument(
        "--dump-bodies-limit",
        type=int,
        default=20000,
        help="Max characters to write per dumped body.",
    )
    return p.parse_args()


def main():
    args = parse_args()
    hints = tuple([h.strip().lower() for h in args.hints.split(",") if h.strip()])
    include_prefixes = tuple([p.strip() for p in args.include_prefixes.split(",") if p.strip()])
    exclude_prefixes = tuple([p.strip() for p in args.exclude_prefixes.split(",") if p.strip()])

    u = (args.url or "").strip()
    p = urlparse(u)
    if p.scheme not in ("http", "https") or not p.netloc:
        print("[ERR] --url must be a full http(s) URL (example: https://goldapple.ru/makiyazh/lice/tonal-nye-sredstva)")
        print(f"[ERR] got: {args.url!r}")
        sys.exit(2)

    driver = build_driver(headless=args.headless)

    request_id_to_url: dict[str, str] = {}
    seen_urls: set[str] = set()

    product_links: set[str] = set()

    try:
        driver.get(args.url)
        time.sleep(6)

        with open(args.debug_urls, "w", encoding="utf-8") as f_urls, open(
            args.debug_jsonl, "w", encoding="utf-8"
        ) as f_jsonl:

            def consume_new_logs():
                nonlocal product_links
                logs_local = driver.get_log("performance")
                for entry in logs_local:
                    msg = json.loads(entry["message"])["message"]
                    method = msg.get("method")
                    params = msg.get("params", {})

                    if method == "Network.responseReceived":
                        response = params.get("response", {})
                        url = response.get("url", "")
                        rid = params.get("requestId")

                        if rid and url:
                            request_id_to_url[rid] = url
                            if url not in seen_urls:
                                seen_urls.add(url)
                                f_urls.write(url + "\n")

                    if method == "Network.loadingFinished":
                        rid = params.get("requestId")
                        url = request_id_to_url.get(rid, "")
                        if not url:
                            continue

                        url_l = url.lower()
                        if hints and not any(h in url_l for h in hints):
                            continue

                        try:
                            body = driver.execute_cdp_cmd("Network.getResponseBody", {"requestId": rid})
                        except Exception:
                            continue

                        text = body.get("body") or ""
                        if not text:
                            continue

                        if body.get("base64Encoded") is True:
                            try:
                                text = base64.b64decode(text).decode("utf-8", errors="replace")
                            except Exception:
                                continue

                        if args.dump_bodies:
                            safe_name = "".join([c if c.isalnum() else "_" for c in urlparse(url).path])
                            dump_path = f"dump_{safe_name}_{rid}.txt"
                            with open(dump_path, "w", encoding="utf-8") as f_dump:
                                f_dump.write(text[: args.dump_bodies_limit])

                        try:
                            payload = json.loads(text)
                        except Exception:
                            continue

                        links = extract_links(payload, include_prefixes=include_prefixes, exclude_prefixes=exclude_prefixes)
                        product_links |= links
                        f_jsonl.write(
                            json.dumps(
                                {
                                    "url": url,
                                    "count_links": len(links),
                                },
                                ensure_ascii=False,
                            )
                            + "\n"
                        )

            # Initial drain
            consume_new_logs()

            if args.scroll_until_stable:
                stable = 0
                prev_count = len(product_links)
                for _ in range(args.max_scrolls):
                    driver.execute_script("window.scrollBy(0, Math.floor(window.innerHeight * 0.95));")
                    time.sleep(args.scroll_pause)
                    consume_new_logs()

                    cur = len(product_links)
                    if cur == prev_count:
                        stable += 1
                    else:
                        stable = 0
                        prev_count = cur

                    if stable >= args.stable_rounds:
                        break
            else:
                for _ in range(args.scrolls):
                    driver.execute_script("window.scrollBy(0, Math.floor(window.innerHeight * 0.95));")
                    time.sleep(args.scroll_pause)
                    consume_new_logs()



        with open(args.out, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["url"])
            for u in sorted(product_links):
                w.writerow([u])

        print(f"[OK] Saved {len(product_links)} links to: {args.out}")
        if len(product_links) == 0:
            print("[WARN] 0 links found.")
            print(f"[DBG] Check: {args.debug_urls} and {args.debug_jsonl}")
            print("[DBG] If DevTools shows a products JSON response, copy its URL and rerun with --hints='that_part'")

    finally:
        driver.quit()


if __name__ == "__main__":
    main()
