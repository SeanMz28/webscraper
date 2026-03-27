"""
Regenerate RHD Installed Images
================================
For every car folder in carav_output that contains:
  - product_dashboard_half_rhd.png   (new RHD dashboard)
  - step1_trim_and_screen_*.png      (existing trim + screen, already generated)
  - product_trim_half.png            (trim half, for the composite)

…this script generates a NEW step2 "Trim & Screen Installed" image using the
RHD dashboard instead of the original one, then rebuilds the composite.

Output files written per car folder:
  step2_installed_<timestamp>_rhd.png   — new AI-generated installed shot
  <folder_name>_composite_rhd.png       — updated 4-panel composite

Usage:
  # Run all cars (full generation)
  python regenerate_rhd_installs.py

  # Dry-run: print what would be processed without calling OpenAI
  python regenerate_rhd_installs.py --dry-run

  # Single car folder (partial name match is fine)
  python regenerate_rhd_installs.py --car "Yaris"

  # Use responses API instead of images.edit
  python regenerate_rhd_installs.py --method responses

Environment:
  Set OPENAI_API_KEY in your environment or in a .env file.
"""

import argparse
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

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("ERROR: Pillow not installed.  Run: pip install Pillow")
    sys.exit(1)

from generate_carav_install import generate_image, get_client, PROMPT_IMAGE2
from carav_pipeline import build_composite

# ─── Paths ───────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "carav_output"

RHD_DASH_NAME = "product_dashboard_half_rhd.png"
TRIM_NAME = "product_trim_half.png"


# ─── Helpers ─────────────────────────────────────────────────────────────

def find_latest_step1(car_dir: Path) -> Path | None:
    """Return the most-recently-modified step1_trim_and_screen_*.png, or None."""
    candidates = sorted(car_dir.glob("step1_trim_and_screen_*.png"),
                        key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def car_name_from_folder(folder_name: str) -> str:
    """Convert folder name (underscores/mixed) to a readable car name for the composite title."""
    # Replace underscores with spaces — the folder names are already pretty readable
    return folder_name.replace("_", " ")


# ─── Per-car logic ────────────────────────────────────────────────────────

def process_car(
    car_dir: Path,
    client,
    method: str,
    dry_run: bool,
) -> bool:
    """
    Generate a new RHD step2 image and composite for one car folder.
    Returns True on success, False on skip/failure.
    """
    folder_name = car_dir.name

    rhd_dash = car_dir / RHD_DASH_NAME
    trim_path = car_dir / TRIM_NAME

    if not rhd_dash.exists():
        logger.warning("[%s] Missing %s — skipping.", folder_name, RHD_DASH_NAME)
        return False

    if not trim_path.exists():
        logger.warning("[%s] Missing %s — skipping.", folder_name, TRIM_NAME)
        return False

    step1_path = find_latest_step1(car_dir)
    if step1_path is None:
        logger.warning("[%s] No step1_trim_and_screen_*.png found — skipping.", folder_name)
        return False

    logger.info("─" * 60)
    logger.info("Car     : %s", folder_name)
    logger.info("RHD dash: %s", rhd_dash.name)
    logger.info("Step1   : %s", step1_path.name)

    if dry_run:
        logger.info("[DRY RUN] Would generate step2_rhd and composite — skipping API call.")
        return True

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # ── Generate new step2 using RHD dashboard + existing step1 ─────────
    # Image order matches PROMPT_IMAGE2:
    #   image 1 → reference dashboard (now the RHD version)
    #   image 2 → assembled trim + screen unit
    logger.info("Generating step2 RHD installed image …")
    t0 = time.time()
    img2_bytes = generate_image(client, [rhd_dash, step1_path], PROMPT_IMAGE2, method)
    elapsed = time.time() - t0
    logger.info("  API call took %.1fs", elapsed)

    if img2_bytes is None:
        logger.error("[%s] step2 RHD generation failed — skipping composite.", folder_name)
        return False

    step2_rhd_path = car_dir / f"step2_installed_{timestamp}_rhd.png"
    step2_rhd_path.write_bytes(img2_bytes)
    logger.info("  Saved → %s (%d bytes)", step2_rhd_path.name, len(img2_bytes))

    # ── Build composite (trim | RHD dash | step1 | step2_rhd) ───────────
    logger.info("Building composite …")
    composite = build_composite(
        trim_path=trim_path,
        dash_path=rhd_dash,
        step1_path=step1_path,
        step2_path=step2_rhd_path,
        output_dir=car_dir,
        car_name=car_name_from_folder(folder_name),
        folder_name=f"{folder_name}_rhd",   # distinct filename from the original
    )
    logger.info("  Composite → %s", composite.name)
    return True


# ─── Main ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Regenerate RHD step2 + composite for all cars in carav_output",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Root carav_output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--car",
        default=None,
        help="Only process folders whose name contains this substring (case-insensitive)",
    )
    parser.add_argument(
        "--method",
        choices=["edit", "responses"],
        default="edit",
        help="OpenAI API method: 'edit' (default) or 'responses'",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be processed without calling OpenAI",
    )
    args = parser.parse_args()

    output_dir: Path = args.output_dir
    if not output_dir.exists():
        logger.error("Output directory not found: %s", output_dir)
        sys.exit(1)

    # Collect car folders
    car_dirs = sorted(p for p in output_dir.iterdir() if p.is_dir())
    if args.car:
        needle = args.car.lower()
        car_dirs = [p for p in car_dirs if needle in p.name.lower()]
        if not car_dirs:
            logger.error("No folders matched --car filter '%s'", args.car)
            sys.exit(1)

    logger.info("Found %d car folder(s) to process.", len(car_dirs))

    client = None
    if not args.dry_run:
        client = get_client()

    succeeded = []
    failed = []
    skipped = []

    for car_dir in car_dirs:
        try:
            ok = process_car(car_dir, client, args.method, args.dry_run)
            if ok:
                succeeded.append(car_dir.name)
            else:
                skipped.append(car_dir.name)
        except Exception as exc:
            logger.exception("Unhandled error for %s: %s", car_dir.name, exc)
            failed.append(car_dir.name)

    # ── Summary ───────────────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("Done.  Succeeded: %d  |  Skipped: %d  |  Failed: %d",
                len(succeeded), len(skipped), len(failed))
    if succeeded:
        logger.info("Succeeded:")
        for name in succeeded:
            logger.info("  ✓  %s", name)
    if skipped:
        logger.info("Skipped (missing files):")
        for name in skipped:
            logger.info("  -  %s", name)
    if failed:
        logger.info("Failed (errors):")
        for name in failed:
            logger.info("  ✗  %s", name)


if __name__ == "__main__":
    main()
