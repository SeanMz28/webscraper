"""
RHD Dashboard Comparison Builder
=================================
For every sub-folder in carav_output/ that has both
  product_dashboard_half.png      (original LHD)
  product_dashboard_half_rhd.png  (converted RHD)

…this script stitches them side-by-side with labels and saves:
  product_dashboard_comparison.png

Usage:
  python3 create_rhd_comparisons.py
  python3 create_rhd_comparisons.py --filter "TOYOTA_Corolla"
  python3 create_rhd_comparisons.py --height 600
  python3 create_rhd_comparisons.py --output-dir ./comparisons
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

SCRIPT_DIR = Path(__file__).parent
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "carav_output"

LHD_FILE = "product_dashboard_half.png"
RHD_FILE = "product_dashboard_half_rhd.png"
OUT_FILE = "product_dashboard_comparison.png"

TARGET_H = 500        # height each panel is scaled to
PADDING = 20          # outer and inner padding (px)
LABEL_H = 50          # height of the label bar below each image
TITLE_H = 60          # height of the car-name title at the top
FONT_SIZE = 26
TITLE_FONT_SIZE = 30
GAP = 4               # thin gap between the two panels

FONT_PATHS = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
    "C:/Windows/Fonts/arialbd.ttf",
]

LEFT_LABEL = "Original  (LHD)"
RIGHT_LABEL = "RHD Conversion"
LEFT_BG  = (210, 60,  60)   # red tint for LHD label
RIGHT_BG = (50,  140, 60)   # green tint for RHD label
LABEL_FG = (255, 255, 255)  # white text


def get_font(size: int):
    for path in FONT_PATHS:
        try:
            return ImageFont.truetype(path, size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def folder_to_car_name(folder_name: str) -> str:
    return folder_name.replace("_", " ").strip()


def build_comparison(lhd_path: Path, rhd_path: Path, car_name: str, out_path: Path, target_h: int):
    lhd = Image.open(lhd_path).convert("RGB")
    rhd = Image.open(rhd_path).convert("RGB")

    # Scale both images to the same height
    def scale(img: Image.Image, h: int) -> Image.Image:
        ratio = h / img.height
        return img.resize((int(img.width * ratio), h), Image.LANCZOS)

    lhd_s = scale(lhd, target_h)
    rhd_s = scale(rhd, target_h)

    font      = get_font(FONT_SIZE)
    title_font = get_font(TITLE_FONT_SIZE)

    # Canvas dimensions
    total_w = PADDING + lhd_s.width + GAP + rhd_s.width + PADDING
    total_h = TITLE_H + PADDING + target_h + LABEL_H + PADDING

    canvas = Image.new("RGB", (total_w, total_h), (245, 245, 245))
    draw = ImageDraw.Draw(canvas)

    # ── Title ────────────────────────────────────────────────────────────
    bbox = draw.textbbox((0, 0), car_name, font=title_font)
    tw   = bbox[2] - bbox[0]
    draw.text(((total_w - tw) // 2, (TITLE_H - (bbox[3] - bbox[1])) // 2),
              car_name, fill=(40, 40, 40), font=title_font)

    y_img = TITLE_H + PADDING

    # ── Left panel (LHD) ─────────────────────────────────────────────────
    x_left = PADDING
    canvas.paste(lhd_s, (x_left, y_img))

    # Label bar
    draw.rectangle(
        [x_left, y_img + target_h, x_left + lhd_s.width, y_img + target_h + LABEL_H],
        fill=LEFT_BG,
    )
    bbox_l = draw.textbbox((0, 0), LEFT_LABEL, font=font)
    tw_l   = bbox_l[2] - bbox_l[0]
    th_l   = bbox_l[3] - bbox_l[1]
    draw.text(
        (x_left + (lhd_s.width - tw_l) // 2, y_img + target_h + (LABEL_H - th_l) // 2),
        LEFT_LABEL, fill=LABEL_FG, font=font,
    )

    # ── Right panel (RHD) ────────────────────────────────────────────────
    x_right = PADDING + lhd_s.width + GAP
    canvas.paste(rhd_s, (x_right, y_img))

    draw.rectangle(
        [x_right, y_img + target_h, x_right + rhd_s.width, y_img + target_h + LABEL_H],
        fill=RIGHT_BG,
    )
    bbox_r = draw.textbbox((0, 0), RIGHT_LABEL, font=font)
    tw_r   = bbox_r[2] - bbox_r[0]
    th_r   = bbox_r[3] - bbox_r[1]
    draw.text(
        (x_right + (rhd_s.width - tw_r) // 2, y_img + target_h + (LABEL_H - th_r) // 2),
        RIGHT_LABEL, fill=LABEL_FG, font=font,
    )

    # ── Thin divider line between panels ────────────────────────────────
    mid_x = PADDING + lhd_s.width
    draw.rectangle([mid_x, y_img, mid_x + GAP, y_img + target_h], fill=(180, 180, 180))

    canvas.save(out_path)
    logger.info("Saved → %s  (%dx%d)", out_path.name, total_w, total_h)


def main():
    parser = argparse.ArgumentParser(
        description="Build LHD vs RHD side-by-side comparison images for all CARAV dashboards."
    )
    parser.add_argument(
        "--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR,
        help=f"Root directory to search (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--filter", metavar="SUBSTRING", default=None,
        help="Only process folders whose name contains this substring (case-insensitive)",
    )
    parser.add_argument(
        "--height", type=int, default=TARGET_H,
        help=f"Panel image height in pixels (default: {TARGET_H})",
    )
    args = parser.parse_args()

    root: Path = args.output_dir

    folders = sorted(
        d for d in root.iterdir()
        if d.is_dir()
        and (d / LHD_FILE).exists()
        and (d / RHD_FILE).exists()
    )

    if not folders:
        logger.error("No folders with both %s and %s found under %s", LHD_FILE, RHD_FILE, root)
        sys.exit(1)

    if args.filter:
        folders = [f for f in folders if args.filter.lower() in f.name.lower()]
        if not folders:
            logger.error("No folders match filter '%s'", args.filter)
            sys.exit(1)

    logger.info("Building comparisons for %d folder(s):", len(folders))
    for f in folders:
        logger.info("  %s", f.name)

    ok, fail = 0, 0
    for folder in folders:
        car_name  = folder_to_car_name(folder.name)
        out_path  = folder / OUT_FILE
        try:
            build_comparison(
                folder / LHD_FILE,
                folder / RHD_FILE,
                car_name,
                out_path,
                args.height,
            )
            ok += 1
        except Exception as exc:
            logger.error("Failed for %s: %s", folder.name, exc)
            fail += 1

    logger.info("Done — %d saved, %d failed.", ok, fail)
    if fail:
        sys.exit(1)


if __name__ == "__main__":
    main()
