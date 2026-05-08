from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from core.sprite_extractor import SpriteExtractor


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Executa a extracao de sprites fora do runtime Python do GIMP."
    )
    parser.add_argument("--input", type=Path, required=True, help="Arquivo de entrada em PNG.")
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
    return parser.parse_args()


def build_metadata(sprites, exported_files: list[Path]) -> dict:
    metadata = []
    for sprite, file_path in zip(sprites, exported_files):
        metadata.append(
            {
                "index": int(sprite.index),
                "view_type": sprite.view_type,
                "bbox": [int(value) for value in sprite.bbox],
                "file_name": file_path.name,
            }
        )
    return {"sprites": metadata}


def main() -> int:
    args = parse_args()

    extractor = SpriteExtractor()
    if not extractor.load_image(str(args.input)):
        print(f"Falha ao carregar imagem de entrada: {args.input}", file=sys.stderr)
        return 1

    sprites = extractor.detect_sprites(
        threshold=args.threshold,
        min_area=args.min_area,
        layout_hint=args.layout_hint or None,
        remove_bg=args.remove_bg,
        upscale=args.upscale,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    exported_files = extractor.export_sprites(
        output_dir=str(args.output_dir),
        prefix="sprite",
        format="png",
        use_view_names=True,
    )

    metadata_path = args.output_dir / "metadata.json"
    metadata_path.write_text(
        json.dumps(build_metadata(sprites, exported_files), ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())