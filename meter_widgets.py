from __future__ import annotations

import math

from PySide6.QtCore import Qt, QTimer, QRectF, QPointF
from PySide6.QtGui import QColor, QPainter, QPen, QLinearGradient
from PySide6.QtWidgets import QWidget, QSizePolicy

from studio_monitor_backend import normalize_meter_display_mode


class AnalogVUMeter(QWidget):
    """Animated analogue VU meter driven by a normalized 0..1 audio level."""
    def __init__(self, channel="L", parent=None):
        super().__init__(parent)
        self.channel = channel
        self.value = 0.0
        self.target = 0.0
        self.setMinimumSize(180, 120)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._animate)
        self.timer.start()

    def set_level(self, level):
        try:
            level = float(level)
        except Exception:
            level = 0.0
        self.target = max(0.0, min(1.0, level))

    def _animate(self):
        # Fast attack, slower return, similar to a physical VU needle.
        rate = 0.34 if self.target > self.value else 0.095
        self.value += (self.target - self.value) * rate
        if abs(self.target - self.value) < 0.0005:
            self.value = self.target
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # Use almost the complete widget for the scale. The old thick metal
        # housing reduced the face and pushed the outer labels over its edge.
        face = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        p.setPen(QPen(QColor("#6d6352"), .8))
        p.setBrush(QColor("#e8d6a7"))
        p.drawRoundedRect(face, 5, 5)

        # One fine highlight replaces the previous heavy outer frame.
        p.setPen(QPen(QColor("#fff1c3"), .6))
        p.drawRoundedRect(face.adjusted(1, 1, -1, -1), 4, 4)

        w, h = face.width(), face.height()
        cx = face.center().x()
        pivot_y = face.bottom() - 7.0
        radius_x = w * .56
        radius_y = h * .86

        # Scale occupies about 80 degrees.
        start_deg = 218.0
        end_deg = 322.0

        labels = [
            (0.00, "-20"),
            (0.13, "-10"),
            (0.25, "-7"),
            (0.36, "-5"),
            (0.47, "-3"),
            (0.57, "-2"),
            (0.66, "-1"),
            (0.75, "0"),
            (0.84, "+1"),
            (0.92, "+2"),
            (1.00, "+3"),
        ]

        # Broad classic VU scale line, with a heavier red overload section.
        scale_ratio=.80
        scale_rect=QRectF(
            cx-radius_x*scale_ratio,
            pivot_y-radius_y*scale_ratio,
            radius_x*scale_ratio*2,
            radius_y*scale_ratio*2,
        )
        qt_start=(360.0-start_deg)*16
        full_span=-(end_deg-start_deg)*16
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor("#302b23"),1.2))
        p.drawArc(scale_rect,int(qt_start),int(full_span))

        red_start_frac=.78
        red_start_deg=start_deg+(end_deg-start_deg)*red_start_frac
        red_qt_start=(360.0-red_start_deg)*16
        red_span=-(end_deg-red_start_deg)*16
        p.setPen(QPen(QColor("#c52c2c"),4.2,Qt.SolidLine,Qt.FlatCap))
        p.drawArc(scale_rect,int(red_qt_start),int(red_span))

        # ticks + labels
        font = p.font()
        font.setPointSizeF(max(7.0, min(9.0, w / 34)))
        font.setBold(True)
        p.setFont(font)

        for frac, label in labels:
            deg = start_deg + (end_deg - start_deg) * frac
            ang = math.radians(deg)
            red_zone = frac > 0.75
            col = QColor("#b42828") if red_zone else QColor("#24211b")
            p.setPen(QPen(col, 1.5))

            x1 = cx + math.cos(ang) * radius_x * 0.66
            y1 = pivot_y + math.sin(ang) * radius_y * 0.66
            x2 = cx + math.cos(ang) * radius_x * 0.83
            y2 = pivot_y + math.sin(ang) * radius_y * 0.83
            p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

            tx = cx + math.cos(ang) * radius_x * 0.94
            ty = pivot_y + math.sin(ang) * radius_y * 0.94
            tr = QRectF(tx - 14, ty - 7, 28, 14)
            p.drawText(tr, Qt.AlignCenter, label)

        # finer intermediate ticks
        p.setPen(QPen(QColor("#494237"), 0.8))
        for i in range(41):
            frac = i / 40.0
            if any(abs(frac - f) < 0.012 for f, _ in labels):
                continue
            deg = start_deg + (end_deg - start_deg) * frac
            ang = math.radians(deg)
            tick_len = 0.045 if i % 2 else 0.075
            x1 = cx + math.cos(ang) * radius_x * (0.80 - tick_len)
            y1 = pivot_y + math.sin(ang) * radius_y * (0.80 - tick_len)
            x2 = cx + math.cos(ang) * radius_x * 0.80
            y2 = pivot_y + math.sin(ang) * radius_y * 0.80
            p.drawLine(QPointF(x1, y1), QPointF(x2, y2))

        # VU + channel marking
        f = p.font()
        f.setPointSizeF(max(7.0, min(12.0, w / 22)))
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor("#1f1d19"))
        p.drawText(QRectF(face.left()+12, face.top()+9, 42, 20), Qt.AlignLeft|Qt.AlignVCenter, "VU")
        p.drawText(QRectF(face.right()-42, face.top()+9, 30, 20), Qt.AlignRight|Qt.AlignVCenter, self.channel)

        # needle
        deg = start_deg + (end_deg - start_deg) * self.value
        ang = math.radians(deg)
        tip_x = cx + math.cos(ang) * radius_x * 0.77
        tip_y = pivot_y + math.sin(ang) * radius_y * 0.77

        # tiny shadow then needle
        p.setPen(QPen(QColor(0, 0, 0, 80), 3, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(cx+1, pivot_y+1), QPointF(tip_x+1, tip_y+1))
        p.setPen(QPen(QColor("#191919"), 1.7, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(cx, pivot_y), QPointF(tip_x, tip_y))

        # pivot
        p.setBrush(QColor("#202020"))
        p.setPen(QPen(QColor("#5c5c5c"), 1))
        p.drawEllipse(QPointF(cx, pivot_y), 4.5, 4.5)

        p.end()


class AudioLevelMeter(AnalogVUMeter):
    """Two renderers sharing the existing normalized channel-level input.

    VU retains the original face and needle motion. LED draws the same input
    on a -60..0 dBFS segment scale. Neither renderer reads audio or changes
    the monitor's alarm, timing, connection or polling state.
    """

    SEGMENT_COUNT = 30

    def __init__(self, channel="L", parent=None, *, display_mode="led"):
        self.display_mode = normalize_meter_display_mode(display_mode)
        super().__init__(channel, parent)

    def set_level(self, level):
        try:
            level = float(level)
        except (TypeError, ValueError, OverflowError):
            level = 0.0
        super().set_level(level if math.isfinite(level) else 0.0)

    def set_display_mode(self, mode):
        self.display_mode = normalize_meter_display_mode(mode)
        # Keep the most recent input when switching; never restart a worker
        # or wait for another audio sample just to change the visualization.
        if self.display_mode == "led":
            self.value = self.target
        self.update()

    def _animate(self):
        if self.display_mode == "vu":
            super()._animate()
        else:
            # The existing audio feed already has its own release smoothing.
            self.value = self.target
            self.update()

    def lit_segment_count(self):
        if self.value <= 0.001:
            return 0
        dbfs = 20.0 * math.log10(self.value)
        fraction = max(0.0, min(1.0, (dbfs + 60.0) / 60.0))
        return min(self.SEGMENT_COUNT, int(math.ceil(fraction * self.SEGMENT_COUNT - 1e-9)))

    def paintEvent(self, event):
        if self.display_mode == "vu":
            super().paintEvent(event)
            return

        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        face = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        p.setPen(QPen(QColor("#245061"), 0.8))
        p.setBrush(QColor("#06131b"))
        p.drawRoundedRect(face, 5, 5)

        inner = face.adjusted(16, 10, -16, -10)
        font = p.font()
        font.setPointSizeF(9)
        font.setBold(True)
        p.setFont(font)
        header = QRectF(inner.left(), inner.top(), inner.width(), 22)
        p.setPen(QColor("#bcecf4"))
        p.drawText(header, Qt.AlignLeft | Qt.AlignVCenter, self.channel)
        p.setPen(QColor("#00d9ff"))
        p.drawText(header, Qt.AlignCenter, "LED")
        font.setPointSizeF(8)
        font.setBold(False)
        p.setFont(font)
        p.setPen(QColor("#8eb0bc"))
        p.drawText(header, Qt.AlignRight | Qt.AlignVCenter, "dBFS")

        bar_height = max(20.0, min(44.0, inner.height() * 0.28))
        bar_y = inner.top() + inner.height() * 0.40
        pitch = inner.width() / self.SEGMENT_COUNT
        gap = max(1.0, min(2.5, pitch * 0.24))
        active = self.lit_segment_count()
        for index in range(self.SEGMENT_COUNT):
            db = -60.0 + (index + 1) * 60.0 / self.SEGMENT_COUNT
            colour = QColor("#27ff72" if db <= -12 else "#ffc22c" if db <= -3 else "#ff3845")
            segment = QRectF(inner.left() + index * pitch + gap / 2, bar_y,
                             max(0.5, pitch - gap), bar_height)
            if index < active:
                fill = QLinearGradient(segment.topLeft(), segment.bottomLeft())
                fill.setColorAt(0.0, colour.lighter(118))
                fill.setColorAt(0.45, colour)
                fill.setColorAt(1.0, colour.darker(145))
                p.setBrush(fill)
                p.setPen(Qt.NoPen)
            else:
                p.setBrush(colour.darker(650))
                p.setPen(QPen(colour.darker(440), 0.5))
            p.drawRoundedRect(segment, 1, 1)

        p.setPen(QColor("#8eb0bc"))
        font.setPointSizeF(8)
        p.setFont(font)
        ticks = (-60, -40, -20, -6, 0) if inner.width() >= 210 else (-60, -30, -12, 0)
        for db in ticks:
            x = inner.left() + (db + 60) / 60.0 * inner.width()
            p.drawLine(QPointF(x, bar_y + bar_height + 4), QPointF(x, bar_y + bar_height + 8))
            label_x = max(inner.left(), min(inner.right() - 26, x - 13))
            label = QRectF(label_x, bar_y + bar_height + 10, 26, 16)
            p.drawText(label, Qt.AlignCenter, str(db))
        p.end()
