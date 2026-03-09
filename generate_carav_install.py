"""
CARAV Installation Image Generator
===================================
Takes two CARAV product images and generates two AI-composed images using
the OpenAI gpt-image-1 API:

  Image 1 — The vehicle dashboard with the trim/fascia frame installed,
            but NO radio placed in it yet (empty opening).

  Image 2 — The same dashboard + trim, now with the radio/head-unit placed
            inside the trim frame.

Source images (from scrape_carav.py):
  <part>_product.png  — left half = trim frame, right half = dashboard
  <part>_fitment.png  — the radio/head-unit to be placed in the trim

Usage:
  python generate_carav_install.py 11-039
  python generate_carav_install.py 11-039 --images-dir carav_images --output-dir carav_output
  python generate_carav_install.py 11-039 --method responses
  python generate_carav_install.py 11-039 --dry-run

Environment:
  Set OPENAI_API_KEY in your environment or in a .env file.
"""

import argparse
import base64
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    from openai import OpenAI
except ImportError:
    print("ERROR: openai package not installed.  Run: pip install openai")
    sys.exit(1)

try:
    from PIL import Image
except ImportError:
    print("ERROR: Pillow package not installed.  Run: pip install Pillow")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ─── Configuration ──────────────────────────────────────────────────────
IMAGE_MODEL = "gpt-image-1"
OUTPUT_SIZE = "1536x1024"  # landscape – good for dashboards

DEFAULT_IMAGES_DIR = Path(__file__).parent / "carav_images"
DEFAULT_OUTPUT_DIR = Path(__file__).parent / "carav_output"


# ─── Helpers ────────────────────────────────────────────────────────────
def load_env():
    """Load .env file if present."""
    env_file = Path(__file__).parent / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def get_client() -> OpenAI:
    """Initialize OpenAI client."""
    load_env()
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        logger.error("OPENAI_API_KEY not set. Set it in your environment or .env file.")
        sys.exit(1)
    return OpenAI(api_key=api_key)


def encode_image_b64(image_path: Path) -> str:
    return base64.standard_b64encode(image_path.read_bytes()).decode("utf-8")


