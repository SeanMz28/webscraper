"""
Trim Installation Image Generator
==================================
Uses OpenAI's gpt-image-1 API to generate images showing what a vehicle
dashboard looks like with an aftermarket trim kit + screen installed.

Workflow per vehicle:
  1. Takes an existing dashboard photo (from dashboards/ folder)
  2. Optionally takes a trim-only photo (from trim_assets/)
  3. Generates a composite showing the trim + screen installed in the dashboard

Usage:
  # Single vehicle test
  python generate_install_image.py --make ISUZU --model D-MAX --year 2005

  # With a specific trim image
  python generate_install_image.py --make ISUZU --model D-MAX --year 2005 \
      --trim-image path/to/trim.jpg

  # With custom screen size
  python generate_install_image.py --make ISUZU --model D-MAX --year 2005 \
      --screen-size '9"'

Environment:
  Set OPENAI_API_KEY in your environment or in a .env file.
"""

import argparse
import base64
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    from openai import OpenAI
except ImportError:
    print("ERROR: openai package not installed. Run: pip install openai")
    sys.exit(1)

try:
    from PIL import Image
except ImportError:
    print("ERROR: Pillow package not installed. Run: pip install Pillow")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

# ─── Configuration ─────────────────────────────────────────────────────
DASHBOARDS_DIR = Path(__file__).parent / "dashboards"
CATALOGUE_DIR = Path(__file__).parent / "catalogue_phase2"
TRIM_ASSETS_DIR = Path(__file__).parent / "trim_assets"

# OpenAI model for image generation
IMAGE_MODEL = "gpt-image-1"

# Default output size
OUTPUT_SIZE = "1536x1024"  # landscape, good for dashboards


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
        logger.error(
            "OPENAI_API_KEY not set. Set it in your environment or in a .env file."
        )
        sys.exit(1)
    return OpenAI(api_key=api_key)


def find_dashboard_folder(make: str, model: str, year: str) -> Path | None:
    """Find the dashboard folder matching make/model/year."""
    make_dir = DASHBOARDS_DIR / make.upper()
    if not make_dir.exists():
        logger.error(f"Make directory not found: {make_dir}")
        return None

    # Try exact match first: MODEL_YEAR
    target = f"{model.upper().replace(' ', '_')}_{year}"
    candidate = make_dir / target
    if candidate.exists():
        return candidate

    # Try partial matches
    for folder in sorted(make_dir.iterdir()):
        if not folder.is_dir():
            continue
        name = folder.name.upper()
        if model.upper().replace(" ", "_") in name and (year in name or name.endswith("_")):
            return folder

    logger.error(f"No dashboard folder found for {make} {model} {year}")
    return None


def get_best_dashboard_image(dashboard_dir: Path) -> Path | None:
    """Select the best dashboard image from a folder (first one by default)."""
    images = sorted(
        [f for f in dashboard_dir.iterdir() if f.suffix.lower() in (".jpg", ".jpeg", ".png")],
        key=lambda f: f.name,
    )
    if not images:
        logger.error(f"No images found in {dashboard_dir}")
        return None

    # Prefer dashboard_01 as it's usually the most relevant
    return images[0]


def load_metadata(dashboard_dir: Path) -> dict:
    """Load metadata.json from the dashboard folder."""
    meta_file = dashboard_dir / "metadata.json"
    if meta_file.exists():
        return json.loads(meta_file.read_text())
    return {}


def encode_image_to_base64(image_path: Path) -> str:
    """Read an image file and return base64 encoded string."""
    return base64.standard_b64encode(image_path.read_bytes()).decode("utf-8")


def _build_prompt(
    vehicle_name: str,
    screen_size: str,
    trim_description: str,
    has_trim_image: bool,
) -> str:
    """Build the image generation prompt."""
    prompt = (
        f"This is a photo of a {vehicle_name} vehicle dashboard interior. "
        f"Replace the factory radio/head unit area with a modern aftermarket "
        f"{screen_size} Android touchscreen head unit. "
        f"The touchscreen should display a home screen with colorful app icons "
        f"(music, navigation, phone, radio, settings, Bluetooth). "
        f"The screen should be surrounded by a black aftermarket trim bezel/frame "
        f"that fits flush and neatly into the dashboard's existing radio slot opening. "
        f"Keep everything else in the dashboard exactly the same — same steering wheel, "
        f"air vents, climate controls, buttons, materials, and interior color. "
        f"The result must look like a realistic professional product photograph "
        f"showing the completed aftermarket head unit installation. Photorealistic quality."
    )

    if trim_description:
        prompt += f" The trim kit product is: {trim_description}."

    if has_trim_image:
        prompt += (
            " The second image provided shows the exact aftermarket trim frame/bezel "
            "to use around the screen. Match its shape and style in the installation."
        )

    return prompt


