import argparse
import csv
import json
import os
import random
import re
import time
import urllib.parse
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlparse
from pathlib import Path

import pandas as pd
from playwright.sync_api import sync_playwright, Page, Browser
import requests
from PIL import Image
import io


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
    # New image fields
    product_image_url: str | None
    shade_image_url: str | None
    swatch_url: str | None
    local_product_image: str | None
    local_shade_image: str | None
    local_swatch_image: str | None


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--links", default="product_links.csv", help="Input CSV with column 'url'")
    p.add_argument("--out-xlsx", default="results.xlsx", help="Output XLSX")
    p.add_argument("--out-csv", default="results.csv", help="Output CSV")
    p.add_argument("--state", default="research_state.json", help="Checkpoint/progress file")
    p.add_argument("--headless", action="store_true")
    p.add_argument("--limit", type=int, default=0, help="Process only first N links (0 = all)")
    p.add_argument("--start", type=int, default=0, help="Start index in links list")
    p.add_argument("--min-delay", type=float, default=2.0)
    p.add_argument("--max-delay", type=float, default=4.0)
    p.add_argument("--retry", type=int, default=2)
    p.add_argument("--dump-errors", action="store_true", help="Dump debug info for failed pages")
    # New image arguments
    p.add_argument("--download-images", action="store_true", help="Download product and shade images")
    p.add_argument("--images-dir", default="images", help="Directory to save downloaded images")
    p.add_argument("--image-size", default="400", help="Image size for downloading")
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


def extract_item_id_from_url(url: str) -> str | None:
    """Extract item ID from URL like /19000472181-make-up-care-matte"""
    path = urlparse(url).path
    path = path.lstrip("/")
    parts = path.split("-")
    if parts and parts[0].isdigit():
        return parts[0]
    return None


def fetch_product_api(page: Page, item_id: str) -> dict[str, Any] | None:
    """Fetch product data via direct API call using page.evaluate with fetch."""
    try:
        api_url = f"https://goldapple.ru/front/api/catalog/product-card/base/v3?locale=ru&itemId={item_id}&customerGroupId=0&cityId=0c5b2444-70a0-4932-980c-b4dc0d3f02b5&regionId=0c5b2444-70a0-4932-980c-b4dc0d3f02b5"
        
        result = page.evaluate("""async (url) => {
            try {
                const response = await fetch(url, {
                    method: 'GET',
                    headers: {
                        'Accept': 'application/json',
                        'Accept-Language': 'ru-RU,ru;q=0.9',
                        'Referer': window.location.href
                    },
                    credentials: 'same-origin'
                });
                
                const status = response.status;
                const text = await response.text();
                
                return {
                    status: status,
                    text: text.substring(0, 50000),
                    ok: response.ok
                };
            } catch (e) {
                return { status: 0, text: '', error: e.toString(), ok: false };
            }
        }""", api_url)
        
        if not result.get('ok'):
            print(f"[DEBUG] API error: status={result.get('status')}, error={result.get('error')}")
            return None
            
        text = result.get('text', '')
        if not text:
            return None
            
        try:
            data = json.loads(text)
            print(f"[DEBUG] API response keys: {list(data.keys()) if isinstance(data, dict) else 'not dict'}")
            return data
        except json.JSONDecodeError as e:
            print(f"[DEBUG] JSON parse error: {e}")
            return None
            
    except Exception as e:
        print(f"[DEBUG] fetch_product_api error: {e}")
        return None


def setup_images_directory(images_dir: str) -> Path:
    """Create images directory structure."""
    base_dir = Path(images_dir)
    base_dir.mkdir(exist_ok=True)
    
    # Create subdirectories
    (base_dir / "products").mkdir(exist_ok=True)
    (base_dir / "shades").mkdir(exist_ok=True)
    (base_dir / "swatches").mkdir(exist_ok=True)
    
    return base_dir


