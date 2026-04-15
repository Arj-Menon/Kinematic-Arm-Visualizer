"""Dialog for explicitly editing a joint's type (Y/P/R) and number."""

from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QComboBox, QSpinBox, QDialogButtonBox,
)


KIND_CHOICES = [
    ("Y", "Yaw (square)"),
    ("P", "Pitch (circle)"),
    ("R", "Roll (triangle)"),
]


class EditJointDialog(QDialog):
    """Returns (kind, number) on accept."""

    def __init__(self, current_kind: str, current_number: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Edit Joint")
        self.setModal(True)

        self.kind_combo = QComboBox()
        for k, label in KIND_CHOICES:
            self.kind_combo.addItem(label, k)
        # Select the matching row
        for i in range(self.kind_combo.count()):
            if self.kind_combo.itemData(i) == current_kind.upper():
                self.kind_combo.setCurrentIndex(i)
                break

        self.number_spin = QSpinBox()
        self.number_spin.setRange(1, 99)
        self.number_spin.setValue(max(1, current_number))

        form = QFormLayout(self)
        form.addRow("Joint type:", self.kind_combo)
        form.addRow("Joint number:", self.number_spin)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def result_kind(self) -> str:
        return self.kind_combo.currentData()

    def result_number(self) -> int:
        return self.number_spin.value()
