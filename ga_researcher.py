import argparse
import csv
import json
import os
import random
import time
import base64
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlparse

import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import WebDriverException


@dataclass
class VariantRow:
    product_url: str
    item_id: str | None
    name: str | None
    brand: str | None
    product_type: str | None
    volume: str | None
    shade_name: str | None
    shade_value: str | None
    price_actual: int | None
    price_regular: int | None
    currency: str | None
    in_stock: bool | None


def build_driver(headless: bool) -> webdriver.Chrome:
    opts = Options()
    if headless:
        opts.add_argument("--headless=new")

    opts.add_argument("--start-maximized")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)

    # performance logs (for Network events)
    opts.set_capability("goog:loggingPrefs", {"performance": "ALL"})

    # Avoid waiting for all subresources; helps with flaky anti-bot pages
    opts.set_capability("pageLoadStrategy", "eager")

    driver = webdriver.Chrome(options=opts)
    driver.set_page_load_timeout(90)
    driver.execute_cdp_cmd("Network.enable", {})
    return driver


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--links", default="product_links.csv", help="Input CSV with column 'url'")
    p.add_argument("--out-xlsx", default="results.xlsx", help="Output XLSX")
    p.add_argument("--out-csv", default="results.csv", help="Output CSV")
    p.add_argument("--state", default="research_state.json", help="Checkpoint/progress file")
    p.add_argument("--headless", action="store_true")
    p.add_argument("--limit", type=int, default=0, help="Process only first N links (0 = all)")
    p.add_argument("--start", type=int, default=0, help="Start index in links list")
    p.add_argument("--min-delay", type=float, default=1.0)
    p.add_argument("--max-delay", type=float, default=2.2)
    p.add_argument("--retry", type=int, default=2)
    p.add_argument("--dump-errors", action="store_true", help="Dump debug info for failed pages")
    p.add_argument("--dump-bodies", action="store_true", help="Dump matched product-card response bodies (truncated)")
    p.add_argument("--dump-bodies-limit", type=int, default=20000)
    return p.parse_args()