def get_image_url(product: dict, image_type: str = "main") -> str | None:
    """Extract image URL from product data."""
    if "media" in product and isinstance(product["media"], dict):
        media = product["media"]
        if "images" in media and isinstance(media["images"], list):
            images = media["images"]
            if images:
                # Return main image or first available
                if image_type == "main" and len(images) > 0:
                    return images[0].get("url")
                elif image_type == "gallery" and len(images) > 1:
                    return images[1].get("url")
    
    # Try alternative image field
    if "image" in product:
        return product["image"]
    elif "imageUrl" in product:
        return product["imageUrl"]
    elif "picture" in product:
        return product["picture"]
    
    return None


def get_shade_image_url(variant: dict) -> str | None:
    """Extract shade-specific image URL from variant data."""
    if "media" in variant and isinstance(variant["media"], dict):
        media = variant["media"]
        if "images" in media and isinstance(media["images"], list):
            images = media["images"]
            if images:
                return images[0].get("url")
    
    # Try variant-specific image fields
    if "image" in variant:
        return variant["image"]
    elif "imageUrl" in variant:
        return variant["imageUrl"]
    elif "picture" in variant:
        return variant["picture"]
    
    return None


def get_swatch_url(product: dict, variant: dict) -> str | None:
    """Extract swatch URL from product or variant data."""
    # Try variant swatch first
    if "swatch" in variant:
        return variant["swatch"]
    elif "swatchUrl" in variant:
        return variant["swatchUrl"]
    elif "colorSwatch" in variant:
        return variant["colorSwatch"]
    
    # Try product swatch
    if "swatch" in product:
        return product["swatch"]
    elif "swatchUrl" in product:
        return product["swatchUrl"]
    elif "colorSwatch" in product:
        return product["colorSwatch"]
    
    # Try to extract from color attributes
    if "attributesValue" in variant and isinstance(variant["attributesValue"], dict):
        attrs = variant["attributesValue"]
        if "colors" in attrs and isinstance(attrs["colors"], str):
            # Sometimes colors contain swatch URLs
            colors = attrs["colors"].split(",")
            for color in colors:
                if "http" in color:
                    return color.strip()
    
    return None


def download_image(url: str, local_path: Path, size: int = 400) -> bool:
    """Download and resize image."""
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        
        # Open image and resize
        img = Image.open(io.BytesIO(response.content))
        
        # Convert to RGB if necessary
        if img.mode in ('RGBA', 'P'):
            img = img.convert('RGB')
        
        # Resize maintaining aspect ratio
        img.thumbnail((size, size), Image.Resampling.LANCZOS)
        
        # Save image
        local_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(local_path, 'JPEG', quality=85)
        
        return True
    except Exception as e:
        print(f"[DEBUG] Failed to download image {url}: {e}")
        return False


def generate_filename(brand: str, product: str, shade: str, suffix: str = "") -> str:
    """Generate safe filename for image."""
    # Clean and combine parts
    parts = []
    if brand:
        parts.append(re.sub(r'[^\w\s-]', '', brand).strip())
    if product:
        parts.append(re.sub(r'[^\w\s-]', '', product).strip()[:20])  # Limit length
    if shade:
        parts.append(re.sub(r'[^\w\s-]', '', shade).strip())
    
    filename = "_".join(filter(None, parts))
    if suffix:
        filename += f"_{suffix}"
    
    # Ensure filename is safe
    filename = re.sub(r'[^\w\._-]', '', filename)
    
    return filename[:100]  # Limit total length


