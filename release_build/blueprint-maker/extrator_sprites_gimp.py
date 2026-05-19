#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
from importlib import import_module
from pathlib import Path
import subprocess
import sys
import tempfile

from core.runtime_config import resolve_helper_python_command
import gi

gi.require_version("Gegl", "0.4")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("Gimp", "3.0")
gi.require_version("Gtk", "3.0")

from gi.repository import (  # noqa: E402
    GdkPixbuf,
    Gegl,
    Gimp,
    GObject,
    GLib,
    Gtk,
)

PROCEDURE_NAME = "python-fu-blueprint-maker-extract-sprites"
RGBA_FORMAT = "R'G'B'A u8"
PLUGIN_DIR = Path(__file__).resolve().parent
EXTERNAL_RUNNER_PATH = PLUGIN_DIR / "external_sprite_runner.py"
RUNTIME_CONFIG_PATH = PLUGIN_DIR / "plugin_runtime_config.json"
RUNTIME_DEPENDENCY_ERROR = (
    "As dependencias Python do plugin nao estao disponiveis para o Python "
    "do GIMP. "
    "Instale numpy e opencv-python no ambiente usado pelo GIMP."
)
PREVIEW_MAX_SIZE = 440


def _get_subprocess_run_kwargs() -> dict:
    kwargs = {
        "capture_output": True,
        "text": True,
        "check": False,
    }

    if sys.platform == "win32":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
        kwargs["startupinfo"] = startupinfo
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)

    return kwargs


def _apply_system_theme(dialog: Gtk.Dialog) -> None:
    settings = Gtk.Settings.get_default()
    if settings is None:
        return

    dialog_settings = dialog.get_settings()
    if dialog_settings is None:
        return

    theme_name = settings.get_property("gtk-theme-name")
    if theme_name:
        dialog_settings.set_property("gtk-theme-name", theme_name)

    dialog_settings.set_property(
        "gtk-application-prefer-dark-theme",
        bool(settings.get_property("gtk-application-prefer-dark-theme")),
    )


def _show_error(message: str):
    Gimp.message(message)


def _choice_is_valid(value: str, allowed_values):
    return value in allowed_values


def _load_runtime_dependencies():
    try:
        cv2 = import_module("cv2")
        np = import_module("numpy")
        sprite_extractor_module = import_module("core.sprite_extractor")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            f"{RUNTIME_DEPENDENCY_ERROR} Modulo ausente: {exc.name}"
        ) from exc

    return cv2, np, sprite_extractor_module.SpriteExtractor


def _drawable_to_bgra(drawable: Gimp.Drawable, cv2, np):
    width = drawable.get_width()
    height = drawable.get_height()
    rect = Gegl.Rectangle.new(0, 0, width, height)
    src = drawable.get_buffer().get(
        rect,
        1.0,
        RGBA_FORMAT,
        Gegl.AbyssPolicy.NONE,
    )
    rgba = np.frombuffer(src, dtype=np.uint8).reshape((height, width, 4))
    return cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA)


def _save_drawable_png(drawable: Gimp.Drawable, destination: Path):
    width = drawable.get_width()
    height = drawable.get_height()
    rect = Gegl.Rectangle.new(0, 0, width, height)
    rgba_bytes = drawable.get_buffer().get(
        rect,
        1.0,
        RGBA_FORMAT,
        Gegl.AbyssPolicy.NONE,
    )
    destination.write_bytes(bytes(rgba_bytes))
    return width, height


def _sprite_to_rgba(sprite_image, cv2):
    if sprite_image.ndim == 2:
        return cv2.cvtColor(sprite_image, cv2.COLOR_GRAY2RGBA)
    if sprite_image.shape[2] == 4:
        return cv2.cvtColor(sprite_image, cv2.COLOR_BGRA2RGBA)
    return cv2.cvtColor(sprite_image, cv2.COLOR_BGR2RGBA)


