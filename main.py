"""
Entry point for the Robotic Arm Manager + Interactive Kinematic Sandbox.

Run:
    python main.py
"""

import sys

from PyQt6.QtWidgets import QApplication

from main_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Robotic Arm Manager")
    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
