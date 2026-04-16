"""
Motor Torque Calculator (MTC).

Standalone QDialog that mirrors the in-visualizer Live MTC Tracker:
  * Link Inputs: length (m) + link weight (kg).
  * Actuators (per joint): preset combo + custom kg spin + "+" save-as
    button, sharing the same actuators.json database as the live panel.
  * Payload (kg) acting at the end-effector.

Worst-case static holding torque, arm fully horizontal:

    τ_j = Σ_{i≥j} m_link_i · g · (X_mid_i − X_j)     # link torques
        + Σ_{k>j} m_act_k  · g · (X_joint_k − X_j)  # actuators outboard of j
        + m_payload · g · (X_end − X_j)             # payload at end-effector

The actuator at joint j itself is excluded — it sits on the pivot and
creates no moment arm about it.
"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel,
    QDoubleSpinBox, QWidget, QDialogButtonBox, QFrame, QScrollArea,
    QPushButton, QTextEdit,
)

from actuator_selector import ActuatorSelector
import actuators_db


G = 9.81  # m/s²


# -------------------------------------------------------------------------
def compute_torques(lengths_m: list[float],
                    weights_kg: list[float]) -> list[float]:
    """Return torque (N·m) at every joint; links-only (no actuators/payload)."""
    n_links = len(lengths_m)
    if n_links == 0 or len(weights_kg) != n_links:
        return []
    return compute_torques_full(
        lengths_m=lengths_m,
        link_masses=weights_kg,
        actuator_masses=[0.0] * (n_links + 1),
        payload_mass=0.0,
    )


def compute_torques_full(
    lengths_m: list[float],
    link_masses: list[float],
    actuator_masses: list[float],
    payload_mass: float,
) -> list[float]:
    """Full-fidelity worst-case static holding torque at every joint."""
    n_links = len(lengths_m)
    if n_links == 0:
        return []
    n_joints = n_links + 1
    if len(link_masses) != n_links or len(actuator_masses) != n_joints:
        return []

    joint_pos = [0.0]
    for L in lengths_m:
        joint_pos.append(joint_pos[-1] + L)
    link_mid = [joint_pos[i] + lengths_m[i] / 2.0 for i in range(n_links)]
    x_end = joint_pos[-1]

    torques: list[float] = []
    for j in range(n_joints):
        xj = joint_pos[j]
        t = 0.0
        for i in range(j, n_links):
            t += link_masses[i] * G * (link_mid[i] - xj)
        for k in range(j + 1, n_joints):
            t += actuator_masses[k] * G * (joint_pos[k] - xj)
        t += payload_mass * G * (x_end - xj)
        torques.append(t)
    return torques


def compute_torques_with_breakdown(
    lengths_m: list[float],
    link_masses: list[float],
    actuator_masses: list[float],
    payload_mass: float,
    joint_labels: list[str] | None = None,
) -> tuple[list[float], str]:
    """
    Worst-case static holding torques plus a human-readable audit log.

    Returns (torques, breakdown_text). Same physics as
    `compute_torques_full`, but each individual moment contribution
    (mass * g * lever_arm) is listed on its own line so the user can
    manually verify what the backend is doing.
    """
    n_links = len(lengths_m)
    if n_links == 0:
        return [], "(no links — nothing to compute)"
    n_joints = n_links + 1
    if len(link_masses) != n_links or len(actuator_masses) != n_joints:
        return [], "(input size mismatch — cannot build breakdown)"
    if joint_labels is None or len(joint_labels) != n_joints:
        joint_labels = [f"J{i + 1}" for i in range(n_joints)]

    joint_pos = [0.0]
    for L in lengths_m:
        joint_pos.append(joint_pos[-1] + L)
    link_mid = [joint_pos[i] + lengths_m[i] / 2.0 for i in range(n_links)]
    x_end = joint_pos[-1]

    lines: list[str] = []
    lines.append("Motor Torque Calculation — Math Breakdown")
    lines.append("=" * 56)
    lines.append(f"g = {G} m/s^2   (arm horizontal; link COM at midpoint)")
    lines.append("")
    lines.append("Joint X-positions along the arm (m):")
    for lbl, x in zip(joint_labels, joint_pos):
        lines.append(f"  {lbl:>6s} : x = {x:.3f} m")
    lines.append(f"  {'x_end':>6s} : x = {x_end:.3f} m  (end-effector)")
    lines.append("")
    lines.append("-" * 56)

    torques: list[float] = []
    for j in range(n_joints):
        xj = joint_pos[j]
        lines.append(
            f"Joint {joint_labels[j]} Breakdown "
            f"(pivot at x = {xj:.3f} m):"
        )

        t = 0.0
        contributed = False

        # Link contributions (links outboard of or including this joint).
        for i in range(j, n_links):
            m = link_masses[i]
            arm = link_mid[i] - xj
            mom = m * G * arm
            t += mom
            lines.append(
                f"  - Link {i + 1} Moment:     "
                f"{m:.3f} kg * {G:.2f} m/s^2 * {arm:.3f} m = {mom:.2f} N.m"
            )
            contributed = True

        # Outboard actuators (the actuator at joint j itself sits on the
        # pivot — zero moment arm, so it is excluded).
        for k in range(j + 1, n_joints):
            m = actuator_masses[k]
            if m <= 0.0:
                continue
            arm = joint_pos[k] - xj
            mom = m * G * arm
            t += mom
            lines.append(
                f"  - Actuator {joint_labels[k]} Moment: "
                f"{m:.3f} kg * {G:.2f} m/s^2 * {arm:.3f} m = {mom:.2f} N.m"
            )
            contributed = True

        # End-effector payload.
        if payload_mass > 0.0:
            arm = x_end - xj
            mom = payload_mass * G * arm
            t += mom
            lines.append(
                f"  - Payload Moment:      "
                f"{payload_mass:.3f} kg * {G:.2f} m/s^2 * {arm:.3f} m = "
                f"{mom:.2f} N.m"
            )
            contributed = True

        if not contributed:
            lines.append("  (no outboard masses — zero torque)")
        lines.append(f"  -> Total {joint_labels[j]} Torque = {t:.2f} N.m")
        lines.append("")
        torques.append(t)

    return torques, "\n".join(lines)


# -------------------------------------------------------------------------
class MathBreakdownDialog(QDialog):
    """Read-only pop-up showing the step-by-step MTC math breakdown."""

    def __init__(self, breakdown_text: str, parent=None,
                 title: str = "MTC Math Breakdown"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(720, 540)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)

        hint = QLabel(
            "Step-by-step audit of the torque at every joint. "
            "Each line is a single moment contribution: "
            "<i>mass × g × lever-arm</i>. Read-only."
        )
        hint.setWordWrap(True)
        lay.addWidget(hint)

        self.text = QTextEdit()
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(QTextEdit.LineWrapMode.NoWrap)
        self.text.setStyleSheet(
            "font-family: Consolas, 'Courier New', monospace; "
            "font-size: 10pt;"
        )
        self.text.setPlainText(breakdown_text)
        lay.addWidget(self.text, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        lay.addWidget(buttons)


# -------------------------------------------------------------------------
class MTCWindow(QDialog):
    """Standalone motor-torque calculator dialog (mirrors the live panel)."""

    def __init__(self,
                 chain: str = "Y-P-P-R-P-R",
                 total_length_mm: float = 600.0,
                 arm_label: str = "",
                 parent=None):
        super().__init__(parent)
        title = ("Motor Torque Calculator"
                 + (f" — {arm_label}" if arm_label else ""))
        self.setWindowTitle(title)
        self.resize(640, 760)

        self.joint_tokens = [t.strip().upper()
                             for t in chain.split("-") if t.strip()] or ["Y"]
        self.n_joints = len(self.joint_tokens)
        self.n_links = max(self.n_joints - 1, 1)

        default_len_per_link_m = (total_length_mm / 1000.0) / self.n_links

        # Joint labels (Y1, P1, P2, R1, ...) — consistent with other UI.
        counters: dict[str, int] = {}
        self.joint_labels: list[str] = []
        for tok in self.joint_tokens:
            counters[tok] = counters.get(tok, 0) + 1
            self.joint_labels.append(f"{tok}{counters[tok]}")

        self._presets = actuators_db.load()

        # -- Scrollable root --
        root_widget = QWidget(self)
        root = QVBoxLayout(root_widget)
        root.setContentsMargins(10, 10, 10, 10)

        header = QLabel(
            f"<h3>Motor Torque Calculator</h3>"
            f"<p>Chain: <b>{chain}</b> &nbsp; "
            f"Joints: {self.n_joints} &nbsp; Links: {self.n_links}<br>"
            "Worst-case static holding torque with the arm fully "
            "horizontal; link COM at midpoint. Accounts for link masses, "
            "outboard actuator masses, and an end-effector payload.</p>"
        )
        header.setWordWrap(True)
        root.addWidget(header)

        # ---------- Link Inputs ----------
        link_frame = QFrame()
        link_frame.setFrameShape(QFrame.Shape.StyledPanel)
        link_v = QVBoxLayout(link_frame)
        link_v.addWidget(QLabel("<b>Link Inputs</b>"))

        link_grid = QGridLayout()
        link_grid.addWidget(QLabel("<b>#</b>"), 0, 0)
        link_grid.addWidget(QLabel("<b>Length</b>"), 0, 1)
        link_grid.addWidget(QLabel("<b>Link Weight</b>"), 0, 2)

        self.length_spins: list[QDoubleSpinBox] = []
        self.link_weight_spins: list[QDoubleSpinBox] = []
        for i in range(self.n_links):
            link_grid.addWidget(QLabel(f"L{i + 1}"), i + 1, 0)

            ls = QDoubleSpinBox()
            ls.setRange(0.001, 100.0)
            ls.setDecimals(3)
            ls.setSuffix(" m")
            ls.setValue(default_len_per_link_m)
            ls.valueChanged.connect(self._recompute)
            link_grid.addWidget(ls, i + 1, 1)
            self.length_spins.append(ls)

            ws = QDoubleSpinBox()
            ws.setRange(0.0, 1000.0)
            ws.setDecimals(3)
            ws.setSuffix(" kg")
            ws.setValue(1.0)
            ws.valueChanged.connect(self._recompute)
            link_grid.addWidget(ws, i + 1, 2)
            self.link_weight_spins.append(ws)
        link_v.addLayout(link_grid)
        root.addWidget(link_frame)

        # ---------- Actuators (per joint) ----------
        act_frame = QFrame()
        act_frame.setFrameShape(QFrame.Shape.StyledPanel)
        act_v = QVBoxLayout(act_frame)
        act_v.addWidget(QLabel("<b>Actuators (per joint)</b>"))

        act_grid = QGridLayout()
        act_grid.addWidget(QLabel("<b>Joint</b>"), 0, 0)
        act_grid.addWidget(QLabel("<b>Actuator Preset</b>"), 0, 1)

        self.actuator_selectors: list[ActuatorSelector] = []
        for i, joint_label in enumerate(self.joint_labels):
            act_grid.addWidget(QLabel(joint_label), i + 1, 0)
            sel = ActuatorSelector(self._presets, self)
            sel.sig_changed = self._recompute
            act_grid.addWidget(sel, i + 1, 1)
            self.actuator_selectors.append(sel)
        act_v.addLayout(act_grid)
        root.addWidget(act_frame)

        # ---------- Payload ----------
        pay_frame = QFrame()
        pay_frame.setFrameShape(QFrame.Shape.StyledPanel)
        pay_layout = QHBoxLayout(pay_frame)
        pay_layout.addWidget(QLabel("<b>Payload</b> (at end-effector):"))
        self.payload_spin = QDoubleSpinBox()
        self.payload_spin.setRange(0.0, 1000.0)
        self.payload_spin.setDecimals(3)
        self.payload_spin.setSuffix(" kg")
        self.payload_spin.setValue(0.0)
        self.payload_spin.valueChanged.connect(self._recompute)
        pay_layout.addWidget(self.payload_spin)
        pay_layout.addStretch(1)
        root.addWidget(pay_frame)

        # ---------- Outputs ----------
        out_frame = QFrame()
        out_frame.setFrameShape(QFrame.Shape.StyledPanel)
        out_v = QVBoxLayout(out_frame)
        out_v.addWidget(QLabel("<b>Required Holding Torque per Joint</b>"))

        out_grid = QGridLayout()
        out_grid.addWidget(QLabel("<b>Joint</b>"), 0, 0)
        out_grid.addWidget(QLabel("<b>Torque (N·m)</b>"), 0, 1)

        self.torque_labels: list[QLabel] = []
        for i, joint_label in enumerate(self.joint_labels):
            out_grid.addWidget(QLabel(joint_label), i + 1, 0)
            lbl = QLabel("0.00")
            lbl.setStyleSheet(
                "font-family: Consolas, monospace; font-weight: bold;"
                " padding: 2px 8px;"
            )
            out_grid.addWidget(lbl, i + 1, 1)
            self.torque_labels.append(lbl)
        out_v.addLayout(out_grid)
        root.addWidget(out_frame)

        # ---------- Math Verification ----------
        self.btn_breakdown = QPushButton("Show Math Breakdown")
        self.btn_breakdown.setToolTip(
            "Open an audit view listing every force × lever-arm "
            "term contributing to each joint's torque."
        )
        self.btn_breakdown.clicked.connect(self._show_breakdown)
        root.addWidget(self.btn_breakdown)
        root.addStretch(1)

        scroll = QScrollArea(self)
        scroll.setWidget(root_widget)
        scroll.setWidgetResizable(True)

        # ---------- Dialog buttons ----------
        dlg_layout = QVBoxLayout(self)
        dlg_layout.setContentsMargins(0, 0, 0, 0)
        dlg_layout.addWidget(scroll)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        dlg_layout.addWidget(buttons)

        self._recompute()

    # ----------------------------------------------------------------
    def on_preset_added(self, presets: dict[str, float],
                        select_name: str, origin: ActuatorSelector):
        """Broadcast a newly-saved preset to every selector in this dialog."""
        self._presets = presets
        for sel in self.actuator_selectors:
            if sel is origin:
                sel.refresh_presets(presets, keep_selection=False)
                idx = sel.combo.findText(select_name)
                if idx >= 0:
                    sel.combo.setCurrentIndex(idx)
            else:
                sel.refresh_presets(presets, keep_selection=True)
        self._recompute()

    def _recompute(self):
        lengths = [s.value() for s in self.length_spins]
        link_masses = [s.value() for s in self.link_weight_spins]
        actuator_masses = [sel.value() for sel in self.actuator_selectors]
        payload = float(self.payload_spin.value())

        torques = compute_torques_full(
            lengths_m=lengths,
            link_masses=link_masses,
            actuator_masses=actuator_masses,
            payload_mass=payload,
        )
        for i, lbl in enumerate(self.torque_labels):
            if i < len(torques):
                lbl.setText(f"{torques[i]:.2f}")
            else:
                lbl.setText("—")

    # ----------------------------------------------------------------
    def _show_breakdown(self):
        """Pop up a read-only dialog with the full math breakdown."""
        lengths = [s.value() for s in self.length_spins]
        link_masses = [s.value() for s in self.link_weight_spins]
        actuator_masses = [sel.value() for sel in self.actuator_selectors]
        payload = float(self.payload_spin.value())

        _torques, text = compute_torques_with_breakdown(
            lengths_m=lengths,
            link_masses=link_masses,
            actuator_masses=actuator_masses,
            payload_mass=payload,
            joint_labels=self.joint_labels,
        )
        dlg = MathBreakdownDialog(text, self, title="MTC Math Breakdown")
        dlg.exec()