def _create_single_sprite_image(
    rgba_bytes: bytes,
    width: int,
    height: int,
    view_type: str,
):
    result_image = Gimp.Image.new(width, height, Gimp.ImageBaseType.RGB)
    layer = Gimp.Layer.new(
        result_image,
        view_type,
        width,
        height,
        Gimp.ImageType.RGBA_IMAGE,
        100.0,
        result_image.get_default_new_layer_mode(),
    )
    result_image.insert_layer(layer, None, 0)

    rect = Gegl.Rectangle.new(0, 0, width, height)
    layer_buffer = layer.get_buffer()
    layer_buffer.set(rect, RGBA_FORMAT, rgba_bytes)
    layer_buffer.flush()
    return result_image


def _create_layered_result_image(sprites, cv2):
    min_x = min(sprite.bbox[0] for sprite in sprites)
    min_y = min(sprite.bbox[1] for sprite in sprites)
    max_x = max(sprite.bbox[0] + sprite.bbox[2] for sprite in sprites)
    max_y = max(sprite.bbox[1] + sprite.bbox[3] for sprite in sprites)

    result_image = Gimp.Image.new(
        max_x - min_x,
        max_y - min_y,
        Gimp.ImageBaseType.RGB,
    )

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


def _create_result_images(sprites, cv2):
    result_images = []
    for sprite in sprites:
        rgba = _sprite_to_rgba(sprite.image, cv2)
        height, width = rgba.shape[:2]
        result_images.append(
            _create_single_sprite_image(
                rgba.tobytes(),
                width,
                height,
                sprite.view_type,
            )
        )
    return result_images


def _create_result_images_from_exports(sprites, output_dir: Path):
    result_images = []
    for sprite in sprites:
        sprite_path = output_dir / sprite["file_name"]
        width = int(sprite["width"])
        height = int(sprite["height"])
        rgba_bytes = sprite_path.read_bytes()
        result_images.append(
            _create_single_sprite_image(
                rgba_bytes,
                width,
                height,
                sprite["view_type"],
            )
        )
    return result_images


def _create_layered_result_image_from_exports(sprites, output_dir: Path):
    min_x = min(sprite["bbox"][0] for sprite in sprites)
    min_y = min(sprite["bbox"][1] for sprite in sprites)
    max_x = max(sprite["bbox"][0] + sprite["bbox"][2] for sprite in sprites)
    max_y = max(sprite["bbox"][1] + sprite["bbox"][3] for sprite in sprites)

    result_image = Gimp.Image.new(
        max_x - min_x,
        max_y - min_y,
        Gimp.ImageBaseType.RGB,
    )

    for index, sprite in enumerate(sprites):
        sprite_path = output_dir / sprite["file_name"]
        width = int(sprite["width"])
        height = int(sprite["height"])
        rgba_bytes = sprite_path.read_bytes()
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
        layer_buffer.set(rect, RGBA_FORMAT, rgba_bytes)
        layer_buffer.flush()

    return result_image


def _collect_dialog_params(
    threshold_scale,
    min_area_spin,
    layout_combo,
    remove_bg_check,
    upscale_combo,
    open_result_check,
    output_mode_combo,
):
    return {
        "threshold": int(threshold_scale.get_value()),
        "min-area": int(min_area_spin.get_value()),
        "layout-hint": layout_combo.get_active_id() or "",
        "remove-bg": remove_bg_check.get_active(),
        "upscale": upscale_combo.get_active_id() or "none",
        "open-result": open_result_check.get_active(),
        "output-mode": output_mode_combo.get_active_id() or "separate-images",
    }


def _create_preview_image(
    rgba_bytes: bytes,
    width: int,
    height: int,
    title: str,
):
    return _create_single_sprite_image(rgba_bytes, width, height, title)


