"""
Interactive Kinematic Sandbox window.

- GridScene with light-grey grid background (no drag trails).
- ZoomableView: wheel-zoom anchored on cursor, full-viewport updates,
  antialiased rendering.
- Strict kinematic chain: first joint is a fixed base, every other joint
  is locked to a circle of radius L around its parent. Moving a parent
  rigidly translates its descendants.
- Joint shapes: Y=square, P=circle, R=triangle pointing to the next joint.
- Overlays: scale legend (bottom-left, tracks zoom) and shape legend
  (top-right, semi-transparent).
"""

import math

from PyQt6.QtCore import Qt, QRectF, QPointF
from PyQt6.QtGui import QPainter, QBrush, QColor, QPen, QFont, QPolygonF
from PyQt6.QtWidgets import (
    QMainWindow, QGraphicsView, QInputDialog, QMessageBox, QToolBar,
    QLabel, QWidget, QVBoxLayout, QFrame, QDockWidget, QGridLayout,
    QDoubleSpinBox, QScrollArea, QHBoxLayout, QPushButton,
)

from graphics_items import JointBlock, LinkLine, GridScene, EndEffectorItem
from mtc_core import (
    compute_torques_full, compute_torques_with_breakdown,
    MathBreakdownDialog,
)
from actuator_selector import ActuatorSelector
import actuators_db


KIND_NAMES = {"Y": "Yaw", "P": "Pitch", "R": "Roll"}


SCENE_W = 4000
SCENE_H = 2400
PX_PER_MM = 1.0          # 1 mm == 1 px at zoom 1.0
LEGEND_MM = 100          # scale legend length in mm


# =========================================================================
class ScaleLegend(QFrame):
    """Bottom-left bar labelled e.g. '100 mm'. Tracks zoom."""

    def __init__(self, parent, px_per_mm: float = PX_PER_MM,
                 mm: float = LEGEND_MM):
        super().__init__(parent)
        self.px_per_mm = px_per_mm
        self.mm = mm
        self._zoom = 1.0
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setStyleSheet(
            "background: rgba(255,255,255,220);"
            "border: 1px solid #555; border-radius: 4px;"
        )
        self._update_size()

    def set_zoom(self, zoom: float):
        self._zoom = max(zoom, 1e-6)
        self._update_size()
        self.update()

    def _bar_px(self) -> int:
        return max(10, int(round(self.mm * self.px_per_mm * self._zoom)))

    def _update_size(self):
        self.resize(self._bar_px() + 20, 36)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        bar = self._bar_px()
        x0 = 10
        y = self.height() - 14
        p.setPen(QPen(QColor("#212121"), 2))
        p.drawLine(x0, y, x0 + bar, y)
        p.drawLine(x0, y - 5, x0, y + 5)
        p.drawLine(x0 + bar, y - 5, x0 + bar, y + 5)
        p.setFont(QFont("Arial", 9, QFont.Weight.Bold))
        p.drawText(x0, y - 8, f"{self.mm:g} mm")


# =========================================================================
class LinksLegend(QLabel):
    """Top-left overlay: joint roster (live names + types) + link lengths."""

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setTextFormat(Qt.TextFormat.RichText)
        self.setStyleSheet(
            "background: rgba(255,255,255,215);"
            "border: 1px solid #666; border-radius: 6px;"
            "padding: 6px 10px; color: #212121;"
        )
        self.setFont(QFont("Consolas", 9))
        self._blocks: list = []
        self._links: list = []
        self.setText("")

    def set_blocks(self, blocks):
        self._blocks = list(blocks)
        self._render()

    def update_links(self, links):
        self._links = list(links)
        self._render()

    def update_joints(self):
        """Re-render after a joint label or kind change."""
        self._render()

    def _render(self):
        if self._blocks:
            joint_rows = "".join(
                f"• {blk.label} "
                f"<span style='color:#555'>"
                f"({KIND_NAMES.get(blk.kind, blk.kind)})</span><br/>"
                for blk in self._blocks
            )
            joints_section = (
                f"<b>Joints</b><br/>{joint_rows}"
            )
        else:
            joints_section = "<b>Joints</b><br/><i>(none)</i>"

        if self._links:
            link_rows = "".join(
                f"• L{i + 1} = {lk.mm_length:.1f} mm<br/>"
                for i, lk in enumerate(self._links)
            )
            total = sum(lk.mm_length for lk in self._links)
            links_section = (
                f"<b>Links</b> &nbsp; <span style='color:#555'>"
                f"(Σ {total:.1f} mm)</span><br/>{link_rows}"
            )
        else:
            links_section = "<b>Links</b><br/><i>(none)</i>"

        self.setText(joints_section + "<br/>" + links_section)
        self.adjustSize()


