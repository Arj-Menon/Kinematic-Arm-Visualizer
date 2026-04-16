"""
Motor Torque Calculator (MTC).

Standalone QDialog that computes the worst-case static holding torque at
each joint of a robotic arm assumed to be fully extended horizontally.

Assumptions:
  * Each link's centre of mass is exactly at its midpoint.
  * Only the outboard links contribute to each joint's torque.

For joint i with position p_i and links j = i .. n-1 (each with length
l_j, weight w_j, and COM at p_j + l_j/2):

    tau_i = Σ_j  w_j * g * (p_j + l_j/2 - p_i)
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton,
    QDoubleSpinBox, QWidget, QDialogButtonBox, QFrame, QScrollArea,
)


G = 9.81  # m/s²


# -------------------------------------------------------------------------
def compute_torques(lengths_m: list[float],
                    weights_kg: list[float]) -> list[float]:
    """Return torque (N·m) required at every joint (n_joints = n_links + 1).

    Joint i holds every link j >= i in bending (horizontal extension).
    The last joint (tip) has nothing outboard, so its torque is 0.
    """
    n_links = len(lengths_m)
    if n_links == 0 or len(weights_kg) != n_links:
        return []
    # Cumulative joint positions from the base (joint 0 at 0.0).
    joint_pos = [0.0]
    for L in lengths_m:
        joint_pos.append(joint_pos[-1] + L)
    link_com = [joint_pos[j] + lengths_m[j] / 2.0 for j in range(n_links)]

    torques = []
    for i in range(n_links + 1):
        t = 0.0
        for j in range(i, n_links):
            d = link_com[j] - joint_pos[i]
            t += weights_kg[j] * G * d
        torques.append(t)
    return torques


# -------------------------------------------------------------------------
class MTCWindow(QDialog):
    """Standalone motor-torque calculator dialog."""

    def __init__(self,
                 chain: str = "Y-P-P-R-P-R",
                 total_length_mm: float = 600.0,
                 arm_label: str = "",
                 parent=None):
        super().__init__(parent)
        title = ("Motor Torque Calculator"
                 + (f" — {arm_label}" if arm_label else ""))
        self.setWindowTitle(title)
        self.resize(560, 620)

        self.joint_tokens = [t.strip().upper()
                             for t in chain.split("-") if t.strip()] or ["Y"]
        self.n_joints = len(self.joint_tokens)
        self.n_links = max(self.n_joints - 1, 1)

        default_len_per_link_m = (total_length_mm / 1000.0) / self.n_links

        root = QVBoxLayout(self)

        # Header
        header = QLabel(
            f"<h3>Motor Torque Calculator</h3>"
            f"<p>Chain: <b>{chain}</b> &nbsp; "
            f"Joints: {self.n_joints} &nbsp; Links: {self.n_links}<br>"
            "Worst-case static holding torque with the arm fully extended "
            "horizontally; each link's COM sits at its midpoint.</p>"
        )
        header.setWordWrap(True)
        root.addWidget(header)

        # ---------- Inputs ----------
        in_frame = QFrame(); in_frame.setFrameShape(QFrame.Shape.StyledPanel)
        in_layout = QVBoxLayout(in_frame)
        in_layout.addWidget(QLabel("<b>Link Inputs</b>"))

        in_grid = QGridLayout()
        in_grid.addWidget(QLabel("<b>Link</b>"), 0, 0)
        in_grid.addWidget(QLabel("<b>Length</b>"), 0, 1)
        in_grid.addWidget(QLabel("<b>Weight</b>"), 0, 2)

        self.length_spins: list[QDoubleSpinBox] = []
        self.weight_spins: list[QDoubleSpinBox] = []

        for i in range(self.n_links):
            in_grid.addWidget(QLabel(f"L{i + 1}"), i + 1, 0)

            ls = QDoubleSpinBox()
            ls.setRange(0.001, 100.0)
            ls.setDecimals(3)
            ls.setSuffix(" m")
            ls.setValue(default_len_per_link_m)
            ls.valueChanged.connect(self._recompute)
            in_grid.addWidget(ls, i + 1, 1)
            self.length_spins.append(ls)

            ws = QDoubleSpinBox()
            ws.setRange(0.0, 1000.0)
            ws.setDecimals(3)
            ws.setSuffix(" kg")
            ws.setValue(1.0)
            ws.valueChanged.connect(self._recompute)
            in_grid.addWidget(ws, i + 1, 2)
            self.weight_spins.append(ws)

        in_layout.addLayout(in_grid)
        root.addWidget(in_frame)

        # ---------- Outputs ----------
        out_frame = QFrame(); out_frame.setFrameShape(QFrame.Shape.StyledPanel)
        out_layout = QVBoxLayout(out_frame)
        out_layout.addWidget(QLabel("<b>Required Holding Torque per Joint</b>"))

        out_grid = QGridLayout()
        out_grid.addWidget(QLabel("<b>Joint</b>"), 0, 0)
        out_grid.addWidget(QLabel("<b>Torque (N·m)</b>"), 0, 1)

        self.torque_labels: list[QLabel] = []
        counters: dict[str, int] = {}
        for i, tok in enumerate(self.joint_tokens):
            counters[tok] = counters.get(tok, 0) + 1
            out_grid.addWidget(QLabel(f"{tok}{counters[tok]}"), i + 1, 0)
            lbl = QLabel("0.00")
            lbl.setStyleSheet(
                "font-family: Consolas, monospace; font-weight: bold;"
                " padding: 2px 8px;"
            )
            out_grid.addWidget(lbl, i + 1, 1)
            self.torque_labels.append(lbl)
        out_layout.addLayout(out_grid)
        root.addWidget(out_frame)

        # ---------- Buttons ----------
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        root.addWidget(buttons)

        self._recompute()

    # ----------------------------------------------------------------
    def _recompute(self):
        lengths = [s.value() for s in self.length_spins]
        weights = [s.value() for s in self.weight_spins]
        torques = compute_torques(lengths, weights)
        for i, lbl in enumerate(self.torque_labels):
            if i < len(torques):
                lbl.setText(f"{torques[i]:.2f}")
            else:
                lbl.setText("—")
