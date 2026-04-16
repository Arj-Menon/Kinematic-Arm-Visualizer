"""
Custom QGraphicsItem subclasses for the Interactive Kinematic Sandbox.

- JointBlock: draggable joint with shape determined by type
              (Y = square, P = circle, R = triangle pointing to child).
              Enforces a strict radius constraint against its parent joint
              and rigidly translates descendants when moved.
- LinkLine:   rubber-banding line between two JointBlocks with a smart,
              perpendicular-offset length label that always reads upright.
- GroundAnchor: small ground-line decoration drawn under the fixed base.
- GridScene:  QGraphicsScene subclass that paints a light-grey grid
              background.
"""

import math

from PyQt6.QtCore import Qt, QRectF, QPointF, QLineF
from PyQt6.QtGui import (
    QBrush, QPen, QColor, QFont, QFontMetrics, QPainter, QPolygonF,
    QPainterPath,
)
from PyQt6.QtWidgets import (
    QGraphicsRectItem, QGraphicsLineItem, QGraphicsItem,
    QGraphicsSimpleTextItem, QInputDialog, QMenu, QGraphicsItemGroup,
    QGraphicsScene,
)


# =========================================================================
class GridScene(QGraphicsScene):
    """Scene with a solid light-grey grid background (no drag trails)."""

    BG_COLOR = QColor("#F2F3F5")
    MINOR = QColor("#DDE1E6")
    MAJOR = QColor("#C1C7CF")
    MINOR_STEP = 25      # px
    MAJOR_EVERY = 4      # every 4th line is a major line (=> 100 px)

    def drawBackground(self, painter: QPainter, rect: QRectF):
        painter.fillRect(rect, self.BG_COLOR)

        step = self.MINOR_STEP
        left = int(math.floor(rect.left() / step) * step)
        top = int(math.floor(rect.top() / step) * step)

        minor_pen = QPen(self.MINOR, 0)
        major_pen = QPen(self.MAJOR, 0)

        # Vertical lines
        x = left
        while x <= rect.right():
            painter.setPen(major_pen if (x // step) % self.MAJOR_EVERY == 0
                           else minor_pen)
            painter.drawLine(QPointF(x, rect.top()), QPointF(x, rect.bottom()))
            x += step
        # Horizontal lines
        y = top
        while y <= rect.bottom():
            painter.setPen(major_pen if (y // step) % self.MAJOR_EVERY == 0
                           else minor_pen)
            painter.drawLine(QPointF(rect.left(), y), QPointF(rect.right(), y))
            y += step


# =========================================================================
class JointBlock(QGraphicsRectItem):
    """
    A joint in the kinematic chain.

    Physics:
    - If `parent_block` is set, the block is constrained to a circle of
      radius `link_length_px` around that parent: when the user drags it,
      the position is snapped using atan2 to the requested angle at
      exactly that radius.
    - When this block moves (by any amount), all descendant blocks are
      translated rigidly by the same delta (the whole sub-chain moves as
      one rigid body).

    Shapes (by `kind`):
    - 'Y' (Yaw)   -> Square
    - 'P' (Pitch) -> Circle
    - 'R' (Roll)  -> Triangle pointing to the next joint
    """

    # Block size is computed dynamically from adjacent link lengths:
    #   size = min(adjacent_mm_lengths) * px_per_mm * SIZE_RATIO
    # and then clamped to [MIN_PX, MAX_PX] in scene units. Because the
    # size lives in scene coordinates, zoom scales blocks together with
    # the links, preserving their relative proportions.
    SIZE_RATIO = 0.4
    MIN_PX = 10.0
    MAX_PX = 40.0
    DEFAULT_PX = 28.0    # used before any adjacent link exists

    COLORS = {
        "Y": QColor("#4FC3F7"),
        "P": QColor("#FFB74D"),
        "R": QColor("#81C784"),
    }
    BASE_COLOR = QColor("#1E3A5F")      # dark blue for fixed base
    BASE_TEXT = QColor("#FFFFFF")

    def __init__(self, label: str, kind: str,
                 parent_block: "JointBlock | None" = None,
                 link_length_mm: float = 0.0,
                 px_per_mm: float = 1.0):
        self.size = self.DEFAULT_PX
        s = self.size
        super().__init__(-s / 2, -s / 2, s, s)
        self.label = label
        self.kind = (kind or "").upper()[:1] or "Y"

        # Chain topology
        self.parent_block = parent_block
        self.px_per_mm = px_per_mm
        self.parent_link: "LinkLine | None" = None  # set when LinkLine is built
        self.children_blocks: list[JointBlock] = []
        if parent_block is not None:
            parent_block.children_blocks.append(self)

        # Connected LinkLines (for geometry refresh)
        self.links: list[LinkLine] = []

        # Propagation guard to avoid re-entering the constraint during
        # rigid-body translation of descendants.
        self._propagating = False
        self._last_pos = QPointF(0.0, 0.0)
        self.is_base = False

        # Optional callback fired after the joint's label or kind changes
        # (so external panels / legends can re-sync names + types).
        self.on_changed = None

        # Visuals
        self.setBrush(QBrush(self.COLORS.get(self.kind, QColor("#BDBDBD"))))
        self.setPen(QPen(Qt.GlobalColor.black, 2))
        # We paint the shape ourselves -- hide the default rect outline:
        self._draw_rect_outline = False

        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setAcceptHoverEvents(True)
        self.setZValue(10)  # blocks render above links

        # Label (child item -> moves with the block)
        self.text_item = QGraphicsSimpleTextItem(label, self)
        self.text_item.setFont(QFont("Arial", 11, QFont.Weight.Bold))
        self._center_text()

    # ----- API ------------------------------------------------------------
    def add_link(self, link: "LinkLine"):
        if link not in self.links:
            self.links.append(link)

    def recompute_size(self):
        """Size block based on the shortest adjacent link, clamped."""
        mm_lengths = []
        if self.parent_link is not None and self.parent_link.mm_length > 0:
            mm_lengths.append(self.parent_link.mm_length)
        for c in self.children_blocks:
            if c.parent_link is not None and c.parent_link.mm_length > 0:
                mm_lengths.append(c.parent_link.mm_length)

        if mm_lengths:
            target_px = min(mm_lengths) * self.px_per_mm * self.SIZE_RATIO
        else:
            target_px = self.DEFAULT_PX
        new_size = max(self.MIN_PX, min(self.MAX_PX, target_px))

        # Rescale label font to roughly fit inside the shape, then
        # expand the shape if the text still wouldn't fit.
        font = self.text_item.font()
        font.setPointSizeF(max(6.0, min(12.0, new_size * 0.32)))
        self.text_item.setFont(font)
        min_for_text = self._text_fit_min_size(font)
        new_size = max(new_size, min_for_text)

        if abs(new_size - self.size) < 1e-3:
            # Still update text placement in case kind/orientation changed.
            self._center_text()
            self.update()
            return
        self.prepareGeometryChange()
        self.size = new_size
        s = new_size
        self.setRect(-s / 2, -s / 2, s, s)
        self._center_text()
        self.update()

    def mark_as_base(self):
        """Make this joint the fixed base (non-movable, distinctive color)."""
        self.is_base = True
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
        self.setBrush(QBrush(self.BASE_COLOR))
        self.text_item.setBrush(QBrush(self.BASE_TEXT))
        self.setToolTip("Fixed base (anchored to ground)")

    # ----- helpers --------------------------------------------------------
    # Triangle centroid offset coefficient: centroid lies at
    # (1 + 2 cos 140°)/3 ≈ -0.177 along the tip direction, so the text
    # naturally sits in the wide rear of the triangle.
    _TRI_CENTROID_K = (1.0 + 2.0 * math.cos(math.radians(140))) / 3.0

    def _center_text(self):
        br = self.text_item.boundingRect()
        if self.kind == "R":
            # Centroid of the triangle, in the block's local coords.
            ang = self._orient_angle()
            r = self.size / 2
            cx = r * self._TRI_CENTROID_K * math.cos(ang)
            cy = r * self._TRI_CENTROID_K * math.sin(ang)
            self.text_item.setPos(cx - br.width() / 2,
                                  cy - br.height() / 2)
        else:
            self.text_item.setPos(-br.width() / 2, -br.height() / 2)

    def _text_fit_min_size(self, font: QFont) -> float:
        """Smallest size (px) that safely contains the text + 4 px padding."""
        fm = QFontMetrics(font)
        w = fm.horizontalAdvance(self.label or "XX")
        h = fm.height()
        pad = 4.0
        if self.kind == "Y":
            return max(w, h) + 2 * pad
        if self.kind == "P":
            return math.hypot(w, h) + 2 * pad
        # Triangle: text must fit at the centroid. Empirically the
        # inscribed rectangle at the centroid is ~ size * 0.55 wide
        # and ~ size * 0.45 tall, so solve for size.
        return max(w / 0.55, h / 0.45) + 2 * pad

    def _orient_angle(self) -> float:
        """Radians toward the first child (fallback: away from parent)."""
        if self.children_blocks:
            c = self.children_blocks[0]
            d = c.pos() - self.pos()
            if d.x() or d.y():
                return math.atan2(d.y(), d.x())
        if self.parent_block is not None:
            d = self.pos() - self.parent_block.pos()
            if d.x() or d.y():
                return math.atan2(d.y(), d.x())
        return 0.0

    # ----- Qt overrides ---------------------------------------------------
    def paint(self, painter: QPainter, option, widget=None):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(self.brush())
        painter.setPen(self.pen())

        r = self.size / 2
        k = self.kind

        if k == "Y":
            painter.drawRect(QRectF(-r, -r, self.size, self.size))
        elif k == "P":
            painter.drawEllipse(QRectF(-r, -r, self.size, self.size))
        elif k == "R":
            ang = self._orient_angle()
            tip = QPointF(r * math.cos(ang), r * math.sin(ang))
            a2 = ang + math.radians(140)
            a3 = ang - math.radians(140)
            p2 = QPointF(r * math.cos(a2), r * math.sin(a2))
            p3 = QPointF(r * math.cos(a3), r * math.sin(a3))
            painter.drawPolygon(QPolygonF([tip, p2, p3]))
        else:
            painter.drawRect(QRectF(-r, -r, self.SIZE, self.SIZE))

        # Ground decoration under the base (drawn in local coords below block)
        if self.is_base:
            pen = QPen(QColor("#37474F"), 2)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            y0 = r + 4
            painter.drawLine(QPointF(-r - 6, y0), QPointF(r + 6, y0))
            # Hatching
            for i in range(-int(r), int(r) + 1, 6):
                painter.drawLine(QPointF(i, y0),
                                 QPointF(i - 5, y0 + 6))

    def boundingRect(self) -> QRectF:
        # Extend slightly for the ground hatching so it repaints cleanly.
        base = super().boundingRect()
        if self.is_base:
            return base.adjusted(-8, 0, 8, 14)
        return base

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        path.addRect(super().boundingRect())  # hit-test area = the block square
        return path

    def itemChange(self, change, value):
        # Radius constraint on drag
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange:
            if self._propagating or self.parent_block is None:
                return super().itemChange(change, value)

            pp = self.parent_block.pos()
            dx = value.x() - pp.x()
            dy = value.y() - pp.y()
            # Authoritative length: the LinkLine's mm_length × px_per_mm.
            L = (self.parent_link.mm_length * self.px_per_mm
                 if self.parent_link is not None else 0.0)
            if L <= 0:
                return super().itemChange(change, value)
            if dx == 0.0 and dy == 0.0:
                # Keep current angle; avoid NaN.
                cur = self.pos() - pp
                ang = math.atan2(cur.y(), cur.x()) if (cur.x() or cur.y()) else 0.0
            else:
                ang = math.atan2(dy, dx)
            snapped = QPointF(pp.x() + L * math.cos(ang),
                              pp.y() + L * math.sin(ang))
            return super().itemChange(change, snapped)

        # After a move: translate descendants rigidly and refresh links
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged:
            new_pos = value
            delta = QPointF(new_pos.x() - self._last_pos.x(),
                            new_pos.y() - self._last_pos.y())
            self._last_pos = QPointF(new_pos)
            if not self._propagating and (delta.x() or delta.y()):
                self._translate_descendants(delta)
            for link in self.links:
                link.update_geometry()
            # Repaint adjacent R-shapes (orientation may have changed)
            # and re-center their text at the new centroid if needed.
            for neighbour in (
                [self.parent_block] if self.parent_block else []
            ) + list(self.children_blocks) + [self]:
                if neighbour.kind == "R":
                    neighbour._center_text()
                neighbour.update()

        return super().itemChange(change, value)

    def _translate_descendants(self, delta: QPointF):
        """Iteratively translate every descendant by `delta`."""
        stack = list(self.children_blocks)
        while stack:
            c = stack.pop()
            c._propagating = True
            try:
                c.setPos(c.pos() + delta)
            finally:
                c._propagating = False
            stack.extend(c.children_blocks)

    # ----- reactive text / type changes -----------------------------------
    def set_kind(self, new_kind: str):
        """Change shape type (Y/P/R) in place; keeps position, z, links."""
        new_kind = (new_kind or "").upper()[:1]
        if new_kind not in ("Y", "P", "R") or new_kind == self.kind:
            return
        self.kind = new_kind
        self.setBrush(QBrush(
            self.BASE_COLOR if self.is_base
            else self.COLORS.get(self.kind, QColor("#BDBDBD"))
        ))
        # Text placement differs per shape; size may need to grow for triangles.
        self.recompute_size()
        self._center_text()
        self.update()
        if callable(self.on_changed):
            self.on_changed(self)

    def on_text_changed(self, new_text: str):
        """Update label text and, if its leading letter changes, the shape."""
        new_text = (new_text or "").strip()
        if not new_text:
            return
        leading = new_text[0].upper()
        self.label = new_text
        self.text_item.setText(new_text)
        if leading in ("Y", "P", "R") and leading != self.kind:
            # set_kind will fire on_changed once after applying both updates.
            self.set_kind(leading)
        else:
            # Still need to refit -- text width changed.
            self.recompute_size()
            self._center_text()
            self.update()
            if callable(self.on_changed):
                self.on_changed(self)

    # ----- context menu ---------------------------------------------------
    def _split_label(self) -> tuple[str, int]:
        """Parse label like 'P3' -> ('P', 3)."""
        kind = self.kind
        num = 1
        if self.label:
            kind = self.label[0].upper()
            digits = "".join(ch for ch in self.label[1:] if ch.isdigit())
            if digits:
                try:
                    num = int(digits)
                except ValueError:
                    pass
        return kind, num

    def contextMenuEvent(self, event):
        menu = QMenu()
        edit = menu.addAction("Edit Joint…")
        chosen = menu.exec(event.screenPos())
        if chosen == edit:
            # Local import to avoid a hard dependency in graphics_items.
            from edit_joint_dialog import EditJointDialog
            kind, num = self._split_label()
            dlg = EditJointDialog(kind, num)
            if dlg.exec() == dlg.DialogCode.Accepted:
                new_label = f"{dlg.result_kind()}{dlg.result_number()}"
                self.on_text_changed(new_label)


# =========================================================================
class LinkLine(QGraphicsLineItem):
    """
    RIGID link between two JointBlocks.

    `mm_length` is the authoritative length. The pixel distance between
    the two joints is ALWAYS kept equal to `mm_length * px_per_mm`:
      * during a drag, JointBlock.itemChange reads this length to snap
        the child to the parent-radius circle;
      * when `set_mm_length()` is called, the child joint is repositioned
        radially along its current angle and the whole sub-chain below it
        is translated rigidly to follow.

    `block_a` is the parent; `block_b` is the child.
    """

    LABEL_OFFSET = 14.0  # perpendicular px offset for length label

    def __init__(self, block_a: JointBlock, block_b: JointBlock,
                 mm_length: float, px_per_mm: float = 1.0,
                 on_length_changed=None, parent=None):
        super().__init__(parent)
        self.block_a = block_a         # parent
        self.block_b = block_b         # child
        self.px_per_mm = px_per_mm
        self.mm_length = float(mm_length)
        self.on_length_changed = on_length_changed  # callback for live totals

        # Wire this link as block_b's parent-link so the drag constraint
        # can read the authoritative mm_length.
        block_b.parent_link = self

        self.setPen(QPen(QColor("#37474F"), 4))
        self.setZValue(0)  # below blocks (Z=10), above grid background

        self.text_item = QGraphicsSimpleTextItem("", self)
        self.text_item.setFont(QFont("Arial", 9, QFont.Weight.Bold))
        self.text_item.setBrush(QBrush(QColor("#1A237E")))
        self._hover = False

        block_a.add_link(self)
        block_b.add_link(self)
        self.setAcceptHoverEvents(True)
        self.update_geometry()
        # Now that the authoritative mm_length is set, resize both joints.
        block_a.recompute_size()
        block_b.recompute_size()

    # ------------------------------------------------------------------
    # Widen the clickable/hit area so short links are still easy to grab.
    HIT_WIDTH = 14.0

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        line = self.line()
        if line.length() <= 0:
            path.addEllipse(line.p1(), self.HIT_WIDTH / 2, self.HIT_WIDTH / 2)
            return path
        # Build a rotated rectangle around the line.
        dx = line.dx() / line.length()
        dy = line.dy() / line.length()
        nx, ny = -dy, dx
        half = self.HIT_WIDTH / 2
        p1 = QPointF(line.x1() + nx * half, line.y1() + ny * half)
        p2 = QPointF(line.x2() + nx * half, line.y2() + ny * half)
        p3 = QPointF(line.x2() - nx * half, line.y2() - ny * half)
        p4 = QPointF(line.x1() - nx * half, line.y1() - ny * half)
        path.moveTo(p1); path.lineTo(p2); path.lineTo(p3)
        path.lineTo(p4); path.closeSubpath()
        return path

    def boundingRect(self) -> QRectF:
        return super().boundingRect().adjusted(
            -self.HIT_WIDTH, -self.HIT_WIDTH,
            self.HIT_WIDTH, self.HIT_WIDTH,
        )

    # ------------------------------------------------------------------
    def hoverEnterEvent(self, event):
        self._hover = True
        self.update_geometry()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self._hover = False
        self.update_geometry()
        super().hoverLeaveEvent(event)

    # ------------------------------------------------------------------
    def set_mm_length(self, new_mm: float):
        """Change the rigid length and propagate downstream.

        Current angle from parent to child is preserved; the child moves
        radially to satisfy the new length, and every descendant is
        translated rigidly by the same delta so the assembly stays rigid.
        """
        new_mm = max(float(new_mm), 0.0)
        if new_mm == self.mm_length:
            return
        self.mm_length = new_mm

        a = self.block_a.pos()
        b_old = self.block_b.pos()
        dx, dy = b_old.x() - a.x(), b_old.y() - a.y()
        if dx == 0.0 and dy == 0.0:
            ang = 0.0
        else:
            ang = math.atan2(dy, dx)
        L_px = self.mm_length * self.px_per_mm
        b_new = QPointF(a.x() + L_px * math.cos(ang),
                        a.y() + L_px * math.sin(ang))
        delta = QPointF(b_new.x() - b_old.x(), b_new.y() - b_old.y())

        # Move the child without re-triggering the radius constraint,
        # then rigidly translate the rest of the sub-chain.
        self.block_b._propagating = True
        try:
            self.block_b.setPos(b_new)
        finally:
            self.block_b._propagating = False
        self.block_b._last_pos = QPointF(b_new)
        if delta.x() or delta.y():
            self.block_b._translate_descendants(delta)

        self.update_geometry()
        # The size of both endpoints (and any neighbour they share a
        # link with) depends on min(adjacent mm_lengths); refresh them.
        self.block_a.recompute_size()
        self.block_b.recompute_size()
        if self.on_length_changed is not None:
            self.on_length_changed()

    # ----- geometry --------------------------------------------------------
    def update_geometry(self):
        a = self.block_a.pos()
        b = self.block_b.pos()
        self.setLine(QLineF(a, b))

        # Length is authoritative from mm_length (rigid link).
        length_px = QLineF(a, b).length()
        self.text_item.setText(f"{self.mm_length:.1f} mm")

        # Decide whether the label fits on/near the link:
        #   - If the link is long enough, center the label with a small
        #     perpendicular offset (default behaviour).
        #   - If the link is too short, nudge the label off to the side
        #     (past the midpoint) so it doesn't sit on top of a joint.
        #   - If it's really tiny, hide the label unless hovered.
        label_w = self.text_item.boundingRect().width()
        fits_centered = length_px >= label_w + 16
        can_side = length_px >= 6  # absolute minimum before we give up
        if not fits_centered and not self._hover:
            self.text_item.setVisible(False)
            return
        self.text_item.setVisible(True)

        # Perpendicular offset + upright rotation
        dx = b.x() - a.x()
        dy = b.y() - a.y()
        angle_deg = math.degrees(math.atan2(dy, dx)) if (dx or dy) else 0.0
        flip = angle_deg > 90 or angle_deg < -90
        draw_angle = angle_deg + 180 if flip else angle_deg

        if length_px > 1e-6:
            # Perpendicular unit vector (rotate +90° CCW from line direction)
            nx = -dy / length_px
            ny = dx / length_px
        else:
            nx, ny = 0.0, -1.0

        # Always place on the "upper" side from the reader's perspective:
        if flip:
            nx, ny = -nx, -ny

        # Push the label further off the line when the link is short so
        # it doesn't overlap adjacent joints.
        offset = self.LABEL_OFFSET if fits_centered else max(
            self.LABEL_OFFSET,
            max(self.block_a.size, self.block_b.size) / 2 + 10,
        )
        mx = (a.x() + b.x()) / 2 + nx * offset
        my = (a.y() + b.y()) / 2 + ny * offset

        br = self.text_item.boundingRect()
        self.text_item.setTransformOriginPoint(br.width() / 2, br.height() / 2)
        self.text_item.setRotation(draw_angle)
        self.text_item.setPos(mx - br.width() / 2, my - br.height() / 2)

    # ----- context menu ---------------------------------------------------
    def contextMenuEvent(self, event):
        menu = QMenu()
        set_len = menu.addAction("Set link length (mm)…")
        chosen = menu.exec(event.screenPos())
        if chosen == set_len:
            val, ok = QInputDialog.getDouble(
                None, "Rigid link length",
                "Length in mm (chain will be pushed/pulled to satisfy):",
                value=self.mm_length,
                min=0.1, max=100000.0, decimals=2,
            )
            if ok:
                self.set_mm_length(val)


# =========================================================================
class EndEffectorItem(QGraphicsItem):
    """Light-red rectangle anchored at the last joint, extending forward.

    Length and width are scene-units (px). Length tracks `mm_length *
    px_per_mm`; width is proportional to the last joint's block size.
    Orientation is taken from the last link's direction (parent->last).
    Origin sits exactly at the last joint's position; positive x extends
    out along the arm. The payload tip is at (length, 0).
    """

    FILL = QColor("#FFCDD2")
    EDGE = QColor("#C62828")

    def __init__(self, last_block: "JointBlock",
                 mm_length: float = 0.0, px_per_mm: float = 1.0):
        super().__init__()
        self.last_block = last_block
        self.mm_length = max(0.0, float(mm_length))
        self.px_per_mm = px_per_mm
        self.setZValue(1)  # above grid + links, below joint blocks

    # ------- geometry --------------------------------------------------
    def _length_px(self) -> float:
        return max(0.0, self.mm_length) * self.px_per_mm

    def _width_px(self) -> float:
        return max(self.last_block.size * 0.7, 8.0)

    def boundingRect(self) -> QRectF:
        L = self._length_px()
        w = self._width_px()
        # Add small margin so the edge stroke isn't clipped.
        return QRectF(-2.0, -w / 2 - 2.0, L + 4.0, w + 4.0)

    def paint(self, painter: QPainter, option, widget=None):
        L = self._length_px()
        if L <= 0.0:
            return
        w = self._width_px()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setBrush(QBrush(self.FILL))
        painter.setPen(QPen(self.EDGE, 1.5))
        painter.drawRect(QRectF(0.0, -w / 2.0, L, w))
        # Mark the payload tip with a small notch so it's obvious where
        # the payload force is applied.
        painter.setPen(QPen(self.EDGE, 1.5))
        painter.drawLine(QPointF(L, -w / 2.0 - 3.0),
                         QPointF(L, w / 2.0 + 3.0))

    # ------- updates ---------------------------------------------------
    def set_mm_length(self, mm: float):
        self.prepareGeometryChange()
        self.mm_length = max(0.0, float(mm))
        self.update_geometry()

    def update_geometry(self):
        """Re-anchor + re-orient using the last link's direction."""
        prev = self.last_block.parent_block
        if prev is not None:
            d = self.last_block.pos() - prev.pos()
            dx, dy = d.x(), d.y()
        else:
            dx, dy = 1.0, 0.0
        ang_deg = (math.degrees(math.atan2(dy, dx))
                   if (dx or dy) else 0.0)
        self.prepareGeometryChange()
        self.setPos(self.last_block.pos())
        self.setRotation(ang_deg)
        self.update()