def generate_with_edit_api(
    client: OpenAI,
    dashboard_image_path: Path,
    make: str,
    model: str,
    year: str,
    screen_size: str = '9"',
    trim_image_path: Path | None = None,
    trim_description: str = "",
) -> bytes | None:
    """
    Use the OpenAI Images Edit API (gpt-image-1) to modify the dashboard photo
    in-place, replacing the radio area with a trim + screen installation.

    This is the preferred method as it preserves the original dashboard context.
    """
    vehicle_name = f"{year} {make} {model}"
    has_trim = trim_image_path is not None and trim_image_path.exists()

    prompt = _build_prompt(vehicle_name, screen_size, trim_description, has_trim)

    logger.info(f"Generating (edit API) for {vehicle_name}...")
    logger.info(f"Dashboard: {dashboard_image_path.name}")
    if has_trim:
        logger.info(f"Trim reference: {trim_image_path.name}")

    try:
        # Build the list of input image file objects
        # gpt-image-1 images.edit accepts multiple images via a list
        image_files = [open(dashboard_image_path, "rb")]
        if has_trim:
            image_files.append(open(trim_image_path, "rb"))

        result = client.images.edit(
            model=IMAGE_MODEL,
            image=image_files,
            prompt=prompt,
            n=1,
            size=OUTPUT_SIZE,
        )

        # Close file handles
        for f in image_files:
            f.close()

        if result.data and len(result.data) > 0:
            image_data = result.data[0]

            if hasattr(image_data, "b64_json") and image_data.b64_json:
                return base64.b64decode(image_data.b64_json)
            elif hasattr(image_data, "url") and image_data.url:
                import requests
                resp = requests.get(image_data.url, timeout=60)
                resp.raise_for_status()
                return resp.content

        logger.error("No image data in API response")
        return None

    except Exception as e:
        logger.error(f"Image edit API failed: {e}")
        logger.exception(e)
        return None


def generate_installation_image(
    client: OpenAI,
    dashboard_image_path: Path,
    make: str,
    model: str,
    year: str,
    screen_size: str = '9"',
    trim_image_path: Path | None = None,
    trim_description: str = "",
) -> bytes | None:
    """
    Fallback: use the Responses API with vision input to generate the image.
    Sends the dashboard image as a user message with the prompt.
    """
    vehicle_name = f"{year} {make} {model}"
    has_trim = trim_image_path is not None and trim_image_path.exists()

    prompt = _build_prompt(vehicle_name, screen_size, trim_description, has_trim)

    logger.info(f"Generating (responses API) for {vehicle_name}...")
    logger.info(f"Dashboard: {dashboard_image_path.name}")

    try:
        # Encode images as base64 data URIs for the responses API
        dash_b64 = encode_image_to_base64(dashboard_image_path)
        dash_mime = "image/png" if dashboard_image_path.suffix.lower() == ".png" else "image/jpeg"

        content_parts = [
            {"type": "input_text", "text": prompt},
            {
                "type": "input_image",
                "image_url": f"data:{dash_mime};base64,{dash_b64}",
            },
        ]

        if has_trim:
            trim_b64 = encode_image_to_base64(trim_image_path)
            trim_mime = "image/png" if trim_image_path.suffix.lower() == ".png" else "image/jpeg"
            content_parts.append({
                "type": "input_image",
                "image_url": f"data:{trim_mime};base64,{trim_b64}",
            })

        result = client.responses.create(
            model="gpt-4o",
            input=[{"role": "user", "content": content_parts}],
            tools=[{"type": "image_generation", "size": OUTPUT_SIZE, "quality": "high"}],
        )

        # Extract generated image from the response
        for item in result.output:
            if hasattr(item, "result") and item.type == "image_generation_call":
                return base64.b64decode(item.result)

        logger.error("No image found in responses API output")
        return None

    except Exception as e:
        logger.error(f"Responses API generation failed: {e}")
        logger.exception(e)
        return None


def save_generated_image(
    image_bytes: bytes,
    make: str,
    model: str,
    year: str,
    output_dir: Path | None = None,
    suffix: str = "installed",
) -> Path:
    """Save the generated image and return its path."""
    if output_dir is None:
        output_dir = CATALOGUE_DIR / make.upper() / f"{model.upper().replace(' ', '_')}_{year}"

    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{suffix}_{timestamp}.png"
    output_path = output_dir / filename

    output_path.write_bytes(image_bytes)
    logger.info(f"Saved generated image: {output_path}")

    return output_path


