"""Instala o plugin Blueprint Maker na pasta de plugins do GIMP 3+.

Modo de uso (inteligente, autodetecta GIMP e Python com deps):

    python install_gimp_plugin.py             # instala no destino padrao
    python install_gimp_plugin.py status      # mostra estado da instalacao
    python install_gimp_plugin.py uninstall   # remove o plugin instalado

Opcoes uteis:

    --target PATH             instala em outro diretorio (ex: pen drive, outro perfil)
    --python PATH             usa este Python como helper para extracao
    --gimp-profile VERSION    escolhe perfil especifico quando ha varios (ex: 3.0, 3.2)
    --auto-deps               tenta instalar numpy/opencv-python no helper via pip
    --no-backup               nao faz backup da instalacao previa antes de sobrescrever
    --dry-run                 mostra o que faria, sem alterar nada
    --json                    saida em formato JSON (util para scripts)
    --verbose / --quiet       controla nivel de log
"""

from __future__ import annotations

import argparse
import datetime
import json
import logging
import os
import platform
import shutil
import stat
import subprocess
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Constantes publicas (mantidas para retrocompatibilidade com testes/imports)
# ---------------------------------------------------------------------------

PLUGIN_DIRNAME = "blueprint-maker"
LEGACY_PLUGIN_DIRNAMES = (
    "my-blueprint-maker",
)
DEFAULT_GIMP_VERSION = "3.0"
FILES_TO_COPY = [
    "blueprint-maker.py",
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

REQUIRED_HELPER_MODULES = (
    "cv2",
    "numpy",
    "PIL",
)
HELPER_REQUIREMENTS = (
    "numpy",
    "opencv-python",
    "Pillow",
)

_VENV_SEARCH_DIRS_LINUX = (
    ".virtualenvs",
    ".local/share/virtualenvs",
    ".cache/pypoetry/virtualenvs",
    ".local/share/uv",
    ".venvs",
    "venvs",
    "miniconda3/envs",
    "anaconda3/envs",
    "miniforge3/envs",
)
_VENV_SEARCH_DIRS_WINDOWS = (
    "Envs",
    ".virtualenvs",
    "AppData/Local/pypoetry/Cache/virtualenvs",
)


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logger = logging.getLogger("install_gimp_plugin")


def _configure_logging(verbose: bool, quiet: bool) -> None:
    level = logging.WARNING
    if quiet:
        level = logging.ERROR
    elif verbose:
        level = logging.DEBUG
    logging.basicConfig(
        level=level,
        format="[%(levelname)s] %(message)s",
        force=True,
    )


# ---------------------------------------------------------------------------
# Utilidades de filesystem
# ---------------------------------------------------------------------------

def get_repo_root() -> Path:
    return Path(__file__).resolve().parent


def _parse_version_dir(path: Path) -> tuple[int, ...] | None:
    try:
        return tuple(int(part) for part in path.name.split("."))
    except ValueError:
        return None


def _looks_like_blueprint_plugin_dir(plugin_dir: Path) -> bool:
    return (plugin_dir / "extrator_sprites_gimp.py").exists() and any(
        (plugin_dir / launcher_name).exists()
        for launcher_name in ("blueprint-maker.py", "my-blueprint-maker.py")
    )


def _is_writable_dir(path: Path) -> bool:
    """Checa rapidamente se o diretorio (ou seu pai) e gravavel pelo usuario."""
    if not path.exists():
        return os.access(path.parent, os.W_OK)
    return os.access(path, os.W_OK)


# ---------------------------------------------------------------------------
# Descoberta de instalacoes do GIMP
# ---------------------------------------------------------------------------

def _candidate_gimp_roots() -> list[Path]:
    """Retorna todos os diretorios-raiz onde o GIMP pode guardar perfis."""
    system = platform.system()
    home = Path.home()

    candidates: list[Path] = []
    if system == "Windows":
        candidates.append(home / "AppData" / "Roaming" / "GIMP")
    elif system == "Darwin":
        candidates.append(home / "Library" / "Application Support" / "GIMP")
    else:
        # Linux: nativo, Flatpak, Snap
        candidates.append(home / ".config" / "GIMP")
        candidates.append(
            home / ".var" / "app" / "org.gimp.GIMP" / "config" / "GIMP"
        )
        candidates.append(home / "snap" / "gimp" / "common" / ".config" / "GIMP")

    return [root for root in candidates if root.is_dir()]


def list_gimp_profiles() -> list[dict]:
    """Lista todos os perfis GIMP detectados, com a pasta de plug-ins de cada.

    Cada entrada: {"root": Path, "version": str, "version_tuple": tuple,
                   "plugins": Path, "writable": bool}
    """
    profiles: list[dict] = []
    for root in _candidate_gimp_roots():
        if not root.is_dir():
            continue
        for child in root.iterdir():
            if not child.is_dir():
                continue
            parsed = _parse_version_dir(child)
            if parsed is None:
                continue
            plugins_dir = child / "plug-ins"
            profiles.append(
                {
                    "root": child,
                    "version": child.name,
                    "version_tuple": parsed,
                    "plugins": plugins_dir,
                    "writable": _is_writable_dir(plugins_dir),
                }
            )
    profiles.sort(key=lambda p: p["version_tuple"], reverse=True)
    return profiles


def get_default_gimp_plugins_root() -> Path:
    """Mantida para retrocompatibilidade. Retorna a pasta plug-ins mais recente."""
    profiles = list_gimp_profiles()
    if profiles:
        return profiles[0]["plugins"]
    candidates = _candidate_gimp_roots()
    if candidates:
        return candidates[0] / DEFAULT_GIMP_VERSION / "plug-ins"
    return Path.home() / ".config" / "GIMP" / DEFAULT_GIMP_VERSION / "plug-ins"


def get_default_target_dir() -> Path:
    return get_default_gimp_plugins_root() / PLUGIN_DIRNAME


def get_default_target_help() -> str:
    return (
        "Diretorio de destino do plugin. Padrao: detecta automaticamente o "
        "GIMP 3+ (Flatpak, Snap, nativo, multiplas versoes). Use "
        "--gimp-profile para escolher uma versao especifica."
    )


# ---------------------------------------------------------------------------
# Descoberta de interpretadores Python com dependencias
# ---------------------------------------------------------------------------

def _resolve_command_path(name_or_path: str) -> Path | None:
    """Resolve um nome de comando (PATH) ou caminho direto para um arquivo valido."""
    if not name_or_path:
        return None
    candidate = Path(name_or_path)
    if candidate.is_file() and (
        os.access(candidate, os.X_OK) or candidate.suffix.lower() == ".exe"
    ):
        return candidate
    resolved = shutil.which(name_or_path)
    if resolved:
        return Path(resolved)
    return None


def _venv_search_dirs() -> tuple[str, ...]:
    if sys.platform == "win32":
        return _VENV_SEARCH_DIRS_WINDOWS
    return _VENV_SEARCH_DIRS_LINUX


def _discover_venv_pythons() -> list[Path]:
    """Procura executaveis Python dentro de virtualenvs comuns no $HOME."""
    home = Path.home()
    found: list[Path] = []
    seen: set[Path] = set()
    for sub in _venv_search_dirs():
        base = home / sub
        if not base.is_dir():
            continue
        for child in base.iterdir():
            if not child.is_dir():
                continue
            # Layout venv: <env>/bin/python ou <env>/Scripts/python.exe
            for python_path in (
                child / "bin" / "python",
                child / "bin" / "python3",
                child / "Scripts" / "python.exe",
            ):
                if python_path.is_file() and python_path not in seen:
                    seen.add(python_path)
                    found.append(python_path)
    return found


def _discover_workspace_venvs() -> list[Path]:
    """Procura venvs dentro do workspace atual (./.venv, ./venv, ../.venv)."""
    candidates: list[Path] = []
    repo_root = get_repo_root()
    for name in (".venv", "venv", ".env"):
        for base in (repo_root, repo_root.parent):
            venv_dir = base / name
            for sub in ("bin", "Scripts"):
                exe_name = "python.exe" if sys.platform == "win32" else "python"
                python_path = venv_dir / sub / exe_name
                if python_path.is_file():
                    candidates.append(python_path)
    return candidates


def discover_python_candidates() -> list[Path]:
    """Retorna todos os interpretadores Python candidatos a helper, em ordem de
    prioridade (atual, PATH, venvs comuns, venvs do workspace)."""
    seen: set[Path] = set()
    result: list[Path] = []

    def _add(name_or_path: str) -> None:
        path = _resolve_command_path(name_or_path)
        if path is not None and path not in seen:
            seen.add(path)
            result.append(path)

    # 1) O Python que esta rodando o instalador
    _add(sys.executable)

    # 2) Comandos do PATH
    if sys.platform == "win32":
        for cmd in ("py", "python", "python3"):
            _add(cmd)
    else:
        for cmd in ("python3", "python"):
            _add(cmd)

    # 3) Venvs comuns no home
    for python_path in _discover_venv_pythons():
        if python_path not in seen:
            seen.add(python_path)
            result.append(python_path)

    # 4) Venvs do workspace
    for python_path in _discover_workspace_venvs():
        if python_path not in seen:
            seen.add(python_path)
            result.append(python_path)

    return result


def _run_python_probe(python_path: Path, code: str, timeout: float = 10.0) -> tuple[int, str, str]:
    """Executa um snippet de Python e retorna (returncode, stdout, stderr)."""
    try:
        proc = subprocess.run(
            [str(python_path), "-c", code],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, "", f"{type(exc).__name__}: {exc}"


def python_dep_status(
    python_path: Path,
    modules: tuple[str, ...] = REQUIRED_HELPER_MODULES,
) -> dict:
    """Verifica quais modulos estao disponiveis no Python informado.

    Retorna {"python": str, "version": str, "available": [...],
             "missing": [...], "ok": bool, "error": str}
    """
    modules_literal = repr(list(modules))
    code = (
        "import json, sys\n"
        "try:\n"
        "    import importlib\n"
        "    out = {}\n"
        "    for m in " + modules_literal + ":\n"
        "        try:\n"
        "            mod = importlib.import_module(m)\n"
        "            v = getattr(mod, '__version__', '?')\n"
        "            out[m] = v\n"
        "        except Exception:\n"
        "            out[m] = None\n"
        "    print('VERSION', sys.version.split()[0])\n"
        "    print('MODS', json.dumps(out))\n"
        "except Exception as e:\n"
        "    print('ERROR', type(e).__name__, str(e))\n"
    )
    rc, stdout, stderr = _run_python_probe(python_path, code)
    status: dict = {
        "python": str(python_path),
        "version": "",
        "available": [],
        "missing": [],
        "ok": False,
        "error": "",
    }
    if rc != 0 and "ERROR" not in stdout:
        status["error"] = (stderr or stdout).strip() or f"returncode={rc}"
        return status
    for line in stdout.splitlines():
        if line.startswith("VERSION "):
            status["version"] = line[len("VERSION "):].strip()
        elif line.startswith("MODS "):
            try:
                mods = json.loads(line[len("MODS "):])
            except json.JSONDecodeError as exc:
                status["error"] = f"parse error: {exc}"
                return status
            for name, ver in mods.items():
                if ver:
                    status["available"].append({"module": name, "version": str(ver)})
                else:
                    status["missing"].append(name)
        elif line.startswith("ERROR "):
            status["error"] = line[len("ERROR "):].strip()
    status["ok"] = not status["missing"] and not status["error"]
    return status


def resolve_helper_python(
    preferred: str | None = None,
    require_deps: bool = True,
) -> dict:
    """Resolve qual Python usar como helper.

    Retorna {"python": str, "version": str, "source": str, "ok": bool, "status": dict}
    """
    # 1) Override explicito sempre vence
    if preferred:
        override = _resolve_command_path(preferred)
        if override is None:
            return {
                "python": preferred,
                "version": "",
                "source": "override",
                "ok": False,
                "status": {"error": f"Python nao encontrado: {preferred}"},
            }
        status = python_dep_status(override)
        return {
            "python": str(override),
            "version": status["version"],
            "source": "override",
            "ok": (status["ok"] if require_deps else True),
            "status": status,
        }

    # 2) Tenta o Python atual primeiro
    current = _resolve_command_path(sys.executable)
    if current is not None:
        status = python_dep_status(current)
        if status["ok"]:
            return {
                "python": str(current),
                "version": status["version"],
                "source": "current",
                "ok": True,
                "status": status,
            }

    # 3) Procura candidatos na ordem
    for candidate in discover_python_candidates():
        if current is not None and candidate == current:
            continue  # ja avaliado acima
        status = python_dep_status(candidate)
        if status["ok"]:
            source = (
                "candidates:path"
                if candidate.parent.name in ("bin", "Scripts")
                else "candidates:venv"
            )
            return {
                "python": str(candidate),
                "version": status["version"],
                "source": source,
                "ok": True,
                "status": status,
            }

    # 4) Nenhum candidato com deps completas; devolve o atual mesmo sem deps
    if current is not None:
        status = python_dep_status(current)
        return {
            "python": str(current),
            "version": status["version"],
            "source": "current-fallback",
            "ok": False,
            "status": status,
        }
    return {
        "python": "",
        "version": "",
        "source": "none",
        "ok": False,
        "status": {"error": "Nenhum Python encontrado"},
    }


# ---------------------------------------------------------------------------
# Instalacao
# ---------------------------------------------------------------------------

def collect_missing_items(repo_root: Path) -> list[str]:
    missing_items: list[str] = []
    for file_name in FILES_TO_COPY:
        if not (repo_root / file_name).exists():
            missing_items.append(file_name)
    for dir_name in DIRECTORIES_TO_COPY:
        if not (repo_root / dir_name).is_dir():
            missing_items.append(dir_name)
    return missing_items


def write_runtime_config(
    target_dir: Path,
    helper_python: str,
    extra: dict | None = None,
) -> Path:
    config_path = target_dir / RUNTIME_CONFIG_FILENAME
    config: dict = {"helper_python": helper_python}
    if extra:
        config.update(extra)
    config_path.write_text(
        json.dumps(config, ensure_ascii=True, indent=2),
        encoding="utf-8",
    )
    return config_path


def backup_existing_install(target_dir: Path) -> Path | None:
    """Se o destino ja existe, move para <target>.backup-<timestamp> e retorna o backup."""
    if not target_dir.exists():
        return None
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = target_dir.with_name(f"{target_dir.name}.backup-{stamp}")
    if backup.exists():
        # Colisao: incrementa sufixo
        suffix = 1
        while True:
            alt = target_dir.with_name(f"{target_dir.name}.backup-{stamp}-{suffix}")
            if not alt.exists():
                backup = alt
                break
            suffix += 1
    shutil.move(str(target_dir), str(backup))
    return backup


def remove_legacy_plugin_dirs(target_dir: Path) -> list[Path]:
    removed_dirs: list[Path] = []
    plugins_root = target_dir.parent

    for legacy_dirname in LEGACY_PLUGIN_DIRNAMES:
        legacy_dir = plugins_root / legacy_dirname
        if legacy_dir == target_dir or not legacy_dir.is_dir():
            continue
        if not _looks_like_blueprint_plugin_dir(legacy_dir):
            continue

        shutil.rmtree(legacy_dir)
        removed_dirs.append(legacy_dir)

    return removed_dirs


def copy_plugin_files(repo_root: Path, target_dir: Path) -> None:
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


def install_plugin(
    target_dir: Path,
    repo_root: Path | None = None,
    helper_python: str | None = None,
    backup: bool = True,
    skip_legacy_cleanup: bool = False,
) -> dict:
    """Instala o plugin em ``target_dir`` e retorna um relatorio estruturado.

    Chaves do retorno:
        target, helper_python, backup, removed_legacy, files, missing_items, ok, error
    """
    repo_root = repo_root or get_repo_root()
    report: dict = {
        "target": str(target_dir),
        "helper_python": "",
        "backup": None,
        "removed_legacy": [],
        "files": [],
        "missing_items": [],
        "ok": False,
        "error": "",
    }

    missing_items = collect_missing_items(repo_root)
    if missing_items:
        report["missing_items"] = missing_items
        report["error"] = "Itens obrigatorios ausentes: " + ", ".join(sorted(missing_items))
        return report

    if not skip_legacy_cleanup:
        report["removed_legacy"] = [str(p) for p in remove_legacy_plugin_dirs(target_dir)]

    if backup and target_dir.exists():
        backup_path = backup_existing_install(target_dir)
        if backup_path is not None:
            report["backup"] = str(backup_path)
            logger.info("Backup criado em %s", backup_path)

    target_dir.mkdir(parents=True, exist_ok=True)
    copy_plugin_files(repo_root, target_dir)
    report["files"] = list(FILES_TO_COPY) + list(DIRECTORIES_TO_COPY)

    if helper_python is None:
        resolution = resolve_helper_python(require_deps=False)
        helper_python = resolution["python"]
        logger.info(
            "Helper Python escolhido: %s (%s) via %s",
            helper_python,
            resolution["version"] or "?",
            resolution["source"],
        )

    write_runtime_config(target_dir, helper_python)
    report["helper_python"] = helper_python
    report["ok"] = True
    return report


def auto_install_helper_dependencies(
    helper_python: str,
    modules: tuple[str, ...] = REQUIRED_HELPER_MODULES,
    timeout: float = 180.0,
) -> dict:
    """Tenta instalar via pip os modulos faltantes do helper."""
    before_status = python_dep_status(Path(helper_python), modules)
    missing = list(before_status["missing"])
    if not missing:
        return {
            "ok": True,
            "before": before_status,
            "after": before_status,
            "installed": [],
            "log": "Nenhuma dependencia faltando",
        }

    pkg_for_module = {
        m: r for m, r in zip(REQUIRED_HELPER_MODULES, HELPER_REQUIREMENTS)
    }
    pkgs = [pkg_for_module[m] for m in missing if m in pkg_for_module] or list(missing)
    cmd = [helper_python, "-m", "pip", "install", "--quiet", *pkgs]
    logger.info("Executando: %s", " ".join(cmd))
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        log = (proc.stdout + "\n" + proc.stderr).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {
            "ok": False,
            "before": before_status,
            "after": before_status,
            "installed": [],
            "log": f"{type(exc).__name__}: {exc}",
        }

    after_status = python_dep_status(Path(helper_python), modules)
    installed_now = [m for m in missing if m not in after_status["missing"]]
    return {
        "ok": after_status["ok"],
        "before": before_status,
        "after": after_status,
        "installed": installed_now,
        "log": log,
    }


# ---------------------------------------------------------------------------
# Verificacao e status
# ---------------------------------------------------------------------------

def verify_installation(target_dir: Path) -> dict:
    """Inspeciona o que esta em ``target_dir`` e devolve um relatorio estruturado."""
    report: dict = {
        "target": str(target_dir),
        "exists": target_dir.exists(),
        "files_present": [],
        "files_missing": list(FILES_TO_COPY),
        "dirs_present": [],
        "dirs_missing": list(DIRECTORIES_TO_COPY),
        "runtime_config": None,
        "helper_status": None,
        "ok": False,
    }
    if not target_dir.exists():
        return report

    for file_name in FILES_TO_COPY:
        if (target_dir / file_name).is_file():
            report["files_present"].append(file_name)
    report["files_missing"] = [f for f in FILES_TO_COPY if f not in report["files_present"]]

    for dir_name in DIRECTORIES_TO_COPY:
        if (target_dir / dir_name).is_dir():
            report["dirs_present"].append(dir_name)
    report["dirs_missing"] = [d for d in DIRECTORIES_TO_COPY if d not in report["dirs_present"]]

    config_path = target_dir / RUNTIME_CONFIG_FILENAME
    if config_path.is_file():
        try:
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
            report["runtime_config"] = cfg
            helper = str(cfg.get("helper_python", "")).strip()
            if helper:
                helper_path = _resolve_command_path(helper)
                if helper_path is not None:
                    report["helper_status"] = python_dep_status(helper_path)
                else:
                    report["helper_status"] = {"error": f"helper_python inacessivel: {helper}"}
        except (OSError, json.JSONDecodeError) as exc:
            report["runtime_config"] = {"error": f"invalido: {exc}"}

    config_ok = (
        isinstance(report["runtime_config"], dict)
        and "error" not in report["runtime_config"]
    )
    report["ok"] = (
        not report["files_missing"]
        and not report["dirs_missing"]
        and config_ok
    )
    return report


def check_gimp_running() -> bool:
    """Detecta se o GIMP esta rodando (e portanto nao vai recarregar o plugin
    sem reiniciar)."""
    try:
        if sys.platform == "win32":
            out = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq gimp-3*.exe"],
                capture_output=True,
                text=True,
                timeout=4,
            )
            return "gimp" in out.stdout.lower()
        out = subprocess.run(
            ["pgrep", "-f", "gimp"],
            capture_output=True,
            text=True,
            timeout=4,
        )
        return out.returncode == 0 and bool(out.stdout.strip())
    except (OSError, subprocess.TimeoutExpired, FileNotFoundError):
        return False


def _read_version(base: Path) -> str:
    """Le uma versao do projeto procurando em pyproject.toml."""
    path = base / "pyproject.toml"
    if not path.is_file():
        return "?"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return "?"
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("version") and "=" in line:
            _, _, value = line.partition("=")
            value = value.strip().strip('"').strip("'")
            if value:
                return value
            break
    return "?"


def get_installation_status(
    target_dir: Path | None = None,
    repo_root: Path | None = None,
) -> dict:
    """Relatorio completo do estado: instalacao, perfis GIMP, GIMP em execucao."""
    repo_root = repo_root or get_repo_root()
    target_dir = target_dir or get_default_target_dir()
    install = verify_installation(target_dir)
    profiles = list_gimp_profiles()
    return {
        "target": str(target_dir),
        "repo_root": str(repo_root),
        "plugin_source_version": _read_version(repo_root),
        "plugin_installed_version": _read_version(target_dir) if install["exists"] else None,
        "install": install,
        "gimp_profiles": [
            {
                "version": p["version"],
                "root": str(p["root"]),
                "plugins": str(p["plugins"]),
                "writable": p["writable"],
            }
            for p in profiles
        ],
        "gimp_running": check_gimp_running(),
    }


# ---------------------------------------------------------------------------
# Desinstalacao
# ---------------------------------------------------------------------------

def uninstall_plugin(target_dir: Path | None = None) -> dict:
    target_dir = target_dir or get_default_target_dir()
    report = {
        "target": str(target_dir),
        "existed": target_dir.exists(),
        "removed": False,
        "removed_legacy": [],
        "ok": False,
    }
    if not target_dir.exists():
        report["ok"] = True
        return report
    try:
        shutil.rmtree(target_dir)
        report["removed"] = True
    except OSError as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        return report
    # Tambem remove diretorios legados conhecidos
    for legacy_name in LEGACY_PLUGIN_DIRNAMES:
        legacy_dir = target_dir.parent / legacy_name
        if not legacy_dir.is_dir():
            continue
        if _looks_like_blueprint_plugin_dir(legacy_dir):
            try:
                shutil.rmtree(legacy_dir)
                report["removed_legacy"].append(str(legacy_dir))
            except OSError as exc:
                report["error"] = f"legacy {legacy_dir}: {exc}"
    report["ok"] = True
    return report


# ---------------------------------------------------------------------------
# Formatacao de saida
# ---------------------------------------------------------------------------

def _format_status_text(status: dict) -> str:
    install = status["install"]
    lines: list[str] = []
    lines.append("Blueprint Maker - Status da instalacao")
    lines.append("")
    lines.append(f"Alvo:             {status['target']}")
    lines.append(f"Origem (repo):    {status['repo_root']}")
    lines.append(f"Versao fonte:     {status['plugin_source_version']}")
    if status["plugin_installed_version"] is not None:
        match = (
            "OK"
            if status["plugin_installed_version"] == status["plugin_source_version"]
            else "diferente"
        )
        lines.append(
            f"Versao instalada: {status['plugin_installed_version']}  ({match})"
        )

    lines.append("")
    if install["exists"]:
        lines.append("Instalacao: presente")
    else:
        lines.append(
            "Instalacao: AUSENTE "
            "(rode 'python install_gimp_plugin.py' para instalar)"
        )

    if install["exists"]:
        if install["files_missing"]:
            lines.append("Arquivos faltando:")
            for f in install["files_missing"]:
                lines.append(f"  - {f}")
        else:
            lines.append("Arquivos: OK")
        if install["dirs_missing"]:
            lines.append("Diretorios faltando:")
            for d in install["dirs_missing"]:
                lines.append(f"  - {d}/")
        else:
            lines.append("Diretorios: OK")

        cfg = install["runtime_config"]
        if isinstance(cfg, dict) and "error" not in cfg:
            helper = cfg.get("helper_python", "")
            lines.append("")
            lines.append(f"Runtime config: helper_python = {helper or '(vazio)'}")
            hs = install.get("helper_status") or {}
            if hs.get("error"):
                lines.append(f"  erro: {hs['error']}")
            elif hs:
                lines.append(f"  versao: {hs.get('version', '?')}")
                if hs.get("available"):
                    mods = ", ".join(
                        f"{a['module']} {a['version']}" for a in hs["available"]
                    )
                    lines.append(f"  modulos OK: {mods}")
                if hs.get("missing"):
                    lines.append(f"  modulos faltando: {', '.join(hs['missing'])}")
        else:
            err = (
                cfg.get("error", "?") if isinstance(cfg, dict) else "ausente"
            )
            lines.append(f"Runtime config: invalido ({err})")

    if status["gimp_profiles"]:
        lines.append("")
        lines.append("Perfis GIMP detectados:")
        for prof in status["gimp_profiles"]:
            writ = "gravavel" if prof["writable"] else "somente leitura"
            lines.append(f"  - {prof['version']} ({writ}) em {prof['root']}")
    if status["gimp_running"]:
        lines.append("")
        lines.append(
            "Aviso: o GIMP parece estar em execucao. "
            "Reinicie-o para carregar o plugin."
        )

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="install_gimp_plugin",
        description=(
            "Instala o plugin Blueprint Maker na pasta de plugins do GIMP 3+. "
            "Detecta automaticamente o GIMP e o Python com dependencias."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Comandos: install (padrao), status, uninstall.\n"
            "Exemplos:\n"
            "  python install_gimp_plugin.py\n"
            "  python install_gimp_plugin.py --gimp-profile 3.0\n"
            "  python install_gimp_plugin.py status --json\n"
            "  python install_gimp_plugin.py uninstall --target /tmp/test"
        ),
    )
    parser.add_argument(
        "command",
        nargs="?",
        default="install",
        choices=["install", "status", "uninstall"],
        help="Operacao a executar (padrao: install).",
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=None,
        help=get_default_target_help(),
    )
    parser.add_argument(
        "--gimp-profile",
        dest="gimp_profile",
        default=None,
        help="Escolhe perfil GIMP especifico (ex: 3.0, 3.2) quando ha varios.",
    )
    parser.add_argument(
        "--python",
        dest="helper_python",
        default=None,
        help="Caminho/nome do Python a usar como helper para extracao.",
    )
    parser.add_argument(
        "--auto-deps",
        action="store_true",
        help="Tenta instalar dependencias faltantes do helper via pip.",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Nao faz backup da instalacao existente antes de sobrescrever.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Mostra o que seria feito, sem alterar nada.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emite o resultado principal em JSON (util para scripts).",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Log detalhado.",
    )
    parser.add_argument(
        "--quiet", "-q",
        action="store_true",
        help="Log minimo (apenas erros).",
    )
    return parser


