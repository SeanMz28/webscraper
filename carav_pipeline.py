"""
CARAV Full Pipeline
===================
One command to fetch, split, generate, and compile CARAV trim installation images.

The pipeline uses a fixed radio/screen image (starsound/car_radio_1_enh.png)
instead of the fitment image from carav-parts.com.

Generation steps:
  Image 1 — Trim + Screen: the trim frame with the radio/screen inserted.
  Image 2 — Trim & Screen Installed: the assembled unit fitted into the dashboard.

Modes:
  --fetch-only   Scrape the product image from carav-parts.com and split it
                 into trim + dashboard halves. No OpenAI calls.

  (default)      Full pipeline: fetch → split → generate (2 AI images) → compile
                 a 2×2 composite with labels.

Usage:
  # Full pipeline
  python carav_pipeline.py 11-039

  # Fetch + split only (no AI generation)
  python carav_pipeline.py 11-039 --fetch-only

  # Use responses API instead of images.edit
  python carav_pipeline.py 11-039 --method responses

  # Custom radio image
  python carav_pipeline.py 11-039 --radio path/to/radio.png

Environment:
  Set OPENAI_API_KEY in your environment or in a .env file (needed for full pipeline).
"""

import argparse
import logging
import sys
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

# ─── Import the existing modules ───────────────────────────────────────
from scrape_carav import scrape_part
from generate_carav_install import (
    split_product_image, generate_image, get_client,
    PROMPT_IMAGE1, PROMPT_IMAGE2, DEFAULT_RADIO_PATH,
)
from remove_watermarks import remove_watermark

import time
from datetime import datetime

# ─── Defaults ───────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
DEFAULT_IMAGES_DIR = SCRIPT_DIR / "carav_images"
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "carav_output"

IMAGE_MODEL = "gpt-image-1"
OUTPUT_SIZE = "1536x1024"


# ─── Composite builder ─────────────────────────────────────────────────
def build_composite(
    trim_path: Path,
    dash_path: Path,
    step1_path: Path | None,
    step2_path: Path | None,
    output_dir: Path,
    car_name: str | None = None,
    folder_name: str | None = None,
) -> Path:
    """
    Build a labelled composite image from all available images.
    If step1/step2 are None (fetch-only mode), builds a 1×2 composite.
    If car_name is given, it is drawn as a title at the top of the composite.
    """
    # Collect (path, label) pairs
    panels: list[tuple[Path, str]] = [
        (trim_path, "Trim Frame"),
        (dash_path, "Dashboard"),
    ]
    if step1_path and step1_path.exists():
        panels.append((step1_path, "Trim + Screen"))
    if step2_path and step2_path.exists():
        panels.append((step2_path, "Trim & Screen Installed"))

    PADDING = 20
    LABEL_H = 40
    FONT_SIZE = 24
    TARGET_H = 500
    TITLE_H = 60 if car_name else 0
    TITLE_FONT_SIZE = 32

    # Load and scale
    scaled: list[tuple[Image.Image, str]] = []
    for p, label in panels:
        img = Image.open(p)
        ratio = TARGET_H / img.height
        new_w = int(img.width * ratio)
        scaled.append((img.resize((new_w, TARGET_H), Image.LANCZOS), label))

    # Determine grid layout
    n = len(scaled)
    cols = 2
    rows = (n + 1) // 2  # 1 row for 1-2 images, 2 rows for 3-4

    # Compute column widths
    col_widths = [0] * cols
    for i, (img, _) in enumerate(scaled):
        c = i % cols
        col_widths[c] = max(col_widths[c], img.width)

    cell_h = TARGET_H + LABEL_H
    canvas_w = PADDING + sum(w + PADDING for w in col_widths)
    canvas_h = TITLE_H + PADDING + rows * (cell_h + PADDING)

    canvas = Image.new("RGB", (canvas_w, canvas_h), "white")
    draw = ImageDraw.Draw(canvas)

    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", FONT_SIZE
        )
    except Exception:
        font = ImageFont.load_default()

    # Draw car name title at the top
    if car_name:
        try:
            title_font = ImageFont.truetype(
                "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", TITLE_FONT_SIZE
            )
        except Exception:
            title_font = font
        bbox_t = draw.textbbox((0, 0), car_name, font=title_font)
        tw_t = bbox_t[2] - bbox_t[0]
        title_x = (canvas_w - tw_t) // 2
        title_y = PADDING
        draw.text((title_x, title_y), car_name, fill="#333333", font=title_font)

    y_offset = TITLE_H  # shift panels down when title is present

    for idx, (img, label) in enumerate(scaled):
        r = idx // cols
        c = idx % cols
        x = PADDING + sum(col_widths[j] + PADDING for j in range(c))
        y = y_offset + PADDING + r * (cell_h + PADDING)

        # Centre image in its column cell
        img_x = x + (col_widths[c] - img.width) // 2
        canvas.paste(img, (img_x, y))

        # Label
        bbox = draw.textbbox((0, 0), label, font=font)
        tw = bbox[2] - bbox[0]
        label_x = x + (col_widths[c] - tw) // 2
        label_y = y + TARGET_H + 5
        draw.text((label_x, label_y), label, fill="black", font=font)

    name = folder_name or "composite"
    out_path = output_dir / f"{name}_composite.png"
    canvas.save(out_path)
    logger.info("Composite saved → %s (%dx%d)", out_path, canvas_w, canvas_h)
    return out_path