# =========================================================================
class ShapeLegend(QFrame):
    """Top-right semi-transparent legend for the joint shapes."""

    ITEMS = [
        ("Y", "Yaw (square)",    QColor("#4FC3F7")),
        ("P", "Pitch (circle)",  QColor("#FFB74D")),
        ("R", "Roll (triangle)", QColor("#81C784")),
    ]

    def __init__(self, parent):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setStyleSheet(
            "background: rgba(255,255,255,200);"
            "border: 1px solid #666; border-radius: 6px;"
        )
        self.setFixedSize(170, 96)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setFont(QFont("Arial", 9, QFont.Weight.Bold))
        row_h = 26
        s = 14
        x0 = 12
        y0 = 12
        for i, (kind, text, color) in enumerate(self.ITEMS):
            cy = y0 + i * row_h + s / 2
            p.setBrush(QBrush(color))
            p.setPen(QPen(Qt.GlobalColor.black, 1.2))
            if kind == "Y":
                p.drawRect(QRectF(x0, cy - s / 2, s, s))
            elif kind == "P":
                p.drawEllipse(QRectF(x0, cy - s / 2, s, s))
            else:  # R: triangle pointing right
                tip = QPointF(x0 + s, cy)
                a = QPointF(x0, cy - s / 2)
                b = QPointF(x0, cy + s / 2)
                p.drawPolygon(QPolygonF([tip, a, b]))
            p.setPen(QPen(QColor("#212121")))
            p.drawText(int(x0 + s + 8), int(cy + 4), text)


