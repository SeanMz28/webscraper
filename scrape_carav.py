"""
CARAV Parts Scraper
===================
Scrapes product images from https://carav-parts.com/search

For a given part number (e.g. "11-039"), retrieves:
  1. The main product image  (img class="browseProductImage")
  2. The fitment/additional image (img class="add_images")
"""

import os
import re
import sys
import logging
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
)
logger = logging.getLogger(__name__)

# ─── Configuration ──────────────────────────────────────────────────────
BASE_URL = "https://carav-parts.com"
SEARCH_URL = f"{BASE_URL}/search"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

OUTPUT_DIR = Path(__file__).parent / "carav_images"


def search_carav(part_number: str) -> requests.Response:
    """POST a search query to carav-parts.com and return the response."""
    data = {
        "searchword": part_number,
        "option": "com_search",
        "Itemid": "123",
    }
    logger.info("Searching CARAV for part number: %s", part_number)
    resp = requests.post(SEARCH_URL, data=data, headers=HEADERS, timeout=20)
    resp.raise_for_status()
    logger.info("Search returned %d bytes (HTTP %d)", len(resp.text), resp.status_code)
    return resp


def extract_images(html: str):
    """
    Extract the two target images and the car name from the search results HTML.

    Returns a dict with keys:
        - 'browseProductImage': URL of the main product image (or None)
        - 'add_images':         URL of the additional/fitment image (or None)
        - 'car_name':           Human-readable car name (or None)
    """
    soup = BeautifulSoup(html, "html.parser")

    result = {"browseProductImage": None, "add_images": None, "car_name": None,
              "description": None, "note": None}

    # Extract car name from <span class="proddef1">
    # Typical text: "CARAV 22-025: 10.1" / 250:241 x 146 mm / TOYOTA Land Cruiser Prado (150) 2017+"
    proddef = soup.find("span", class_="proddef1")
    if proddef:
        raw = proddef.get_text(strip=True)
        result["description"] = raw
        logger.info("Full description: %s", raw)
        # Car name is after the last ' / ' separator
        parts = raw.split("/")
        if len(parts) >= 3:
            car_name = parts[-1].strip()
            if car_name:
                result["car_name"] = car_name
                logger.info("Extracted car name: %s", car_name)
        if result["car_name"] is None:
            logger.warning("Could not extract car name from: %s", raw)

    # Extract the "Note:" text that follows the product images
    note_text_parts = []
    for text_node in soup.find_all(string=re.compile(r'Note:', re.IGNORECASE)):
        parent = text_node.parent
        if parent:
            full = parent.get_text(strip=True)
            note_text_parts.append(full)
    if note_text_parts:
        result["note"] = " | ".join(note_text_parts)
        logger.info("Note: %s", result["note"])

    # 1. Main product image: <img class="browseProductImage" ...>
    img_tag = soup.find("img", class_="browseProductImage")
    if img_tag and img_tag.get("src"):
        result["browseProductImage"] = urljoin(BASE_URL, img_tag["src"])
        logger.info("Found browseProductImage: %s", result["browseProductImage"])
    else:
        logger.warning("browseProductImage not found on page")

    # 2. Additional image: <img class="add_images" ...>
    add_tag = soup.find("img", class_="add_images")
    if add_tag and add_tag.get("src"):
        result["add_images"] = urljoin(BASE_URL, add_tag["src"])
        logger.info("Found add_images: %s", result["add_images"])
    else:
        # Sometimes add_images is a container div; check for inner img
        add_div = soup.find(class_="add_images")
        if add_div:
            inner_img = add_div.find("img") if add_div.name != "img" else add_div
            if inner_img and inner_img.get("src"):
                result["add_images"] = urljoin(BASE_URL, inner_img["src"])
                logger.info("Found add_images (inner): %s", result["add_images"])
        if result["add_images"] is None:
            logger.warning("add_images not found on page")

    return result


def download_image(url: str, dest_path: Path) -> bool:
    """Download an image from *url* and save it to *dest_path*. Returns True on success."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20, stream=True)
        resp.raise_for_status()
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        with open(dest_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        logger.info("Saved %s (%d bytes)", dest_path, dest_path.stat().st_size)
        return True
    except Exception as e:
        logger.error("Failed to download %s: %s", url, e)
        return False


def _make_safe_folder_name(car_name: str) -> str:
    """Convert a car name like 'TOYOTA Land Cruiser Prado (150) 2017+' to a filesystem-safe folder name."""
    # Replace characters that are problematic in paths
    safe = re.sub(r'[<>:"/\\|?*]', '', car_name)
    safe = safe.replace('  ', ' ').strip()
    safe = re.sub(r'\s+', '_', safe)
    return safe


def scrape_part(part_number: str, output_dir: Path = OUTPUT_DIR):
    """
    End-to-end: search for a part number, extract both images, download them.

    Folders are named by car name when available, falling back to part number.
    Files are named without the CARAV part number prefix.

    Returns a dict with keys:
        - image labels → file paths
        - 'car_name'  → the extracted car name (or None)
        - 'folder_name' → the folder name used
    """
    resp = search_carav(part_number)
    images = extract_images(resp.text)

    car_name = images.pop("car_name", None)
    description = images.pop("description", None)
    note = images.pop("note", None)
    folder_name = _make_safe_folder_name(car_name) if car_name else part_number

    # Each part gets its own subfolder named by car
    part_dir = output_dir / folder_name
    part_dir.mkdir(parents=True, exist_ok=True)
    downloaded = {
        "car_name": car_name,
        "folder_name": folder_name,
        "description": description,
        "note": note,
    }

    for label, url in images.items():
        if url is None:
            logger.warning("Skipping %s — no URL found", label)
            continue

        ext = url.rsplit(".", 1)[-1].split("?")[0] if "." in url else "png"
        suffix = "product" if label == "browseProductImage" else "fitment"
        filename = f"{suffix}.{ext}"
        dest = part_dir / filename

        if download_image(url, dest):
            downloaded[label] = str(dest)

    return downloaded


# ─── CLI entry point ────────────────────────────────────────────────────
if __name__ == "__main__":
    part = sys.argv[1] if len(sys.argv) > 1 else "11-039"
    logger.info("=== CARAV Scraper — part %s ===", part)
    results = scrape_part(part)

    print("\n--- Results ---")
    if results:
        for label, path in results.items():
            print(f"  {label:25s} → {path}")
    else:
        print("  No images downloaded.")
