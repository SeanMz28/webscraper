"""
RHD Trim Generator
===================
For each sub-folder in cat_output/ that contains a product_trim_half_clean.png,
horizontally flip (mirror) the image to produce the RHD version.

The result is saved as  product_trim_half_clean_rhd.png  in the same folder.

Usage:
  # Process all folders
  python generate_rhd_trims.py --output-dir cat_output

  # Process specific numbered folders
  python generate_rhd_trims.py --output-dir cat_output --numbers "6,10,31"

  # Process a range
  python generate_rhd_trims.py --output-dir cat_output --numbers "7-12"

  # Dry-run: list what would be processed
  python generate_rhd_trims.py --output-dir cat_output --numbers "6,10" --dry-run

  # Skip folders that already have an RHD trim
  python generate_rhd_trims.py --output-dir cat_output --skip-existing
"""

import argparse
import logging
import sys
from pathlib import Path

from PIL import Image

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ─── Configuration ──────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "cat_output"
INPUT_FILENAME = "product_trim_half_clean.png"
OUTPUT_FILENAME = "product_trim_half_clean_rhd.png"


# ─── Main ────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Generate RHD versions of CARAV trim images by horizontal flip."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Root output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--filter",
        metavar="SUBSTRING",
        default=None,
        help="Only process folders whose name contains this substring (case-insensitive)",
    )
    parser.add_argument(
        "--numbers",
        metavar="RANGE",
        default=None,
        help=(
            "Only process numbered folders matching these numbers. "
            "Supports ranges and comma-separated values, e.g. '7-12' or '6,10,31'"
        ),
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip folders that already have a product_trim_half_clean_rhd.png",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List folders and exit without processing",
    )
    args = parser.parse_args()

    output_dir: Path = args.output_dir

    # ── Collect folders ─────────────────────────────────────────────────
    folders = sorted(
        d for d in output_dir.iterdir()
        if d.is_dir() and (d / INPUT_FILENAME).exists()
    )

    if not folders:
        logger.error(
            "No sub-folders with '%s' found under %s", INPUT_FILENAME, output_dir
        )
        sys.exit(1)

    if args.numbers:
        nums = set()
        for part in args.numbers.split(","):
            part = part.strip()
            if "-" in part:
                lo, hi = part.split("-", 1)
                nums.update(range(int(lo), int(hi) + 1))
            else:
                nums.add(int(part))
        folders = [
            f for f in folders
            if f.name[:2].isdigit() and int(f.name[:2]) in nums
        ]
        if not folders:
            logger.error("No folders match --numbers '%s'", args.numbers)
            sys.exit(1)

    if args.filter:
        folders = [f for f in folders if args.filter.lower() in f.name.lower()]
        if not folders:
            logger.error("No folders match filter '%s'", args.filter)
            sys.exit(1)

    if args.skip_existing:
        before = len(folders)
        folders = [f for f in folders if not (f / OUTPUT_FILENAME).exists()]
        skipped = before - len(folders)
        if skipped:
            logger.info("Skipping %d folder(s) that already have %s", skipped, OUTPUT_FILENAME)

    if not folders:
        logger.info("Nothing to process.")
        return

    logger.info("Found %d folder(s) to process:", len(folders))
    for f in folders:
        logger.info("  %s", f.name)

    if args.dry_run:
        logger.info("Dry-run mode — exiting without processing.")
        return

    # ── Process ─────────────────────────────────────────────────────────
    succeeded = 0
    failed = 0

    for idx, folder in enumerate(folders, 1):
        input_path = folder / INPUT_FILENAME
        output_path = folder / OUTPUT_FILENAME

        print(f"\n[{idx}/{len(folders)}] {folder.name}")
        print(f"  Input : {input_path}")
        print(f"  Output: {output_path}")

        try:
            with Image.open(input_path) as img:
                flipped = img.transpose(Image.FLIP_LEFT_RIGHT)
                flipped.save(output_path)
                size = output_path.stat().st_size
                logger.info("  Saved → %s  (%d bytes)", OUTPUT_FILENAME, size)
                succeeded += 1
        except Exception as exc:
            logger.error("  FAILED: %s", exc)
            failed += 1

    print()
    logger.info("=" * 60)
    logger.info("Done.  %d succeeded, %d failed out of %d total.", succeeded, failed, len(folders))


if __name__ == "__main__":
    main()
