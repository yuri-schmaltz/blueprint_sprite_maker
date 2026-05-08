"""Instala os arquivos necessarios do plugin na pasta de plugins do GIMP 3."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path


PLUGIN_DIRNAME = "my-blueprint-maker"
DEFAULT_GIMP_VERSION = "3.0"
FILES_TO_COPY = [
    "my-blueprint-maker.py",
    "extrator_sprites_gimp.py",
    "README.md",
    "requirements.txt",
]
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
    appdata = Path.home() / "AppData" / "Roaming"
    gimp_root = appdata / "GIMP"
    if not gimp_root.is_dir():
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
        "Diretorio de destino do plugin. O padrao usa a versao mais recente em "
        "%APPDATA%/GIMP/<versao>/plug-ins/my-blueprint-maker."
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


def install_plugin(target_dir: Path, repo_root: Path | None = None) -> Path:
    repo_root = repo_root or get_repo_root()
    missing_items = collect_missing_items(repo_root)
    if missing_items:
        missing = ", ".join(sorted(missing_items))
        raise FileNotFoundError(f"Itens obrigatorios ausentes no repositorio: {missing}")

    target_dir.mkdir(parents=True, exist_ok=True)

    for file_name in FILES_TO_COPY:
        shutil.copy2(repo_root / file_name, target_dir / file_name)

    for dir_name in DIRECTORIES_TO_COPY:
        source_dir = repo_root / dir_name
        destination_dir = target_dir / dir_name
        if destination_dir.exists():
            shutil.rmtree(destination_dir)
        shutil.copytree(source_dir, destination_dir, ignore=IGNORED_NAMES)

    return target_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Instala o plugin My Blueprint Maker na pasta de plugins do GIMP 3."
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