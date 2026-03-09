"""
CARAV Full Pipeline
===================
One command to fetch, split, generate, and compile CARAV trim installation images.

Modes:
  --fetch-only   Scrape images from carav-parts.com and split the product image
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
from generate_carav_install import split_product_image, generate_image, get_client, PROMPT_IMAGE1, PROMPT_IMAGE2

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
    part_number: str,
    trim_path: Path,
    dash_path: Path,
    step1_path: Path | None,
    step2_path: Path | None,
    output_dir: Path,
) -> Path:
    """
    Build a labelled composite image from all available images.
    If step1/step2 are None (fetch-only mode), builds a 1×2 composite.
    Otherwise builds a 2×2 grid.
    """
    # Collect (path, label) pairs
    panels: list[tuple[Path, str]] = [
        (trim_path, "Trim Frame"),
        (dash_path, "Dashboard"),
    ]
    if step1_path and step1_path.exists():
        panels.append((step1_path, "Step 1: Trim Installed"))
    if step2_path and step2_path.exists():
        panels.append((step2_path, "Step 2: Trim + Screen Installed"))

    PADDING = 20
    LABEL_H = 40
    FONT_SIZE = 24
    TARGET_H = 500

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
    canvas_h = PADDING + rows * (cell_h + PADDING)

    canvas = Image.new("RGB", (canvas_w, canvas_h), "white")
    draw = ImageDraw.Draw(canvas)

    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", FONT_SIZE
        )
    except Exception:
        font = ImageFont.load_default()

    for idx, (img, label) in enumerate(scaled):
        r = idx // cols
        c = idx % cols
        x = PADDING + sum(col_widths[j] + PADDING for j in range(c))
        y = PADDING + r * (cell_h + PADDING)

        # Centre image in its column cell
        img_x = x + (col_widths[c] - img.width) // 2
        canvas.paste(img, (img_x, y))

        # Label
        bbox = draw.textbbox((0, 0), label, font=font)
        tw = bbox[2] - bbox[0]
        label_x = x + (col_widths[c] - tw) // 2
        label_y = y + TARGET_H + 5
        draw.text((label_x, label_y), label, fill="black", font=font)

    out_path = output_dir / f"{part_number}_composite.png"
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
):
    """
    Full or partial pipeline.

    fetch_only=True  → scrape + split + composite (no OpenAI)
    fetch_only=False → scrape + split + generate (×2) + composite
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # ── 1. Fetch images from carav-parts.com ────────────────────────────
    logger.info("=" * 60)
    logger.info("CARAV Pipeline — %s  (mode: %s)", part_number, "fetch-only" if fetch_only else "full")
    logger.info("=" * 60)

    logger.info("Phase 1 — Fetching images from carav-parts.com …")
    downloaded = scrape_part(part_number, output_dir=images_dir)

    if not downloaded:
        logger.error("No images found for part %s — aborting.", part_number)
        sys.exit(1)

    # scrape_part saves into images_dir/<part_number>/
    part_images_dir = images_dir / part_number
    product_path = part_images_dir / f"{part_number}_product.png"
    fitment_path = part_images_dir / f"{part_number}_fitment.png"

    for p in (product_path, fitment_path):
        if not p.exists():
            logger.error("Expected file not found after scrape: %s", p)
            sys.exit(1)

    # ── 2. Split product image ──────────────────────────────────────────
    # Output goes into output_dir/<part_number>/
    part_output_dir = output_dir / part_number
    part_output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Phase 2 — Splitting product image into trim + dashboard halves …")
    trim_path, dash_path = split_product_image(product_path, part_output_dir)

    step1_path = None
    step2_path = None

    # ── 3. Generate AI images (unless --fetch-only) ─────────────────────
    if not fetch_only:
        client = get_client()

        logger.info("Phase 3a — Generating Image 1 (trim on dashboard, no radio) …")
        t0 = time.time()
        img1_bytes = generate_image(client, [dash_path, trim_path], PROMPT_IMAGE1, method)
        logger.info("  API call took %.1fs", time.time() - t0)

        if img1_bytes is None:
            logger.error("Image 1 generation failed — aborting.")
            sys.exit(1)

        step1_path = part_output_dir / f"{part_number}_step1_trim_only_{timestamp}.png"
        step1_path.write_bytes(img1_bytes)
        logger.info("  Saved → %s (%d bytes)", step1_path, len(img1_bytes))

        logger.info("Phase 3b — Generating Image 2 (trim + radio installed) …")
        t0 = time.time()
        img2_bytes = generate_image(client, [step1_path, fitment_path], PROMPT_IMAGE2, method)
        logger.info("  API call took %.1fs", time.time() - t0)

        if img2_bytes is None:
            logger.error("Image 2 generation failed.")
            sys.exit(1)

        step2_path = part_output_dir / f"{part_number}_step2_with_radio_{timestamp}.png"
        step2_path.write_bytes(img2_bytes)
        logger.info("  Saved → %s (%d bytes)", step2_path, len(img2_bytes))
    else:
        logger.info("Phase 3 — Skipped (fetch-only mode, no AI generation)")

    # ── 4. Compile composite ────────────────────────────────────────────
    logger.info("Phase 4 — Building composite image …")
    composite = build_composite(
        part_number, trim_path, dash_path, step1_path, step2_path, part_output_dir,
    )

    # ── Summary ─────────────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info("Pipeline complete for %s", part_number)
    logger.info("=" * 60)

    print("\n--- Output Files ---")
    for f in sorted(part_output_dir.glob(f"{part_number}*")):
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
    )


if __name__ == "__main__":
    main()