def _resolve_target(args: argparse.Namespace) -> Path:
    if args.target is not None:
        return args.target
    profiles = list_gimp_profiles()
    if args.gimp_profile and profiles:
        wanted = tuple(int(p) for p in args.gimp_profile.split("."))
        for prof in profiles:
            if prof["version_tuple"] == wanted:
                return prof["plugins"] / PLUGIN_DIRNAME
    if profiles:
        return profiles[0]["plugins"] / PLUGIN_DIRNAME
    return get_default_target_dir()


def _emit_json(payload: dict) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _cmd_install(args: argparse.Namespace) -> int:
    target_dir = _resolve_target(args)
    profiles = list_gimp_profiles()
    if profiles:
        logger.info(
            "Perfis GIMP detectados: %s",
            ", ".join(p["version"] for p in profiles),
        )

    resolution = resolve_helper_python(preferred=args.helper_python, require_deps=False)
    if not resolution["python"]:
        logger.error("Nenhum Python encontrado para usar como helper.")
        if args.json:
            _emit_json({"ok": False, "error": "no python found"})
        return 1
    if not resolution["ok"] and not args.auto_deps:
        missing = resolution["status"].get("missing", [])
        logger.warning(
            "Helper %s esta sem dependencias: %s. "
            "Use --auto-deps para tentar instalar via pip.",
            resolution["python"],
            ", ".join(missing) or "(desconhecido)",
        )

    if args.dry_run:
        payload = {
            "command": "install",
            "dry_run": True,
            "target": str(target_dir),
            "helper_python": resolution["python"],
            "helper_status": resolution["status"],
            "gimp_profiles": [
                {"version": p["version"], "writable": p["writable"]}
                for p in profiles
            ],
        }
        if args.json:
            _emit_json(payload)
        else:
            print(f"[dry-run] Instalaria em: {target_dir}")
            print(f"[dry-run] Helper Python: {resolution['python']} "
                  f"({resolution['version']})")
            missing = resolution["status"].get("missing", [])
            print(f"[dry-run] Faltam deps no helper: "
                  f"{', '.join(missing) if missing else 'nenhuma'}")
        return 0

    if check_gimp_running():
        logger.warning(
            "GIMP parece estar em execucao. Reinicie o GIMP apos a instalacao "
            "para o plugin aparecer no menu."
        )

    report = install_plugin(
        target_dir=target_dir,
        helper_python=resolution["python"],
        backup=not args.no_backup,
    )

    auto_deps_result = None
    if args.auto_deps and not resolution["ok"]:
        logger.warning("Tentando instalar dependencias via pip...")
        auto_deps_result = auto_install_helper_dependencies(resolution["python"])
        if auto_deps_result["ok"]:
            logger.info(
                "Dependencias instaladas: %s",
                ", ".join(auto_deps_result["installed"]) or "(nenhuma)",
            )
        else:
            logger.error(
                "Falha ao instalar dependencias: %s",
                auto_deps_result["log"][:600],
            )

    verify = verify_installation(target_dir)
    payload = {
        "command": "install",
        "ok": report["ok"] and verify.get("ok", False),
        "report": report,
        "verify": verify,
        "auto_deps": auto_deps_result,
    }

    if args.json:
        _emit_json(payload)
    else:
        if report["ok"]:
            print(f"Plugin instalado em {report['target']}")
            print(f"Helper Python: {report['helper_python']}")
            if report.get("backup"):
                print(f"Backup da instalacao anterior: {report['backup']}")
            if report.get("removed_legacy"):
                print(f"Diretorios legados removidos: "
                      f"{', '.join(report['removed_legacy'])}")
            if verify.get("helper_status"):
                hs = verify["helper_status"]
                if hs.get("available"):
                    mods = ", ".join(
                        f"{a['module']} {a['version']}"
                        for a in hs["available"]
                    )
                    print(f"Dependencias OK: {mods}")
                elif hs.get("missing"):
                    print(f"Dependencias faltando no helper: "
                          f"{', '.join(hs['missing'])}. Use --auto-deps.")
            if auto_deps_result:
                if auto_deps_result["ok"]:
                    print(f"pip install OK: "
                          f"{', '.join(auto_deps_result['installed']) or '(nenhuma)'}")
                else:
                    print("pip install falhou - veja o log acima.")
            print("Reinicie o GIMP 3+ para recarregar o menu do plugin.")
        else:
            print(f"Falha: {report.get('error', '?')}")
        return 0 if report["ok"] else 1
    return 0 if report["ok"] else 1


