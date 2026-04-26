"""Generate JoyBoy desktop packaging icons from the web monogram asset."""

from __future__ import annotations

import argparse
from pathlib import Path


PROJECT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = PROJECT_DIR / "web" / "static" / "images" / "monogramme.png"
DEFAULT_WINDOWS_ICON = PROJECT_DIR / "packaging" / "assets" / "joyboy.ico"
WINDOWS_ICON_SIZES = ((16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256))


def generate_windows_icon(source: Path = DEFAULT_SOURCE, target: Path = DEFAULT_WINDOWS_ICON) -> Path:
    try:
        from PIL import Image, ImageOps
    except ImportError as exc:
        raise SystemExit("Pillow is required: python -m pip install Pillow") from exc

    source = source.expanduser().resolve()
    target = target.expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"Icon source not found: {source}")

    target.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        image = ImageOps.exif_transpose(image).convert("RGBA")
        side = max(image.size)
        canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
        offset = ((side - image.width) // 2, (side - image.height) // 2)
        canvas.alpha_composite(image, offset)
        canvas.save(target, format="ICO", sizes=WINDOWS_ICON_SIZES)
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate JoyBoy desktop app icons.")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="Source PNG/SVG rasterized asset")
    parser.add_argument("--windows-icon", type=Path, default=DEFAULT_WINDOWS_ICON, help="Output .ico path")
    args = parser.parse_args()

    icon = generate_windows_icon(args.source, args.windows_icon)
    print(f"Generated Windows icon: {icon}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