def _pixbuf_from_rgba_bytes(rgba_bytes: bytes, width: int, height: int):
    rowstride = width * 4
    pixbuf = GdkPixbuf.Pixbuf.new_from_bytes(
        GLib.Bytes.new(rgba_bytes),
        GdkPixbuf.Colorspace.RGB,
        True,
        8,
        width,
        height,
        rowstride,
    )
    if width <= PREVIEW_MAX_SIZE and height <= PREVIEW_MAX_SIZE:
        return pixbuf

    scale = min(PREVIEW_MAX_SIZE / width, PREVIEW_MAX_SIZE / height)
    scaled_width = max(1, int(width * scale))
    scaled_height = max(1, int(height * scale))
    return pixbuf.scale_simple(
        scaled_width,
        scaled_height,
        GdkPixbuf.InterpType.BILINEAR,
    )


def _set_preview_widget(
    preview_image_widget,
    preview_info_label,
    rgba_bytes,
    width: int,
    height: int,
    sprite_count: int | None = None,
):
    pixbuf = _pixbuf_from_rgba_bytes(rgba_bytes, width, height)
    preview_image_widget.set_from_pixbuf(pixbuf)
    if sprite_count is None:
        preview_info_label.set_text(f"Preview {width}x{height}")
    else:
        preview_info_label.set_text(
            f"Preview {width}x{height} | "
            f"Sprites detectados: {sprite_count}"
        )


def _refresh_preview_widget(
    drawable: Gimp.Drawable,
    params: dict,
    preview_kind: str,
    preview_image_widget,
    preview_info_label,
    preview_hint_label,
):
    preview_image, sprite_count = _run_external_preview(
        drawable,
        params,
        preview_kind,
    )
    preview_layer = preview_image.get_layers()[0]
    preview_width = preview_layer.get_width()
    preview_height = preview_layer.get_height()
    preview_rect = Gegl.Rectangle.new(0, 0, preview_width, preview_height)
    preview_bytes = bytes(
        preview_layer.get_buffer().get(
            preview_rect,
            1.0,
            RGBA_FORMAT,
            Gegl.AbyssPolicy.NONE,
        )
    )
    _set_preview_widget(
        preview_image_widget,
        preview_info_label,
        preview_bytes,
        preview_width,
        preview_height,
        sprite_count,
    )
    preview_hint_label.set_text(
        "Preview de mascara"
        if preview_kind == "mask"
        else "Preview de deteccao"
    )


def _schedule_preview_refresh(
    state: dict,
    build_params,
    drawable: Gimp.Drawable,
):
    source_id = state.get("preview_source_id")
    if source_id:
        GLib.source_remove(source_id)

    state["preview_info_label"].set_text("Atualizando preview...")

    def _run_preview_update():
        try:
            params = build_params()
            _refresh_preview_widget(
                drawable,
                params,
                state["preview_kind"],
                state["preview_image_widget"],
                state["preview_info_label"],
                state["preview_hint_label"],
            )
        except (RuntimeError, OSError, ValueError) as exc:
            _show_error(f"Falha ao gerar preview: {exc}")
            state["preview_info_label"].set_text("Falha ao atualizar preview.")
        finally:
            state["preview_source_id"] = None
        return False

    state["preview_source_id"] = GLib.timeout_add(350, _run_preview_update)


