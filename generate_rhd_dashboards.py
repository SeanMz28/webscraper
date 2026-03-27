"""
RHD Dashboard Generator
========================
For each sub-folder in carav_output/ that contains a product_dashboard_half.png,
send the image to the OpenAI gpt-image-1 images.edit API with a prompt that
converts the left-hand-drive (LHD) dashboard to right-hand-drive (RHD).

The result is saved as  product_dashboard_half_rhd.png  in the same folder.

Usage:
  # Process all 10 folders
  python generate_rhd_dashboards.py

  # Process one specific folder (partial match on folder name)
  python generate_rhd_dashboards.py --filter "TOYOTA_Corolla"

  # Use responses API instead of images.edit
  python generate_rhd_dashboards.py --method responses

  # Dry-run: list what would be processed without calling the API
  python generate_rhd_dashboards.py --dry-run

  # Skip folders that already have an RHD file
  python generate_rhd_dashboards.py --skip-existing

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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ─── Configuration ──────────────────────────────────────────────────────
IMAGE_MODEL = "gpt-image-1"
OUTPUT_SIZE = "1536x1024"  # landscape — matches the rest of the pipeline

SCRIPT_DIR = Path(__file__).parent
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "carav_output"
INPUT_FILENAME = "product_dashboard_half.png"
OUTPUT_FILENAME = "product_dashboard_half_rhd.png"

# Delay between API calls (seconds) to avoid rate-limit errors
API_DELAY_SECONDS = 3


# ─── Prompt ─────────────────────────────────────────────────────────────
def build_prompt(car_name: str) -> str:
    """
    Craft the image-edit prompt for a specific car model.
    The source image is the original LHD dashboard half scraped from carav-parts.com.
    """
    return (
        f"This is a photograph of the dashboard interior of a {car_name}.\n\n"
        "TASK: Redraw this exact dashboard as a RIGHT-HAND DRIVE (RHD) version.\n\n"
        "CRITICAL RULES:\n"
        "- This must be the SAME section of the same car's dashboard. Keep the same "
        "camera angle, same framing, same cropping, and the same overall composition "
        "as the original image.\n"
        "- Move the steering wheel to the RIGHT side of the dashboard if it was on "
        "the left, or keep it on the right if it is already there. Adjust the "
        "instrument cluster and any driver-side controls to match the RHD layout.\n"
        "- The centre console, infotainment/radio slot, climate controls, air vents, "
        "and all other central dashboard elements must remain IDENTICAL — same "
        "position relative to the centre, same design, same colours.\n"
        "- Preserve ALL text, labels, numbers, and symbols on buttons, dials, and "
        "screens EXACTLY as they appear in the original — in English, with correct "
        "spelling and layout. Do NOT invent, translate, or alter any text.\n"
        "- Match the original lighting, material textures, and colour palette.\n"
        "- Photorealistic quality, as if it is a genuine manufacturer showroom photograph.\n"
        "- Do NOT add watermarks, logos, or any overlaid text."
    )


# ─── Helpers ────────────────────────────────────────────────────────────
def load_env():
    env_file = SCRIPT_DIR / ".env"
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


def folder_to_car_name(folder_name: str) -> str:
    """
    Convert a folder name like
      'TOYOTA_Corolla_(E210)_2018+'
    into a readable car name like
      'Toyota Corolla (E210) 2018+'
    """
    name = folder_name.replace("_", " ").strip()
    # Title-case the make (first word) but preserve the rest mostly as-is
    parts = name.split(" ", 1)
    if parts:
        parts[0] = parts[0].title()
    return " ".join(parts)


def encode_image_b64(path: Path) -> str:
    return base64.standard_b64encode(path.read_bytes()).decode("utf-8")


# ─── API calls ──────────────────────────────────────────────────────────
def generate_via_edit(client: OpenAI, image_path: Path, prompt: str) -> bytes | None:
    """Send image to images.edit and return raw PNG bytes."""
    with open(image_path, "rb") as fh:
        try:
            result = client.images.edit(
                model=IMAGE_MODEL,
                image=fh,
                prompt=prompt,
                n=1,
                size=OUTPUT_SIZE,
                quality="high",
            )
        except Exception as exc:
            logger.error("images.edit API error: %s", exc)
            return None

    if result.data:
        entry = result.data[0]
        if hasattr(entry, "b64_json") and entry.b64_json:
            return base64.b64decode(entry.b64_json)
        if hasattr(entry, "url") and entry.url:
            import requests as _req
            return _req.get(entry.url, timeout=60).content
    logger.error("No image data in images.edit response")
    return None


def generate_via_responses(client: OpenAI, image_path: Path, prompt: str) -> bytes | None:
    """Fallback: use the Responses API with image_generation tool."""
    b64 = encode_image_b64(image_path)
    try:
        result = client.responses.create(
            model="gpt-4o",
            input=[{
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_image", "image_url": f"data:image/png;base64,{b64}"},
                ],
            }],
            tools=[{"type": "image_generation", "size": OUTPUT_SIZE, "quality": "high"}],
        )
    except Exception as exc:
        logger.error("Responses API error: %s", exc)
        return None

    for item in result.output:
        if hasattr(item, "result") and item.type == "image_generation_call":
            return base64.b64decode(item.result)
    logger.error("No image data in responses API output")
    return None


def generate_rhd(
    client: OpenAI,
    image_path: Path,
    car_name: str,
    method: str,
) -> bytes | None:
    prompt = build_prompt(car_name)
    logger.debug("Prompt:\n%s", prompt)
    if method == "edit":
        return generate_via_edit(client, image_path, prompt)
    else:
        return generate_via_responses(client, image_path, prompt)


# ─── Main ────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(
        description="Generate RHD versions of CARAV dashboard half-images using OpenAI."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=f"Root output directory (default: {DEFAULT_OUTPUT_DIR})",
    )
    parser.add_argument(
        "--filter",
        metavar="SUBSTRING",
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
        "--skip-existing",
        action="store_true",
        help="Skip folders that already have a product_dashboard_half_rhd.png",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List folders and exit without calling the API",
    )
    args = parser.parse_args()

    output_dir: Path = args.output_dir

    # ── Collect folders ─────────────────────────────────────────────────
    folders = sorted(
        d for d in output_dir.iterdir()
        if d.is_dir() and (d / INPUT_FILENAME).exists()
    )

    if not folders:
        logger.error(
            "No sub-folders with '%s' found under %s", INPUT_FILENAME, output_dir
        )
        sys.exit(1)

    if args.filter:
        folders = [f for f in folders if args.filter.lower() in f.name.lower()]
        if not folders:
            logger.error("No folders match filter '%s'", args.filter)
            sys.exit(1)

    if args.skip_existing:
        before = len(folders)
        folders = [f for f in folders if not (f / OUTPUT_FILENAME).exists()]
        skipped = before - len(folders)
        if skipped:
            logger.info("Skipping %d folder(s) that already have %s", skipped, OUTPUT_FILENAME)

    logger.info("Found %d folder(s) to process:", len(folders))
    for f in folders:
        logger.info("  %s", f.name)

    if args.dry_run:
        logger.info("Dry-run mode — exiting without API calls.")
        return

    client = get_client()

    # ── Process each folder ─────────────────────────────────────────────
    success, failed = 0, 0
    for idx, folder in enumerate(folders, start=1):
        input_path = folder / INPUT_FILENAME
        output_path = folder / OUTPUT_FILENAME
        car_name = folder_to_car_name(folder.name)

        logger.info(
            "─" * 60 + "\n[%d/%d] %s\n  Input : %s\n  Output: %s",
            idx, len(folders), car_name, input_path, output_path,
        )

        t0 = time.time()
        img_bytes = generate_rhd(client, input_path, car_name, args.method)
        elapsed = time.time() - t0

        if img_bytes:
            output_path.write_bytes(img_bytes)
            logger.info(
                "  Saved → %s  (%.1fs, %d bytes)",
                output_path.name, elapsed, len(img_bytes),
            )
            success += 1
        else:
            logger.error("  FAILED for %s (%.1fs)", folder.name, elapsed)
            failed += 1

        # Brief pause between calls to respect rate limits
        if idx < len(folders):
            logger.info("  Waiting %ss before next call …", API_DELAY_SECONDS)
            time.sleep(API_DELAY_SECONDS)

    # ── Summary ─────────────────────────────────────────────────────────
    logger.info("=" * 60)
    logger.info(
        "Done.  %d succeeded, %d failed out of %d total.",
        success, failed, len(folders),
    )
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
