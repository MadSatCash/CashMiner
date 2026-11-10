"""Abrir CashMiner sin consola en Windows (doble clic: Pythonw)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from cashminer.app.logging_setup import run_gui
run_gui(show_error_dialog=True)
