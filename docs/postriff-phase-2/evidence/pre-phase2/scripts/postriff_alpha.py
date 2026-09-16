#!/usr/bin/env python3
"""Run from any directory; the alpha never imports legacy Studio bindings."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from postriff_alpha.server import main

if __name__ == "__main__":
    main()