# ─── Pipeline ───────────────────────────────────────────────────────────
def run_pipeline(
    part_number: str,
    fetch_only: bool = False,
    method: str = "edit",
    images_dir: Path = DEFAULT_IMAGES_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    radio_path: Path = DEFAULT_RADIO_PATH,
):
    """
    Full or partial pipeline.

    fetch_only=True  → scrape + split + composite (no OpenAI)
    fetch_only=False → scrape + split + generate (×2) + composite
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # ── 1. Fetch product image from carav-parts.com ─────────────────────
    logger.info("=" * 60)
    logger.info("CARAV Pipeline — %s  (mode: %s)", part_number, "fetch-only" if fetch_only else "full")
    logger.info("=" * 60)

    logger.info("Phase 1 — Fetching product image from carav-parts.com …")
    downloaded = scrape_part(part_number, output_dir=images_dir)

    if not downloaded:
        logger.error("No images found for part %s — aborting.", part_number)
        sys.exit(1)

    # Extract car name and folder name from scrape result
    car_name = downloaded.get("car_name")
    folder_name = downloaded.get("folder_name", part_number)

    part_images_dir = images_dir / folder_name
    product_path = part_images_dir / "product.png"

    if not product_path.exists():
        logger.error("Expected product image not found after scrape: %s", product_path)
        sys.exit(1)

    if not fetch_only and not radio_path.exists():
        logger.error("Radio/screen image not found: %s", radio_path)
        sys.exit(1)

    logger.info("  Car name: %s", car_name or "(not available)")
    logger.info("  Folder:   %s", folder_name)

    # ── 2. Split product image ──────────────────────────────────────────
    part_output_dir = output_dir / folder_name
    part_output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Phase 2 — Splitting product image into trim + dashboard halves …")
    trim_path, dash_path = split_product_image(product_path, part_output_dir)

    step1_path = None
    step2_path = None

    # ── 3. Remove watermarks from split halves ───────────────────────
    if not fetch_only:
        client = get_client()

        logger.info("Phase 2b — Removing watermarks from trim half …")
        t0 = time.time()
        clean_bytes = remove_watermark(client, trim_path, method)
        if clean_bytes:
            backup = trim_path.with_suffix(trim_path.suffix + ".bak")
            if not backup.exists():
                import shutil
                shutil.copy2(trim_path, backup)
            trim_path.write_bytes(clean_bytes)
            logger.info("  Cleaned %s in %.1fs (%d bytes)", trim_path.name, time.time() - t0, len(clean_bytes))
        else:
            logger.warning("  Watermark removal failed for %s — proceeding with original", trim_path.name)

    # ── 4. Generate AI images (unless --fetch-only) ─────────────────────
    if not fetch_only:

        logger.info("Phase 4a — Generating Image 1 (trim + screen product shot) …")
        logger.info("  Radio/screen image: %s", radio_path)
        t0 = time.time()
        img1_bytes = generate_image(client, [trim_path, radio_path], PROMPT_IMAGE1, method)
        logger.info("  API call took %.1fs", time.time() - t0)

        if img1_bytes is None:
            logger.error("Image 1 generation failed — aborting.")
            sys.exit(1)

        step1_path = part_output_dir / f"step1_trim_and_screen_{timestamp}.png"
        step1_path.write_bytes(img1_bytes)
        logger.info("  Saved → %s (%d bytes)", step1_path, len(img1_bytes))

        logger.info("Phase 4b — Generating Image 2 (trim & screen installed in dashboard) …")
        t0 = time.time()
        img2_bytes = generate_image(client, [dash_path, step1_path], PROMPT_IMAGE2, method)
        logger.info("  API call took %.1fs", time.time() - t0)

        if img2_bytes is None:
            logger.error("Image 2 generation failed.")
            sys.exit(1)

        step2_path = part_output_dir / f"step2_installed_{timestamp}.png"
        step2_path.write_bytes(img2_bytes)
        logger.info("  Saved → %s (%d bytes)", step2_path, len(img2_bytes))
    else:
        logger.info("Phase 3/4 — Skipped (fetch-only mode, no AI generation)")

    # ── 4. Compile composite ────────────────────────────────────────────
    logger.info("Phase 4 — Building composite image …")
    composite = build_composite(
        trim_path, dash_path, step1_path, step2_path, part_output_dir,
        car_name=car_name, folder_name=folder_name,
    )

    # ── Summary ─────────────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("Pipeline complete for %s (%s)", part_number, car_name or folder_name)
    logger.info("=" * 60)

    print("\n--- Output Files ---")
    for f in sorted(part_output_dir.glob("*")):
        if f.is_file():
            size = f.stat().st_size
            print(f"  {f.name:55s}  {size:>10,} bytes")
    print(f"\nComposite → {composite}")
    return composite


# ─── CLI ────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="CARAV full pipeline: fetch → split → generate → compile",
    )
    parser.add_argument(
        "part_number",
        help="CARAV part number, e.g. 11-039 or 11-478",
    )
    parser.add_argument(
        "--fetch-only",
        action="store_true",
        help="Only fetch images and split — no AI generation (no OPENAI_API_KEY needed)",
    )
    parser.add_argument(
        "--method",
        choices=["edit", "responses"],
        default="edit",
        help="OpenAI API method: 'edit' (images.edit, default) or 'responses' (gpt-4o vision)",
    )
    parser.add_argument(
        "--radio",
        type=Path,
        default=DEFAULT_RADIO_PATH,
        help=f"Path to radio/screen image (default: {DEFAULT_RADIO_PATH})",
    )
    parser.add_argument(
        "--images-dir",
        type=Path,
        default=DEFAULT_IMAGES_DIR,
        help=f"Directory for scraped CARAV images (default: {DEFAULT_IMAGES_DIR})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory for output images (default: {DEFAULT_OUTPUT_DIR})",
    )

    args = parser.parse_args()

    run_pipeline(
        part_number=args.part_number,
        fetch_only=args.fetch_only,
        method=args.method,
        images_dir=args.images_dir,
        output_dir=args.output_dir,
        radio_path=args.radio,
    )


if __name__ == "__main__":
    main()
