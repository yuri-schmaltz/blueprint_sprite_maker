"""Instala os arquivos necessarios do plugin na pasta de plugins do GIMP 3."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import stat
import sys
from pathlib import Path


PLUGIN_DIRNAME = "my-blueprint-maker"
DEFAULT_GIMP_VERSION = "3.0"
FILES_TO_COPY = [
    "my-blueprint-maker.py",
    "extrator_sprites_gimp.py",
    "external_sprite_runner.py",
    "README.md",
    "requirements.txt",
]
RUNTIME_CONFIG_FILENAME = "plugin_runtime_config.json"
DIRECTORIES_TO_COPY = [
    "components",
    "core",
    "gui",
    "locales",
    "resources",
]
IGNORED_NAMES = shutil.ignore_patterns(
    "__pycache__",
    "*.pyc",
    "*.pyo",
    ".pytest_cache",
)


def get_repo_root() -> Path:
    return Path(__file__).resolve().parent


def _parse_version_dir(path: Path) -> tuple[int, ...] | None:
    try:
        return tuple(int(part) for part in path.name.split("."))
    except ValueError:
        return None


def get_default_gimp_plugins_root() -> Path:
    system = platform.system()
    home = Path.home()

    possible_roots = []
    if system == "Windows":
        possible_roots.append(home / "AppData" / "Roaming" / "GIMP")
    elif system == "Darwin":
        possible_roots.append(
            home / "Library" / "Application Support" / "GIMP"
        )
    else:
        possible_roots.append(home / ".config" / "GIMP")
        possible_roots.append(
            home / ".var" / "app" / "org.gimp.GIMP" / "config" / "GIMP"
        )

    gimp_root = None
    for root in possible_roots:
        if root.is_dir():
            gimp_root = root
            break

    if gimp_root is None:
        gimp_root = possible_roots[0]
        return gimp_root / DEFAULT_GIMP_VERSION / "plug-ins"

    version_dirs = []
    for child in gimp_root.iterdir():
        if not child.is_dir():
            continue
        parsed_version = _parse_version_dir(child)
        if parsed_version is not None:
            version_dirs.append((parsed_version, child))

    if not version_dirs:
        return gimp_root / DEFAULT_GIMP_VERSION / "plug-ins"

    return max(version_dirs, key=lambda item: item[0])[1] / "plug-ins"


def get_default_target_dir() -> Path:
    return get_default_gimp_plugins_root() / PLUGIN_DIRNAME


def get_default_target_help() -> str:
    return (
        "Diretorio de destino do plugin. O padrao detecta automaticamente a "
        "versao mais recente do GIMP "
        "(Windows, macOS, Linux Flatpak/AppImage/Nativo)."
    )


def collect_missing_items(repo_root: Path) -> list[str]:
    missing_items: list[str] = []
    for file_name in FILES_TO_COPY:
        if not (repo_root / file_name).exists():
            missing_items.append(file_name)
    for dir_name in DIRECTORIES_TO_COPY:
        if not (repo_root / dir_name).is_dir():
            missing_items.append(dir_name)
    return missing_items


def write_runtime_config(target_dir: Path) -> Path:
    config_path = target_dir / RUNTIME_CONFIG_FILENAME
    config = {"helper_python": sys.executable}
    config_path.write_text(
        json.dumps(config, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
    return config_path


def install_plugin(target_dir: Path, repo_root: Path | None = None) -> Path:
    repo_root = repo_root or get_repo_root()
    missing_items = collect_missing_items(repo_root)
    if missing_items:
        missing = ", ".join(sorted(missing_items))
        raise FileNotFoundError(
            f"Itens obrigatorios ausentes no repositorio: {missing}"
        )

    target_dir.mkdir(parents=True, exist_ok=True)

    for file_name in FILES_TO_COPY:
        dest_file = target_dir / file_name
        shutil.copy2(repo_root / file_name, dest_file)
        if dest_file.suffix == ".py" and platform.system() != "Windows":
            os.chmod(dest_file, dest_file.stat().st_mode | stat.S_IEXEC)

    for dir_name in DIRECTORIES_TO_COPY:
        source_dir = repo_root / dir_name
        destination_dir = target_dir / dir_name
        if destination_dir.exists():
            shutil.rmtree(destination_dir)
        shutil.copytree(source_dir, destination_dir, ignore=IGNORED_NAMES)

    write_runtime_config(target_dir)

    return target_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Instala o plugin My Blueprint Maker na pasta de plugins "
        "do GIMP 3."
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=get_default_target_dir(),
        help=get_default_target_help(),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    installed_dir = install_plugin(args.target)
    print(f"Plugin instalado em: {installed_dir}")
    print("Reinicie o GIMP 3+ para recarregar o menu do plugin.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
