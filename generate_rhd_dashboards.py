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
IMAGE_MODEL = "chatgpt-image-latest"
OUTPUT_SIZE = "1536x1024"  # landscape — matches the rest of the pipeline

SCRIPT_DIR = Path(__file__).parent
DEFAULT_OUTPUT_DIR = SCRIPT_DIR / "carav_output"
INPUT_FILENAME = "product_dashboard_half.png"
OUTPUT_FILENAME = "product_dashboard_half_rhd.png"

# Delay between API calls (seconds) to avoid rate-limit errors
API_DELAY_SECONDS = 3


# ─── Prompt ─────────────────────────────────────────────────────────────
def build_prompt(car_name: str, description: str = "", note: str = "") -> str:
    """
    Craft the image-edit prompt for a specific car model.
    The source image is the original LHD dashboard half scraped from carav-parts.com.
    When description and note are provided (from info.txt), they add extra context.
    """
    # Build the identity line with as much detail as we have
    if description:
        identity = (
            f"This is a photograph of the dashboard interior for the following vehicle:\n"
            f"  {description}\n"
        )
        if note:
            identity += f"  Additional info: {note}\n"
    else:
        identity = f"This is a photograph of the dashboard interior of a {car_name}.\n"

    return (
        identity + "\n"
        "TASK: Recreate this exact dashboard image as it would appear in a RIGHT-HAND "
        "DRIVE (RHD) version of this vehicle.\n\n"
        "FOCUS: The centre console area — the radio/infotainment slot, climate controls, "
        "air vents, and gear area — is the most important part of this image. Keep it "
        "as the focal point of the composition.\n\n"
        "CRITICAL RULES:\n"
        "- Keep the SAME framing, camera angle, cropping, and composition as the "
        "original image. Do NOT zoom out, widen the frame, or reveal more of the "
        "dashboard than what is shown in the original.\n"
        "- Do NOT add a steering wheel, instrument cluster, or any other elements "
        "that are not visible in the original image. Only recreate what is already "
        "shown.\n"
        "- The centre console, infotainment/radio slot, climate controls, air vents, "
        "and all other central dashboard elements must remain IDENTICAL — same "
        "position, same design, same colours, same proportions.\n"
        "- The only change should be that the dashboard layout is mirrored to reflect "
        "a right-hand drive configuration (i.e. the passenger side becomes the driver "
        "side and vice versa).\n"
        "- Preserve ALL text, labels, numbers, and symbols on buttons, dials, and "
        "screens EXACTLY as they appear in the original — in English, with correct "
        "spelling and layout. Do NOT invent, translate, or alter any text.\n"
        "- Match the original lighting, material textures, and colour palette.\n"
        "- Photorealistic quality, as if it is a genuine manufacturer showroom photograph.\n"
        "- Do NOT add watermarks, logos, or any overlaid text.\n"
        "- Do NOT add any new objects, accessories, or details that are not present "
        "in the original image."
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
    Strips any leading number prefix like '06_'.
    """
    name = folder_name
    # Strip leading NN_ numeric prefix added by numbering
    if len(name) > 3 and name[:2].isdigit() and name[2] == '_':
        name = name[3:]
    name = name.replace("_", " ").strip()
    # Title-case the make (first word) but preserve the rest mostly as-is
    parts = name.split(" ", 1)
    if parts:
        parts[0] = parts[0].title()
    return " ".join(parts)


def read_info_txt(folder: Path) -> dict:
    """
    Read info.txt from a folder and return a dict with keys:
    part_number, car_name, description, note.  Missing keys default to ''.
    """
    info_path = folder / "info.txt"
    result = {"part_number": "", "car_name": "", "description": "", "note": ""}
    if not info_path.exists():
        return result
    for line in info_path.read_text().splitlines():
        if line.startswith("Part Number:"):
            result["part_number"] = line.split(":", 1)[1].strip()
        elif line.startswith("Car Name:"):
            val = line.split(":", 1)[1].strip()
            if val and val != "N/A":
                result["car_name"] = val
        elif line.startswith("Description:"):
            result["description"] = line.split(":", 1)[1].strip()
        elif line.startswith("Note:"):
            val = line.split(":", 1)[1].strip()
            # Strip the redundant leading "Note:" if present
            if val.startswith("Note:"):
                val = val[5:].strip()
            result["note"] = val
    return result


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
    description: str = "",
    note: str = "",
) -> bytes | None:
    prompt = build_prompt(car_name, description, note)
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
        "--numbers",
        metavar="RANGE",
        default=None,
        help=(
            "Only process numbered folders matching these numbers. "
            "Supports ranges and comma-separated values, e.g. '1-6' or '1,2,3,5,6'"
        ),
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

    if args.numbers:
        # Parse --numbers into a set of ints, e.g. "1-6" or "1,2,3,5,6"
        nums = set()
        for part in args.numbers.split(","):
            part = part.strip()
            if "-" in part:
                lo, hi = part.split("-", 1)
                nums.update(range(int(lo), int(hi) + 1))
            else:
                nums.add(int(part))
        folders = [
            f for f in folders
            if f.name[:2].isdigit() and int(f.name[:2]) in nums
        ]
        if not folders:
            logger.error("No folders match --numbers '%s'", args.numbers)
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

        # Read info.txt for richer context
        info = read_info_txt(folder)
        car_name = info["car_name"] or folder_to_car_name(folder.name)
        description = info["description"]
        note = info["note"]

        logger.info(
            "─" * 60 + "\n[%d/%d] %s\n  Input : %s\n  Output: %s\n  Desc  : %s",
            idx, len(folders), car_name, input_path, output_path, description or "(none)",
        )

        t0 = time.time()
        img_bytes = generate_rhd(client, input_path, car_name, args.method, description, note)
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
