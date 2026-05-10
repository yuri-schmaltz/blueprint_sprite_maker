#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import runpy
import sys
from pathlib import Path


PLUGIN_DIR = Path(__file__).resolve().parent
PLUGIN_ENTRYPOINT = PLUGIN_DIR / "extrator_sprites_gimp.py"


def main() -> int:
    if str(PLUGIN_DIR) not in sys.path:
        sys.path.insert(0, str(PLUGIN_DIR))

    runpy.run_path(str(PLUGIN_ENTRYPOINT), run_name="__main__")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())