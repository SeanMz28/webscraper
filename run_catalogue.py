"""
CARAV Catalogue Builder
=======================
Batch fetch + split for a list of CARAV part numbers.
Saves images to cat_input/ and split outputs + vehicle info to cat_output/.

Usage:
  python run_catalogue.py
"""

import csv
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

from scrape_carav import scrape_part
from generate_carav_install import split_product_image

SCRIPT_DIR = Path(__file__).parent
CAT_INPUT = SCRIPT_DIR / "cat_input"
CAT_OUTPUT = SCRIPT_DIR / "cat_output"

# ─── Part numbers to fetch ──────────────────────────────────────────────
PART_NUMBERS = [
    "11-450",
    "11-457",
    "11-011",
    "22-498",
    "11-481",
    "22-181",
    "22-407",
    "22-180",
    "22-275",
    "22-630",
    "22-645",
    "11-276",
    "22-621",
    "22-626",
    "11-491",
    "22-906",
    "11-507",
    "22-012",
    "22-680",
    "22-360",
    "22-070",
    "22-613",
    "22-810",
    "22-629",
    "11-397",
    "22-813",
    "22-515",
    "22-079",
    "22-081",
    "22-781",
    "11-516",
    "11-086",
    "22-023",
    "11-429",
    "22-309",
    "11-478",
    "22-567",
    "22-654",
    "22-655",
    "22-015",
    "22-259",
    "22-157",
    "22-795",
    "22-958",
    "22-743",
    "22-981",
    "22-588",
    "11-037",
    "22-013",
    "22-031",
    "22-032",
    "22-600",
    "22-987",
    "22-025",
    "11-343",
    "11-401",
    "11-342",
    "11-793",
    "11-039",
    "11-795",
    "08-008",
    "08-009",
    "22-540",
]


def write_info_file(part_number: str, result: dict, output_dir: Path):
    """Write vehicle information to info.txt in the part's output folder."""
    folder_name = result.get("folder_name", part_number)
    part_dir = output_dir / folder_name
    part_dir.mkdir(parents=True, exist_ok=True)
    info_path = part_dir / "info.txt"

    lines = [
        f"Part Number: CARAV {part_number}",
        f"Car Name: {result.get('car_name') or 'N/A'}",
        f"Description: {result.get('description') or 'N/A'}",
        f"Note: {result.get('note') or 'N/A'}",
        f"Folder: {folder_name}",
        f"Fetched: {datetime.now().isoformat()}",
    ]
    info_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    logger.info("  Saved info → %s", info_path)


def run_catalogue():
    CAT_INPUT.mkdir(parents=True, exist_ok=True)
    CAT_OUTPUT.mkdir(parents=True, exist_ok=True)

    total = len(PART_NUMBERS)
    succeeded = []
    failed = []

    # CSV summary file
    csv_path = CAT_OUTPUT / "catalogue_summary.csv"
    csv_file = open(csv_path, "w", newline="", encoding="utf-8")
    writer = csv.writer(csv_file)
    writer.writerow(["part_number", "car_name", "description", "note", "folder_name", "status"])

    for i, part in enumerate(PART_NUMBERS, 1):
        logger.info("=" * 60)
        logger.info("[%d/%d] Fetching CARAV %s …", i, total, part)
        logger.info("=" * 60)

        try:
            # 1. Scrape images from carav-parts.com → cat_input/<folder>/
            result = scrape_part(part, output_dir=CAT_INPUT)

            if not result:
                logger.error("  No results for %s — skipping", part)
                failed.append(part)
                writer.writerow([part, "", "", "", "", "FAILED - no results"])
                continue

            folder_name = result.get("folder_name", part)
            car_name = result.get("car_name") or ""
            description = result.get("description") or ""
            note = result.get("note") or ""

            product_path = CAT_INPUT / folder_name / "product.png"
            if not product_path.exists():
                # Try .jpg
                product_path = CAT_INPUT / folder_name / "product.jpg"

            if not product_path.exists():
                logger.error("  Product image not found for %s — skipping split", part)
                failed.append(part)
                writer.writerow([part, car_name, description, note, folder_name, "FAILED - no product image"])
                continue

            # 2. Split product image → cat_output/<folder>/
            part_output = CAT_OUTPUT / folder_name
            part_output.mkdir(parents=True, exist_ok=True)
            split_product_image(product_path, part_output)

            # 3. Write info file
            write_info_file(part, result, CAT_OUTPUT)

            # 4. CSV row
            writer.writerow([part, car_name, description, note, folder_name, "OK"])
            succeeded.append(part)
            logger.info("  ✓ %s → %s", part, folder_name)

        except Exception as e:
            logger.error("  ERROR processing %s: %s", part, e, exc_info=True)
            failed.append(part)
            writer.writerow([part, "", "", "", "", f"ERROR - {e}"])

        # Small delay to be polite to the server
        time.sleep(1)

    csv_file.close()

    # ─── Summary ────────────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("CATALOGUE COMPLETE")
    logger.info("  Succeeded: %d / %d", len(succeeded), total)
    logger.info("  Failed:    %d / %d", len(failed), total)
    if failed:
        logger.info("  Failed parts: %s", ", ".join(failed))
    logger.info("  Summary CSV: %s", csv_path)
    logger.info("=" * 60)


if __name__ == "__main__":
    run_catalogue()
