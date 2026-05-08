from pathlib import Path

import install_gimp_plugin


def test_parse_version_dir_handles_numeric_directories():
    assert install_gimp_plugin._parse_version_dir(Path("3.2")) == (3, 2)
    assert install_gimp_plugin._parse_version_dir(Path("3.0")) == (3, 0)
    assert install_gimp_plugin._parse_version_dir(Path("dev")) is None


def test_get_default_gimp_plugins_root_uses_latest_profile(monkeypatch, tmp_path):
    fake_home = tmp_path / "home"
    gimp_root = fake_home / "AppData" / "Roaming" / "GIMP"
    (gimp_root / "3.0").mkdir(parents=True)
    (gimp_root / "3.2").mkdir(parents=True)
    (gimp_root / "dev").mkdir(parents=True)

    monkeypatch.setattr(install_gimp_plugin.Path, "home", lambda: fake_home)

    plugins_root = install_gimp_plugin.get_default_gimp_plugins_root()

    assert plugins_root == gimp_root / "3.2" / "plug-ins"


def test_collect_missing_items_detects_absent_entries(tmp_path):
    missing = install_gimp_plugin.collect_missing_items(tmp_path)

    assert "my-blueprint-maker.py" in missing
    assert "extrator_sprites_gimp.py" in missing
    assert "core" in missing


def test_install_plugin_copies_required_structure(tmp_path):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    target_dir = tmp_path / "target"

    for file_name in install_gimp_plugin.FILES_TO_COPY:
        (repo_root / file_name).write_text(f"content for {file_name}", encoding="utf-8")

    for dir_name in install_gimp_plugin.DIRECTORIES_TO_COPY:
        source_dir = repo_root / dir_name
        source_dir.mkdir()
        (source_dir / "sample.txt").write_text(dir_name, encoding="utf-8")
        pycache_dir = source_dir / "__pycache__"
        pycache_dir.mkdir()
        (pycache_dir / "ignored.pyc").write_bytes(b"cache")

    installed_dir = install_gimp_plugin.install_plugin(target_dir, repo_root=repo_root)

    assert installed_dir == target_dir
    for file_name in install_gimp_plugin.FILES_TO_COPY:
        assert (target_dir / file_name).exists()

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

    install_gimp_plugin.install_plugin(target_dir, repo_root=repo_root)

    for dir_name in install_gimp_plugin.DIRECTORIES_TO_COPY:
        assert (target_dir / dir_name / "fresh.txt").exists()
        assert not (target_dir / dir_name / "stale.txt").exists()