def read_links(path: str) -> list[str]:
    links: list[str] = []
    with open(path, newline="", encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            u = (row.get("url") or "").strip()
            if u:
                links.append(u)
    return links


def load_state(path: str) -> dict[str, Any]:
    if not os.path.exists(path):
        return {"done": []}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(path: str, state: dict[str, Any]) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def take_delay(min_delay: float, max_delay: float) -> None:
    time.sleep(min_delay + random.random() * max(0.0, max_delay - min_delay))


def extract_from_payload(product_url: str, payload: dict[str, Any]) -> list[VariantRow]:
    # We support a couple of possible shapes.
    # Primary (observed in cards-list): payload['data']['cards'][*]['product']
    # For product-card/base/v3 it will likely be payload['data'] / payload itself.

    def find_product_obj(obj: Any) -> dict[str, Any] | None:
        if isinstance(obj, dict):
            # Common nesting
            if "data" in obj and isinstance(obj["data"], (dict, list)):
                got = find_product_obj(obj["data"])
                if got:
                    return got

            # Some shapes: {data:{product:{...}}} or {data:{item:{...}}}
            if "product" in obj and isinstance(obj["product"], dict):
                p = obj["product"]
                if "price" in p and "url" in p:
                    return p
            if "item" in obj and isinstance(obj["item"], dict):
                it = obj["item"]
                got = find_product_obj(it)
                if got:
                    return got

            if obj.get("type") == "Product" and "price" in obj and "url" in obj:
                return obj
            for v in obj.values():
                got = find_product_obj(v)
                if got:
                    return got
        elif isinstance(obj, list):
            for x in obj:
                got = find_product_obj(x)
                if got:
                    return got
        return None

    prod = find_product_obj(payload)
    if not prod:
        return []

    price = prod.get("price") or {}
    actual = (price.get("actual") or {}).get("amount")
    regular = (price.get("regular") or {}).get("amount")
    currency = (price.get("actual") or {}).get("currency") or (price.get("regular") or {}).get("currency")

    attrs = prod.get("attributes") or {}
    units = attrs.get("units") or {}
    volume = None
    if isinstance(units, dict):
        values = units.get("values")
        name = units.get("name")
        if isinstance(values, list) and values:
            volume = f"{values[0]} {name}" if name else str(values[0])

    colors = attrs.get("colors") or {}
    shade_name = None
    shade_values: list[str] = []
    if isinstance(colors, dict):
        shade_name = colors.get("name")
        vals = colors.get("values")
        # values can be list of dicts (swatches) or strings.
        if isinstance(vals, list):
            for v in vals:
                if isinstance(v, str):
                    shade_values.append(v)
                elif isinstance(v, dict):
                    # sometimes there is 'name' or 'title'; sometimes only images
                    if isinstance(v.get("name"), str):
                        shade_values.append(v["name"])

    if not shade_values:
        shade_values = [None]

    rows: list[VariantRow] = []
    for sv in shade_values:
        rows.append(
            VariantRow(
                product_url=product_url,
                item_id=str(prod.get("itemId")) if prod.get("itemId") is not None else None,
                name=prod.get("name"),
                brand=prod.get("brand"),
                product_type=prod.get("productType"),
                volume=volume,
                shade_name=shade_name,
                shade_value=sv,
                price_actual=actual,
                price_regular=regular,
                currency=currency,
                in_stock=prod.get("inStock"),
            )
        )

    return rows


def fetch_product_via_api(driver: webdriver.Chrome, item_id: str) -> dict[str, Any] | None:
    """Fetch product JSON via API using CDP Fetch API to avoid opening product pages."""
    try:
        url = f"https://goldapple.ru/front/api/catalog/product-card/base/v3?locale=ru&itemId={item_id}&customerGroupId=0&cityId=0c5b2444-70a0-4932-980c-b4dc0d3f02b5&regionId=0c5b2444-70a0-4932-980c-b4dc0d3f02b5"
        
        # Use CDP Fetch API to make the request
        fetch_result = driver.execute_cdp_cmd("Fetch.enable", {"patterns": []})
        
        # Alternative: use Runtime.evaluate to make fetch request via JS
        script = f"""
            return fetch("{url}", {{
                method: "GET",
                headers: {{
                    "Accept": "application/json",
                    "Accept-Language": "ru-RU,ru;q=0.9",
                    "Referer": "https://goldapple.ru/"
                }},
                credentials: "include"
            }}).then(r => r.json()).catch(e => ({{error: e.message}}));
        """
        
        result = driver.execute_cdp_cmd("Runtime.evaluate", {
            "expression": script,
            "awaitPromise": True,
            "returnByValue": True,
            "timeout": 10000
        })
        
        if result.get("exceptionDetails"):
            return None
            
        value = result.get("result", {}).get("value")
        if isinstance(value, dict) and "error" not in value:
            return value
        return None
        
    except Exception as e:
        print(f"[API Fetch Error] {e}")
        return None
    driver: webdriver.Chrome,
    url_hint: str,
    wait_seconds: float,
    poll_interval: float,
    dump_bodies: bool,
    dump_limit: int,
) -> dict[str, Any] | None:
    """Wait for a network response whose URL contains url_hint, then return parsed JSON body."""

    req_to_url: dict[str, str] = {}
    deadline = time.time() + wait_seconds

    while time.time() < deadline:
        logs = driver.get_log("performance")
        for entry in logs:
            msg = json.loads(entry["message"])["message"]
            method = msg.get("method")
            params = msg.get("params", {})

            if method == "Network.responseReceived":
                response = params.get("response", {})
                url = response.get("url", "")
                rid = params.get("requestId")
                if rid and url:
                    req_to_url[rid] = url

            if method == "Network.loadingFinished":
                rid = params.get("requestId")
                url = req_to_url.get(rid, "")
                if not url or url_hint not in url:
                    continue

                try:
                    body = driver.execute_cdp_cmd("Network.getResponseBody", {"requestId": rid})
                except Exception:
                    continue

                text = (body.get("body") or "").strip()
                if not text:
                    continue

                if body.get("base64Encoded") is True:
                    try:
                        text = base64.b64decode(text).decode("utf-8", errors="replace")
                    except Exception:
                        continue

                if dump_bodies:
                    safe = "".join([c if c.isalnum() else "_" for c in urlparse(url).path])
                    with open(f"dump_product_{safe}_{rid}.txt", "w", encoding="utf-8") as f:
                        f.write(text[:dump_limit])

                try:
                    return json.loads(text)
                except Exception:
                    continue

        time.sleep(poll_interval)

    return None


