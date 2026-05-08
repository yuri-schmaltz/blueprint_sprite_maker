#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
from importlib import import_module
from pathlib import Path
import subprocess
import sys
import tempfile

import gi

gi.require_version("Gegl", "0.4")
gi.require_version("Gimp", "3.0")

from gi.repository import Gegl, Gimp, GObject


PROCEDURE_NAME = "python-fu-my-blueprint-maker-extract-sprites"
RGBA_FORMAT = "R'G'B'A u8"
PLUGIN_DIR = Path(__file__).resolve().parent
EXTERNAL_RUNNER_PATH = PLUGIN_DIR / "external_sprite_runner.py"
RUNTIME_CONFIG_PATH = PLUGIN_DIR / "plugin_runtime_config.json"
RUNTIME_DEPENDENCY_ERROR = (
    "As dependencias Python do plugin nao estao disponiveis para o Python do GIMP. "
    "Instale numpy e opencv-python no ambiente usado pelo GIMP."
)


def _show_error(message: str):
    Gimp.message(message)


def _choice_is_valid(value: str, allowed_values):
    return value in allowed_values


def _load_runtime_config() -> dict:
    if not RUNTIME_CONFIG_PATH.exists():
        return {}
    return json.loads(RUNTIME_CONFIG_PATH.read_text(encoding="utf-8"))


def _load_pillow_image_module():
    try:
        return import_module("PIL.Image")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "O plugin precisa do Pillow no Python do GIMP para usar o modo de execucao externo."
        ) from exc


def _load_runtime_dependencies():
    try:
        cv2 = import_module("cv2")
        np = import_module("numpy")
        sprite_extractor_module = import_module("core.sprite_extractor")
    except ModuleNotFoundError as exc:
        raise RuntimeError(f"{RUNTIME_DEPENDENCY_ERROR} Modulo ausente: {exc.name}") from exc

    return cv2, np, sprite_extractor_module.SpriteExtractor


def _drawable_to_bgra(drawable: Gimp.Drawable, cv2, np):
    width = drawable.get_width()
    height = drawable.get_height()
    rect = Gegl.Rectangle.new(0, 0, width, height)
    src = drawable.get_buffer().get(rect, 1.0, RGBA_FORMAT, Gegl.AbyssPolicy.NONE)
    rgba = np.frombuffer(src, dtype=np.uint8).reshape((height, width, 4))
    return cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA)


def _save_drawable_png(drawable: Gimp.Drawable, destination: Path):
    pillow_image = _load_pillow_image_module()
    width = drawable.get_width()
    height = drawable.get_height()
    rect = Gegl.Rectangle.new(0, 0, width, height)
    rgba_bytes = drawable.get_buffer().get(rect, 1.0, RGBA_FORMAT, Gegl.AbyssPolicy.NONE)
    image = pillow_image.frombytes("RGBA", (width, height), bytes(rgba_bytes), "raw", "RGBA")
    image.save(destination)


def _sprite_to_rgba(sprite_image, cv2):
    if sprite_image.ndim == 2:
        return cv2.cvtColor(sprite_image, cv2.COLOR_GRAY2RGBA)
    if sprite_image.shape[2] == 4:
        return cv2.cvtColor(sprite_image, cv2.COLOR_BGRA2RGBA)
    return cv2.cvtColor(sprite_image, cv2.COLOR_BGR2RGBA)


def _create_result_image(source_image: Gimp.Image, sprites, cv2):
    min_x = min(sprite.bbox[0] for sprite in sprites)
    min_y = min(sprite.bbox[1] for sprite in sprites)
    max_x = max(sprite.bbox[0] + sprite.bbox[2] for sprite in sprites)
    max_y = max(sprite.bbox[1] + sprite.bbox[3] for sprite in sprites)

    result_image = Gimp.Image.new(max_x - min_x, max_y - min_y, Gimp.ImageBaseType.RGB)

    for index, sprite in enumerate(sprites):
        rgba = _sprite_to_rgba(sprite.image, cv2)
        height, width = rgba.shape[:2]
        layer_name = f"{index + 1:02d}_{sprite.view_type}"
        layer = Gimp.Layer.new(
            result_image,
            layer_name,
            width,
            height,
            Gimp.ImageType.RGBA_IMAGE,
            100.0,
            result_image.get_default_new_layer_mode(),
        )
        result_image.insert_layer(layer, None, index)
        layer.set_offsets(sprite.bbox[0] - min_x, sprite.bbox[1] - min_y)

        rect = Gegl.Rectangle.new(0, 0, width, height)
        layer_buffer = layer.get_buffer()
        layer_buffer.set(rect, RGBA_FORMAT, rgba.tobytes())
        layer_buffer.flush()

    return result_image


