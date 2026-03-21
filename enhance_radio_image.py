"""
Radio Image Enhancer (OpenAI Image Generation)
==============================================
Uses OpenAI's gpt-image-1 edit API to improve the clarity of a radio product image,
keep it visually very close to the original, and ensure on-screen UI text is in English.

Usage:
  python3 enhance_radio_image.py --input starsound/car_radio_1.jpeg
  python3 enhance_radio_image.py --input starsound/car_radio_1.jpeg --output starsound/car_radio_1_enh.png
  python3 enhance_radio_image.py --input starsound/car_radio_1.jpeg --method responses

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
    print("ERROR: openai package not installed. Run: pip install openai")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

IMAGE_MODEL = "gpt-image-1"
DEFAULT_INPUT = Path(__file__).parent / "starsound" / "car_radio_1.jpeg"


def load_env() -> None:
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


def build_prompt() -> str:
    return (
        "You are editing a product image of a car radio/head unit. "
        "Create a clearer, cleaner, high-quality product image while keeping it as close as possible to the original image. "
        "Preserve the exact product shape, dimensions, angle, layout, button placement, branding position, and overall composition. "
        "The radio must be front-facing, straight-on, and centered as a direct head-on product shot with no tilt or perspective skew. "
        "Do not redesign the device, do not add or remove features, and do not change framing or perspective except to keep the product strictly front-facing. "
        "Improve sharpness, readability, and contrast carefully, reducing blur/noise/compression artifacts. "
        "Any visible on-screen UI labels or text should be in clear English. "
        "Make the background pure white and clean, but do not change the product's lighting style or shadows. "
        "Result should look like a professional e-commerce product photo."
    )


def edit_image_via_images_api(client: OpenAI, input_path: Path, size: str) -> bytes | None:
    prompt = build_prompt()

    try:
        with open(input_path, "rb") as image_file:
            result = client.images.edit(
                model=IMAGE_MODEL,
                image=[image_file],
                prompt=prompt,
                n=1,
                size=size,
            )

        if result.data and len(result.data) > 0:
            image_data = result.data[0]
            if getattr(image_data, "b64_json", None):
                return base64.b64decode(image_data.b64_json)
            if getattr(image_data, "url", None):
                import requests

                resp = requests.get(image_data.url, timeout=60)
                resp.raise_for_status()
                return resp.content

    except Exception as exc:
        logger.error("images.edit request failed: %s", exc)
        return None

    return None


def edit_image_via_responses_api(client: OpenAI, input_path: Path, size: str) -> bytes | None:
    prompt = build_prompt()
    mime = "image/png" if input_path.suffix.lower() == ".png" else "image/jpeg"
    b64 = base64.standard_b64encode(input_path.read_bytes()).decode("utf-8")

    try:
        result = client.responses.create(
            model="gpt-4o",
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_image", "image_url": f"data:{mime};base64,{b64}"},
                    ],
                }
            ],
            tools=[{"type": "image_generation", "size": size, "quality": "high"}],
        )

        for item in result.output:
            if item.type == "image_generation_call" and getattr(item, "result", None):
                return base64.b64decode(item.result)

    except Exception as exc:
        logger.error("responses API request failed: %s", exc)
        return None

    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Enhance a radio image while preserving original design.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="Path to input image")
    parser.add_argument("--output", type=Path, default=None, help="Path to output image")
    parser.add_argument(
        "--size",
        default="1536x1024",
        help="Output size for OpenAI image generation (example: 1536x1024)",
    )
    parser.add_argument(
        "--method",
        choices=["edit", "responses"],
        default="edit",
        help="API method to use",
    )
    parser.add_argument("--dry-run", action="store_true", help="Validate inputs only, no API call")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    input_path = args.input

    if not input_path.exists():
        logger.error("Input image not found: %s", input_path)
        sys.exit(1)

    output_path = args.output
    if output_path is None:
        output_path = input_path.with_name(f"{input_path.stem}_enhanced.png")

    logger.info("Input: %s", input_path)
    logger.info("Output: %s", output_path)
    logger.info("Method: %s", args.method)
    logger.info("Size: %s", args.size)

    if args.dry_run:
        logger.info("Dry-run complete. No API request sent.")
        return

    client = get_client()
    if args.method == "edit":
        image_bytes = edit_image_via_images_api(client, input_path, args.size)
    else:
        image_bytes = edit_image_via_responses_api(client, input_path, args.size)

    if not image_bytes:
        logger.error("No image generated.")
        sys.exit(1)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(image_bytes)
    logger.info("Saved generated image: %s", output_path)


if __name__ == "__main__":
    main()
