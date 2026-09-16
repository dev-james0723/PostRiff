"""Vercel Services entrypoint for the hosted PostRiff Phase 2 API."""
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"
if str(SOURCE) not in sys.path:
    sys.path.insert(0, str(SOURCE))

from postriff_phase2.hosted_app import app  # noqa: E402,F401
