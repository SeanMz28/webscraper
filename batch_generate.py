"""
Batch Generate Pipeline (Steps 4 + Composite)
==============================================
Runs the AI generation and composite steps for multiple folders in cat_output/.

For each folder it:
  1. Picks the dashboard image: product_dashboard_half_rhd.png if available,
     otherwise product_dashboard_half.png.
  2. Uses product_trim_half_clean.png as the trim image.
  3. Generates Image 1 (trim + screen) via OpenAI.
  4. Generates Image 2 (trim & screen installed in dashboard) via OpenAI.
  5. Builds a labelled composite.

Usage:
  # Process folders 01-49
  python batch_generate.py --folder-range 1-49

  # Dry run
  python batch_generate.py --folder-range 1-49 --dry-run

  # Specific folders only
  python batch_generate.py --folders 5 12 30

Environment:
  Set OPENAI_API_KEY in your environment or in a .env file.
"""

import argparse
import logging
import re
import sys
import time
from datetime import datetime
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

try:
    from PIL import Image
except ImportError:
    print("ERROR: Pillow not installed.  Run: pip install Pillow")
    sys.exit(1)

from generate_carav_install import (
    generate_image, get_client,
    PROMPT_IMAGE1, PROMPT_IMAGE2,
)
from carav_pipeline import build_composite

SCRIPT_DIR = Path(__file__).parent
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "cat_output"
RADIO_DIR = SCRIPT_DIR / "starsound"
RADIO_MAP = {
    "0": RADIO_DIR / "car_radio_1_enh.png",
    "1": RADIO_DIR / "car_radio_1_enh.png",
    "2": RADIO_DIR / "car_radio_2_enh.png",
}


def _folder_num(name: str) -> int | None:
    """Extract the leading numeric prefix from a folder name."""
    digits = ""
    for ch in name:
        if ch.isdigit():
            digits += ch
        else:
            break
    return int(digits) if digits else None


def find_folders(
    output_dir: Path,
    folder_range: str | None = None,
    folder_numbers: list[int] | None = None,
) -> list[Path]:
    """Return sorted list of matching sub-folders in output_dir."""
    lo, hi = 0, 9999
    if folder_range:
        parts = folder_range.split("-")
        lo, hi = int(parts[0]), int(parts[1])

    nums = set(folder_numbers) if folder_numbers else None

    matched = []
    for d in sorted(output_dir.iterdir()):
        if not d.is_dir():
            continue
        n = _folder_num(d.name)
        if n is None:
            continue
        if nums and n not in nums:
            continue
        if not nums and not (lo <= n <= hi):
            continue
        matched.append(d)
    return matched


def pick_radio(folder: Path) -> Path | None:
    """Read info.txt and return the correct radio image based on part number."""
    info_file = folder / "info.txt"
    if not info_file.exists():
        logger.warning("  Missing info.txt in %s", folder.name)
        return None

    text = info_file.read_text()
    m = re.search(r"Part Number:\s*CARAV\s+(\d)", text)
    if not m:
        logger.warning("  Could not parse part number from info.txt in %s", folder.name)
        return None

    prefix = m.group(1)
    radio = RADIO_MAP.get(prefix)
    if radio is None or not radio.exists():
        logger.warning("  No radio image for prefix '%s' in %s", prefix, folder.name)
        return None

    logger.info("  Radio:     %s (part prefix %s)", radio.name, prefix)
    return radio


def pick_images(folder: Path) -> tuple[Path, Path] | None:
    """
    Pick dashboard and trim images from a folder.
    Returns (trim_path, dash_path) or None if required files are missing.
    """
    trim = folder / "product_trim_half_clean.png"
    if not trim.exists():
        logger.warning("  Missing product_trim_half_clean.png in %s", folder.name)
        return None

    dash = folder / "product_dashboard_half_rhd.png"
    if not dash.exists():
        dash = folder / "product_dashboard_half.png"
    if not dash.exists():
        logger.warning("  Missing dashboard image in %s", folder.name)
        return None

    logger.info("  Trim:      %s", trim.name)
    logger.info("  Dashboard: %s", dash.name)
    return trim, dash


def run(
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    method: str = "edit",
    folder_range: str | None = None,
    folder_numbers: list[int] | None = None,
    dry_run: bool = False,
):
    folders = find_folders(output_dir, folder_range, folder_numbers)
    if not folders:
        logger.warning("No matching folders found.")
        return

    logger.info("Found %d folder(s) to process", len(folders))

    if not dry_run:
        client = get_client()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    success = 0
    failed = 0

    for idx, folder in enumerate(folders, 1):
        logger.info("=" * 60)
        logger.info("[%d/%d] %s", idx, len(folders), folder.name)
        logger.info("=" * 60)

        images = pick_images(folder)
        if not images:
            failed += 1
            continue

        trim_path, dash_path = images

        radio_path = pick_radio(folder)
        if not radio_path:
            failed += 1
            continue

        if dry_run:
            logger.info("  DRY RUN — would generate 2 images + composite")
            success += 1
            continue

        # Step 1: Generate trim + screen
        logger.info("  Generating Image 1 (trim + screen) …")
        t0 = time.time()
        img1_bytes = generate_image(client, [trim_path, radio_path], PROMPT_IMAGE1, method)
        logger.info("  API call took %.1fs", time.time() - t0)

        if img1_bytes is None:
            logger.error("  Image 1 generation failed — skipping folder.")
            failed += 1
            continue

        step1_path = folder / f"step1_trim_and_screen_{timestamp}.png"
        step1_path.write_bytes(img1_bytes)
        logger.info("  Saved → %s (%d bytes)", step1_path.name, len(img1_bytes))

        # Step 2: Generate installed in dashboard
        logger.info("  Generating Image 2 (installed in dashboard) …")
        t0 = time.time()
        img2_bytes = generate_image(client, [dash_path, step1_path], PROMPT_IMAGE2, method)
        logger.info("  API call took %.1fs", time.time() - t0)

        if img2_bytes is None:
            logger.error("  Image 2 generation failed — skipping composite.")
            failed += 1
            continue

        step2_path = folder / f"step2_installed_{timestamp}.png"
        step2_path.write_bytes(img2_bytes)
        logger.info("  Saved → %s (%d bytes)", step2_path.name, len(img2_bytes))

        # Step 3: Build composite
        logger.info("  Building composite …")
        build_composite(
            trim_path, dash_path, step1_path, step2_path, folder,
            folder_name=folder.name,
        )

        success += 1

    logger.info("=" * 60)
    logger.info("Done. %d succeeded, %d failed out of %d folders.", success, failed, len(folders))
    logger.info("=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Batch generate AI images + composites for cat_output folders.",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--folder-range",
        type=str,
        help="Range of folder numbers to process (e.g. '1-49').",
    )
    group.add_argument(
        "--folders",
        type=int,
        nargs="+",
        help="Specific folder number(s) to process (e.g. --folders 5 12 30).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory containing output folders (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--method",
        choices=["edit", "responses"],
        default="edit",
        help="OpenAI API method: 'edit' (default) or 'responses'.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List folders and images without calling the API.",
    )
    args = parser.parse_args()

    run(
        output_dir=args.output_dir,
        method=args.method,
        folder_range=args.folder_range,
        folder_numbers=args.folders,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
