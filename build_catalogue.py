"""
Build watermarked catalogue from cat_output.

For each subfolder in cat_output:
  - watermark_bg.png  → product_trim_half_clean.png, step1_trim_and_screen_*.png
  - watermark_white.png → product_dashboard_half_rhd.png (fallback product_dashboard_half.png),
                           step2_installed_*.png, *_composite.png
  - info.txt is copied with Part Number line removed and all mentions of carav stripped.

Usage:
  python build_catalogue.py                     # all folders
  python build_catalogue.py --folder BMW        # test on one folder
"""

import argparse
import re
import sys
from pathlib import Path

from add_watermark import add_watermark

ROOT = Path(__file__).resolve().parent
CAT_OUTPUT = ROOT / "cat_output"
CATALOGUE = ROOT / "catalogue"
WATERMARK_BG = ROOT / "starsound" / "watermark_bg.png"
WATERMARK_WHITE = ROOT / "starsound" / "watermark_white.png"

OPACITY = 0.5
MARGIN = 24
SCALE = 0.25


def clean_info_txt(src: Path, dst: Path) -> None:
    """Copy info.txt, removing Part Number line and any carav references."""
    lines = src.read_text(encoding="utf-8").splitlines()
    cleaned = []
    for line in lines:
        # Skip the Part Number line entirely
        if line.strip().lower().startswith("part number"):
            continue
        # Remove "CARAV 11-481: " style references
        line = re.sub(r"CARAV\s*\d*[-]?\d*:?\s*", "", line, flags=re.IGNORECASE)
        # Remove any remaining standalone "carav" word
        line = re.sub(r"\bCARAV\b\s*", "", line, flags=re.IGNORECASE)
        cleaned.append(line)
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text("\n".join(cleaned), encoding="utf-8")


def process_folder(src_folder: Path, dst_folder: Path) -> None:
    """Process a single cat_output subfolder into catalogue."""
    dst_folder.mkdir(parents=True, exist_ok=True)
    count = 0

    # --- info.txt ---
    info_src = src_folder / "info.txt"
    if info_src.exists():
        clean_info_txt(info_src, dst_folder / "info.txt")
        print(f"  ✓ info.txt")
        count += 1
    else:
        print(f"  ✗ info.txt not found")

    # --- watermark_bg → product_trim_half_clean.png ---
    trim_clean = src_folder / "product_trim_half_clean.png"
    if trim_clean.exists():
        add_watermark(trim_clean, WATERMARK_BG, dst_folder / trim_clean.name,
                      opacity=OPACITY, margin=MARGIN, scale=SCALE)
        print(f"  ✓ {trim_clean.name}")
        count += 1
    else:
        print(f"  ✗ product_trim_half_clean.png not found")

    # --- watermark_bg → step1_trim_and_screen_*.png ---
    step1_files = sorted(src_folder.glob("step1_trim_and_screen_*.png"))
    if step1_files:
        f = step1_files[0]  # take the first/latest
        add_watermark(f, WATERMARK_BG, dst_folder / f.name,
                      opacity=OPACITY, margin=MARGIN, scale=SCALE)
        print(f"  ✓ {f.name}")
        count += 1
    else:
        print(f"  ✗ step1_trim_and_screen_*.png not found")

    # --- watermark_white → dashboard (rhd preferred, fallback to half) ---
    dash_rhd = src_folder / "product_dashboard_half_rhd.png"
    dash_half = src_folder / "product_dashboard_half.png"
    if dash_rhd.exists():
        add_watermark(dash_rhd, WATERMARK_WHITE, dst_folder / "product_dashboard_half_rhd.png",
                      opacity=OPACITY, margin=MARGIN, scale=SCALE)
        print(f"  ✓ product_dashboard_half_rhd.png")
        count += 1
    elif dash_half.exists():
        add_watermark(dash_half, WATERMARK_WHITE, dst_folder / "product_dashboard_half.png",
                      opacity=OPACITY, margin=MARGIN, scale=SCALE)
        print(f"  ✓ product_dashboard_half.png (fallback)")
        count += 1
    else:
        print(f"  ✗ no dashboard image found")

    # --- watermark_white → step2_installed_*.png ---
    step2_files = sorted(src_folder.glob("step2_installed_*.png"))
    if step2_files:
        f = step2_files[0]
        add_watermark(f, WATERMARK_WHITE, dst_folder / f.name,
                      opacity=OPACITY, margin=MARGIN, scale=SCALE)
        print(f"  ✓ {f.name}")
        count += 1
    else:
        print(f"  ✗ step2_installed_*.png not found")

    # --- watermark_white → *_composite.png ---
    composite_files = sorted(src_folder.glob("*_composite.png"))
    if composite_files:
        f = composite_files[0]
        add_watermark(f, WATERMARK_WHITE, dst_folder / f.name,
                      opacity=OPACITY, margin=MARGIN, scale=SCALE)
        print(f"  ✓ {f.name}")
        count += 1
    else:
        print(f"  ✗ *_composite.png not found")

    print(f"  → {count}/6 files")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build catalogue with watermarked images")
    parser.add_argument("--folder", type=str, default=None,
                        help="Process only folders matching this substring (for testing)")
    parser.add_argument("--output", type=Path, default=CATALOGUE,
                        help="Output base directory (default: catalogue/)")
    args = parser.parse_args()

    if not WATERMARK_BG.exists():
        sys.exit(f"Watermark not found: {WATERMARK_BG}")
    if not WATERMARK_WHITE.exists():
        sys.exit(f"Watermark not found: {WATERMARK_WHITE}")

    if args.folder:
        matches = [d for d in sorted(CAT_OUTPUT.iterdir()) if d.is_dir() and args.folder in d.name]
        if not matches:
            sys.exit(f"No folder matching '{args.folder}' in {CAT_OUTPUT}")
        folders = matches[:1]
    else:
        folders = sorted(d for d in CAT_OUTPUT.iterdir() if d.is_dir())

    print(f"Processing {len(folders)} folder(s) → {args.output}\n")
    for src in folders:
        dst = args.output / src.name
        print(f"[{src.name}]")
        process_folder(src, dst)
        print()

    print("Done.")


if __name__ == "__main__":
    main()
