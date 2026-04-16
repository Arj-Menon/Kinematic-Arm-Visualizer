"""Motor-torque physics and read-only breakdown dialog.

Physics (per joint, regime selected by joint type letter):

  * Pitch (P) — static gravity-holding torque
        tau = sum_outboard( m_i * g * r_i )
        r_i = horizontal distance from the pivot to component i's true
        location along the arm. Arm assumed fully horizontal; link COM
        sits at the link midpoint; the end-effector COM sits at its own
        midpoint (last_joint + ee_length/2); the payload sits at the
        end-effector's tip (last_joint + ee_length).

  * Yaw (Y) / Roll (R) — dynamic inertial torque about the joint axis
        tau = I * alpha
        I   = sum_outboard( m_i * r_total_i^2 )
        r_total_i = sqrt( r_axial_i^2 + e_j^2 )
        e_j is the perpendicular offset of the rotation axis from the
        chain's main line for joint j (Y / R only; P ignores e).

Outboard components (for a pivot at index j):
  * each link i (i >= j)        : m_link_i  at r_axial = link_mid_i  - x_j
  * each actuator k (k > j)     : m_act_k   at r_axial = x_k         - x_j
  * end-effector body           : m_ee      at r_axial = x_ee_mid    - x_j
  * payload (tip of EE)         : m_payload at r_axial = x_payload   - x_j
The actuator at j sits on the pivot itself and contributes nothing.
"""

import math

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QTextEdit, QDialogButtonBox,
)


G = 9.81  # m/s^2


def _kind_of(s: str) -> str:
    s = (s or "").strip().upper()
    return s[0] if s else "Y"


def _geometry(lengths_m: list[float], ee_length_m: float):
    n_links = len(lengths_m)
    joint_pos = [0.0]
    for L in lengths_m:
        joint_pos.append(joint_pos[-1] + L)
    link_mid = [joint_pos[i] + lengths_m[i] / 2.0 for i in range(n_links)]
    x_last = joint_pos[-1]
    x_ee_mid = x_last + ee_length_m / 2.0
    x_payload = x_last + ee_length_m
    return joint_pos, link_mid, x_ee_mid, x_payload


def compute_torques_full(
    *,
    lengths_m: list[float],
    link_masses: list[float],
    actuator_masses: list[float],
    payload_mass: float,
    joint_kinds: list[str],
    joint_offsets_m: list[float],
    target_alpha: float,
    ee_length_m: float,
    ee_mass: float,
) -> list[float]:
    """Per-joint torque using gravity (P) or inertia-with-offset (Y/R)."""
    n_links = len(lengths_m)
    if n_links == 0:
        return []
    n_joints = n_links + 1
    if (len(link_masses) != n_links
            or len(actuator_masses) != n_joints
            or len(joint_kinds) != n_joints
            or len(joint_offsets_m) != n_joints):
        return []

    joint_pos, link_mid, x_ee_mid, x_payload = _geometry(lengths_m, ee_length_m)
    out: list[float] = []
    for j in range(n_joints):
        xj = joint_pos[j]
        kind = _kind_of(joint_kinds[j])
        e = joint_offsets_m[j] if kind in ("Y", "R") else 0.0

        if kind == "P":
            t = 0.0
            for i in range(j, n_links):
                t += link_masses[i] * G * (link_mid[i] - xj)
            for k in range(j + 1, n_joints):
                t += actuator_masses[k] * G * (joint_pos[k] - xj)
            if ee_mass > 0.0:
                t += ee_mass * G * (x_ee_mid - xj)
            if payload_mass > 0.0:
                t += payload_mass * G * (x_payload - xj)
        else:
            inertia = 0.0
            e2 = e * e
            for i in range(j, n_links):
                r_ax = link_mid[i] - xj
                inertia += link_masses[i] * (r_ax * r_ax + e2)
            for k in range(j + 1, n_joints):
                r_ax = joint_pos[k] - xj
                inertia += actuator_masses[k] * (r_ax * r_ax + e2)
            if ee_mass > 0.0:
                r_ax = x_ee_mid - xj
                inertia += ee_mass * (r_ax * r_ax + e2)
            if payload_mass > 0.0:
                r_ax = x_payload - xj
                inertia += payload_mass * (r_ax * r_ax + e2)
            t = inertia * target_alpha
        out.append(t)
    return out