def _create_result_image_from_exports(source_image: Gimp.Image, sprites, output_dir: Path):
    pillow_image = _load_pillow_image_module()
    min_x = min(sprite["bbox"][0] for sprite in sprites)
    min_y = min(sprite["bbox"][1] for sprite in sprites)
    max_x = max(sprite["bbox"][0] + sprite["bbox"][2] for sprite in sprites)
    max_y = max(sprite["bbox"][1] + sprite["bbox"][3] for sprite in sprites)

    result_image = Gimp.Image.new(max_x - min_x, max_y - min_y, Gimp.ImageBaseType.RGB)

    for index, sprite in enumerate(sprites):
        sprite_path = output_dir / sprite["file_name"]
        with pillow_image.open(sprite_path) as sprite_image:
            rgba = sprite_image.convert("RGBA")
            width, height = rgba.size
            layer_name = f"{index + 1:02d}_{sprite['view_type']}"
            layer = Gimp.Layer.new(
                result_image,
                layer_name,
                width,
                height,
                Gimp.ImageType.RGBA_IMAGE,
                100.0,
                result_image.get_default_new_layer_mode(),
            )
            result_image.insert_layer(layer, None, index)
            layer.set_offsets(sprite["bbox"][0] - min_x, sprite["bbox"][1] - min_y)

            rect = Gegl.Rectangle.new(0, 0, width, height)
            layer_buffer = layer.get_buffer()
            layer_buffer.set(rect, RGBA_FORMAT, rgba.tobytes())
            layer_buffer.flush()

    return result_image


def _run_external_extraction(image: Gimp.Image, drawable: Gimp.Drawable, config):
    runtime_config = _load_runtime_config()
    helper_python = Path(runtime_config.get("helper_python", ""))

    if not helper_python.exists():
        raise RuntimeError(
            "Nao foi encontrado um Python externo configurado para executar a extracao. "
            "Reinstale o plugin pelo repositorio para atualizar plugin_runtime_config.json."
        )
    if not EXTERNAL_RUNNER_PATH.exists():
        raise RuntimeError("O helper externo do plugin nao foi encontrado na pasta instalada.")

    with tempfile.TemporaryDirectory(prefix="my_blueprint_maker_") as temp_dir_str:
        temp_dir = Path(temp_dir_str)
        input_path = temp_dir / "input.png"
        output_dir = temp_dir / "output"
        _save_drawable_png(drawable, input_path)

        command = [
            str(helper_python),
            str(EXTERNAL_RUNNER_PATH),
            "--input",
            str(input_path),
            "--output-dir",
            str(output_dir),
            "--threshold",
            str(int(config.get_property("threshold"))),
            "--min-area",
            str(int(config.get_property("min-area"))),
            "--layout-hint",
            (config.get_property("layout-hint") or "").strip().lower(),
            "--upscale",
            (config.get_property("upscale") or "none").strip().lower(),
        ]
        if bool(config.get_property("remove-bg")):
            command.append("--remove-bg")

        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        if completed.returncode != 0:
            details = (completed.stderr or completed.stdout or "").strip()
            raise RuntimeError(details or "A execucao externa do extrator falhou.")

        metadata_path = output_dir / "metadata.json"
        if not metadata_path.exists():
            raise RuntimeError("A execucao externa nao gerou metadata.json.")

        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        sprites = metadata.get("sprites", [])
        if not sprites:
            return None

        return _create_result_image_from_exports(image, sprites, output_dir)


