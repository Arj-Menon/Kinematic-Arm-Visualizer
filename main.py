"""
Entry point for the Robotic Arm Manager + Interactive Kinematic Sandbox.

Run:
    python main.py
"""

import sys

from PyQt6.QtWidgets import QApplication

from main_window import MainWindow
from updater import check_for_updates

CURRENT_VERSION = "v1.0.0"


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Robotic Arm Manager")
    win = MainWindow(current_version=CURRENT_VERSION)
    win.show()
    check_for_updates(CURRENT_VERSION, parent=win, silent_if_no_update=True)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