def _run_external_preview(
    drawable: Gimp.Drawable,
    params: dict,
    preview_kind: str,
):
    helper_command = resolve_helper_python_command(RUNTIME_CONFIG_PATH)

    if not helper_command:
        raise RuntimeError(
            "Nao foi encontrado um Python externo configurado nem um "
            "fallback valido para gerar a preview."
        )

    with tempfile.TemporaryDirectory(
        prefix="blueprint_preview_"
    ) as temp_dir_str:
        temp_dir = Path(temp_dir_str)
        input_path = temp_dir / "input.rgba"
        output_dir = temp_dir / "output"
        width, height = _save_drawable_png(drawable, input_path)

        command = [
            *helper_command,
            str(EXTERNAL_RUNNER_PATH),
            "--input",
            str(input_path),
            "--width",
            str(width),
            "--height",
            str(height),
            "--output-dir",
            str(output_dir),
            "--threshold",
            str(int(params["threshold"])),
            "--min-area",
            str(int(params["min-area"])),
            "--layout-hint",
            (params["layout-hint"] or "").strip().lower(),
            "--upscale",
            (params["upscale"] or "none").strip().lower(),
            "--preview-kind",
            preview_kind,
        ]
        if params["remove-bg"]:
            command.append("--remove-bg")

        completed = subprocess.run(command, **_get_subprocess_run_kwargs())
        if completed.returncode != 0:
            details = (completed.stderr or completed.stdout or "").strip()
            raise RuntimeError(details or "A geracao da preview falhou.")

        metadata = json.loads(
            (output_dir / "metadata.json").read_text(encoding="utf-8")
        )
        preview = metadata.get("preview")
        if not preview:
            raise RuntimeError("A preview nao foi gerada.")

        preview_path = output_dir / preview["file_name"]
        return (
            _create_preview_image(
                preview_path.read_bytes(),
                int(preview["width"]),
                int(preview["height"]),
                (
                    "preview_mask"
                    if preview_kind == "mask"
                    else "preview_detection"
                ),
            ),
            int(preview.get("sprite_count", 0)),
        )