# =========================================================================
class LiveMTCPanel(QWidget):
    """
    Live motor-torque tracker for the visualizer.

    Per-joint physics (selected by joint type letter):
      * Pitch (P)        -> tau = sum( m_i * g * r_i )
      * Yaw / Roll (Y/R) -> tau = I * alpha,
                            I = sum( m_i * (r_axial_i^2 + e_j^2) )

    Inputs:
      * Per link  : Length (mm, two-way bound to canvas) + Weight (kg).
      * Per joint : Actuator preset, plus offset e (mm) — Y/R only.
      * Tip       : End-Effector length (mm), End-Effector weight (kg),
                    Payload weight (kg).
      * Global    : Target angular acceleration alpha (rad/s^2).
    """

    DEFAULT_ALPHA = 3.14  # rad/s^2

    def __init__(self, blocks: list, links: list, parent=None):
        super().__init__(parent)
        self.blocks = blocks
        self.links = links
        self._presets = actuators_db.load()
        self._syncing_lengths = False  # canvas<->panel echo guard

        # External hook: visualizer sets this to receive EE-length changes
        # (so the canvas EE rectangle can be rescaled in real time).
        self.on_ee_length_changed = None

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        title = QLabel("<h3>Live MTC Tracker</h3>")
        title.setTextFormat(Qt.TextFormat.RichText)
        root.addWidget(title)

        subtitle = QLabel(
            "Per-component torque, arm horizontal. "
            "<b>Pitch</b>: Σ m·g·r per downstream mass. "
            "<b>Yaw / Roll</b>: I·α with I = Σ m·(r_axial² + e²)."
        )
        subtitle.setWordWrap(True)
        subtitle.setTextFormat(Qt.TextFormat.RichText)
        subtitle.setStyleSheet("color: #555;")
        root.addWidget(subtitle)

        # --- Global dynamics input --------------------------------------
        glob_frame = QFrame(); glob_frame.setFrameShape(QFrame.Shape.StyledPanel)
        glob_layout = QHBoxLayout(glob_frame)
        glob_layout.addWidget(QLabel("<b>Target Angular Accel α</b>:"))
        self.alpha_spin = QDoubleSpinBox()
        self.alpha_spin.setRange(0.0, 10000.0)
        self.alpha_spin.setDecimals(4)
        self.alpha_spin.setSingleStep(0.1)
        self.alpha_spin.setSuffix(" rad/s²")
        self.alpha_spin.setValue(self.DEFAULT_ALPHA)
        self.alpha_spin.setToolTip(
            "Used by Yaw / Roll joints only (τ = I · α). Pitch ignores α."
        )
        self.alpha_spin.valueChanged.connect(self.refresh)
        glob_layout.addWidget(self.alpha_spin)
        glob_layout.addStretch(1)
        root.addWidget(glob_frame)

        # --- Links: editable length spin + link-weight spin -------------
        link_frame = QFrame(); link_frame.setFrameShape(QFrame.Shape.StyledPanel)
        link_v = QVBoxLayout(link_frame)
        link_v.addWidget(QLabel("<b>Links</b>"))

        link_grid = QGridLayout()
        link_grid.addWidget(QLabel("<b>#</b>"), 0, 0)
        link_grid.addWidget(QLabel("<b>Length</b>"), 0, 1)
        link_grid.addWidget(QLabel("<b>Link Weight</b>"), 0, 2)

        self.length_spins: list[QDoubleSpinBox] = []
        self.link_weight_spins: list[QDoubleSpinBox] = []
        for i, link in enumerate(links):
            link_grid.addWidget(QLabel(f"L{i + 1}"), i + 1, 0)

            ls = QDoubleSpinBox()
            ls.setRange(0.1, 100000.0)
            ls.setDecimals(2)
            ls.setSingleStep(1.0)
            ls.setSuffix(" mm")
            ls.setValue(link.mm_length)
            ls.setToolTip(
                "Edit to scale the link on the canvas. The visual link "
                "and downstream chain follow live."
            )
            ls.valueChanged.connect(
                lambda val, idx=i: self._on_length_spin_changed(idx, val)
            )
            link_grid.addWidget(ls, i + 1, 1)
            self.length_spins.append(ls)

            ws = QDoubleSpinBox()
            ws.setRange(0.0, 1000.0)
            ws.setDecimals(3)
            ws.setSuffix(" kg")
            ws.setValue(1.0)
            ws.valueChanged.connect(self.refresh)
            link_grid.addWidget(ws, i + 1, 2)
            self.link_weight_spins.append(ws)
        link_v.addLayout(link_grid)
        root.addWidget(link_frame)

        # --- Actuators (+ Y/R offset) -----------------------------------
        act_frame = QFrame(); act_frame.setFrameShape(QFrame.Shape.StyledPanel)
        act_v = QVBoxLayout(act_frame)
        act_v.addWidget(QLabel("<b>Actuators (per joint)</b>"))

        self.act_grid = QGridLayout()
        self.act_grid.addWidget(QLabel("<b>Joint</b>"), 0, 0)
        self.act_grid.addWidget(QLabel("<b>Actuator Preset</b>"), 0, 1)
        self.act_grid.addWidget(QLabel("<b>Offset e (mm)</b>"), 0, 2)

        self.actuator_selectors: list[ActuatorSelector] = []
        self.act_joint_labels: list[QLabel] = []
        self.offset_spins: list[QDoubleSpinBox] = []
        for i, blk in enumerate(blocks):
            jl = QLabel(blk.label)
            self.act_grid.addWidget(jl, i + 1, 0)
            self.act_joint_labels.append(jl)

            sel = ActuatorSelector(self._presets, self)
            sel.sig_changed = self.refresh
            self.act_grid.addWidget(sel, i + 1, 1)
            self.actuator_selectors.append(sel)

            os = QDoubleSpinBox()
            os.setRange(0.0, 100000.0)
            os.setDecimals(2)
            os.setSingleStep(1.0)
            os.setSuffix(" mm")
            os.setValue(0.0)
            os.setToolTip(
                "Perpendicular axis offset for Yaw / Roll joints. "
                "Adds e² to the squared-radius of every downstream mass "
                "in this joint's I. Disabled for Pitch joints."
            )
            os.valueChanged.connect(self.refresh)
            self.act_grid.addWidget(os, i + 1, 2)
            self.offset_spins.append(os)
            self._sync_offset_enabled(i)
        act_v.addLayout(self.act_grid)
        root.addWidget(act_frame)

        # --- End-effector + payload --------------------------------------
        tip_frame = QFrame(); tip_frame.setFrameShape(QFrame.Shape.StyledPanel)
        tip_v = QVBoxLayout(tip_frame)
        tip_v.addWidget(QLabel("<b>End-Effector & Payload</b>"))

        tip_grid = QGridLayout()
        tip_grid.addWidget(QLabel("End-Effector Length:"), 0, 0)
        self.ee_length_spin = QDoubleSpinBox()
        self.ee_length_spin.setRange(0.0, 100000.0)
        self.ee_length_spin.setDecimals(2)
        self.ee_length_spin.setSingleStep(1.0)
        self.ee_length_spin.setSuffix(" mm")
        self.ee_length_spin.setValue(0.0)
        self.ee_length_spin.setToolTip(
            "Light-red rectangle drawn from the last joint outward. "
            "EE COM = last_joint + length / 2; payload tip = last_joint "
            "+ length."
        )
        self.ee_length_spin.valueChanged.connect(self._on_ee_length_changed)
        tip_grid.addWidget(self.ee_length_spin, 0, 1)

        tip_grid.addWidget(QLabel("End-Effector Weight:"), 1, 0)
        self.ee_weight_spin = QDoubleSpinBox()
        self.ee_weight_spin.setRange(0.0, 1000.0)
        self.ee_weight_spin.setDecimals(3)
        self.ee_weight_spin.setSuffix(" kg")
        self.ee_weight_spin.setValue(0.0)
        self.ee_weight_spin.valueChanged.connect(self.refresh)
        tip_grid.addWidget(self.ee_weight_spin, 1, 1)

        tip_grid.addWidget(QLabel("Payload Weight:"), 2, 0)
        self.payload_spin = QDoubleSpinBox()
        self.payload_spin.setRange(0.0, 1000.0)
        self.payload_spin.setDecimals(3)
        self.payload_spin.setSuffix(" kg")
        self.payload_spin.setValue(0.0)
        self.payload_spin.valueChanged.connect(self.refresh)
        tip_grid.addWidget(self.payload_spin, 2, 1)
        tip_v.addLayout(tip_grid)
        root.addWidget(tip_frame)

        # --- Outputs -----------------------------------------------------
        out_frame = QFrame(); out_frame.setFrameShape(QFrame.Shape.StyledPanel)
        out_v = QVBoxLayout(out_frame)
        out_v.addWidget(QLabel("<b>Required Torque</b>"))

        self.out_grid = QGridLayout()
        self.out_grid.addWidget(QLabel("<b>Joint</b>"), 0, 0)
        self.out_grid.addWidget(QLabel("<b>Regime</b>"), 0, 1)
        self.out_grid.addWidget(QLabel("<b>Torque (N·m)</b>"), 0, 2)

        self.torque_labels: list[QLabel] = []
        self.out_joint_labels: list[QLabel] = []
        self.out_regime_labels: list[QLabel] = []
        for i, blk in enumerate(blocks):
            jl = QLabel(blk.label)
            self.out_grid.addWidget(jl, i + 1, 0)
            self.out_joint_labels.append(jl)

            rl = QLabel(self._regime_text(blk.kind))
            rl.setStyleSheet("color: #555;")
            self.out_grid.addWidget(rl, i + 1, 1)
            self.out_regime_labels.append(rl)

            tl = QLabel("0.00")
            tl.setStyleSheet(
                "font-family: Consolas, monospace; font-weight: bold;"
                " padding: 2px 8px;"
            )
            self.out_grid.addWidget(tl, i + 1, 2)
            self.torque_labels.append(tl)
        out_v.addLayout(self.out_grid)
        root.addWidget(out_frame)

        # --- Math verification ------------------------------------------
        self.btn_breakdown = QPushButton("Show Math Breakdown")
        self.btn_breakdown.setToolTip(
            "Per-joint audit listing m, r_axial, e, r and the resulting "
            "moment / inertia for every downstream mass."
        )
        self.btn_breakdown.clicked.connect(self._show_breakdown)
        root.addWidget(self.btn_breakdown)
        root.addStretch(1)

        self.refresh()

    # ----------------------------------------------------------------
    @staticmethod
    def _regime_text(kind: str) -> str:
        k = (kind or "").upper()[:1]
        if k == "P":
            return "Pitch — Σ m·g·r"
        if k == "Y":
            return "Yaw — I·α (uses e)"
        if k == "R":
            return "Roll — I·α (uses e)"
        return "Unknown — I·α"

    def _sync_offset_enabled(self, i: int):
        """Pitch joints can't have an axis offset — grey it out + zero it."""
        if not (0 <= i < len(self.offset_spins)):
            return
        kind = (self.blocks[i].kind or "").upper()[:1]
        spin = self.offset_spins[i]
        if kind == "P":
            blocked = spin.blockSignals(True)
            spin.setValue(0.0)
            spin.setEnabled(False)
            spin.blockSignals(blocked)
        else:
            spin.setEnabled(True)

    # ----------------------------------------------------------------
    def on_preset_added(self, presets: dict[str, float],
                        select_name: str, origin: "ActuatorSelector"):
        self._presets = presets
        for sel in self.actuator_selectors:
            if sel is origin:
                sel.refresh_presets(presets, keep_selection=False)
                idx = sel.combo.findText(select_name)
                if idx >= 0:
                    sel.combo.setCurrentIndex(idx)
            else:
                sel.refresh_presets(presets, keep_selection=True)
        self.refresh()

    # ----------------------------------------------------------------
    def relabel_joints(self):
        """Re-render labels + regime tags after a canvas rename / retype."""
        for i, blk in enumerate(self.blocks):
            if i < len(self.act_joint_labels):
                self.act_joint_labels[i].setText(blk.label)
            if i < len(self.out_joint_labels):
                self.out_joint_labels[i].setText(blk.label)
            if i < len(self.out_regime_labels):
                self.out_regime_labels[i].setText(self._regime_text(blk.kind))
            self._sync_offset_enabled(i)
        self.refresh()

    # ----------------------------------------------------------------
    def _on_length_spin_changed(self, idx: int, value_mm: float):
        if self._syncing_lengths:
            return
        if not (0 <= idx < len(self.links)):
            return
        link = self.links[idx]
        if abs(link.mm_length - value_mm) < 1e-6:
            return
        link.set_mm_length(value_mm)

    def _on_ee_length_changed(self, value_mm: float):
        """Forward EE length to the visualizer canvas, then recompute."""
        if callable(self.on_ee_length_changed):
            self.on_ee_length_changed(float(value_mm))
        self.refresh()

    # ----------------------------------------------------------------
    def ee_length_mm(self) -> float:
        return float(self.ee_length_spin.value())

    def ee_mass_kg(self) -> float:
        return float(self.ee_weight_spin.value())

    # ----------------------------------------------------------------
    def refresh(self):
        """Recompute torques from live scene + all input widgets."""
        # Sync canvas lengths -> spinboxes (no echo back to set_mm_length).
        self._syncing_lengths = True
        try:
            for i, lk in enumerate(self.links):
                if i >= len(self.length_spins):
                    break
                spin = self.length_spins[i]
                if abs(spin.value() - lk.mm_length) > 1e-6:
                    blocked = spin.blockSignals(True)
                    spin.setValue(lk.mm_length)
                    spin.blockSignals(blocked)
        finally:
            self._syncing_lengths = False

        lengths_m = [lk.mm_length / 1000.0 for lk in self.links]
        link_masses = [s.value() for s in self.link_weight_spins]
        actuator_masses = [sel.value() for sel in self.actuator_selectors]
        joint_kinds = [blk.kind for blk in self.blocks]
        joint_offsets_m = [s.value() / 1000.0 for s in self.offset_spins]
        payload = float(self.payload_spin.value())
        ee_length_m = float(self.ee_length_spin.value()) / 1000.0
        ee_mass = float(self.ee_weight_spin.value())
        alpha = float(self.alpha_spin.value())

        torques = compute_torques_full(
            lengths_m=lengths_m,
            link_masses=link_masses,
            actuator_masses=actuator_masses,
            payload_mass=payload,
            joint_kinds=joint_kinds,
            joint_offsets_m=joint_offsets_m,
            target_alpha=alpha,
            ee_length_m=ee_length_m,
            ee_mass=ee_mass,
        )
        for i, tl in enumerate(self.torque_labels):
            if i < len(torques):
                tl.setText(f"{torques[i]:.2f}")
            else:
                tl.setText("—")

    # ----------------------------------------------------------------
    def _show_breakdown(self):
        lengths_m = [lk.mm_length / 1000.0 for lk in self.links]
        link_masses = [s.value() for s in self.link_weight_spins]
        actuator_masses = [sel.value() for sel in self.actuator_selectors]
        joint_kinds = [blk.kind for blk in self.blocks]
        joint_offsets_m = [s.value() / 1000.0 for s in self.offset_spins]
        joint_labels = [blk.label for blk in self.blocks]
        payload = float(self.payload_spin.value())
        ee_length_m = float(self.ee_length_spin.value()) / 1000.0
        ee_mass = float(self.ee_weight_spin.value())
        alpha = float(self.alpha_spin.value())

        _torques, text = compute_torques_with_breakdown(
            lengths_m=lengths_m,
            link_masses=link_masses,
            actuator_masses=actuator_masses,
            payload_mass=payload,
            joint_kinds=joint_kinds,
            joint_offsets_m=joint_offsets_m,
            joint_labels=joint_labels,
            target_alpha=alpha,
            ee_length_m=ee_length_m,
            ee_mass=ee_mass,
        )
        dlg = MathBreakdownDialog(
            text, self, title="Live MTC Math Breakdown"
        )
        dlg.exec()


