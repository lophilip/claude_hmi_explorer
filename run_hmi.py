"""Substation HMI with a configurable DNP3 outstation.

Usage:  python run_hmi.py [project.json]
"""
import logging
import sys

from PySide6.QtWidgets import QApplication

from substation_hmi.main_window import MainWindow, apply_dark_palette


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    app = QApplication(sys.argv)
    app.setApplicationName("Substation HMI")
    apply_dark_palette(app)
    win = MainWindow(sys.argv[1] if len(sys.argv) > 1 else None)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
