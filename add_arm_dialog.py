"""Modal dialog for entering a new robotic arm record."""

from PyQt6.QtWidgets import (
    QDialog, QFormLayout, QLineEdit, QDoubleSpinBox, QDialogButtonBox,
    QMessageBox,
)


class AddArmDialog(QDialog):
    """Collects a new arm entry. Access `.data()` after exec() succeeds."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add New Arm")
        self.setModal(True)

        self.company = QLineEdit()
        self.model = QLineEdit()
        self.chain = QLineEdit()
        self.chain.setPlaceholderText("e.g. Y-P-P-R-P-R")

        self.payload = QDoubleSpinBox()
        self.payload.setSuffix(" kg")
        self.payload.setRange(0.0, 100000.0)
        self.payload.setDecimals(2)

        self.weight = QDoubleSpinBox()
        self.weight.setSuffix(" kg")
        self.weight.setRange(0.0, 100000.0)
        self.weight.setDecimals(2)

        self.cost = QDoubleSpinBox()
        self.cost.setPrefix("$ ")
        self.cost.setRange(0.0, 1e9)
        self.cost.setDecimals(2)
        self.cost.setGroupSeparatorShown(True)

        self.max_length = QDoubleSpinBox()
        self.max_length.setSuffix(" mm")
        self.max_length.setRange(0.0, 1e6)
        self.max_length.setDecimals(1)

        form = QFormLayout(self)
        form.addRow("Company:", self.company)
        form.addRow("Model:", self.model)
        form.addRow("Kinematic Chain:", self.chain)
        form.addRow("Payload:", self.payload)
        form.addRow("Weight:", self.weight)
        form.addRow("Cost:", self.cost)
        form.addRow("Max Length:", self.max_length)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._try_accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def _try_accept(self):
        if not self.company.text().strip() or not self.model.text().strip():
            QMessageBox.warning(self, "Missing data",
                                "Company and Model are required.")
            return
        if not self.chain.text().strip():
            QMessageBox.warning(self, "Missing data",
                                "Kinematic Chain is required "
                                "(e.g. Y-P-P-R-P-R).")
            return
        self.accept()

    def data(self) -> dict:
        return {
            "Company": self.company.text().strip(),
            "Model": self.model.text().strip(),
            "Kinematic Chain": self.chain.text().strip(),
            "Payload [Kg]": self.payload.value(),
            "Weight [Kg]": self.weight.value(),
            "Cost": self.cost.value(),
            "Max Length [mm]": self.max_length.value(),
        }
