#!/usr/bin/env python3
"""
Create Before/After Comparison Images
======================================
Stitches original dashboard images side-by-side with AI-generated
trim installation images. No API calls needed — pure image manipulation.

Usage:
  # Compare a specific vehicle
  python3 create_comparisons.py --make TOYOTA --model AURIS --year 2014-present

  # Compare all vehicles in catalogue_phase2
  python3 create_comparisons.py --all

  # Custom output directory
  python3 create_comparisons.py --make ISUZU --model D-MAX --year 2005 --output-dir ./my_comparisons

  # Adjust image height (default: 800px)
  python3 create_comparisons.py --make TOYOTA --model AURIS --year 2014-present --height 600
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

DASHBOARDS_DIR = Path(__file__).parent / "dashboards"
CATALOGUE_DIR = Path(__file__).parent / "catalogue_phase2"

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


def find_originals(make: str, model: str, year: str) -> list[Path]:
    """Find original dashboard images."""
    folder_name = f"{model.upper().replace(' ', '_')}_{year}"
    dirpath = DASHBOARDS_DIR / make.upper() / folder_name
    if not dirpath.exists():
        # Try partial match
        make_dir = DASHBOARDS_DIR / make.upper()
        if make_dir.exists():
            for d in sorted(make_dir.iterdir()):
                if d.is_dir() and model.upper().replace(" ", "_") in d.name.upper():
                    if year in d.name or d.name.endswith("_"):
                        dirpath = d
                        break

    if not dirpath.exists():
        logger.error(f"Originals folder not found: {dirpath}")
        return []

    return sorted(f for f in dirpath.iterdir() if f.suffix.lower() in (".jpg", ".jpeg", ".png"))


def find_generated(make: str, model: str, year: str) -> list[Path]:
    """Find generated trim installation images."""
    folder_name = f"{model.upper().replace(' ', '_')}_{year}"
    dirpath = CATALOGUE_DIR / make.upper() / folder_name
    if not dirpath.exists():
        logger.error(f"Generated folder not found: {dirpath}")
        return []

    return sorted(
        f for f in dirpath.iterdir()
        if f.suffix.lower() == ".png" and "trim_installed" in f.name
    )


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


def compare_vehicle(
    make: str,
    model: str,
    year: str,
    output_dir: Path | None = None,
    max_height: int = 800,
) -> list[Path]:
    """Create comparison images for a single vehicle. Returns list of output paths."""
    originals = find_originals(make, model, year)
    generated = find_generated(make, model, year)

    if not originals:
        logger.error(f"No original images found for {make} {model} {year}")
        return []
    if not generated:
        logger.error(f"No generated images found for {make} {model} {year}")
        return []

    count = min(len(originals), len(generated))
    if len(originals) != len(generated):
        logger.warning(
            f"Mismatch: {len(originals)} originals vs {len(generated)} generated. "
            f"Will compare first {count} pairs."
        )

    if output_dir is None:
        folder_name = f"{model.upper().replace(' ', '_')}_{year}"
        output_dir = CATALOGUE_DIR / make.upper() / folder_name / "comparisons"

    output_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for i, (orig, gen) in enumerate(zip(originals[:count], generated[:count]), 1):
        out_path = output_dir / f"comparison_{i:02d}.png"
        w, h = create_comparison(orig, gen, out_path, max_height)
        logger.info(f"Saved: {out_path} ({w}x{h})")
        results.append(out_path)

    logger.info(f"Created {len(results)} comparisons in {output_dir}")
    return results


def compare_all(output_base: Path | None = None, max_height: int = 800):
    """Create comparisons for all vehicles in catalogue_phase2."""
    if not CATALOGUE_DIR.exists():
        logger.error(f"Catalogue directory not found: {CATALOGUE_DIR}")
        return

    total = 0
    for make_dir in sorted(CATALOGUE_DIR.iterdir()):
        if not make_dir.is_dir():
            continue
        for model_dir in sorted(make_dir.iterdir()):
            if not model_dir.is_dir():
                continue

            make = make_dir.name
            # Parse model and year from folder name like "D-MAX_2005" or "AURIS_2014-present"
            parts = model_dir.name.rsplit("_", 1)
            if len(parts) == 2:
                model, year = parts
            else:
                model, year = model_dir.name, ""

            out_dir = output_base / make / model_dir.name / "comparisons" if output_base else None
            results = compare_vehicle(make, model, year, out_dir, max_height)
            total += len(results)

    logger.info(f"Total comparisons created: {total}")


def main():
    parser = argparse.ArgumentParser(
        description="Create before/after comparison images for trim installations"
    )

    parser.add_argument("--make", help="Vehicle make (e.g., TOYOTA)")
    parser.add_argument("--model", help="Vehicle model (e.g., AURIS)")
    parser.add_argument("--year", help="Vehicle year (e.g., 2014-present)")
    parser.add_argument("--all", action="store_true", help="Process all vehicles in catalogue_phase2")
    parser.add_argument("--output-dir", default=None, help="Custom output directory")
    parser.add_argument("--height", type=int, default=800, help="Max image height in pixels (default: 800)")

    args = parser.parse_args()

    output_dir = Path(args.output_dir) if args.output_dir else None

    if args.all:
        compare_all(output_base=output_dir, max_height=args.height)
    elif args.make and args.model and args.year:
        compare_vehicle(args.make, args.model, args.year, output_dir, args.height)
    else:
        parser.error("Provide --make, --model, and --year, or use --all")


if __name__ == "__main__":
    main()