def _cmd_status(args: argparse.Namespace) -> int:
    target_dir = _resolve_target(args)
    status = get_installation_status(target_dir)
    if args.json:
        _emit_json(status)
    else:
        print(_format_status_text(status))
    return 0


def _cmd_uninstall(args: argparse.Namespace) -> int:
    target_dir = _resolve_target(args)
    if not args.target:
        # Confirma apenas quando estamos prestes a apagar o padrao
        if not args.dry_run and target_dir.exists():
            logger.warning(
                "Removendo %s (use --target para confirmar).", target_dir
            )
    report = uninstall_plugin(target_dir)
    if args.json:
        _emit_json(report)
    else:
        if report["removed"]:
            print(f"Plugin removido de {report['target']}")
        elif report["existed"]:
            print(f"Falha ao remover {report['target']}: "
                  f"{report.get('error', '?')}")
            return 1
        else:
            print(f"Nada a remover em {report['target']} (ja estava ausente).")
        for legacy in report.get("removed_legacy", []):
            print(f"Legacy removido: {legacy}")
    return 0 if report["ok"] else 1


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Funcao publica preservada para retrocompatibilidade (pyproject entry point)."""
    parser = _build_arg_parser()
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    parser = _build_arg_parser()
    args = parser.parse_args(argv)
    _configure_logging(verbose=args.verbose, quiet=args.quiet)

    if args.command == "install":
        return _cmd_install(args)
    if args.command == "status":
        return _cmd_status(args)
    if args.command == "uninstall":
        return _cmd_uninstall(args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