def _run_configuration_dialog(config, drawable: Gimp.Drawable) -> bool:
    dialog = Gtk.Dialog(title="Blueprint Maker", modal=True)
    _apply_system_theme(dialog)
    dialog.add_button("_Cancelar", Gtk.ResponseType.CANCEL)
    dialog.add_button("Preview deteccao", 1001)
    dialog.add_button("Preview mascara", 1002)
    dialog.add_button("_Extrair", Gtk.ResponseType.OK)
    dialog.set_default_response(Gtk.ResponseType.OK)
    dialog.set_default_size(760, 620)
    dialog.set_resizable(True)

    content_area = dialog.get_content_area()
    content_area.set_spacing(12)
    content_area.set_margin_top(12)
    content_area.set_margin_bottom(12)
    content_area.set_margin_start(12)
    content_area.set_margin_end(12)

    container = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
    content_area.add(container)

    description = Gtk.Label(
        label=(
            "Configure a deteccao, gere previews e escolha o formato de "
            "saida antes da extracao."
        ),
        xalign=0.0,
    )
    description.set_line_wrap(True)
    container.pack_start(description, False, False, 0)

    main_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
    container.pack_start(main_box, True, True, 0)

    controls_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    controls_box.set_size_request(280, -1)
    main_box.pack_start(controls_box, False, False, 0)

    detection_frame = Gtk.Frame(label="Deteccao")
    controls_box.pack_start(detection_frame, False, False, 0)
    detection_grid = Gtk.Grid(column_spacing=12, row_spacing=8)
    detection_grid.set_border_width(10)
    detection_frame.add(detection_grid)

    threshold_label = Gtk.Label(label="Threshold", xalign=0.0)
    threshold_scale = Gtk.Scale.new_with_range(
        Gtk.Orientation.HORIZONTAL,
        1,
        255,
        1,
    )
    threshold_scale.set_digits(0)
    threshold_scale.set_hexpand(True)
    threshold_scale.set_value(float(config.get_property("threshold")))

    min_area_label = Gtk.Label(label="Area minima", xalign=0.0)
    min_area_spin = Gtk.SpinButton.new_with_range(1, 10000000, 1)
    min_area_spin.set_value(float(config.get_property("min-area")))

    layout_label = Gtk.Label(label="Layout", xalign=0.0)
    layout_combo = Gtk.ComboBoxText()
    layout_combo.append("", "Automatico")
    layout_combo.append("3x2", "3x2")
    layout_combo.append("2x3", "2x3")
    layout_combo.append("2x2", "2x2")
    layout_combo.set_active_id(
        (config.get_property("layout-hint") or "").strip().lower()
    )

    advanced_frame = Gtk.Frame(label="Opcoes avancadas")
    controls_box.pack_start(advanced_frame, False, False, 0)
    advanced_grid = Gtk.Grid(column_spacing=12, row_spacing=8)
    advanced_grid.set_border_width(10)
    advanced_frame.add(advanced_grid)

    remove_bg_check = Gtk.CheckButton(label="Remover fundo")
    remove_bg_check.set_active(bool(config.get_property("remove-bg")))

    upscale_label = Gtk.Label(label="Upscale", xalign=0.0)
    upscale_combo = Gtk.ComboBoxText()
    upscale_combo.append("none", "Nenhum")
    upscale_combo.append("fsrcnn", "FSRCNN")
    upscale_combo.append("edsr", "EDSR")
    upscale_combo.set_active_id(
        (config.get_property("upscale") or "none").strip().lower()
    )

    output_frame = Gtk.Frame(label="Saida")
    controls_box.pack_start(output_frame, False, False, 0)
    output_grid = Gtk.Grid(column_spacing=12, row_spacing=8)
    output_grid.set_border_width(10)
    output_frame.add(output_grid)

    open_result_check = Gtk.CheckButton(label="Abrir imagens ao concluir")
    open_result_check.set_active(bool(config.get_property("open-result")))

    output_mode_label = Gtk.Label(label="Modo de saida", xalign=0.0)
    output_mode_combo = Gtk.ComboBoxText()
    output_mode_combo.append("separate-images", "Uma imagem por sprite")
    output_mode_combo.append("layered-image", "Uma imagem unica com camadas")
    output_mode_combo.set_active_id(
        (config.get_property("output-mode") or "separate-images")
        .strip()
        .lower()
    )

    detection_grid.attach(threshold_label, 0, 0, 1, 1)
    detection_grid.attach(threshold_scale, 1, 0, 1, 1)
    detection_grid.attach(min_area_label, 0, 1, 1, 1)
    detection_grid.attach(min_area_spin, 1, 1, 1, 1)
    detection_grid.attach(layout_label, 0, 2, 1, 1)
    detection_grid.attach(layout_combo, 1, 2, 1, 1)

    advanced_grid.attach(remove_bg_check, 0, 0, 2, 1)
    advanced_grid.attach(upscale_label, 0, 1, 1, 1)
    advanced_grid.attach(upscale_combo, 1, 1, 1, 1)

    output_grid.attach(output_mode_label, 0, 0, 1, 1)
    output_grid.attach(output_mode_combo, 1, 0, 1, 1)
    output_grid.attach(open_result_check, 0, 1, 2, 1)

    preview_frame = Gtk.Frame(label="Preview")
    main_box.pack_start(preview_frame, True, True, 0)

    preview_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
    preview_box.set_border_width(10)
    preview_frame.add(preview_box)

    preview_hint_label = Gtk.Label(
        label=(
            "Use os botoes de preview para visualizar a deteccao ou a "
            "mascara antes de extrair."
        ),
        xalign=0.0,
    )
    preview_hint_label.set_line_wrap(True)
    preview_box.pack_start(preview_hint_label, False, False, 0)

    preview_image_widget = Gtk.Image()
    preview_image_widget.set_hexpand(True)
    preview_image_widget.set_vexpand(True)
    preview_box.pack_start(preview_image_widget, True, True, 0)

    preview_info_label = Gtk.Label(
        label="Nenhuma preview gerada ainda.",
        xalign=0.0,
    )
    preview_box.pack_start(preview_info_label, False, False, 0)

    preview_state = {
        "preview_kind": "detection",
        "preview_source_id": None,
        "preview_image_widget": preview_image_widget,
        "preview_info_label": preview_info_label,
        "preview_hint_label": preview_hint_label,
    }

    def _current_params():
        return _collect_dialog_params(
            threshold_scale,
            min_area_spin,
            layout_combo,
            remove_bg_check,
            upscale_combo,
            open_result_check,
            output_mode_combo,
        )

    def _queue_detection_preview(*_args):
        preview_state["preview_kind"] = "detection"
        _schedule_preview_refresh(preview_state, _current_params, drawable)

    def _queue_mask_preview(*_args):
        preview_state["preview_kind"] = "mask"
        _schedule_preview_refresh(preview_state, _current_params, drawable)

    threshold_scale.connect("value-changed", _queue_detection_preview)
    min_area_spin.connect("value-changed", _queue_detection_preview)
    layout_combo.connect("changed", _queue_detection_preview)
    remove_bg_check.connect("toggled", _queue_detection_preview)
    upscale_combo.connect("changed", _queue_detection_preview)
    output_mode_combo.connect("changed", _queue_detection_preview)

    dialog.show_all()
    _queue_detection_preview()

    while True:
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            if preview_state["preview_source_id"]:
                GLib.source_remove(preview_state["preview_source_id"])
                preview_state["preview_source_id"] = None
            params = _current_params()
            for key, value in params.items():
                config.set_property(key, value)
            dialog.destroy()
            return True

        if response in {
            Gtk.ResponseType.CANCEL,
            Gtk.ResponseType.DELETE_EVENT,
        }:
            if preview_state["preview_source_id"]:
                GLib.source_remove(preview_state["preview_source_id"])
                preview_state["preview_source_id"] = None
            dialog.destroy()
            return False

        if response in {1001, 1002}:
            if response == 1002:
                _queue_mask_preview()
            else:
                _queue_detection_preview()


