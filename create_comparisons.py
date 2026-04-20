#!/usr/bin/env python3
"""
Create Before/After Comparison Images
======================================
Stitches original dashboard images (product_dashboard_half.png) side-by-side
with AI-generated trim installation images (step2_installed*.png) from cat_output.

All comparisons are saved to a single "comparisons" folder.

Usage:
  # Compare all vehicles in cat_output
  python3 create_comparisons.py

  # Custom output directory
  python3 create_comparisons.py --output-dir ./my_comparisons

  # Adjust image height (default: 800px)
  python3 create_comparisons.py --height 600
"""

import argparse
import logging
import sys
from pathlib import Path

try:
    from PIL import Image, ImageDraw, ImageFont
except ImportError:
    print("ERROR: Pillow not installed. Run: pip install Pillow")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

CAT_OUTPUT_DIR = Path(__file__).parent / "cat_output"
DEFAULT_OUTPUT_DIR = Path(__file__).parent / "comparisons"

# Label styling
LABEL_HEIGHT = 40
GAP = 10
BEFORE_COLOR = (200, 50, 50)
AFTER_COLOR = (50, 150, 50)
FONT_SIZE = 24
FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "C:/Windows/Fonts/arialbd.ttf",
]


def get_font(size: int = FONT_SIZE):
    """Try to load a nice font, fall back to default."""
    for path in FONT_PATHS:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def create_comparison(
    original: Path,
    generated: Path,
    output_path: Path,
    max_height: int = 800,
):
    """Create a single side-by-side comparison image."""
    orig = Image.open(original)
    gen = Image.open(generated)

    # Resize both to the same height
    target_h = min(orig.height, gen.height, max_height)
    orig_w = int(orig.width * (target_h / orig.height))
    gen_w = int(gen.width * (target_h / gen.height))
    orig = orig.resize((orig_w, target_h), Image.LANCZOS)
    gen = gen.resize((gen_w, target_h), Image.LANCZOS)

    # Create canvas
    total_w = orig_w + GAP + gen_w
    total_h = target_h + LABEL_HEIGHT
    canvas = Image.new("RGB", (total_w, total_h), (255, 255, 255))
    canvas.paste(orig, (0, LABEL_HEIGHT))
    canvas.paste(gen, (orig_w + GAP, LABEL_HEIGHT))

    # Draw labels
    draw = ImageDraw.Draw(canvas)
    font = get_font()

    # Center labels above each image
    before_text = "BEFORE"
    after_text = "AFTER"
    before_bbox = draw.textbbox((0, 0), before_text, font=font)
    after_bbox = draw.textbbox((0, 0), after_text, font=font)
    before_tw = before_bbox[2] - before_bbox[0]
    after_tw = after_bbox[2] - after_bbox[0]

    draw.text(((orig_w - before_tw) // 2, 8), before_text, fill=BEFORE_COLOR, font=font)
    draw.text((orig_w + GAP + (gen_w - after_tw) // 2, 8), after_text, fill=AFTER_COLOR, font=font)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, quality=95)
    return total_w, total_h


def compare_all(output_dir: Path, max_height: int = 800):
    """Create comparisons for all vehicles in cat_output."""
    if not CAT_OUTPUT_DIR.exists():
        logger.error(f"cat_output directory not found: {CAT_OUTPUT_DIR}")
        return

    output_dir.mkdir(parents=True, exist_ok=True)
    total = 0

    for vehicle_dir in sorted(CAT_OUTPUT_DIR.iterdir()):
        if not vehicle_dir.is_dir():
            continue

        original = vehicle_dir / "product_dashboard_half.png"
        if not original.exists():
            logger.warning(f"No product_dashboard_half.png in {vehicle_dir.name}, skipping")
            continue

        generated_files = sorted(vehicle_dir.glob("step2_installed*.png"))
        if not generated_files:
            logger.warning(f"No step2_installed*.png in {vehicle_dir.name}, skipping")
            continue

        for i, gen_file in enumerate(generated_files, 1):
            suffix = f"_{i:02d}" if len(generated_files) > 1 else ""
            out_name = f"{vehicle_dir.name}_comparison{suffix}.png"
            out_path = output_dir / out_name
            w, h = create_comparison(original, gen_file, out_path, max_height)
            logger.info(f"Saved: {out_path} ({w}x{h})")
            total += 1

    logger.info(f"Total comparisons created: {total}")


def main():
    parser = argparse.ArgumentParser(
        description="Create before/after comparison images for trim installations"
    )

    parser.add_argument("--output-dir", default=None, help="Custom output directory (default: ./comparisons)")
    parser.add_argument("--height", type=int, default=800, help="Max image height in pixels (default: 800)")

    args = parser.parse_args()

    output_dir = Path(args.output_dir) if args.output_dir else DEFAULT_OUTPUT_DIR
    compare_all(output_dir=output_dir, max_height=args.height)


if __name__ == "__main__":
    main()