def parse_product_data(data: dict, url: str, args) -> list[VariantRow] | None:
    """Parse product data from API response."""
    
    # Navigate to product object
    product = None
    
    if isinstance(data, dict):
        # Try data.product
        if "data" in data and isinstance(data["data"], dict):
            if "product" in data["data"]:
                product = data["data"]["product"]
            else:
                product = data["data"]
        # Try direct product
        elif "product" in data:
            product = data["product"]
        # Check if this is already product
        elif "itemId" in data or "name" in data:
            product = data
    
    if not product or not isinstance(product, dict):
        print(f"[DEBUG] No product found in data")
        return None
    
    print(f"[DEBUG] Product keys: {list(product.keys())}")
    
    # Extract variants - each variant will become a separate row
    variants = product.get("variants", [])
    if not variants:
        print(f"[DEBUG] No variants found")
        return None
    
    print(f"[DEBUG] Found {len(variants)} variants")
    
    rows = []
    item_id_base = str(product.get("itemId")) if product.get("itemId") else extract_item_id_from_url(url)
    
    for i, variant in enumerate(variants):
        if not isinstance(variant, dict):
            continue
        
        # Debug: show variant structure for first variant
        if i == 0:
            print(f"[DEBUG] Variant {i} keys: {list(variant.keys())}")
            for key in variant.keys():
                val = variant.get(key)
                if isinstance(val, dict) and len(str(val)) < 200:
                    print(f"[DEBUG]   {key}: {val}")
                elif isinstance(val, list) and len(val) < 5:
                    print(f"[DEBUG]   {key}: {val}")
                elif not isinstance(val, (dict, list)):
                    print(f"[DEBUG]   {key}: {val}")
            
        # Extract price for this variant
        price_actual = None
        price_regular = None
        currency = None
        
        variant_price = variant.get("price", {})
        if isinstance(variant_price, dict):
            actual = variant_price.get("actual", {})
            regular = variant_price.get("regular", {})
            
            if isinstance(actual, dict):
                price_actual = actual.get("amount")
                currency = actual.get("currency")
            elif isinstance(actual, (int, float)):
                price_actual = actual
                
            if isinstance(regular, dict):
                price_regular = regular.get("amount")
                if not currency:
                    currency = regular.get("currency")
            elif isinstance(regular, (int, float)):
                price_regular = regular
        
        # Extract variant-specific attributes
        volume = None
        shade_name = None
        shade_value = None
        
        # Get attributesValue from variant (this is where colors are stored)
        attrs_value = variant.get("attributesValue", {})
        if isinstance(attrs_value, dict):
            # Volume from attributesValue
            units = attrs_value.get("units")
            if units and str(units).isdigit():
                volume = f"{units} мл"
            
            # Colors from attributesValue - this is a string like "01, Light"
            colors_str = attrs_value.get("colors", "")
            if colors_str:
                # Split by comma and clean up
                color_parts = [c.strip() for c in colors_str.split(",") if c.strip()]
                if color_parts:
                    # If multiple parts, combine them (e.g., "01 Light")
                    if len(color_parts) > 1:
                        shade_value = " ".join(color_parts)
                        shade_name = "Оттенок"
                    else:
                        # Single part, use as is
                        shade_value = color_parts[0]
        
        # Fallback to product-level attributes if needed
        if not volume:
            product_attrs = product.get("attributes", {})
            if isinstance(product_attrs, dict):
                units = product_attrs.get("units")
                if isinstance(units, dict):
                    unit_values = units.get("values", [])
                    unit_name = units.get("name", "")
                    if unit_values:
                        volume = f"{unit_values[0]} {unit_name}".strip()
        
        # If still no shade_value, try to get from product-level colors
        if not shade_value:
            product_attrs = product.get("attributes", {})
            if isinstance(product_attrs, dict):
                colors = product_attrs.get("colors")
                if isinstance(colors, dict):
                    shade_name = colors.get("name")
                    color_values = colors.get("values", [])
                    if i < len(color_values):
                        cv = color_values[i]
                        if isinstance(cv, str):
                            shade_value = cv
                        elif isinstance(cv, dict):
                            shade_val = cv.get("name") or cv.get("value") or cv.get("title")
                            if shade_val:
                                shade_value = str(shade_val)
        
        # Extract image URLs
        product_image_url = get_image_url(product, "main")
        shade_image_url = get_shade_image_url(variant)
        swatch_url = get_swatch_url(product, variant)
        
        # Initialize local paths
        local_product_image = None
        local_shade_image = None
        local_swatch_image = None
        
        # Download images if requested
        if args.download_images:
            images_dir = setup_images_directory(args.images_dir)
            image_size = int(args.image_size)
            
            # Generate filenames
            brand = product.get("brand", "unknown")
            product_name = product.get("name", "unknown")
            shade_name_clean = shade_value or "no-shade"
            
            if product_image_url:
                filename = generate_filename(brand, product_name, shade_name_clean, "product")
                local_product_image = str(images_dir / "products" / f"{filename}.jpg")
                download_image(product_image_url, Path(local_product_image), image_size)
            
            if shade_image_url:
                filename = generate_filename(brand, product_name, shade_name_clean, "shade")
                local_shade_image = str(images_dir / "shades" / f"{filename}.jpg")
                download_image(shade_image_url, Path(local_shade_image), image_size)
            
            if swatch_url:
                filename = generate_filename(brand, product_name, shade_name_clean, "swatch")
                local_swatch_image = str(images_dir / "swatches" / f"{filename}.jpg")
                download_image(swatch_url, Path(local_swatch_image), min(100, image_size))  # Smaller for swatches
        
        # Create row for this variant
        rows.append(VariantRow(
            product_url=url,
            item_id=f"{item_id_base}_{i}" if len(variants) > 1 else item_id_base,
            name=product.get("name"),
            brand=product.get("brand"),
            product_type=product.get("productType"),
            volume=volume,
            shade_name=shade_name,
            shade_value=shade_value,
            price_actual=int(price_actual) if price_actual else None,
            price_regular=int(price_regular) if price_regular else None,
            currency=currency,
            in_stock=variant.get("inStock", product.get("inStock")),
            # New image fields
            product_image_url=product_image_url,
            shade_image_url=shade_image_url,
            swatch_url=swatch_url,
            local_product_image=local_product_image,
            local_shade_image=local_shade_image,
            local_swatch_image=local_swatch_image
        ))
    
    return rows


