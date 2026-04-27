"""
Rebuild Composites with Car Name
=================================
Regenerates the composite image for every folder in cat_output/,
adding the car name as a title at the top.

Usage:
  python rebuild_composites.py
"""

import logging
import re
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

from carav_pipeline import build_composite

SCRIPT_DIR = Path(__file__).parent
CAT_OUTPUT = SCRIPT_DIR / "cat_output"


def read_car_name(info_path: Path) -> str | None:
    """Read the car name from info.txt and clean up extra whitespace."""
    text = info_path.read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("Car Name:"):
            name = line.split(":", 1)[1].strip()
            # Collapse multiple whitespace
            name = re.sub(r"\s+", " ", name)
            if name and name != "N/A":
                return name
    return None


def car_name_from_folder(folder_name: str) -> str:
    """Derive a readable car name from the folder name as fallback."""
    # Strip leading number prefix like "06_"
    name = re.sub(r"^\d+_", "", folder_name)
    # Replace underscores with spaces
    name = name.replace("_", " ")
    return name


def latest_file(folder: Path, prefix: str) -> Path | None:
    """Find the latest file matching a prefix, sorted by name (timestamp)."""
    matches = sorted(folder.glob(f"{prefix}*.png"))
    return matches[-1] if matches else None


def main():
    folders = sorted(
        d for d in CAT_OUTPUT.iterdir()
        if d.is_dir()
    )

    logger.info("Found %d folders in cat_output/", len(folders))
    success = 0
    failed = 0

    for folder in folders:
        logger.info("--- %s ---", folder.name)

        # Read car name
        info_path = folder / "info.txt"
        if info_path.exists():
            car_name = read_car_name(info_path)
        else:
            car_name = None

        if not car_name:
            car_name = car_name_from_folder(folder.name)

        # Find trim image (prefer clean version)
        trim_path = folder / "product_trim_half_clean.png"
        if not trim_path.exists():
            trim_path = folder / "product_trim_half.png"
        if not trim_path.exists():
            logger.warning("  No trim image — skipping")
            failed += 1
            continue

        # Find dashboard image (prefer RHD)
        dash_path = folder / "product_dashboard_half_rhd.png"
        if not dash_path.exists():
            dash_path = folder / "product_dashboard_half.png"
        if not dash_path.exists():
            logger.warning("  No dashboard image — skipping")
            failed += 1
            continue

        # Find step1 and step2 (latest by timestamp)
        step1_path = latest_file(folder, "step1_trim_and_screen_")
        step2_path = latest_file(folder, "step2_installed_")

        logger.info("  Car name: %s", car_name)
        build_composite(
            trim_path, dash_path, step1_path, step2_path, folder,
            car_name=car_name, folder_name=folder.name,
        )
        success += 1

    logger.info("=" * 60)
    logger.info("Done. %d succeeded, %d failed.", success, failed)
    logger.info("=" * 60)


if __name__ == "__main__":
    main()
