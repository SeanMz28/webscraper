"""
Vertical Product Image Splitter
================================
Splits product.png images top-down (top half → dashboard, bottom half → trim)
for cases where the CARAV product image is stacked vertically instead of
side-by-side.

Reads from cat_input/<folder>/product.png and writes:
  cat_output/<folder>/product_trim_half.png
  cat_output/<folder>/product_dashboard_half.png

Usage:
  # Split specific folders by number
  python split_product_vertical.py --folders 4 12 15

  # Custom split ratio (default: top 50%)
  python split_product_vertical.py --folders 4 12 --split-ratio 0.45

  # Dry run — show which files would be processed
  python split_product_vertical.py --folders 4 12 --dry-run
"""

import argparse
import logging
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("ERROR: Pillow not installed.  Run: pip install Pillow")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

SCRIPT_DIR = Path(__file__).parent
DEFAULT_INPUT_DIR = SCRIPT_DIR / "cat_input"
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "cat_output"


def find_folders(input_dir: Path, folder_numbers: list[int]) -> list[Path]:
    """Find folders in input_dir whose numeric prefix matches any of the given numbers."""
    matched = []
    for d in sorted(input_dir.iterdir()):
        if not d.is_dir():
            continue
        digits = ""
        for ch in d.name:
            if ch.isdigit():
                digits += ch
            else:
                break
        if digits and int(digits) in folder_numbers:
            matched.append(d)
    return matched


def split_vertical(
    product_path: Path,
    output_dir: Path,
    split_ratio: float = 0.50,
) -> tuple[Path, Path]:
    """
    Split a product image into top half (dashboard) and bottom half (trim).
    Returns (trim_path, dashboard_path).
    """
    img = Image.open(product_path)
    w, h = img.size
    split_y = int(h * split_ratio)

    dash_img = img.crop((0, 0, w, split_y))
    trim_img = img.crop((0, split_y, w, h))

    output_dir.mkdir(parents=True, exist_ok=True)

    trim_path = output_dir / "product_trim_half.png"
    dash_path = output_dir / "product_dashboard_half.png"

    trim_img.save(trim_path)
    dash_img.save(dash_path)

    logger.info(
        "  Split → dashboard (%dx%d) + trim (%dx%d)",
        dash_img.width, dash_img.height, trim_img.width, trim_img.height,
    )
    return trim_path, dash_path


def run(
    folder_numbers: list[int],
    input_dir: Path = DEFAULT_INPUT_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    split_ratio: float = 0.50,
    dry_run: bool = False,
):
    folders = find_folders(input_dir, folder_numbers)

    if not folders:
        logger.warning("No matching folders found for numbers: %s", folder_numbers)
        return

    logger.info("Found %d folder(s) to process", len(folders))

    for folder in folders:
        product_path = folder / "product.png"
        if not product_path.exists():
            logger.warning("  Skipping %s — no product.png found", folder.name)
            continue

        # Output goes to the matching folder name in cat_output
        out_folder = output_dir / folder.name
        logger.info("Processing: %s", folder.name)

        if dry_run:
            logger.info("  DRY RUN — would split %s → %s/", product_path, out_folder)
            continue

        split_vertical(product_path, out_folder, split_ratio)

    logger.info("Done.")


def main():
    parser = argparse.ArgumentParser(
        description="Split product.png images top-down (dashboard on top, trim on bottom).",
    )
    parser.add_argument(
        "--folders",
        type=int,
        nargs="+",
        required=True,
        help="Folder number(s) to process, e.g. --folders 4 12 15",
    )
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=DEFAULT_INPUT_DIR,
        help=f"Input directory containing numbered folders (default: {DEFAULT_INPUT_DIR})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--split-ratio",
        type=float,
        default=0.50,
        help="Fraction of image height for the top (dashboard) half (default: 0.50)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show which files would be processed without splitting.",
    )
    args = parser.parse_args()

    run(
        folder_numbers=args.folders,
        input_dir=args.input_dir,
        output_dir=args.output_dir,
        split_ratio=args.split_ratio,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
