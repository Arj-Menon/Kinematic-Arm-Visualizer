"""
Reusable actuator-preset selector widget.

One row that combines:
  [ QComboBox of preset names + "Custom…" ]
  [ QDoubleSpinBox for the custom kg value ]
  [ "+" QPushButton to save the custom value under a new name ]

Presets are read from / written to `actuators.json` via `actuators_db`.

The host widget (e.g. LiveMTCPanel, MTCWindow) must implement a single
method so new presets can be broadcast to its peer selectors:

    on_preset_added(presets: dict[str, float],
                    select_name: str,
                    origin: ActuatorSelector) -> None
"""

from PyQt6.QtWidgets import (
    QWidget, QComboBox, QDoubleSpinBox, QPushButton, QHBoxLayout,
    QInputDialog, QMessageBox,
)

import actuators_db


CUSTOM_LABEL = "Custom…"


class ActuatorSelector(QWidget):
    """Actuator preset selector. Call `value()` for the effective mass (kg)."""

    def __init__(self, presets: dict[str, float], panel, parent=None):
        super().__init__(parent)
        self._presets = presets
        self._panel = panel
        self.sig_changed = None  # callable set by the owning panel

        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(4)

        self.combo = QComboBox()
        self._repopulate_combo()
        self.combo.currentIndexChanged.connect(self._on_combo_changed)

        self.custom_spin = QDoubleSpinBox()
        self.custom_spin.setRange(0.0, 1000.0)
        self.custom_spin.setDecimals(3)
        self.custom_spin.setSuffix(" kg")
        self.custom_spin.setValue(0.2)
        self.custom_spin.valueChanged.connect(self._on_custom_changed)

        self.btn_add = QPushButton("+")
        self.btn_add.setFixedWidth(24)
        self.btn_add.setToolTip("Save current custom weight as a named preset")
        self.btn_add.clicked.connect(self._on_save_clicked)

        lay.addWidget(self.combo, 1)
        lay.addWidget(self.custom_spin)
        lay.addWidget(self.btn_add)

        self._sync_custom_enabled()

    # ----- public -----------------------------------------------------
    def value(self) -> float:
        if self.combo.currentText() == CUSTOM_LABEL:
            return float(self.custom_spin.value())
        return float(self._presets.get(self.combo.currentText(), 0.0))

    def refresh_presets(self, presets: dict[str, float], keep_selection=True):
        self._presets = presets
        current = self.combo.currentText()
        blocked = self.combo.blockSignals(True)
        self._repopulate_combo()
        if keep_selection:
            idx = self.combo.findText(current)
            if idx >= 0:
                self.combo.setCurrentIndex(idx)
        self.combo.blockSignals(blocked)
        self._sync_custom_enabled()

    # ----- internals --------------------------------------------------
    def _repopulate_combo(self):
        self.combo.clear()
        for name in sorted(self._presets.keys()):
            self.combo.addItem(name)
        self.combo.addItem(CUSTOM_LABEL)

    def _sync_custom_enabled(self):
        is_custom = self.combo.currentText() == CUSTOM_LABEL
        self.custom_spin.setEnabled(is_custom)
        self.btn_add.setEnabled(is_custom)

    def _on_combo_changed(self, _i):
        self._sync_custom_enabled()
        if self.sig_changed:
            self.sig_changed()

    def _on_custom_changed(self, _v):
        if self.sig_changed and self.combo.currentText() == CUSTOM_LABEL:
            self.sig_changed()

    def _on_save_clicked(self):
        name, ok = QInputDialog.getText(
            self, "Save actuator preset",
            "Preset name (e.g. 'NEMA-17 + planetary'):",
        )
        name = (name or "").strip()
        if not ok or not name:
            return
        if name == CUSTOM_LABEL:
            QMessageBox.warning(self, "Reserved name",
                                f"'{CUSTOM_LABEL}' is reserved.")
            return
        updated = actuators_db.add(name, self.custom_spin.value())
        self._panel.on_preset_added(updated, select_name=name, origin=self)
