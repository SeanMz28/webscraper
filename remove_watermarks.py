"""
CARAV Image Watermark Remover
=============================
Removes watermarks and CARAV labels from images inside the carav_images/
or carav_output/ folders using the OpenAI gpt-image-1 images.edit API.

For each matched image it:
  1. Sends the image to gpt-image-1 with a prompt asking it to cleanly
     remove any watermarks, logos, and CARAV text overlays.
  2. Saves the cleaned image back (overwriting the original by default,
     or to a separate folder with --output-dir).

Usage:
  # Process all *_fitment* images in carav_images/ (default)
  python remove_watermarks.py

  # Process all *_product_trim_half* images in carav_output/
  python remove_watermarks.py --images-dir carav_output --pattern "*_product_trim_half*"

  python remove_watermarks.py --part 22-813           # process only one part number
  python remove_watermarks.py --dry-run               # list files without calling the API
  python remove_watermarks.py --method responses      # use the Responses API instead of images.edit

Environment:
  Set OPENAI_API_KEY in your environment or in a .env file.
"""

import argparse
import base64
import logging
import os
import sys
import time
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
OUTPUT_SIZE = "1536x1024"   # landscape – matches generate_carav_install.py

DEFAULT_IMAGES_DIR = Path(__file__).parent / "carav_images"


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


DEFAULT_PATTERN = "*_fitment*"


def find_target_images(
    images_dir: Path,
    pattern: str = DEFAULT_PATTERN,
    part_number: str | None = None,
) -> list[Path]:
    """Return sorted list of images matching *pattern*, optionally filtered by part number."""
    if part_number:
        part_dir = images_dir / part_number
        if not part_dir.is_dir():
            logger.error("Part directory not found: %s", part_dir)
            return []
        candidates = sorted(part_dir.glob(pattern))
    else:
        candidates = sorted(images_dir.rglob(pattern))

    images = [
        p for p in candidates
        if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")
        and ".bak" not in p.suffixes
    ]
    logger.info("Found %d image(s) matching '%s'", len(images), pattern)
    return images


# ─── Prompt ─────────────────────────────────────────────────────────────
WATERMARK_REMOVAL_PROMPT = (
    "This is a product photo of a car radio/head-unit or a dashboard fitment image.\n\n"
    "TASK: Remove ALL watermarks, overlay text, and logo stamps from the image. "
    "Specifically:\n"
    "- Remove any 'CARAV' text or logo overlays.\n"
    "- Remove any website URLs or domain watermarks.\n"
    "- Remove any semi-transparent text stamps.\n"
    "- Remove any diagonal or tiled watermark patterns.\n\n"
    "CRITICAL RULES:\n"
    "- Keep the EXACT same product, angle, framing, colors, and background.\n"
    "- Do NOT change or alter the actual product shown in any way.\n"
    "- The cleaned area where watermarks were should be naturally filled in "
    "to match the surrounding image content.\n"
    "- Output a clean, professional product photograph with no text overlays.\n"
    "- Maintain the original image quality and resolution."
)


# ─── Generation: images.edit API ────────────────────────────────────────
def remove_watermark_via_edit(client: OpenAI, image_path: Path) -> bytes | None:
    """Use gpt-image-1 images.edit to remove watermarks from a single image."""
    with open(image_path, "rb") as fh:
        try:
            result = client.images.edit(
                model=IMAGE_MODEL,
                image=[fh],
                prompt=WATERMARK_REMOVAL_PROMPT,
                n=1,
                size=OUTPUT_SIZE,
            )
        except Exception as e:
            logger.error("images.edit failed for %s: %s", image_path.name, e)
            return None

    if result.data and len(result.data) > 0:
        entry = result.data[0]
        if hasattr(entry, "b64_json") and entry.b64_json:
            return base64.b64decode(entry.b64_json)
        if hasattr(entry, "url") and entry.url:
            import requests as _req
            return _req.get(entry.url, timeout=60).content
    logger.error("No image data in images.edit response for %s", image_path.name)
    return None