class BlueprintMakerGimpPlugin(Gimp.PlugIn):
    def do_query_procedures(self):
        return [PROCEDURE_NAME]

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(self, name, Gimp.PDBProcType.PLUGIN, self.run, None)
        procedure.set_image_types("*")
        procedure.set_menu_label("Extrair sprites para nova imagem")
        procedure.add_menu_path("<Image>/Filters/My Blueprint Maker")
        procedure.set_documentation(
            "Detecta sprites na camada ativa e cria uma nova imagem com cada sprite em uma camada.",
            "Usa o motor de deteccao existente do projeto para transformar uma sprite sheet em uma nova imagem do GIMP com camadas separadas.",
            None,
        )
        procedure.set_attribution("Antigravity", "Antigravity", "2025")
        procedure.add_int_argument(
            "threshold",
            "Threshold",
            "Sensibilidade da deteccao de sprite.",
            0,
            255,
            10,
            GObject.ParamFlags.READWRITE,
        )
        procedure.add_int_argument(
            "min-area",
            "Area minima",
            "Ignora regioes menores que este valor em pixels.",
            1,
            10000000,
            100,
            GObject.ParamFlags.READWRITE,
        )
        procedure.add_string_argument(
            "layout-hint",
            "Layout",
            "Opcional: vazio, 2x2, 2x3 ou 3x2.",
            "",
            GObject.ParamFlags.READWRITE,
        )
        procedure.add_boolean_argument(
            "remove-bg",
            "Remover fundo",
            "Aplica rembg antes da deteccao, se disponivel.",
            False,
            GObject.ParamFlags.READWRITE,
        )
        procedure.add_string_argument(
            "upscale",
            "Upscale",
            "Opcional: none, fsrcnn ou edsr.",
            "none",
            GObject.ParamFlags.READWRITE,
        )
        procedure.add_boolean_argument(
            "open-result",
            "Abrir resultado",
            "Abre a nova imagem automaticamente quando houver interface grafica.",
            True,
            GObject.ParamFlags.READWRITE,
        )
        return procedure

    def run(self, procedure, run_mode, image, drawables, config, run_data):
        if not drawables or len(drawables) != 1:
            _show_error("Selecione exatamente uma camada para extrair os sprites.")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, None)

        layout_hint = (config.get_property("layout-hint") or "").strip().lower()
        if layout_hint and not _choice_is_valid(layout_hint, {"2x2", "2x3", "3x2"}):
            _show_error("O layout deve ser vazio, 2x2, 2x3 ou 3x2.")
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, None)

        upscale = (config.get_property("upscale") or "none").strip().lower()
        if not _choice_is_valid(upscale, {"none", "fsrcnn", "edsr"}):
            _show_error("O upscale deve ser none, fsrcnn ou edsr.")
            return procedure.new_return_values(Gimp.PDBStatusType.CALLING_ERROR, None)

        try:
            cv2, np, SpriteExtractor = _load_runtime_dependencies()
            extractor = SpriteExtractor()
            extractor.original_image = _drawable_to_bgra(drawables[0], cv2, np)
            extractor.processed_image = extractor.original_image.copy()
            sprites = extractor.detect_sprites(
                threshold=int(config.get_property("threshold")),
                min_area=int(config.get_property("min-area")),
                layout_hint=layout_hint or None,
                remove_bg=bool(config.get_property("remove-bg")),
                upscale=upscale,
            )
            if not sprites:
                _show_error("Nenhum sprite foi detectado com os parametros atuais.")
                return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, None)

            result_image = _create_result_image(image, sprites, cv2)
        except RuntimeError:
            try:
                result_image = _run_external_extraction(image, drawables[0], config)
            except Exception as exc:
                _show_error(f"Falha ao processar a camada: {exc}")
                return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, None)

            if result_image is None:
                _show_error("Nenhum sprite foi detectado com os parametros atuais.")
                return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, None)
        except Exception as exc:
            _show_error(f"Falha ao processar a camada: {exc}")
            return procedure.new_return_values(Gimp.PDBStatusType.EXECUTION_ERROR, None)

        if bool(config.get_property("open-result")) and Gimp.Display.name() is not None:
            Gimp.Display.new(result_image)

        return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, None)


Gimp.main(BlueprintMakerGimpPlugin.__gtype__, sys.argv)