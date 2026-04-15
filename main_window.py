"""
Main application window: browse robotic arms from robotic_arms.xlsx and launch
the Interactive Kinematic Sandbox for a selected row.
"""

from pathlib import Path

import pandas as pd
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QAction
from PyQt6.QtWidgets import (
    QMainWindow, QTableView, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QMessageBox, QFileDialog, QAbstractItemView,
)

from pandas_model import PandasModel
from visualizer_window import VisualizerWindow
from add_arm_dialog import AddArmDialog


DEFAULT_XLSX = Path(__file__).parent / "robotic_arms.xlsx"

EXPECTED_COLUMNS = [
    "Company", "Model", "Kinematic Chain",
    "Payload [Kg]", "Weight [Kg]", "Cost", "Max Length [mm]",
]

# Map legacy / unbracketed header names to the canonical ones above.
HEADER_RENAME_MAP = {
    "Kinematic": "Kinematic Chain",
    "Kinematic chain": "Kinematic Chain",
    "Payload": "Payload [Kg]",
    "Payload (Kg)": "Payload [Kg]",
    "Payload_kg": "Payload [Kg]",
    "Weight": "Weight [Kg]",
    "Weight (Kg)": "Weight [Kg]",
    "Weight_kg": "Weight [Kg]",
    "Max Length": "Max Length [mm]",
    "Max length": "Max Length [mm]",
    "MaxLength": "Max Length [mm]",
    "Max Length (mm)": "Max Length [mm]",
}


def _normalize_headers(df):
    """Rename known legacy columns, drop duplicates, enforce canonical order."""
    df = df.rename(columns=HEADER_RENAME_MAP)
    # Remove duplicate-named columns (keep first occurrence).
    df = df.loc[:, ~df.columns.duplicated()]
    # Add any missing canonical columns as blanks.
    for col in EXPECTED_COLUMNS:
        if col not in df.columns:
            df[col] = ""
    # Enforce canonical order; keep unknown extras at the end.
    extras = [c for c in df.columns if c not in EXPECTED_COLUMNS]
    return df[EXPECTED_COLUMNS + extras].copy()


class MainWindow(QMainWindow):
    """Top-level window with the arm catalogue table."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Robotic Arm Manager")
        self.resize(1000, 600)

        self.df = pd.DataFrame(columns=EXPECTED_COLUMNS)
        self._visualizers = []  # keep references so windows aren't GC'd
        self.current_xlsx = DEFAULT_XLSX

        self._build_ui()
        self._load_excel(DEFAULT_XLSX)

    # ------------------------------------------------------------------
    def _build_ui(self):
        central = QWidget(self)
        layout = QVBoxLayout(central)

        header = QLabel("<h2>Robotic Arm Catalogue</h2>")
        layout.addWidget(header)

        self.table = QTableView(self)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setSortingEnabled(True)
        self.table.setAlternatingRowColors(True)
        layout.addWidget(self.table)

        btn_row = QHBoxLayout()
        self.btn_reload = QPushButton("Reload Excel…")
        self.btn_add = QPushButton("Add New Arm…")
        self.btn_launch = QPushButton("Launch Visualizer")
        self.btn_launch.setDefault(True)
        btn_row.addWidget(self.btn_reload)
        btn_row.addWidget(self.btn_add)
        btn_row.addStretch(1)
        btn_row.addWidget(self.btn_launch)
        layout.addLayout(btn_row)

        self.setCentralWidget(central)

        # File menu
        act_open = QAction("&Open Excel…", self)
        act_open.triggered.connect(self._pick_excel)
        act_quit = QAction("&Quit", self)
        act_quit.triggered.connect(self.close)
        file_menu = self.menuBar().addMenu("&File")
        file_menu.addAction(act_open)
        file_menu.addSeparator()
        file_menu.addAction(act_quit)

        # Signals
        self.btn_reload.clicked.connect(lambda: self._load_excel(self.current_xlsx))
        self.btn_add.clicked.connect(self._add_arm)
        self.btn_launch.clicked.connect(self._launch_visualizer)
        self.table.doubleClicked.connect(lambda _ix: self._launch_visualizer())

    # ------------------------------------------------------------------
    def _pick_excel(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open robotic arm catalogue",
            str(DEFAULT_XLSX.parent), "Excel files (*.xlsx *.xlsm)",
        )
        if path:
            self._load_excel(Path(path))

    def _load_excel(self, path: Path):
        if not path.exists():
            QMessageBox.warning(self, "File missing",
                                f"Could not find {path}.\n"
                                "You can open another file from File → Open Excel.")
            return
        try:
            df = pd.read_excel(path)
        except Exception as exc:  # openpyxl errors, etc.
            QMessageBox.critical(self, "Load error", f"Failed to read Excel:\n{exc}")
            return

        # Keep/align expected columns (add missing as blank, preserve extras after)
        for col in EXPECTED_COLUMNS:
            if col not in df.columns:
                df[col] = ""
        ordered = EXPECTED_COLUMNS + [c for c in df.columns if c not in EXPECTED_COLUMNS]
        self.df = df[ordered].copy()
        self.current_xlsx = path

        self.table.setModel(PandasModel(self.df))
        self.table.resizeColumnsToContents()

    def _refresh_table(self):
        self.table.setModel(PandasModel(self.df))
        self.table.resizeColumnsToContents()

    def _add_arm(self):
        dlg = AddArmDialog(self)
        if dlg.exec() != dlg.DialogCode.Accepted:
            return
        new_row = dlg.data()

        # Append to in-memory df (preserve column order & any extras).
        self.df = pd.concat(
            [self.df, pd.DataFrame([new_row])], ignore_index=True
        )

        # Persist to Excel.
        try:
            self.df.to_excel(self.current_xlsx, index=False)
        except Exception as exc:
            QMessageBox.critical(
                self, "Save error",
                f"Added in memory but failed to write {self.current_xlsx}:\n{exc}",
            )
        self._refresh_table()

    # ------------------------------------------------------------------
    def _selected_row(self) -> dict | None:
        sel = self.table.selectionModel()
        if sel is None or not sel.hasSelection():
            return None
        row = sel.selectedRows()[0].row()
        return self.df.iloc[row].to_dict()

    def _launch_visualizer(self):
        row = self._selected_row()
        default_cfg = "Y-P-P-R-P-R"
        default_len = 600.0
        arm_label = ""
        if row is not None:
            chain = str(row.get("Kinematic Chain", "") or "").strip()
            if chain:
                default_cfg = chain
            try:
                ml = float(row.get("Max Length", 0) or 0)
                if ml > 0:
                    default_len = ml
            except (TypeError, ValueError):
                pass
            arm_label = f"{row.get('Company', '')} {row.get('Model', '')}".strip()

        win = VisualizerWindow.prompt_and_launch(
            self, arm_label=arm_label,
            default_config=default_cfg,
            default_length_mm=default_len,
        )
        if win is not None:
            self._visualizers.append(win)
