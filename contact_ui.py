"""
contact_ui.py
─────────────
Launcher shim for the Streamlit UI.
Installed as the `contact-ui` entry point by pyproject.toml.
"""

import subprocess
import sys
from pathlib import Path


def run():
    app = Path(__file__).parent / "app.py"
    subprocess.run(
        [sys.executable, "-m", "streamlit", "run", str(app), "--"] + sys.argv[1:]
    )
