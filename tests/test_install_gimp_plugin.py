import json
import platform
from pathlib import Path

import install_gimp_plugin


def test_parse_version_dir_handles_numeric_directories():
    assert install_gimp_plugin._parse_version_dir(Path("3.2")) == (3, 2)
    assert install_gimp_plugin._parse_version_dir(Path("3.0")) == (3, 0)
    assert install_gimp_plugin._parse_version_dir(Path("dev")) is None


def test_get_default_gimp_plugins_root_uses_latest_profile(
    monkeypatch,
    tmp_path,
):
    fake_home = tmp_path / "home"
    monkeypatch.setattr(platform, "system", lambda: "Windows")
    gimp_root = fake_home / "AppData" / "Roaming" / "GIMP"
    (gimp_root / "3.0").mkdir(parents=True)
    (gimp_root / "3.2").mkdir(parents=True)
    (gimp_root / "dev").mkdir(parents=True)

    monkeypatch.setattr(install_gimp_plugin.Path, "home", lambda: fake_home)

    plugins_root = install_gimp_plugin.get_default_gimp_plugins_root()

    assert plugins_root == gimp_root / "3.2" / "plug-ins"


def test_collect_missing_items_detects_absent_entries(tmp_path):
    missing = install_gimp_plugin.collect_missing_items(tmp_path)

    assert "blueprint-maker.py" in missing
    assert "extrator_sprites_gimp.py" in missing
    assert "external_sprite_runner.py" in missing
    assert "core" in missing