def save_catalogue_metadata(
    output_dir: Path,
    make: str,
    model: str,
    year: str,
    dashboard_source: str,
    generated_files: list[str],
    screen_size: str,
    trim_description: str,
):
    """Save metadata about the generated catalogue entry."""
    meta = {
        "vehicle": {
            "make": make,
            "model": model,
            "year_range": year,
        },
        "generation": {
            "api": IMAGE_MODEL,
            "screen_size": screen_size,
            "trim_description": trim_description,
            "dashboard_source": dashboard_source,
            "generated_files": generated_files,
            "generation_date": datetime.now().isoformat(),
        },
    }

    meta_path = output_dir / "generation_metadata.json"
    meta_path.write_text(json.dumps(meta, indent=2))
    logger.info(f"Saved metadata: {meta_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Generate trim/screen installation images for vehicle dashboards"
    )
    parser.add_argument("--make", required=True, help="Vehicle make (e.g., ISUZU)")
    parser.add_argument("--model", required=True, help="Vehicle model (e.g., D-MAX)")
    parser.add_argument("--year", required=True, help="Vehicle year (e.g., 2005)")
    parser.add_argument(
        "--screen-size", default='9"', help='Screen size (default: 9")'
    )
    parser.add_argument(
        "--trim-image", default=None, help="Path to trim-only image (optional)"
    )
    parser.add_argument(
        "--trim-description", default="", help="Description of the trim kit"
    )
    parser.add_argument(
        "--dashboard-index",
        type=int,
        default=0,
        help="Index of dashboard image to use (0=first, default)",
    )
    parser.add_argument(
        "--output-dir", default=None, help="Custom output directory"
    )
    parser.add_argument(
        "--method",
        choices=["edit", "responses"],
        default="edit",
        help="API method: 'edit' (images.edit, default) or 'responses' (responses API with vision)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate inputs and show what would be done, without calling the API",
    )

    args = parser.parse_args()

    # Initialize OpenAI client (skip in dry-run mode)
    client = None
    if not args.dry_run:
        client = get_client()

    # Find dashboard images
    dashboard_dir = find_dashboard_folder(args.make, args.model, args.year)
    if not dashboard_dir:
        sys.exit(1)

    # Get dashboard image
    images = sorted(
        [f for f in dashboard_dir.iterdir() if f.suffix.lower() in (".jpg", ".jpeg", ".png")],
    )
    if args.dashboard_index >= len(images):
        logger.error(
            f"Dashboard index {args.dashboard_index} out of range (found {len(images)} images)"
        )
        sys.exit(1)

    dashboard_image = images[args.dashboard_index]
    logger.info(f"Using dashboard image: {dashboard_image}")

    # Load metadata for trim description
    metadata = load_metadata(dashboard_dir)
    trim_desc = args.trim_description
    if not trim_desc and metadata:
        vehicle_info = metadata.get("vehicle", {})
        trim_desc = vehicle_info.get("description", "")

    # Prepare trim image if provided
    trim_image = Path(args.trim_image) if args.trim_image else None

    # Set output directory
    output_dir = Path(args.output_dir) if args.output_dir else None

    # Generate the image
    logger.info("=" * 60)
    logger.info(f"Vehicle: {args.year} {args.make} {args.model}")
    logger.info(f"Method: {args.method}")
    logger.info(f"Screen: {args.screen_size}")
    logger.info(f"Trim: {trim_desc or 'generic'}")
    logger.info("=" * 60)

    start_time = time.time()

    if args.dry_run:
        logger.info("[DRY RUN] Would generate image using '%s' method", args.method)
        logger.info("[DRY RUN] Dashboard image: %s (%d bytes)", dashboard_image.name, dashboard_image.stat().st_size)
        if trim_image and trim_image.exists():
            logger.info("[DRY RUN] Trim image: %s (%d bytes)", trim_image.name, trim_image.stat().st_size)
        output_dir_preview = output_dir or (
            CATALOGUE_DIR / args.make.upper() / f"{args.model.upper().replace(' ', '_')}_{args.year}"
        )
        logger.info("[DRY RUN] Output would be saved to: %s", output_dir_preview)
        logger.info("[DRY RUN] Prompt preview:\n%s", _build_prompt(
            f"{args.year} {args.make} {args.model}", args.screen_size, trim_desc,
            trim_image is not None and trim_image.exists() if trim_image else False,
        ))
        logger.info("[DRY RUN] All inputs validated. Ready to run for real once OPENAI_API_KEY is set.")
        sys.exit(0)

    if args.method == "edit":
        result_bytes = generate_with_edit_api(
            client=client,
            dashboard_image_path=dashboard_image,
            make=args.make,
            model=args.model,
            year=args.year,
            screen_size=args.screen_size,
            trim_image_path=trim_image,
            trim_description=trim_desc,
        )
    else:
        result_bytes = generate_installation_image(
            client=client,
            dashboard_image_path=dashboard_image,
            make=args.make,
            model=args.model,
            year=args.year,
            screen_size=args.screen_size,
            trim_image_path=trim_image,
            trim_description=trim_desc,
        )

    elapsed = time.time() - start_time

    if result_bytes:
        output_path = save_generated_image(
            image_bytes=result_bytes,
            make=args.make,
            model=args.model,
            year=args.year,
            output_dir=output_dir,
            suffix=f"trim_installed_{args.method}",
        )

        # Save metadata
        save_catalogue_metadata(
            output_dir=output_path.parent,
            make=args.make,
            model=args.model,
            year=args.year,
            dashboard_source=str(dashboard_image),
            generated_files=[output_path.name],
            screen_size=args.screen_size,
            trim_description=trim_desc,
        )

        logger.info(f"Generation completed in {elapsed:.1f}s")
        logger.info(f"Output: {output_path}")
    else:
        logger.error(f"Generation failed after {elapsed:.1f}s")
        sys.exit(1)


if __name__ == "__main__":
    main()
