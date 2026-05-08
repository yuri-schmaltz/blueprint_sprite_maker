from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

from core.sprite_extractor import SpriteExtractor


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Executa a extracao de sprites fora do runtime Python do GIMP."
    )
    parser.add_argument("--input", type=Path, required=True, help="Arquivo binario RGBA de entrada.")
    parser.add_argument(
        "--output-dir",
        type=Path,
        required=True,
        help="Diretorio onde os sprites exportados e o metadata.json serao gravados.",
    )
    parser.add_argument("--threshold", type=int, default=10)
    parser.add_argument("--min-area", type=int, default=100)
    parser.add_argument("--layout-hint", default="")
    parser.add_argument("--remove-bg", action="store_true")
    parser.add_argument("--upscale", default="none")
    parser.add_argument("--width", type=int, required=True)
    parser.add_argument("--height", type=int, required=True)
    parser.add_argument(
        "--preview-kind",
        choices=["detection", "mask"],
        default="",
        help="Gera uma preview de deteccao ou mascara em vez de exportar sprites.",
    )
    return parser.parse_args()


def _rgba_file_to_bgra_image(path: Path, width: int, height: int) -> np.ndarray:
    rgba = np.frombuffer(path.read_bytes(), dtype=np.uint8).reshape((height, width, 4))
    return cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA)


def _sprite_to_rgba_bytes(sprite_image: np.ndarray) -> tuple[bytes, int, int]:
    if sprite_image.ndim == 2:
        rgba = cv2.cvtColor(sprite_image, cv2.COLOR_GRAY2RGBA)
    elif sprite_image.shape[2] == 4:
        rgba = cv2.cvtColor(sprite_image, cv2.COLOR_BGRA2RGBA)
    else:
        rgba = cv2.cvtColor(sprite_image, cv2.COLOR_BGR2RGBA)

    height, width = rgba.shape[:2]
    return rgba.tobytes(), width, height


def _preview_to_rgba_bytes(preview_image: np.ndarray) -> tuple[bytes, int, int]:
    if preview_image.ndim == 2:
        rgba = cv2.cvtColor(preview_image, cv2.COLOR_GRAY2RGBA)
    elif preview_image.shape[2] == 4:
        rgba = preview_image
    else:
        rgba = cv2.cvtColor(preview_image, cv2.COLOR_BGR2RGBA)

    height, width = rgba.shape[:2]
    return rgba.tobytes(), width, height


def build_metadata(sprites, output_dir: Path) -> dict:
    metadata = []
    for sprite in sprites:
        rgba_bytes, width, height = _sprite_to_rgba_bytes(sprite.image)
        file_name = f"sprite_{sprite.index + 1:02d}.rgba"
        (output_dir / file_name).write_bytes(rgba_bytes)
        metadata.append(
            {
                "index": int(sprite.index),
                "view_type": sprite.view_type,
                "bbox": [int(value) for value in sprite.bbox],
                "file_name": file_name,
                "width": width,
                "height": height,
            }
        )
    return {"sprites": metadata}


def build_preview_metadata(extractor: SpriteExtractor, preview_kind: str, output_dir: Path) -> dict:
    if preview_kind == "mask":
        preview_image = extractor.get_binary_mask_preview()
    else:
        preview_image = extractor.get_preview_image(draw_boxes=True)

    if preview_image is None:
        return {"preview": None}

    rgba_bytes, width, height = _preview_to_rgba_bytes(preview_image)
    file_name = f"preview_{preview_kind}.rgba"
    (output_dir / file_name).write_bytes(rgba_bytes)
    return {
        "preview": {
            "file_name": file_name,
            "width": width,
            "height": height,
            "kind": preview_kind,
            "sprite_count": len(extractor.sprites),
        }
    }


def main() -> int:
    args = parse_args()

    extractor = SpriteExtractor()
    try:
        extractor.original_image = _rgba_file_to_bgra_image(args.input, args.width, args.height)
    except Exception as exc:
        print(f"Falha ao carregar imagem de entrada: {exc}", file=sys.stderr)
        return 1

    extractor.processed_image = extractor.original_image.copy()

    sprites = extractor.detect_sprites(
        threshold=args.threshold,
        min_area=args.min_area,
        layout_hint=args.layout_hint or None,
        remove_bg=args.remove_bg,
        upscale=args.upscale,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)

    metadata_path = args.output_dir / "metadata.json"
    if args.preview_kind:
        metadata = build_preview_metadata(extractor, args.preview_kind, args.output_dir)
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=True, indent=2), encoding="utf-8")
        return 0

    metadata_path.write_text(
        json.dumps(build_metadata(sprites, args.output_dir), ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())