# ─── Generation: responses API fallback ─────────────────────────────────
def remove_watermark_via_responses(client: OpenAI, image_path: Path) -> bytes | None:
    """Use the Responses API with image_generation tool as a fallback."""
    mime = "image/png" if image_path.suffix.lower() == ".png" else "image/jpeg"
    b64 = encode_image_b64(image_path)
    parts = [
        {"type": "input_text", "text": WATERMARK_REMOVAL_PROMPT},
        {"type": "input_image", "image_url": f"data:{mime};base64,{b64}"},
    ]
    try:
        result = client.responses.create(
            model="gpt-4o",
            input=[{"role": "user", "content": parts}],
            tools=[{"type": "image_generation", "size": OUTPUT_SIZE, "quality": "high"}],
        )
    except Exception as e:
        logger.error("Responses API failed for %s: %s", image_path.name, e)
        return None

    for item in result.output:
        if hasattr(item, "result") and item.type == "image_generation_call":
            return base64.b64decode(item.result)
    logger.error("No image data in responses API output for %s", image_path.name)
    return None


def remove_watermark(client: OpenAI, image_path: Path, method: str) -> bytes | None:
    """Dispatch to the chosen generation method."""
    if method == "edit":
        return remove_watermark_via_edit(client, image_path)
    else:
        return remove_watermark_via_responses(client, image_path)


# ─── Main workflow ──────────────────────────────────────────────────────
def run(
    images_dir: Path = DEFAULT_IMAGES_DIR,
    output_dir: Path | None = None,
    part_number: str | None = None,
    pattern: str = DEFAULT_PATTERN,
    method: str = "edit",
    dry_run: bool = False,
):
    """
    Process all matching images: remove watermarks and save cleaned versions.
    If output_dir is None the originals are overwritten (a backup is kept with .bak suffix).
    Returns list of saved output paths.
    """
    fitment_images = find_target_images(images_dir, pattern, part_number)
    if not fitment_images:
        logger.warning("No fitment images found. Nothing to do.")
        return []

    if dry_run:
        logger.info("DRY RUN — would process the following files:")
        for p in fitment_images:
            logger.info("  %s", p)
        return []

    client = get_client()
    saved: list[Path] = []

    for idx, img_path in enumerate(fitment_images, 1):
        logger.info("[%d/%d] Processing: %s", idx, len(fitment_images), img_path)
        t0 = time.time()

        image_bytes = remove_watermark(client, img_path, method)
        if not image_bytes:
            logger.warning("Skipping %s — generation returned no data.", img_path.name)
            continue

        elapsed = time.time() - t0
        logger.info("  Generated in %.1fs (%d bytes)", elapsed, len(image_bytes))

        # Determine output path
        if output_dir:
            # Mirror the subfolder structure
            rel = img_path.relative_to(images_dir)
            dest = output_dir / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
        else:
            # Overwrite in-place — keep a backup
            backup = img_path.with_suffix(img_path.suffix + ".bak")
            if not backup.exists():
                img_path.rename(backup)
                logger.info("  Backup saved: %s", backup.name)
            else:
                logger.info("  Backup already exists: %s", backup.name)
            dest = img_path

        dest.write_bytes(image_bytes)
        logger.info("  Saved: %s", dest)
        saved.append(dest)

    logger.info("Done. %d / %d images cleaned.", len(saved), len(fitment_images))
    return saved


# ─── CLI ────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Remove watermarks and CARAV labels from images using OpenAI gpt-image-1.",
    )
    parser.add_argument(
        "--images-dir",
        type=Path,
        default=DEFAULT_IMAGES_DIR,
        help="Root directory containing part-number sub-folders with images (default: carav_images/)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Save cleaned images here instead of overwriting originals. "
             "Directory structure is mirrored. If omitted, originals are overwritten (backups kept as .bak).",
    )
    parser.add_argument(
        "--part",
        type=str,
        default=None,
        help="Only process a single part number (e.g. 22-813).",
    )
    parser.add_argument(
        "--method",
        choices=["edit", "responses"],
        default="edit",
        help="OpenAI API method: 'edit' (images.edit, default) or 'responses' (gpt-4o vision).",
    )
    parser.add_argument(
        "--pattern",
        type=str,
        default=DEFAULT_PATTERN,
        help="Glob pattern to match target image filenames (default: '*_fitment*'). "
             "Use '*_product_trim_half*' for trim images in carav_output/.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List files that would be processed without calling the API.",
    )
    args = parser.parse_args()

    run(
        images_dir=args.images_dir,
        output_dir=args.output_dir,
        part_number=args.part,
        pattern=args.pattern,
        method=args.method,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    main()
