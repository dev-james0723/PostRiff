"""Entry point for the separate rafii-control Vercel project only."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from rafii_control.hosted import app