# =========================================================================
class ZoomableView(QGraphicsView):
    """Wheel-zoom anchored on the cursor, with full-viewport redraws."""

    MIN_ZOOM = 0.1
    MAX_ZOOM = 20.0

    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self._zoom = 1.0
        self.on_zoom_changed = None

        self.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.TextAntialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        self.setViewportUpdateMode(
            QGraphicsView.ViewportUpdateMode.FullViewportUpdate
        )
        self.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorUnderMouse
        )
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag)
        self.setCacheMode(QGraphicsView.CacheModeFlag.CacheNone)

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta == 0:
            return
        factor = 1.15 if delta > 0 else 1 / 1.15
        new_zoom = self._zoom * factor
        if new_zoom < self.MIN_ZOOM or new_zoom > self.MAX_ZOOM:
            return
        self._zoom = new_zoom
        self.scale(factor, factor)
        if self.on_zoom_changed is not None:
            self.on_zoom_changed(self._zoom)
        event.accept()

    def zoom(self) -> float:
        return self._zoom


# =========================================================================
class VisualizerWindow(QMainWindow):
    """Pop-up window showing the draggable kinematic chain."""

    def __init__(self, config: str, total_length_mm: float,
                 arm_label: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(
            f"Kinematic Sandbox — {arm_label}" if arm_label
            else "Kinematic Sandbox"
        )
        self.resize(1100, 700)

        self.config = config
        self.total_length_mm = total_length_mm
        self.px_per_mm = PX_PER_MM

        self.scene = GridScene(0, 0, SCENE_W, SCENE_H, self)
        self.view = ZoomableView(self.scene, self)
        self.view.on_zoom_changed = self._on_zoom

        central = QWidget(self)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.view)
        self.setCentralWidget(central)

        tb = QToolBar("Info", self)
        self.addToolBar(tb)
        self.status_label = QLabel("")
        tb.addWidget(self.status_label)

        self.blocks: list[JointBlock] = []
        self.links: list[LinkLine] = []
        self._build_chain()

        # Overlays
        vp = self.view.viewport()
        self.scale_legend = ScaleLegend(vp, px_per_mm=self.px_per_mm,
                                        mm=LEGEND_MM)
        self.shape_legend = ShapeLegend(vp)
        self.links_legend = LinksLegend(vp)
        self.links_legend.set_blocks(self.blocks)
        self.scale_legend.show()
        self.shape_legend.show()
        self.links_legend.show()

        # End-effector visual: rectangle anchored at last joint.
        self.ee_item: EndEffectorItem | None = None
        if self.blocks:
            self.ee_item = EndEffectorItem(
                self.blocks[-1], mm_length=0.0, px_per_mm=self.px_per_mm,
            )
            self.scene.addItem(self.ee_item)
            self.ee_item.update_geometry()

        # Live MTC dock panel — right-hand side, dockable / floatable.
        self.mtc_panel = LiveMTCPanel(self.blocks, self.links, self)
        self.mtc_panel.on_ee_length_changed = self._on_ee_length_changed

        # Two-way binding: when a joint is renamed / retyped on the canvas,
        # propagate to the panel rows + the joint legend.
        for blk in self.blocks:
            blk.on_changed = self._on_joint_changed
        scroll = QScrollArea()
        scroll.setWidget(self.mtc_panel)
        scroll.setWidgetResizable(True)
        self.mtc_dock = QDockWidget("Live MTC Tracker", self)
        self.mtc_dock.setWidget(scroll)
        self.mtc_dock.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
            | QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.mtc_dock)

        self._refresh_status()
        self._position_overlays()

    # ---------------------------------------------------------------
    def _build_chain(self):
        tokens = [t.strip().upper() for t in self.config.split("-") if t.strip()]
        if not tokens:
            QMessageBox.warning(self, "Invalid config",
                                "Configuration string has no joints.")
            return

        n_joints = len(tokens)
        n_links = max(n_joints - 1, 1)
        link_len_mm = self.total_length_mm / n_links
        link_len_px = link_len_mm * self.px_per_mm

        y = SCENE_H / 2
        total_px = link_len_px * (n_joints - 1)
        start_x = max(160.0, (SCENE_W - total_px) / 2)

        counters: dict[str, int] = {}
        prev: JointBlock | None = None
        for i, tok in enumerate(tokens):
            counters[tok] = counters.get(tok, 0) + 1
            label = f"{tok}{counters[tok]}"

            block = JointBlock(
                label=label,
                kind=tok,
                parent_block=prev,
                link_length_mm=0.0,   # authoritative length lives on LinkLine
                px_per_mm=self.px_per_mm,
            )
            x = start_x + i * link_len_px
            block.setPos(x, y)
            block._last_pos = QPointF(x, y)
            self.scene.addItem(block)
            if i == 0:
                block.mark_as_base()
            self.blocks.append(block)
            prev = block

        for i in range(len(self.blocks) - 1):
            link = LinkLine(
                self.blocks[i], self.blocks[i + 1],
                mm_length=link_len_mm,
                px_per_mm=self.px_per_mm,
                on_length_changed=self._refresh_status,
            )
            self.scene.addItem(link)
            self.links.append(link)

        self._refresh_status()

    def _refresh_status(self):
        total_mm = sum(link.mm_length for link in self.links)
        self.status_label.setText(
            f"  Config: {self.config}     "
            f"Total length (live): {total_mm:.1f} mm     "
            f"Scale: {self.px_per_mm:g} px = 1 mm  (scroll to zoom)     "
            "Drag joints (base is fixed); right-click a link to resize.  "
        )
        if hasattr(self, "links_legend"):
            self.links_legend.update_links(self.links)
            self._position_overlays()
        if getattr(self, "ee_item", None) is not None:
            self.ee_item.update_geometry()
        if hasattr(self, "mtc_panel"):
            self.mtc_panel.refresh()

    # ---------------------------------------------------------------
    def _on_joint_changed(self, _block):
        """Canvas just renamed / retyped a joint — re-sync legend + panel."""
        if hasattr(self, "links_legend"):
            self.links_legend.update_joints()
            self._position_overlays()
        if hasattr(self, "mtc_panel"):
            self.mtc_panel.relabel_joints()

    # ---------------------------------------------------------------
    def _on_ee_length_changed(self, mm: float):
        """Panel changed EE length — rescale the canvas rectangle."""
        if self.ee_item is not None:
            self.ee_item.set_mm_length(mm)

    # ---------------------------------------------------------------
    def _on_zoom(self, zoom: float):
        self.scale_legend.set_zoom(zoom)
        self._position_overlays()

    def _position_overlays(self):
        vp = self.view.viewport()
        m = 12
        self.scale_legend.move(m, vp.height() - self.scale_legend.height() - m)
        self.shape_legend.move(vp.width() - self.shape_legend.width() - m, m)
        if hasattr(self, "links_legend"):
            self.links_legend.move(m, m)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_overlays()

    # ---------------------------------------------------------------
    @staticmethod
    def prompt_and_launch(parent=None, arm_label: str = "",
                          default_config: str = "Y-P-P-R-P-R",
                          default_length_mm: float = 600.0):
        config, ok = QInputDialog.getText(
            parent, "Joint configuration",
            "Enter kinematic chain (dash-separated, e.g. Y-P-P-R-P-R):",
            text=default_config,
        )
        if not ok or not config.strip():
            return None

        length, ok = QInputDialog.getDouble(
            parent, "Total link length",
            "Total link length (mm):",
            value=default_length_mm, min=1.0, max=100000.0, decimals=1,
        )
        if not ok:
            return None

        win = VisualizerWindow(config.strip(), length, arm_label, parent)
        win.show()
        return win