def _run_external_extraction(
    image: Gimp.Image,
    drawable: Gimp.Drawable,
    config,
):
    helper_command = resolve_helper_python_command(RUNTIME_CONFIG_PATH)

    if not helper_command:
        raise RuntimeError(
            "Nao foi encontrado um Python externo configurado nem um "
            "fallback valido para executar a extracao. Reinstale o plugin "
            "pelo repositorio para atualizar plugin_runtime_config.json."
        )
    if not EXTERNAL_RUNNER_PATH.exists():
        raise RuntimeError(
            "O helper externo do plugin nao foi encontrado na pasta "
            "instalada."
        )

    with tempfile.TemporaryDirectory(
        prefix="blueprint_maker_"
    ) as temp_dir_str:
        temp_dir = Path(temp_dir_str)
        input_path = temp_dir / "input.rgba"
        output_dir = temp_dir / "output"
        width, height = _save_drawable_png(drawable, input_path)

        command = [
            *helper_command,
            str(EXTERNAL_RUNNER_PATH),
            "--input",
            str(input_path),
            "--width",
            str(width),
            "--height",
            str(height),
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

        completed = subprocess.run(command, **_get_subprocess_run_kwargs())
        if completed.returncode != 0:
            details = (completed.stderr or completed.stdout or "").strip()
            raise RuntimeError(
                details or "A execucao externa do extrator falhou."
            )

        metadata_path = output_dir / "metadata.json"
        if not metadata_path.exists():
            raise RuntimeError("A execucao externa nao gerou metadata.json.")

        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        sprites = metadata.get("sprites", [])
        if not sprites:
            return None

        output_mode = (
            (config.get_property("output-mode") or "separate-images")
            .strip()
            .lower()
        )
        if output_mode == "layered-image":
            return [
                _create_layered_result_image_from_exports(
                    sprites,
                    output_dir,
                )
            ]
        return _create_result_images_from_exports(sprites, output_dir)


class BlueprintMakerGimpPlugin(Gimp.PlugIn):
    def do_query_procedures(self):
        return [PROCEDURE_NAME]

    def do_create_procedure(self, name):
        procedure = Gimp.ImageProcedure.new(
            self,
            name,
            Gimp.PDBProcType.PLUGIN,
            self.run,
            None,
        )
        procedure.set_image_types("*")
        procedure.set_menu_label("Extrair sprites para nova imagem")
        procedure.add_menu_path("<Image>/Filters/Blueprint Maker")
        procedure.set_documentation(
            (
                "Detecta sprites na camada ativa e cria uma nova imagem para "
                "cada sprite detectado."
            ),
            (
                "Usa o motor de deteccao existente do projeto para gerar uma "
                "imagem separada no GIMP para cada sprite identificado."
            ),
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
            (
                "Abre a nova imagem automaticamente quando houver interface "
                "grafica."
            ),
            True,
            GObject.ParamFlags.READWRITE,
        )
        procedure.add_string_argument(
            "output-mode",
            "Modo de saida",
            "Escolha entre separate-images ou layered-image.",
            "separate-images",
            GObject.ParamFlags.READWRITE,
        )
        return procedure

    def run(self, procedure, run_mode, image, drawables, config, run_data):
        if not drawables or len(drawables) != 1:
            _show_error(
                "Selecione exatamente uma camada para extrair os sprites."
            )
            return procedure.new_return_values(
                Gimp.PDBStatusType.EXECUTION_ERROR,
                None,
            )

        interactive_cancelled = (
            run_mode == Gimp.RunMode.INTERACTIVE
            and not _run_configuration_dialog(config, drawables[0])
        )
        if interactive_cancelled:
            return procedure.new_return_values(Gimp.PDBStatusType.CANCEL, None)

        layout_hint = (
            (config.get_property("layout-hint") or "").strip().lower()
        )
        if layout_hint and not _choice_is_valid(
            layout_hint,
            {"2x2", "2x3", "3x2"},
        ):
            _show_error("O layout deve ser vazio, 2x2, 2x3 ou 3x2.")
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR,
                None,
            )

        upscale = (config.get_property("upscale") or "none").strip().lower()
        if not _choice_is_valid(upscale, {"none", "fsrcnn", "edsr"}):
            _show_error("O upscale deve ser none, fsrcnn ou edsr.")
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR,
                None,
            )

        output_mode = (
            (config.get_property("output-mode") or "separate-images")
            .strip()
            .lower()
        )
        if not _choice_is_valid(
            output_mode,
            {"separate-images", "layered-image"},
        ):
            _show_error(
                "O modo de saida deve ser separate-images ou layered-image."
            )
            return procedure.new_return_values(
                Gimp.PDBStatusType.CALLING_ERROR,
                None,
            )

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
                _show_error(
                    "Nenhum sprite foi detectado com os parametros atuais."
                )
                return procedure.new_return_values(
                    Gimp.PDBStatusType.EXECUTION_ERROR,
                    None,
                )

            if output_mode == "layered-image":
                result_images = [_create_layered_result_image(sprites, cv2)]
            else:
                result_images = _create_result_images(sprites, cv2)
        except RuntimeError:
            try:
                result_images = _run_external_extraction(
                    image,
                    drawables[0],
                    config,
                )
            except (RuntimeError, OSError, ValueError) as exc:
                _show_error(f"Falha ao processar a camada: {exc}")
                return procedure.new_return_values(
                    Gimp.PDBStatusType.EXECUTION_ERROR,
                    None,
                )

            if not result_images:
                _show_error(
                    "Nenhum sprite foi detectado com os parametros atuais."
                )
                return procedure.new_return_values(
                    Gimp.PDBStatusType.EXECUTION_ERROR,
                    None,
                )
        except (RuntimeError, OSError, ValueError) as exc:
            _show_error(f"Falha ao processar a camada: {exc}")
            return procedure.new_return_values(
                Gimp.PDBStatusType.EXECUTION_ERROR,
                None,
            )

        should_open_result = bool(config.get_property("open-result"))
        if should_open_result and Gimp.Display.name() is not None:
            for result_image in result_images:
                Gimp.Display.new(result_image)

        return procedure.new_return_values(Gimp.PDBStatusType.SUCCESS, None)


Gimp.main(BlueprintMakerGimpPlugin.__gtype__, sys.argv)
