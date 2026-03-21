import argparse
from pathlib import Path

from PIL import Image


def apply_opacity(watermark: Image.Image, opacity: float) -> Image.Image:
    if not 0 <= opacity <= 1:
        raise ValueError("Opacity must be between 0 and 1")

    wm = watermark.convert("RGBA")
    if opacity == 1:
        return wm

    alpha = wm.getchannel("A")
    alpha = alpha.point(lambda px: int(px * opacity))
    wm.putalpha(alpha)
    return wm


def add_watermark(
    input_image: Path,
    watermark_image: Path,
    output_image: Path,
    opacity: float = 0.25,
    margin: int = 24,
    scale: float = 0.25,
) -> None:
    if not input_image.exists():
        raise FileNotFoundError(f"Input image not found: {input_image}")
    if not watermark_image.exists():
        raise FileNotFoundError(f"Watermark image not found: {watermark_image}")

    with Image.open(input_image).convert("RGBA") as base, Image.open(watermark_image).convert("RGBA") as wm_raw:
        target_w = max(1, int(base.width * scale))
        ratio = target_w / wm_raw.width
        target_h = max(1, int(wm_raw.height * ratio))

        wm = wm_raw.resize((target_w, target_h), Image.Resampling.LANCZOS)
        wm = apply_opacity(wm, opacity)

        x = max(0, base.width - wm.width - margin)
        y = max(0, base.height - wm.height - margin)

        base.alpha_composite(wm, dest=(x, y))

        output_image.parent.mkdir(parents=True, exist_ok=True)
        if output_image.suffix.lower() in {".jpg", ".jpeg"}:
            base.convert("RGB").save(output_image, quality=95)
        else:
            base.save(output_image)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Add a PNG watermark to the bottom-right of an image.")
    parser.add_argument("input", type=Path, help="Path to source image")
    parser.add_argument("watermark", type=Path, help="Path to watermark PNG")
    parser.add_argument("--output", type=Path, default=None, help="Output image path")
    parser.add_argument("--opacity", type=float, default=0.25, help="Watermark opacity (0.0 - 1.0)")
    parser.add_argument("--margin", type=int, default=24, help="Margin from right/bottom edges in pixels")
    parser.add_argument("--scale", type=float, default=0.25, help="Watermark width as fraction of source width")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output = args.output
    if output is None:
        output = args.input.with_name(f"{args.input.stem}_watermarked{args.input.suffix}")

    add_watermark(
        input_image=args.input,
        watermark_image=args.watermark,
        output_image=output,
        opacity=args.opacity,
        margin=args.margin,
        scale=args.scale,
    )

    print(f"Saved watermarked image: {output}")


if __name__ == "__main__":
    main()