def main():
    args = parse_args()

    links = read_links(args.links)
    if args.start:
        links = links[args.start:]
    if args.limit and args.limit > 0:
        links = links[:args.limit]

    state = load_state(args.state)
    done: set[str] = set(state.get("done", []))

    rows: list[VariantRow] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=args.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-web-security",
                "--disable-features=IsolateOrigins,site-per-process"
            ]
        )
        
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="ru-RU",
            user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        )
        
        page = context.new_page()
        
        # Open main page first to get session
        try:
            print("[INIT] Opening main page...")
            page.goto("https://goldapple.ru/", wait_until="domcontentloaded", timeout=30000)
            time.sleep(3)
            print("[INIT] Session established")
        except Exception as e:
            print(f"[WARN] Failed to open main page: {e}")

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
                        item_id = extract_item_id_from_url(url)
                        if not item_id:
                            raise RuntimeError(f"Could not extract item ID from URL: {url}")
                        
                        print(f"[PROCESS] {url} (itemId={item_id})")
                        
                        # First navigate to product page to establish session context
                        print(f"[OPEN] Navigating to product page...")
                        page.goto(url, wait_until="domcontentloaded", timeout=30000)
                        time.sleep(2)
                        
                        # Now make API call from this page context
                        print(f"[API] Fetching product data...")
                        api_data = fetch_product_api(page, item_id)
                        
                        if not api_data:
                            raise RuntimeError("Failed to fetch API data")
                        
                        # Parse product data
                        variants = parse_product_data(api_data, url, args)
                        if not variants:
                            raise RuntimeError("Could not parse product data from API")
                        
                        rows.extend(variants)
                        ok = True
                        print(f"[OK] Extracted {len(variants)} variant(s)")

                    except Exception as e:
                        last_err = e
                        print(f"[DEBUG] Attempt {attempt} failed: {e}")
                        
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
                    print(f"[PROGRESS] {len(done)}/{len(links)} done")

                take_delay(args.min_delay, args.max_delay)

        finally:
            browser.close()

    if rows:
        df = pd.DataFrame([asdict(r) for r in rows])
        df.to_csv(args.out_csv, index=False, encoding="utf-8")
        df.to_excel(args.out_xlsx, index=False)
        print(f"\n[SAVED] {args.out_csv} ({len(rows)} rows)")
        print(f"[SAVED] {args.out_xlsx}")
    else:
        print("\n[WARN] No data collected")


if __name__ == "__main__":
    main()
