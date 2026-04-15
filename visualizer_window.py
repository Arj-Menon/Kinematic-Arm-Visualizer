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
    QLabel, QWidget, QVBoxLayout, QFrame,
)

from graphics_items import JointBlock, LinkLine, GridScene


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
    """Top-left overlay listing every link's live mm_length."""

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
        self.setText("")

    def update_links(self, links):
        if not links:
            self.setText("<b>Links</b><br/><i>(none)</i>")
        else:
            rows = "".join(
                f"• L{i+1} = {lk.mm_length:.1f} mm<br/>"
                for i, lk in enumerate(links)
            )
            total = sum(lk.mm_length for lk in links)
            self.setText(
                f"<b>Links</b> &nbsp; <span style='color:#555'>"
                f"(Σ {total:.1f} mm)</span><br/>{rows}"
            )
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
        self.scale_legend.show()
        self.shape_legend.show()
        self.links_legend.show()
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
