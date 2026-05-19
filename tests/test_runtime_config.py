from core import runtime_config


def test_resolve_helper_python_command_uses_configured_path(tmp_path):
    helper_path = tmp_path / "python.exe"
    helper_path.write_text("", encoding="utf-8")
    config_path = tmp_path / runtime_config.RUNTIME_CONFIG_FILENAME
    config_path.write_text(
        '{"helper_python": "%s"}' % helper_path.as_posix(),
        encoding="utf-8",
    )

    resolved_command = runtime_config.resolve_helper_python_command(
        config_path
    )

    assert resolved_command == [str(helper_path)]


def test_resolve_helper_python_command_uses_windows_py_fallback(
    monkeypatch,
    tmp_path,
):
    config_path = tmp_path / runtime_config.RUNTIME_CONFIG_FILENAME
    config_path.write_text(
        '{"helper_python": "/usr/bin/python"}',
        encoding="utf-8",
    )

    monkeypatch.setattr(runtime_config.sys, "platform", "win32")
    monkeypatch.setattr(
        runtime_config.shutil,
        "which",
        lambda command_name: (
            r"C:\\Windows\\py.exe" if command_name == "py" else None
        ),
    )

    resolved_command = runtime_config.resolve_helper_python_command(
        config_path
    )

    assert resolved_command == [r"C:\Windows\py.exe", "-3"]


def test_resolve_helper_python_command_returns_empty_without_candidates(
    monkeypatch,
    tmp_path,
):
    config_path = tmp_path / runtime_config.RUNTIME_CONFIG_FILENAME

    monkeypatch.setattr(runtime_config.sys, "platform", "win32")
    monkeypatch.setattr(runtime_config.shutil, "which", lambda _: None)

    resolved_command = runtime_config.resolve_helper_python_command(
        config_path
    )

    assert resolved_command == []
