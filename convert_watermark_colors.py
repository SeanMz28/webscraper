"""
Watermark Color Converter
=========================
Uses the OpenAI gpt-image-1 images.edit API to change the black parts of the
Digital StarSound watermark logo to white, producing a version suitable for
placement on dark backgrounds.

Default input:  starsound/watermark.png
Default output: starsound/watermark_white.png

Usage:
  python convert_watermark_colors.py
  python convert_watermark_colors.py --input starsound/watermark.png --output starsound/watermark_white.png

Environment:
  Set OPENAI_API_KEY in your environment or in a .env file.
"""

import argparse
import base64
import logging
import os
import sys
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
DEFAULT_INPUT = Path(__file__).parent / "starsound" / "watermark.png"
DEFAULT_OUTPUT = Path(__file__).parent / "starsound" / "watermark_white.png"

COLOR_CONVERSION_PROMPT = (
    "This is a logo image for 'Digital StarSound'.\n\n"
    "TASK: Change all BLACK colored areas in this logo to WHITE.\n\n"
    "SPECIFIC RULES:\n"
    "- Convert every black or near-black pixel (text, outlines, fills) to pure white.\n"
    "- Keep all RED areas exactly as they are — do NOT change the red color.\n"
    "- Preserve the transparent or white background exactly as-is.\n"
    "- Do NOT alter the shape, layout, size, or any other aspect of the logo.\n"
    "- The result should be identical to the input except that black has become white.\n"
    "- Maintain sharp, clean edges — do not blur or smooth the logo.\n"
    "- Output the image with a transparent background (PNG format)."
)


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
    load_env()
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        logger.error("OPENAI_API_KEY not set. Set it in your environment or .env file.")
        sys.exit(1)
    return OpenAI(api_key=api_key)


def ensure_png_rgba(image_path: Path) -> Path:
    """
    gpt-image-1 images.edit requires a PNG with an alpha channel.
    If the source file is not RGBA PNG, convert it and return the temp path.
    """
    with Image.open(image_path) as img:
        if image_path.suffix.lower() == ".png" and img.mode == "RGBA":
            return image_path  # already suitable

        rgba = img.convert("RGBA")
        tmp = image_path.with_suffix(".tmp_rgba.png")
        rgba.save(tmp)
        logger.info("Converted source to RGBA PNG: %s", tmp)
        return tmp


# ─── API call ───────────────────────────────────────────────────────────
def convert_colors_via_edit(client: OpenAI, image_path: Path) -> bytes | None:
    """
    Send the logo to gpt-image-1 images.edit and ask it to swap black → white.
    Returns raw PNG bytes on success, or None on failure.
    """
    rgba_path = ensure_png_rgba(image_path)
    try:
        with open(rgba_path, "rb") as fh:
            result = client.images.edit(
                model=IMAGE_MODEL,
                image=[fh],
                prompt=COLOR_CONVERSION_PROMPT,
                n=1,
                size="1024x1024",
            )
    except Exception as e:
        logger.error("images.edit failed: %s", e)
        return None
    finally:
        # Clean up temp file if we created one
        if rgba_path != image_path and rgba_path.exists():
            rgba_path.unlink()

    if result.data and len(result.data) > 0:
        entry = result.data[0]
        if hasattr(entry, "b64_json") and entry.b64_json:
            return base64.b64decode(entry.b64_json)
        if hasattr(entry, "url") and entry.url:
            import requests as _req
            return _req.get(entry.url, timeout=60).content

    logger.error("No image data returned by the API.")
    return None


# ─── Main ───────────────────────────────────────────────────────────────
def run(input_path: Path, output_path: Path) -> Path | None:
    if not input_path.exists():
        logger.error("Input image not found: %s", input_path)
        sys.exit(1)

    logger.info("Input : %s", input_path)
    logger.info("Output: %s", output_path)

    client = get_client()
    logger.info("Sending logo to OpenAI gpt-image-1 for color conversion…")

    image_bytes = convert_colors_via_edit(client, input_path)
    if not image_bytes:
        logger.error("Color conversion failed — no image data returned.")
        return None

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(image_bytes)
    logger.info("Saved white-logo version: %s", output_path)
    return output_path


def main():
    parser = argparse.ArgumentParser(
        description="Change black areas of the StarSound watermark logo to white using OpenAI gpt-image-1.",
    )
    parser.add_argument(
        "--input",
        type=Path,
        default=DEFAULT_INPUT,
        help=f"Path to the source watermark PNG (default: {DEFAULT_INPUT})",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"Path to save the converted logo (default: {DEFAULT_OUTPUT})",
    )
    args = parser.parse_args()
    run(args.input, args.output)


if __name__ == "__main__":
    main()