# ─── Image splitting ───────────────────────────────────────────────────
def split_product_image(product_path: Path, output_dir: Path):
    """
    Split the CARAV product image into two halves:
      left  → trim/fascia frame
      right → vehicle dashboard
    Returns (trim_path, dashboard_path).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    img = Image.open(product_path)
    w, h = img.size
    split_x = int(w * 0.55)  # trim is the left 55%

    trim_img = img.crop((0, 0, split_x, h))
    dash_img = img.crop((split_x, 0, w, h))

    stem = product_path.stem  # e.g. "11-039_product"
    trim_path = output_dir / f"{stem}_trim_half.png"
    dash_path = output_dir / f"{stem}_dashboard_half.png"

    trim_img.save(trim_path)
    dash_img.save(dash_path)

    logger.info("Split product image → trim (%dx%d) + dashboard (%dx%d)",
                trim_img.width, trim_img.height, dash_img.width, dash_img.height)
    return trim_path, dash_path


# ─── Prompt builders ───────────────────────────────────────────────────
PROMPT_IMAGE1 = (
    "I am providing two images:\n"
    "1. A reference photo of a specific vehicle dashboard interior.\n"
    "2. A black aftermarket trim/fascia frame that fits the radio slot.\n\n"
    "CRITICAL RULES:\n"
    "- The generated image must depict the EXACT SAME dashboard as the reference photo. "
    "Match the same car model, same dashboard shape, same materials, same colors, "
    "same air vents, same buttons, same climate controls, and same camera angle/perspective. "
    "Do NOT change the car or dashboard design.\n"
    "- This is a RIGHT-HAND DRIVE vehicle. However, if the reference photo does not show "
    "a steering wheel or any indication of driving side, do NOT add a steering wheel "
    "or any driving-side elements that are not visible in the reference. Only reproduce "
    "exactly what is shown in the reference photo.\n"
    "- Insert the trim frame from image 2 neatly into the factory radio slot opening "
    "so it sits flush with the surrounding dashboard surface.\n"
    "- The opening inside the trim frame must be EMPTY — no radio or screen, "
    "just the black rectangular opening of the trim frame.\n"
    "- Keep the same framing, angle, and perspective as the reference photo.\n"
    "- Photorealistic professional product photograph quality."
)

PROMPT_IMAGE2 = (
    "I am providing two images:\n"
    "1. A vehicle dashboard with an aftermarket trim/fascia frame already installed "
    "(there is an empty black opening where a radio will go).\n"
    "2. A radio/head-unit that must be placed inside the trim frame opening.\n\n"
    "CRITICAL RULES:\n"
    "- The generated image must depict the EXACT SAME dashboard as image 1. "
    "Keep the identical car model, dashboard shape, materials, colors, air vents, "
    "buttons, climate controls, and camera angle/perspective. "
    "Do NOT change the car or dashboard design.\n"
    "- This is a RIGHT-HAND DRIVE vehicle. However, do NOT add a steering wheel "
    "or any driving-side elements that are not already visible in image 1. "
    "Only reproduce exactly what is shown.\n"
    "- Place the radio/head-unit from image 2 neatly inside the trim frame opening "
    "so it sits flush, as if professionally installed.\n"
    "- Keep the same framing, angle, and perspective as image 1.\n"
    "- Photorealistic professional product photograph quality."
)


# ─── Generation: images.edit API ────────────────────────────────────────
def generate_via_edit(client: OpenAI, image_paths: list[Path], prompt: str) -> bytes | None:
    """Use gpt-image-1 images.edit to produce an image from reference images + prompt."""
    handles = [open(p, "rb") for p in image_paths]
    try:
        result = client.images.edit(
            model=IMAGE_MODEL,
            image=handles,
            prompt=prompt,
            n=1,
            size=OUTPUT_SIZE,
        )
    finally:
        for h in handles:
            h.close()

    if result.data and len(result.data) > 0:
        entry = result.data[0]
        if hasattr(entry, "b64_json") and entry.b64_json:
            return base64.b64decode(entry.b64_json)
        if hasattr(entry, "url") and entry.url:
            import requests as _req
            return _req.get(entry.url, timeout=60).content
    logger.error("No image data in images.edit response")
    return None


# ─── Generation: responses API fallback ─────────────────────────────────
def generate_via_responses(client: OpenAI, image_paths: list[Path], prompt: str) -> bytes | None:
    """Use the Responses API with image_generation tool as a fallback."""
    parts: list[dict] = [{"type": "input_text", "text": prompt}]
    for p in image_paths:
        mime = "image/png" if p.suffix.lower() == ".png" else "image/jpeg"
        b64 = encode_image_b64(p)
        parts.append({"type": "input_image", "image_url": f"data:{mime};base64,{b64}"})

    result = client.responses.create(
        model="gpt-4o",
        input=[{"role": "user", "content": parts}],
        tools=[{"type": "image_generation", "size": OUTPUT_SIZE, "quality": "high"}],
    )

    for item in result.output:
        if hasattr(item, "result") and item.type == "image_generation_call":
            return base64.b64decode(item.result)
    logger.error("No image data in responses API output")
    return None


def generate_image(client: OpenAI, image_paths: list[Path], prompt: str, method: str) -> bytes | None:
    """Dispatch to the chosen generation method."""
    try:
        if method == "edit":
            return generate_via_edit(client, image_paths, prompt)
        else:
            return generate_via_responses(client, image_paths, prompt)
    except Exception as e:
        logger.error("Generation failed (%s): %s", method, e)
        logger.exception(e)
        return None


# ─── Main workflow ──────────────────────────────────────────────────────
def run(
    part_number: str,
    images_dir: Path = DEFAULT_IMAGES_DIR,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    method: str = "edit",
    dry_run: bool = False,
):
    """
    Full pipeline: split, generate image 1, then generate image 2.
    Returns list of saved output paths.
    """
    # Each part has its own subfolder
    images_dir = images_dir / part_number
    output_dir = output_dir / part_number

    product_path = images_dir / f"{part_number}_product.png"
    fitment_path = images_dir / f"{part_number}_fitment.png"

    for p in (product_path, fitment_path):
        if not p.exists():
            logger.error("Required image not found: %s", p)
            sys.exit(1)

    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # ── Step 1: Split product image ─────────────────────────────────────
    logger.info("Step 1 — Splitting product image into trim + dashboard halves")
    trim_path, dash_path = split_product_image(product_path, output_dir)

    if dry_run:
        logger.info("[DRY RUN] Would generate Image 1 (dashboard + trim, no radio)")
        logger.info("[DRY RUN]   inputs: %s, %s", dash_path.name, trim_path.name)
        logger.info("[DRY RUN] Would generate Image 2 (Image 1 + radio from fitment)")
        logger.info("[DRY RUN]   inputs: Image1, %s", fitment_path.name)
        logger.info("[DRY RUN] Done — no API calls made.")
        return []

    client = get_client()
    saved: list[Path] = []

    # ── Step 2: Generate Image 1 — dashboard + trim, empty ──────────────
    logger.info("Step 2 — Generating Image 1 (trim on dashboard, no radio) …")
    t0 = time.time()
    img1_bytes = generate_image(client, [dash_path, trim_path], PROMPT_IMAGE1, method)
    logger.info("  Image 1 API call took %.1fs", time.time() - t0)

    if img1_bytes is None:
        logger.error("Image 1 generation failed — aborting.")
        sys.exit(1)

    img1_path = output_dir / f"{part_number}_step1_trim_only_{timestamp}.png"
    img1_path.write_bytes(img1_bytes)
    saved.append(img1_path)
    logger.info("  Saved Image 1 → %s (%d bytes)", img1_path, len(img1_bytes))

    # ── Step 3: Generate Image 2 — dashboard + trim + radio ─────────────
    logger.info("Step 3 — Generating Image 2 (trim + radio installed) …")
    t0 = time.time()
    img2_bytes = generate_image(client, [img1_path, fitment_path], PROMPT_IMAGE2, method)
    logger.info("  Image 2 API call took %.1fs", time.time() - t0)

    if img2_bytes is None:
        logger.error("Image 2 generation failed.")
        sys.exit(1)

    img2_path = output_dir / f"{part_number}_step2_with_radio_{timestamp}.png"
    img2_path.write_bytes(img2_bytes)
    saved.append(img2_path)
    logger.info("  Saved Image 2 → %s (%d bytes)", img2_path, len(img2_bytes))

    logger.info("Done — %d images generated in %s/", len(saved), output_dir)
    return saved


# ─── CLI ────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Generate CARAV trim installation images via OpenAI",
    )
    parser.add_argument(
        "part_number",
        help="CARAV part number, e.g. 11-039",
    )
    parser.add_argument(
        "--images-dir",
        type=Path,
        default=DEFAULT_IMAGES_DIR,
        help=f"Directory with scraped CARAV images (default: {DEFAULT_IMAGES_DIR})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Directory to write generated images (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--method",
        choices=["edit", "responses"],
        default="edit",
        help="API method: 'edit' (images.edit, default) or 'responses' (gpt-4o vision)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate inputs and show plan, without calling the API",
    )
    args = parser.parse_args()

    logger.info("=== CARAV Install Generator — %s ===", args.part_number)
    results = run(
        part_number=args.part_number,
        images_dir=args.images_dir,
        output_dir=args.output_dir,
        method=args.method,
        dry_run=args.dry_run,
    )

    print("\n--- Results ---")
    if results:
        for p in results:
            print(f"  {p}")
    else:
        print("  No images generated (dry-run or failure).")


if __name__ == "__main__":
    main()