def main():
    args = parse_args()

    links = read_links(args.links)
    if args.start:
        links = links[args.start :]
    if args.limit and args.limit > 0:
        links = links[: args.limit]

    state = load_state(args.state)
    done: set[str] = set(state.get("done", []))

    driver = build_driver(headless=args.headless)
    
    # First, open the main page to get session/cookies
    try:
        print("[INIT] Opening main page to get session...")
        driver.get("https://goldapple.ru/")
        time.sleep(5)
        print("[INIT] Session established")
    except Exception as e:
        print(f"[WARN] Failed to open main page: {e}")

    rows: list[VariantRow] = []

    try:
        for idx, url in enumerate(links, start=args.start):
            if url in done:
                continue

            attempt = 0
            ok = False
            last_err = None

            while attempt <= args.retry and not ok:
                attempt += 1
                try:
                    # Extract item ID from URL
                    item_id = extract_item_id_from_url(url)
                    if not item_id:
                        raise RuntimeError(f"Could not extract item ID from URL: {url}")
                    
                    print(f"[FETCH] itemId={item_id}")
                    
                    # Fetch product data via API
                    payload = fetch_product_via_api(driver, item_id)
                    
                    if not payload:
                        raise RuntimeError("API returned no payload")

                    extracted = extract_from_payload(url, payload)
                    if not extracted:
                        raise RuntimeError("payload parsed but product object not found")

                    rows.extend(extracted)
                    ok = True

                except Exception as e:
                    last_err = e
                    # If Chrome crashed/closed, recreate driver
                    if isinstance(e, WebDriverException) and ("no such window" in str(e).lower() or "invalid session id" in str(e).lower()):
                        try:
                            driver.quit()
                        except Exception:
                            pass
                        driver = build_driver(headless=args.headless)
                        # Re-establish session
                        try:
                            driver.get("https://goldapple.ru/")
                            time.sleep(5)
                        except Exception:
                            pass

                    if args.dump_errors:
                        safe = "".join([c if c.isalnum() else "_" for c in urlparse(url).path])
                        with open(f"error_{safe}_{int(time.time())}.txt", "w", encoding="utf-8") as f:
                            f.write(f"URL: {url}\n")
                            f.write(f"Error: {repr(e)}\n")

                    take_delay(args.min_delay, args.max_delay)

            if not ok:
                print(f"[ERR] {url} -> {last_err}")
            else:
                done.add(url)
                state["done"] = sorted(done)
                save_state(args.state, state)
                print(f"[OK] {len(done)}/{len(links)} processed")

            take_delay(args.min_delay, args.max_delay)

    finally:
        try:
            driver.quit()
        except Exception:
            pass

    if rows:
        df = pd.DataFrame([asdict(r) for r in rows])
        df.to_csv(args.out_csv, index=False, encoding="utf-8")
        df.to_excel(args.out_xlsx, index=False)
        print(f"Saved: {args.out_csv}")
        print(f"Saved: {args.out_xlsx}")
    else:
        print("[WARN] No data collected")


if __name__ == "__main__":
    main()