def compute_torques_with_breakdown(
    *,
    lengths_m: list[float],
    link_masses: list[float],
    actuator_masses: list[float],
    payload_mass: float,
    joint_kinds: list[str],
    joint_offsets_m: list[float],
    joint_labels: list[str],
    target_alpha: float,
    ee_length_m: float,
    ee_mass: float,
) -> tuple[list[float], str]:
    """Per-joint torques + audit text listing r for every component."""
    n_links = len(lengths_m)
    if n_links == 0:
        return [], "(no links — nothing to compute)"
    n_joints = n_links + 1
    if (len(link_masses) != n_links
            or len(actuator_masses) != n_joints
            or len(joint_kinds) != n_joints
            or len(joint_offsets_m) != n_joints
            or len(joint_labels) != n_joints):
        return [], "(input size mismatch — cannot build breakdown)"

    joint_pos, link_mid, x_ee_mid, x_payload = _geometry(lengths_m, ee_length_m)
    x_last = joint_pos[-1]

    lines: list[str] = []
    lines.append("Motor Torque Calculation — Math Breakdown")
    lines.append("=" * 64)
    lines.append(
        f"g = {G} m/s^2   |   target alpha = {target_alpha:.4f} rad/s^2"
    )
    lines.append(
        f"End-effector: length = {ee_length_m:.3f} m, "
        f"mass = {ee_mass:.3f} kg, payload = {payload_mass:.3f} kg"
    )
    lines.append("Pitch (P)        -> tau = sum( m_i * g * r_i )")
    lines.append("Yaw / Roll (Y/R) -> tau = I * alpha,"
                 "  I = sum( m_i * (r_axial_i^2 + e_j^2) )")
    lines.append("")
    lines.append("Component X-positions along the arm (m):")
    for lbl, x in zip(joint_labels, joint_pos):
        lines.append(f"  {lbl:>6s}     : x = {x:.3f} m")
    lines.append(f"  {'last':>6s}     : x = {x_last:.3f} m  (last joint)")
    lines.append(f"  {'ee_mid':>6s}    : x = {x_ee_mid:.3f} m  (EE COM)")
    lines.append(f"  {'tip':>6s}     : x = {x_payload:.3f} m  (EE tip / payload)")
    lines.append("")
    lines.append("-" * 64)

    torques: list[float] = []
    for j in range(n_joints):
        xj = joint_pos[j]
        kind = _kind_of(joint_kinds[j])
        if kind == "P":
            regime = "Pitch — static gravity"
            e_used = 0.0
        elif kind == "Y":
            regime = "Yaw — dynamic inertia"
            e_used = joint_offsets_m[j]
        elif kind == "R":
            regime = "Roll — dynamic inertia"
            e_used = joint_offsets_m[j]
        else:
            regime = f"Unknown ({kind}) — dynamic inertia"
            e_used = joint_offsets_m[j]

        head = (
            f"Joint {joint_labels[j]} [{kind}]  ({regime}; "
            f"pivot x = {xj:.3f} m"
        )
        if kind != "P":
            head += f", offset e = {e_used:.3f} m"
        head += "):"
        lines.append(head)
        contributed = False

        if kind == "P":
            t = 0.0
            for i in range(j, n_links):
                m = link_masses[i]
                r = link_mid[i] - xj
                mom = m * G * r
                t += mom
                lines.append(
                    f"  - Link {i + 1:<2d}    : "
                    f"m={m:.3f} kg, r={r:.3f} m  "
                    f"=> {m:.3f} * {G:.2f} * {r:.3f} = {mom:.2f} N.m"
                )
                contributed = True
            for k in range(j + 1, n_joints):
                m = actuator_masses[k]
                if m <= 0.0:
                    continue
                r = joint_pos[k] - xj
                mom = m * G * r
                t += mom
                lines.append(
                    f"  - Actuator {joint_labels[k]:<3s}: "
                    f"m={m:.3f} kg, r={r:.3f} m  "
                    f"=> {m:.3f} * {G:.2f} * {r:.3f} = {mom:.2f} N.m"
                )
                contributed = True
            if ee_mass > 0.0:
                r = x_ee_mid - xj
                mom = ee_mass * G * r
                t += mom
                lines.append(
                    f"  - EE body    : "
                    f"m={ee_mass:.3f} kg, r={r:.3f} m  "
                    f"=> {ee_mass:.3f} * {G:.2f} * {r:.3f} = {mom:.2f} N.m"
                )
                contributed = True
            if payload_mass > 0.0:
                r = x_payload - xj
                mom = payload_mass * G * r
                t += mom
                lines.append(
                    f"  - Payload    : "
                    f"m={payload_mass:.3f} kg, r={r:.3f} m  "
                    f"=> {payload_mass:.3f} * {G:.2f} * {r:.3f} = "
                    f"{mom:.2f} N.m"
                )
                contributed = True
            if not contributed:
                lines.append("  (no outboard masses — zero torque)")
            lines.append(f"  -> Total {joint_labels[j]} tau = {t:.2f} N.m")
        else:
            inertia = 0.0
            e = e_used
            e2 = e * e
            for i in range(j, n_links):
                m = link_masses[i]
                r_ax = link_mid[i] - xj
                r_tot = math.sqrt(r_ax * r_ax + e2)
                term = m * (r_ax * r_ax + e2)
                inertia += term
                lines.append(
                    f"  - Link {i + 1:<2d}    : "
                    f"m={m:.3f} kg, r_ax={r_ax:.3f} m, e={e:.3f} m, "
                    f"r={r_tot:.3f} m  "
                    f"=> {m:.3f} * {r_tot:.3f}^2 = {term:.4f} kg.m^2"
                )
                contributed = True
            for k in range(j + 1, n_joints):
                m = actuator_masses[k]
                if m <= 0.0:
                    continue
                r_ax = joint_pos[k] - xj
                r_tot = math.sqrt(r_ax * r_ax + e2)
                term = m * (r_ax * r_ax + e2)
                inertia += term
                lines.append(
                    f"  - Actuator {joint_labels[k]:<3s}: "
                    f"m={m:.3f} kg, r_ax={r_ax:.3f} m, e={e:.3f} m, "
                    f"r={r_tot:.3f} m  "
                    f"=> {m:.3f} * {r_tot:.3f}^2 = {term:.4f} kg.m^2"
                )
                contributed = True
            if ee_mass > 0.0:
                r_ax = x_ee_mid - xj
                r_tot = math.sqrt(r_ax * r_ax + e2)
                term = ee_mass * (r_ax * r_ax + e2)
                inertia += term
                lines.append(
                    f"  - EE body    : "
                    f"m={ee_mass:.3f} kg, r_ax={r_ax:.3f} m, e={e:.3f} m, "
                    f"r={r_tot:.3f} m  "
                    f"=> {ee_mass:.3f} * {r_tot:.3f}^2 = {term:.4f} kg.m^2"
                )
                contributed = True
            if payload_mass > 0.0:
                r_ax = x_payload - xj
                r_tot = math.sqrt(r_ax * r_ax + e2)
                term = payload_mass * (r_ax * r_ax + e2)
                inertia += term
                lines.append(
                    f"  - Payload    : "
                    f"m={payload_mass:.3f} kg, r_ax={r_ax:.3f} m, "
                    f"e={e:.3f} m, r={r_tot:.3f} m  "
                    f"=> {payload_mass:.3f} * {r_tot:.3f}^2 = "
                    f"{term:.4f} kg.m^2"
                )
                contributed = True
            if not contributed:
                lines.append("  (no outboard masses — I = 0, tau = 0)")
            t = inertia * target_alpha
            lines.append(f"  -> I = {inertia:.4f} kg.m^2")
            lines.append(
                f"  -> Total {joint_labels[j]} tau = I * alpha = "
                f"{inertia:.4f} * {target_alpha:.4f} = {t:.2f} N.m"
            )
        lines.append("")
        torques.append(t)

    return torques, "\n".join(lines)


class MathBreakdownDialog(QDialog):
    """Read-only pop-up showing the step-by-step torque math."""

    def __init__(self, breakdown_text: str, parent=None,
                 title: str = "MTC Math Breakdown"):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.resize(820, 620)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 10, 10, 10)

        hint = QLabel(
            "Per-joint audit. Pitch lists <i>m * g * r</i> for every "
            "downstream mass. Yaw / Roll lists <i>m * (r_axial² + e²)</i> "
            "for each, then <i>tau = I * alpha</i>. "
            "EE body sits at <i>last_joint + ee_length / 2</i>; payload at "
            "<i>last_joint + ee_length</i>."
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
