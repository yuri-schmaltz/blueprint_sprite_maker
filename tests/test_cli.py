"""
Tests for main.py CLI argument parsing
"""

import subprocess
import sys


def test_cli_version():
    """Test that --version flag returns the correct version string"""
    result = subprocess.run(
        [sys.executable, "main.py", "--version"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "Blueprint Maker 1.1.1" in result.stdout


def test_cli_help():
    """Test that --help flag returns usage instructions"""
    result = subprocess.run(
        [sys.executable, "main.py", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "usage: main.py" in result.stdout


def test_cli_invalid_arg():
    """Test that invalid arguments are handled gracefully by argparse"""
    result = subprocess.run(
        [sys.executable, "main.py", "--invalid-flag"],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "unrecognized arguments: --invalid-flag" in result.stderr