def test_install_plugin_copies_required_structure(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    target_dir = tmp_path / "target"

    for file_name in install_gimp_plugin.FILES_TO_COPY:
        (repo_root / file_name).write_text(
            f"content for {file_name}",
            encoding="utf-8",
        )

    for dir_name in install_gimp_plugin.DIRECTORIES_TO_COPY:
        source_dir = repo_root / dir_name
        source_dir.mkdir()
        (source_dir / "sample.txt").write_text(dir_name, encoding="utf-8")
        pycache_dir = source_dir / "__pycache__"
        pycache_dir.mkdir()
        (pycache_dir / "ignored.pyc").write_bytes(b"cache")

    report = install_gimp_plugin.install_plugin(
        target_dir,
        repo_root=repo_root,
    )

    assert report["ok"] is True
    assert Path(report["target"]) == target_dir
    assert report["helper_python"]  # resolved by smart resolver
    for file_name in install_gimp_plugin.FILES_TO_COPY:
        assert (target_dir / file_name).exists()

    runtime_config = json.loads(
        (target_dir / install_gimp_plugin.RUNTIME_CONFIG_FILENAME).read_text(
            encoding="utf-8"
        )
    )
    assert runtime_config["helper_python"]

    for dir_name in install_gimp_plugin.DIRECTORIES_TO_COPY:
        assert (target_dir / dir_name / "sample.txt").exists()
        assert not (target_dir / dir_name / "__pycache__").exists()


def test_install_plugin_replaces_existing_directories(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    target_dir = tmp_path / "target"
    target_dir.mkdir()

    for file_name in install_gimp_plugin.FILES_TO_COPY:
        (repo_root / file_name).write_text(file_name, encoding="utf-8")

    for dir_name in install_gimp_plugin.DIRECTORIES_TO_COPY:
        source_dir = repo_root / dir_name
        source_dir.mkdir()
        (source_dir / "fresh.txt").write_text("fresh", encoding="utf-8")

        stale_dir = target_dir / dir_name
        stale_dir.mkdir()
        (stale_dir / "stale.txt").write_text("stale", encoding="utf-8")

    report = install_gimp_plugin.install_plugin(target_dir, repo_root=repo_root)
    assert report["ok"] is True

    for dir_name in install_gimp_plugin.DIRECTORIES_TO_COPY:
        assert (target_dir / dir_name / "fresh.txt").exists()
        assert not (target_dir / dir_name / "stale.txt").exists()


def test_install_plugin_removes_legacy_blueprint_directory(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    target_dir = tmp_path / install_gimp_plugin.PLUGIN_DIRNAME
    legacy_dir = tmp_path / install_gimp_plugin.LEGACY_PLUGIN_DIRNAMES[0]
    legacy_dir.mkdir()

    for file_name in install_gimp_plugin.FILES_TO_COPY:
        (repo_root / file_name).write_text(file_name, encoding="utf-8")

    for dir_name in install_gimp_plugin.DIRECTORIES_TO_COPY:
        source_dir = repo_root / dir_name
        source_dir.mkdir()
        (source_dir / "fresh.txt").write_text("fresh", encoding="utf-8")

    (legacy_dir / "extrator_sprites_gimp.py").write_text(
        "legacy",
        encoding="utf-8",
    )
    (legacy_dir / "my-blueprint-maker.py").write_text(
        "legacy",
        encoding="utf-8",
    )

    report = install_gimp_plugin.install_plugin(target_dir, repo_root=repo_root)
    assert report["ok"] is True

    assert not legacy_dir.exists()
    assert any("blueprint" in p for p in report["removed_legacy"])


def test_release_bundle_includes_plugin_installer():
    repo_root = Path(__file__).resolve().parents[1]
    release_dir = (
        repo_root / "release_build" / install_gimp_plugin.PLUGIN_DIRNAME
    )
    source_installer = repo_root / "install_gimp_plugin.py"
    bundled_installer = release_dir / "install_gimp_plugin.py"

    assert release_dir.is_dir()
    assert bundled_installer.exists()
    bundled_text = bundled_installer.read_text(encoding="utf-8")
    source_text = source_installer.read_text(encoding="utf-8")

    assert bundled_text == source_text


def test_release_bundle_runtime_config_is_not_platform_pinned():
    repo_root = Path(__file__).resolve().parents[1]
    runtime_config_path = (
        repo_root
        / "release_build"
        / install_gimp_plugin.PLUGIN_DIRNAME
        / install_gimp_plugin.RUNTIME_CONFIG_FILENAME
    )

    runtime_config = json.loads(
        runtime_config_path.read_text(encoding="utf-8")
    )

    assert runtime_config == {"helper_python": ""}


def test_release_bundle_runtime_helper_matches_source():
    repo_root = Path(__file__).resolve().parents[1]
    source_helper = repo_root / "core" / "runtime_config.py"
    bundled_helper = (
        repo_root
        / "release_build"
        / install_gimp_plugin.PLUGIN_DIRNAME
        / "core"
        / "runtime_config.py"
    )

    assert bundled_helper.read_text(
        encoding="utf-8"
    ) == source_helper.read_text(
        encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Cobertura das funcionalidades inteligentes (discovery, backup, status, uninstall)
# ---------------------------------------------------------------------------

import subprocess as _subprocess  # noqa: E402


def test_list_gimp_profiles_finds_multiple_versions(monkeypatch, tmp_path):
    fake_home = tmp_path / "home"
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(install_gimp_plugin.Path, "home", lambda: fake_home)
    gimp_root = fake_home / ".config" / "GIMP"
    (gimp_root / "3.0" / "plug-ins").mkdir(parents=True)
    (gimp_root / "3.2" / "plug-ins").mkdir(parents=True)
    (gimp_root / "dev").mkdir(parents=True)  # ignorado: nao-numerico

    profiles = install_gimp_plugin.list_gimp_profiles()

    versions = [p["version"] for p in profiles]
    assert versions == ["3.2", "3.0"]  # ordem decrescente
    assert profiles[0]["plugins"] == gimp_root / "3.2" / "plug-ins"


def test_list_gimp_profiles_includes_flatpak_root(monkeypatch, tmp_path):
    fake_home = tmp_path / "home"
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(install_gimp_plugin.Path, "home", lambda: fake_home)
    flatpak_root = (
        fake_home / ".var" / "app" / "org.gimp.GIMP" / "config" / "GIMP"
    )
    (flatpak_root / "3.2" / "plug-ins").mkdir(parents=True)

    profiles = install_gimp_plugin.list_gimp_profiles()

    assert any(
        str(p["root"]).startswith(str(flatpak_root)) for p in profiles
    )


def test_get_default_gimp_plugins_root_falls_back_to_home(
    monkeypatch, tmp_path
):
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(install_gimp_plugin.Path, "home", lambda: tmp_path)

    plugins_root = install_gimp_plugin.get_default_gimp_plugins_root()

    assert plugins_root == tmp_path / ".config" / "GIMP" / "3.0" / "plug-ins"


def test_discover_python_candidates_includes_current():
    candidates = install_gimp_plugin.discover_python_candidates()
    assert any(
        Path(c) == Path(install_gimp_plugin.sys.executable) for c in candidates
    )


def test_python_dep_status_reports_missing_module(tmp_path):
    # Usa o Python que roda pytest, que tem numpy/opencv do requirements.txt
    python_path = Path(install_gimp_plugin.sys.executable)

    status = install_gimp_plugin.python_dep_status(python_path, modules=("numpy",))

    assert status["ok"]
    assert any(a["module"] == "numpy" for a in status["available"])


def test_python_dep_status_reports_missing_when_module_absent(tmp_path):
    python_path = Path(install_gimp_plugin.sys.executable)
    status = install_gimp_plugin.python_dep_status(
        python_path, modules=("definitely_not_a_real_module_qwerty",)
    )
    assert not status["ok"]
    assert "definitely_not_a_real_module_qwerty" in status["missing"]


def test_resolve_helper_python_prefers_python_with_deps(monkeypatch):
    current = Path(install_gimp_plugin.sys.executable)

    resolution = install_gimp_plugin.resolve_helper_python(preferred=str(current))
    assert resolution["ok"]
    assert resolution["source"] == "override"
    assert Path(resolution["python"]) == current


def test_resolve_helper_python_returns_error_for_missing_override():
    resolution = install_gimp_plugin.resolve_helper_python(
        preferred="/nonexistent/python/binary"
    )
    assert not resolution["ok"]
    assert "nao encontrado" in resolution["status"]["error"]


def test_backup_existing_install_creates_timestamped_copy(tmp_path):
    target = tmp_path / "blueprint-maker"
    target.mkdir()
    (target / "blueprint-maker.py").write_text("v1", encoding="utf-8")

    backup = install_gimp_plugin.backup_existing_install(target)

    assert backup is not None
    assert backup.exists()
    assert backup.name.startswith("blueprint-maker.backup-")
    assert (backup / "blueprint-maker.py").read_text(encoding="utf-8") == "v1"
    assert not target.exists()


def test_backup_existing_install_noop_when_missing(tmp_path):
    target = tmp_path / "blueprint-maker"
    assert install_gimp_plugin.backup_existing_install(target) is None


def test_install_plugin_supports_no_backup(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    (target_dir / "old.txt").write_text("old", encoding="utf-8")

    for file_name in install_gimp_plugin.FILES_TO_COPY:
        (repo_root / file_name).write_text(file_name, encoding="utf-8")
    for dir_name in install_gimp_plugin.DIRECTORIES_TO_COPY:
        (repo_root / dir_name).mkdir()

    report = install_gimp_plugin.install_plugin(
        target_dir,
        repo_root=repo_root,
        backup=False,
        helper_python=install_gimp_plugin.sys.executable,
    )
    assert report["ok"]
    assert report["backup"] is None
    # Sem backup, target do conteudo do install
    assert (target_dir / "blueprint-maker.py").exists()


def test_install_plugin_with_explicit_helper_python(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    target_dir = tmp_path / "target"

    for file_name in install_gimp_plugin.FILES_TO_COPY:
        (repo_root / file_name).write_text(file_name, encoding="utf-8")
    for dir_name in install_gimp_plugin.DIRECTORIES_TO_COPY:
        (repo_root / dir_name).mkdir()

    explicit = install_gimp_plugin.sys.executable
    report = install_gimp_plugin.install_plugin(
        target_dir,
        repo_root=repo_root,
        helper_python=explicit,
        backup=False,
    )
    assert report["helper_python"] == explicit
    cfg = json.loads(
        (target_dir / install_gimp_plugin.RUNTIME_CONFIG_FILENAME).read_text(
            encoding="utf-8"
        )
    )
    assert cfg["helper_python"] == explicit


def test_install_plugin_reports_missing_repo_items(tmp_path):
    repo_root = tmp_path / "empty"
    repo_root.mkdir()
    target_dir = tmp_path / "target"

    report = install_gimp_plugin.install_plugin(
        target_dir, repo_root=repo_root, backup=False
    )
    assert not report["ok"]
    assert report["missing_items"]
    assert "blueprint-maker.py" in report["missing_items"]


def test_uninstall_plugin_removes_directory(tmp_path):
    target = tmp_path / "blueprint-maker"
    target.mkdir()
    (target / "blueprint-maker.py").write_text("x", encoding="utf-8")

    report = install_gimp_plugin.uninstall_plugin(target)

    assert report["ok"]
    assert report["removed"]
    assert not target.exists()


def test_uninstall_plugin_handles_missing_directory(tmp_path):
    target = tmp_path / "blueprint-maker"
    report = install_gimp_plugin.uninstall_plugin(target)
    assert report["ok"]
    assert not report["removed"]


def test_verify_installation_detects_missing_files(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    target_dir = tmp_path / "target"
    target_dir.mkdir()

    # Cria apenas alguns arquivos
    (target_dir / "blueprint-maker.py").write_text("x", encoding="utf-8")

    verify = install_gimp_plugin.verify_installation(target_dir)
    assert verify["exists"]
    assert "blueprint-maker.py" in verify["files_present"]
    assert "extrator_sprites_gimp.py" in verify["files_missing"]
    assert not verify["ok"]


def test_verify_installation_reports_helper_deps(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    target_dir = tmp_path / "target"
    target_dir.mkdir()
    for f in install_gimp_plugin.FILES_TO_COPY:
        (target_dir / f).write_text(f, encoding="utf-8")
    for d in install_gimp_plugin.DIRECTORIES_TO_COPY:
        (target_dir / d).mkdir()

    helper = install_gimp_plugin.sys.executable
    install_gimp_plugin.write_runtime_config(target_dir, helper)

    verify = install_gimp_plugin.verify_installation(target_dir)
    assert verify["ok"]
    assert verify["runtime_config"]["helper_python"] == helper
    assert verify["helper_status"] is not None
    assert verify["helper_status"]["version"]


def test_get_installation_status_full_report(tmp_path, monkeypatch):
    fake_home = tmp_path / "home"
    monkeypatch.setattr(platform, "system", lambda: "Linux")
    monkeypatch.setattr(install_gimp_plugin.Path, "home", lambda: fake_home)
    gimp_root = fake_home / ".config" / "GIMP"
    (gimp_root / "3.0" / "plug-ins").mkdir(parents=True)

    target = gimp_root / "3.0" / "plug-ins" / install_gimp_plugin.PLUGIN_DIRNAME
    status = install_gimp_plugin.get_installation_status(target_dir=target)

    assert status["target"] == str(target)
    assert status["plugin_source_version"]  # veio do pyproject
    assert not status["install"]["exists"]
    assert status["gimp_profiles"][0]["version"] == "3.0"


def test_check_gimp_running_returns_bool(monkeypatch):
    # Substitui subprocess.run para retornar saidas previsiveis
    class FakeProc:
        returncode = 1
        stderr = ""
        stdout = ""

    monkeypatch.setattr(
        install_gimp_plugin.subprocess, "run",
        lambda *a, **k: FakeProc(),
    )
    assert install_gimp_plugin.check_gimp_running() is False


def test_auto_install_helper_dependencies_is_noop_when_complete():
    helper = install_gimp_plugin.sys.executable
    result = install_gimp_plugin.auto_install_helper_dependencies(
        helper, modules=("numpy",)
    )
    assert result["ok"]
    assert result["installed"] == []
    assert "Nenhuma" in result["log"]


# ---------------------------------------------------------------------------
# CLI (subcomandos install / status / uninstall)
# ---------------------------------------------------------------------------


def test_cli_status_default_emits_text(capsys):
    code = install_gimp_plugin.main(["status", "--target", "/no/such/bpm/dir"])
    assert code == 0
    out = capsys.readouterr().out
    assert "Status da instalacao" in out
    assert "Instalacao: AUSENTE" in out


def test_cli_status_json_emits_valid_json(capsys):
    code = install_gimp_plugin.main(
        ["status", "--target", "/no/such/bpm/dir", "--json"]
    )
    assert code == 0
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert "install" in parsed
    assert "gimp_profiles" in parsed


def test_cli_install_dry_run(tmp_path):
    target = tmp_path / "bpm"
    code = install_gimp_plugin.main(
        ["install", "--target", str(target), "--dry-run"]
    )
    assert code == 0
    assert not target.exists()  # nada foi criado


def test_cli_install_creates_target(tmp_path):
    repo_root = install_gimp_plugin.get_repo_root()
    target = tmp_path / "bpm"
    code = install_gimp_plugin.main(
        ["install", "--target", str(target), "--python", install_gimp_plugin.sys.executable]
    )
    assert code == 0
    assert target.is_dir()
    assert (target / "blueprint-maker.py").exists()
    cfg = json.loads(
        (target / install_gimp_plugin.RUNTIME_CONFIG_FILENAME).read_text(
            encoding="utf-8"
        )
    )
    assert cfg["helper_python"] == install_gimp_plugin.sys.executable
    _ = repo_root  # noqa: F841


def test_cli_install_json_emits_report(capsys, tmp_path):
    target = tmp_path / "bpm"
    code = install_gimp_plugin.main(
        [
            "install",
            "--target", str(target),
            "--python", install_gimp_plugin.sys.executable,
            "--json",
        ]
    )
    assert code == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["ok"] is True
    assert parsed["report"]["target"] == str(target)


def test_cli_uninstall_removes_target(tmp_path):
    target = tmp_path / "bpm"
    target.mkdir()
    (target / "blueprint-maker.py").write_text("x", encoding="utf-8")

    code = install_gimp_plugin.main(["uninstall", "--target", str(target)])
    assert code == 0
    assert not target.exists()


def test_cli_uninstall_handles_missing(tmp_path):
    target = tmp_path / "bpm"
    code = install_gimp_plugin.main(["uninstall", "--target", str(target)])
    assert code == 0


def test_cli_unknown_command_returns_error():
    # argparse chama sys.exit(2) diretamente em flag desconhecida
    import pytest as _pytest
    with _pytest.raises(SystemExit) as excinfo:
        install_gimp_plugin.main(["--unknown-flag"])
    assert excinfo.value.code != 0


def test_cli_help_works(capsys):
    # argparse chama sys.exit(0) diretamente em --help
    import pytest as _pytest
    with _pytest.raises(SystemExit) as excinfo:
        install_gimp_plugin.main(["--help"])
    assert excinfo.value.code == 0
