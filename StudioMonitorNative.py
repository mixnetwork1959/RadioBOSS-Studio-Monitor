from __future__ import annotations
import sys, os, math, time, json, threading
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor

from PySide6.QtCore import Qt, QTimer, Signal, QObject, QRectF, QPointF, QSettings
from PySide6.QtGui import QColor, QPainter, QPen, QBrush, QFont, QPainterPath, QPixmap, QLinearGradient
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QLabel, QVBoxLayout, QHBoxLayout,
    QGridLayout, QFrame, QTableWidget, QTableWidgetItem, QHeaderView,
    QProgressBar, QSizePolicy, QScrollArea,
    QPushButton,
    QMessageBox
)

import studio_monitor_backend as backend
from settings_dialog import SettingsDialog

BASE = (
    Path(sys.executable).resolve().parent
    if getattr(sys,"frozen",False)
    else Path(__file__).resolve().parent
)
backend.CONFIG = BASE / "studio_monitor_config.json"

THEME_PALETTES = {
    "dark": {
        "cyan":"#00d9ff", "green":"#27ff72", "amber":"#ffc22c", "red":"#ff3845",
        "panel":"#041018", "bg":"#010406", "text":"#eafaff", "muted":"#7695a5",
        "border":"rgba(0,217,255,0.55)", "soft_border":"rgba(0,217,255,0.28)",
        "onair_text":"#ff6670", "onair_bg":"#26050a", "brand":"#ffc14b", "brand_sub":"#d8f7ff",
        "title":"#f3fbff", "cover_bg":"#02080d", "cover_text":"#49626d",
        "status_bg":"#061018", "button_bg":"#07161e", "button_text":"#dff8ff",
        "button_hover":"#0b2430", "button_pressed":"#031015", "input_bg":"#02080d",
        "input_border":"#285260", "tab_bg":"#07161e", "tab_text":"#b9dbe5",
        "progress_bg":"#02080d", "table_bg":"#02080d", "table_grid":"#0a222d",
        "header_bg":"#06151d", "row_border":"#07151c", "scroll_bg":"#031016",
        "scroll_handle":"#008db0", "active_bg":"#062412", "station_active_bg":"#063421",
        "alert_bg":"#26050a", "table_muted":"#58757f",
    },
    "light": {
        "cyan":"#007a9d", "green":"#008743", "amber":"#a45d00", "red":"#bd2437",
        "panel":"#ffffff", "bg":"#e7eef2", "text":"#15252d", "muted":"#536b77",
        "border":"rgba(0,122,157,0.55)", "soft_border":"rgba(0,122,157,0.25)",
        "onair_text":"#a51429", "onair_bg":"#ffe8ec", "brand":"#9b5900", "brand_sub":"#3d6672",
        "title":"#10232c", "cover_bg":"#f4f8fa", "cover_text":"#59717c",
        "status_bg":"#eef6f8", "button_bg":"#f4f9fb", "button_text":"#17323c",
        "button_hover":"#e2f1f5", "button_pressed":"#d5e7ed", "input_bg":"#ffffff",
        "input_border":"#80aebc", "tab_bg":"#dfecef", "tab_text":"#365d69",
        "progress_bg":"#dbe8ec", "table_bg":"#ffffff", "table_grid":"#d6e4e8",
        "header_bg":"#dcebf0", "row_border":"#e3edf0", "scroll_bg":"#e2ecef",
        "scroll_handle":"#5795a8", "active_bg":"#e3f5e9", "station_active_bg":"#dff4e7",
        "alert_bg":"#ffe8ec", "table_muted":"#667d87",
    },
}


def _theme_palette(theme):
    return THEME_PALETTES["light" if str(theme or "").lower()=="light" else "dark"]


# Runtime colour aliases are also used by the live status updates and table
# items. apply_theme() refreshes them whenever the user changes appearance.
CYAN = THEME_PALETTES["dark"]["cyan"]
GREEN = THEME_PALETTES["dark"]["green"]
AMBER = THEME_PALETTES["dark"]["amber"]
RED = THEME_PALETTES["dark"]["red"]
PANEL = THEME_PALETTES["dark"]["panel"]
BG = THEME_PALETTES["dark"]["bg"]
TEXT = THEME_PALETTES["dark"]["text"]
MUTED = THEME_PALETTES["dark"]["muted"]
ACTIVE_BG = THEME_PALETTES["dark"]["active_bg"]
ALERT_BG = THEME_PALETTES["dark"]["alert_bg"]
STATION_ACTIVE_BG = THEME_PALETTES["dark"]["station_active_bg"]
TABLE_MUTED = THEME_PALETTES["dark"]["table_muted"]


def apply_theme(app,theme):
    global CYAN,GREEN,AMBER,RED,PANEL,BG,TEXT,MUTED
    global ACTIVE_BG,ALERT_BG,STATION_ACTIVE_BG,TABLE_MUTED
    name="light" if str(theme or "").lower()=="light" else "dark"
    colours=_theme_palette(name)
    CYAN=colours["cyan"]; GREEN=colours["green"]; AMBER=colours["amber"]; RED=colours["red"]
    PANEL=colours["panel"]; BG=colours["bg"]; TEXT=colours["text"]; MUTED=colours["muted"]
    ACTIVE_BG=colours["active_bg"]; ALERT_BG=colours["alert_bg"]
    STATION_ACTIVE_BG=colours["station_active_bg"]; TABLE_MUTED=colours["table_muted"]
    app.setProperty("studioMonitorTheme",name)
    app.setStyleSheet(stylesheet(name))
    for widget in app.topLevelWidgets():
        widget.update()

class DataSignals(QObject):
    state = Signal(dict)
    weather = Signal(dict)
    audio = Signal(dict)
    error = Signal(str)

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


class _LegacyTurntableWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.angle = 0.0
        self.playing = False
        self.setMinimumSize(320, 240)
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self.advance)
        self.timer.start()
        self._last = time.perf_counter()

    def set_playing(self, playing: bool):
        self.playing = bool(playing)

    def advance(self):
        now = time.perf_counter()
        # Never catch up missed GUI frames with a large angular jump. If a
        # status/table refresh briefly delays Qt, continue smoothly from the
        # last visible position instead.
        dt = max(0.0, min(1.0/60.0, now - self._last))
        self._last = now
        if self.playing:
            self.angle = (self.angle + dt * 200.0) % 360.0  # 33 1/3 rpm
            self.update()

    def _button(self, p, rect, text, active=False):
        p.setPen(QPen(QColor("#333a3e"), 1))
        p.setBrush(QColor("#0b0d0f"))
        p.drawRect(rect)
        if active:
            p.setPen(QPen(QColor("#d7e8ef"), 1.2))
        else:
            p.setPen(QPen(QColor("#8a969c"), 1))
        f = p.font()
        f.setPointSizeF(7)
        f.setBold(active)
        p.setFont(f)
        p.drawText(rect, Qt.AlignCenter, text)

    def paintEvent(self, event):
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.Antialiasing, True)
            r = self.rect().adjusted(7, 7, -7, -7)

            # --- SL-1210MKII-like chassis proportions from user reference photo ---
            p.setPen(QPen(QColor("#1e2428"), 1))
            # Turntable deck surface: keep it dark so no large grey block
            # appears behind/left of the tonearm.
            p.setBrush(QColor("#0b1115"))
            p.drawRoundedRect(r, 7, 7)

            deck_w = r.width()
            deck_h = r.height()

            # platter dominates left/center, leaving a narrow right control strip
            platter_d = min(deck_h * .88, deck_w * .68)
            cx = r.left() + platter_d * .62
            cy = r.top() + deck_h * .48
            outer_r = platter_d / 2

            # heavy aluminium platter edge
            p.setPen(QPen(QColor("#242b2f"), 1))
            p.setBrush(QColor("#0d1012"))
            p.drawEllipse(QPointF(cx, cy), outer_r + 6, outer_r + 6)

            # dotted strobe rim: four close rows, like the real 1210 edge
            p.save()
            p.translate(cx, cy)
            p.setPen(Qt.NoPen)
            dot_rows = [
                (outer_r + 4.5, 1.25, "#d6dde0", 112),
                (outer_r + 1.4, 1.00, "#9ba7ac", 112),
                (outer_r - 1.5, 0.90, "#d3dbde", 112),
                (outer_r - 4.4, 0.75, "#7f8b90", 112),
            ]
            for rr, dotr, col, count in dot_rows:
                for i in range(count):
                    a = math.radians(i * (360.0 / count))
                    p.setBrush(QColor(col))
                    p.drawEllipse(QPointF(math.cos(a)*rr, math.sin(a)*rr), dotr, dotr)

            # stylized strobe lamp reflection at front-right of platter edge
            p.setBrush(QColor("#5cecff"))
            for a_deg in (42, 45, 48):
                a = math.radians(a_deg)
                p.drawEllipse(QPointF(math.cos(a)*(outer_r+3.5), math.sin(a)*(outer_r+3.5)), 1.8, 1.8)
            p.restore()

            # rotating vinyl / slipmat area
            vinyl_r = outer_r - 10
            p.save()
            p.translate(cx, cy)
            p.rotate(self.angle)
            p.setBrush(QColor("#050505"))
            p.setPen(QPen(QColor("#1f2326"), 1))
            p.drawEllipse(QRectF(-vinyl_r, -vinyl_r, vinyl_r*2, vinyl_r*2))

            p.setPen(QPen(QColor("#1b1b1b"), .65))
            for k in range(15):
                rr = vinyl_r * (.37 + k*.039)
                p.drawEllipse(QRectF(-rr, -rr, rr*2, rr*2))

            # subtle asymmetric sheen so rotation is visible, but not cartoonish
            sheen = QPen(QColor(225, 230, 232, 28), 2.4)
            sheen.setCapStyle(Qt.RoundCap)
            p.setPen(sheen)
            p.drawArc(QRectF(-vinyl_r*.86, -vinyl_r*.86, vinyl_r*1.72, vinyl_r*1.72), 22*16, 28*16)
            p.drawArc(QRectF(-vinyl_r*.64, -vinyl_r*.64, vinyl_r*1.28, vinyl_r*1.28), 208*16, 20*16)

            # label / spindle
            label_r = vinyl_r * .23
            p.setBrush(QColor("#111518"))
            p.setPen(QPen(QColor("#4a5459"), 1))
            p.drawEllipse(QRectF(-label_r, -label_r, label_r*2, label_r*2))
            p.setBrush(QColor("#d8dee1"))
            p.setPen(QPen(QColor("#202528"), 1.1))
            p.drawEllipse(QPointF(0,0), 3.7, 3.7)
            p.restore()

            # silver 7-inch single adapter ("puck"); the RECORD has the large hole.
            puck_x, puck_y = r.left()+24, r.top()+18
            p.setPen(QPen(QColor("#7b878d"), 1))
            p.setBrush(QColor("#bcc5c9"))
            p.drawEllipse(QPointF(puck_x, puck_y), 11, 11)
            p.setBrush(QColor("#dce2e5"))
            p.drawEllipse(QPointF(puck_x-2.2, puck_y-2.2), 5.0, 5.0)
            # only the small spindle receiving recess
            p.setBrush(QColor("#343b3f"))
            p.setPen(QPen(QColor("#858f94"), .8))
            p.drawEllipse(QPointF(puck_x, puck_y), 1.8, 1.8)

            # --- SL-1200/1210-style tonearm assembly at upper-right ---
            # Keep the gimbal compact and let the tube carry the silhouette.
            # Earlier versions made the S too deep and the counterweight look
            # detached; the geometry below uses one continuous mechanical axis.
            arm_scale = max(.78, min(1.30, deck_h / 300.0))
            px = r.right() - 68 * arm_scale
            py = r.top() + 49 * arm_scale

            # Height-adjustment base and gimbal bearing.
            p.setPen(QPen(QColor("#121719"), 1))
            p.setBrush(QColor("#0a0d0f"))
            p.drawEllipse(QPointF(px, py), 30*arm_scale, 30*arm_scale)
            p.setPen(QPen(QColor("#5c686e"), 1.2))
            p.setBrush(QColor("#252c30"))
            p.drawEllipse(QPointF(px, py), 24*arm_scale, 24*arm_scale)
            p.setPen(QPen(QColor("#99a4a9"), 1.2))
            p.setBrush(QColor("#101416"))
            p.drawEllipse(QPointF(px, py), 16*arm_scale, 16*arm_scale)

            # Horizontal bearing bridge and two visible gimbal caps.
            p.setPen(QPen(QColor("#8e999e"), 1.8*arm_scale, Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(px-15*arm_scale,py),QPointF(px+15*arm_scale,py))
            for bx in (px-15*arm_scale, px+15*arm_scale):
                p.setBrush(QColor("#b8c1c5"))
                p.setPen(QPen(QColor("#4f5a60"), 1))
                p.drawEllipse(QPointF(bx,py),4.0*arm_scale,4.0*arm_scale)
            p.setBrush(QColor("#c8d0d3"))
            p.setPen(QPen(QColor("#59646a"), 1))
            p.drawEllipse(QPointF(px,py),6.0*arm_scale,6.0*arm_scale)

            # Rear shaft and compact cylindrical counterweight.  The -64 degree
            # axis is the direct continuation of the tube through the pivot.
            p.save()
            p.translate(px,py)
            p.rotate(-64)
            p.setPen(QPen(QColor("#8f9a9f"),3.0*arm_scale,Qt.SolidLine,Qt.RoundCap))
            p.drawLine(QPointF(0,0),QPointF(42*arm_scale,0))
            p.setPen(QPen(QColor("#4e585d"),1))
            p.setBrush(QColor("#8e989d"))
            p.drawRoundedRect(QRectF(13*arm_scale,-7*arm_scale,29*arm_scale,14*arm_scale),3,3)
            p.setPen(QPen(QColor("#626c71"),.7))
            for x in range(16,42,4):
                xx=x*arm_scale
                p.drawLine(QPointF(xx,-6.2*arm_scale),QPointF(xx,6.2*arm_scale))
            p.setPen(QPen(QColor("#b7c0c4"),.8))
            p.drawLine(QPointF(14*arm_scale,-6*arm_scale),QPointF(14*arm_scale,6*arm_scale))
            p.restore()

            # Anti-skate dial, cue lever and the separate arm-rest post.
            p.setBrush(QColor("#171c1f"))
            p.setPen(QPen(QColor("#69757b"), 1))
            p.drawEllipse(QPointF(px+27*arm_scale, py+10*arm_scale), 7*arm_scale, 7*arm_scale)
            rest_x=px+19*arm_scale; rest_y=py+69*arm_scale
            p.setPen(QPen(QColor("#8d989d"),2.2*arm_scale,Qt.SolidLine,Qt.RoundCap))
            p.drawLine(QPointF(rest_x,rest_y+16*arm_scale),QPointF(rest_x,rest_y-8*arm_scale))
            p.setPen(QPen(QColor("#c1c9cc"),1.5*arm_scale))
            p.drawArc(QRectF(rest_x-7*arm_scale,rest_y-13*arm_scale,14*arm_scale,10*arm_scale),0,180*16)
            p.setPen(QPen(QColor("#30383c"),3*arm_scale,Qt.SolidLine,Qt.RoundCap))
            p.drawLine(QPointF(px+31*arm_scale,py+36*arm_scale),QPointF(px+37*arm_scale,py+54*arm_scale))

            # The arm terminates just outside the record.  The two curves have
            # a gentle inflection: recognisably S-shaped, without the old
            # banana/J silhouette.
            connector=QPointF(cx+vinyl_r*.92,cy+vinyl_r*.10)
            arm=QPainterPath(QPointF(px-5*arm_scale,py+8*arm_scale))
            arm.cubicTo(
                QPointF(px-10*arm_scale,py+20*arm_scale),
                QPointF(px-16*arm_scale,py+47*arm_scale),
                QPointF(px-29*arm_scale,py+66*arm_scale)
            )
            arm.cubicTo(
                QPointF(px-42*arm_scale,py+89*arm_scale),
                QPointF(connector.x()+20*arm_scale,connector.y()-4*arm_scale),
                connector
            )

            p.setBrush(Qt.NoBrush)
            # A narrow shadow gives the tube depth without the old triangular
            # filled-path artefact.
            p.setPen(QPen(QColor(0,0,0,110),5.8*arm_scale,Qt.SolidLine,Qt.RoundCap,Qt.RoundJoin))
            p.drawPath(arm)
            p.setPen(QPen(QColor("#aeb8bd"),4.2*arm_scale,Qt.SolidLine,Qt.RoundCap,Qt.RoundJoin))
            p.drawPath(arm)
            p.setPen(QPen(QColor("#eef2f4"),.9*arm_scale,Qt.SolidLine,Qt.RoundCap,Qt.RoundJoin))
            p.drawPath(arm)

            # Detachable SME-style headshell, cartridge and stylus.  It follows
            # the groove tangent instead of pointing along the arm tube.
            stylus_target=QPointF(cx+vinyl_r*.61,cy+vinyl_r*.22)
            dx=stylus_target.x()-connector.x(); dy=stylus_target.y()-connector.y()
            shell_angle=math.degrees(math.atan2(dy,dx))
            shell_len=max(1.0,math.hypot(dx,dy))
            p.save()
            p.translate(connector)
            p.rotate(shell_angle)

            p.setPen(QPen(QColor("#657177"),1))
            p.setBrush(QColor("#c0c9cd"))
            p.drawRoundedRect(QRectF(-3*arm_scale,-4.5*arm_scale,9*arm_scale,9*arm_scale),2,2)

            shell=QPainterPath()
            shell.moveTo(5*arm_scale,-6*arm_scale)
            shell.lineTo((shell_len-8*arm_scale),-4*arm_scale)
            shell.lineTo(shell_len,0)
            shell.lineTo((shell_len-8*arm_scale),4*arm_scale)
            shell.lineTo(5*arm_scale,6*arm_scale)
            shell.closeSubpath()
            p.setBrush(QColor("#1a1e21"))
            p.setPen(QPen(QColor("#6f7b80"),1))
            p.drawPath(shell)

            # Headshell slots and finger lift.
            p.setPen(QPen(QColor("#9aa5aa"),1))
            for x in (11,17):
                p.drawLine(QPointF(x*arm_scale,-2.2*arm_scale),QPointF(x*arm_scale,2.2*arm_scale))
            p.setPen(QPen(QColor("#aeb8bd"),1.4*arm_scale,Qt.SolidLine,Qt.RoundCap))
            p.drawLine(QPointF(12*arm_scale,-5*arm_scale),QPointF(9*arm_scale,-14*arm_scale))
            p.drawLine(QPointF(9*arm_scale,-14*arm_scale),QPointF(17*arm_scale,-15*arm_scale))

            # Cartridge and stylus.  In the top view the needle tip itself is
            # the target point on the outer groove.
            p.setBrush(QColor("#0b0d0f"))
            p.setPen(QPen(QColor("#3e484d"),1))
            p.drawRoundedRect(QRectF(shell_len-17*arm_scale,-3*arm_scale,14*arm_scale,6*arm_scale),1.5,1.5)
            p.setPen(QPen(QColor("#d1d7da"),.9*arm_scale))
            p.drawLine(QPointF(shell_len-3*arm_scale,2*arm_scale),QPointF(shell_len,0))
            p.setBrush(QColor("#73eaff"))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(shell_len,0),1.25*arm_scale,1.25*arm_scale)
            p.restore()

            # --- pitch fader at far right, vertical as in real 1210 ---
            fx = r.right() - 23
            fy = r.top() + deck_h * .36
            fh = deck_h * .44
            p.setPen(QPen(QColor("#363f43"), 1))
            p.setBrush(QColor("#0b0e10"))
            p.drawRect(QRectF(fx, fy, 15, fh))

            p.setPen(QPen(QColor("#8f9ba0"), 1.2))
            p.drawLine(QPointF(fx+7.5, fy+8), QPointF(fx+7.5, fy+fh-8))

            # pitch scale ticks
            p.setPen(QPen(QColor("#727e83"), .8))
            for i in range(9):
                yy = fy + 7 + i*(fh-14)/8
                p.drawLine(QPointF(fx-5, yy), QPointF(fx-1, yy))

            p.setBrush(QColor("#b3bdc1"))
            p.setPen(QPen(QColor("#616c71"), 1))
            p.drawRoundedRect(QRectF(fx+1.5, fy+fh*.56, 12, 16), 2, 2)

            # --- lower-left controls from the user's real SL-1210MKII reference ---
            by = r.bottom() - 34

            # Large rectangular silver START/STOP button, matching the real deck.
            ss_rect = QRectF(r.left()+10, by-4, 52, 34)
            p.setPen(QPen(QColor("#59656b"), 1.2))
            p.setBrush(QColor("#aeb8bc"))
            p.drawRect(ss_rect)
            # inset top surface gives it the mechanical push-button look
            p.setPen(QPen(QColor("#d9e0e3"), 1.0))
            p.setBrush(QColor("#bcc5c9"))
            p.drawRect(ss_rect.adjusted(3, 3, -3, -3))
            p.setPen(QColor("#2a3033"))
            f=p.font(); f.setPointSizeF(5.8); f.setBold(True); p.setFont(f)
            p.drawText(ss_rect, Qt.AlignCenter, "START/STOP")

            # Separate small silver speed buttons, directly to the right and slightly lower.
            speed_y = by + 11
            for bx, label, active in ((r.left()+68, "33", True), (r.left()+97, "45", False)):
                br = QRectF(bx, speed_y, 25, 12)
                p.setPen(QPen(QColor("#647178"), 1.0))
                p.setBrush(QColor("#aeb8bc"))
                p.drawRect(br)
                p.setPen(QPen(QColor("#dce2e5"), .7))
                p.drawLine(br.topLeft()+QPointF(1,1), br.topRight()+QPointF(-1,1))
                p.setPen(QColor("#202629" if active else "#394247"))
                f=p.font(); f.setPointSizeF(5.6); f.setBold(active); p.setFont(f)
                p.drawText(br, Qt.AlignCenter, label)

            # popup stylus light / lamp near platter front-right
            lamp_x = cx + outer_r*.70
            lamp_y = cy + outer_r*.82
            p.setBrush(QColor("#c9d2d5"))
            p.setPen(QPen(QColor("#657177"), 1))
            p.drawEllipse(QPointF(lamp_x, lamp_y), 6, 6)
            p.setBrush(QColor("#e9edef"))
            p.drawEllipse(QPointF(lamp_x, lamp_y), 2.5, 2.5)

            # tiny manufacturer-style text only, no logo copying
            p.setPen(QColor("#b3bfc4"))
            f = p.font()
            f.setPointSizeF(6.5)
            f.setBold(True)
            p.setFont(f)
            p.drawText(QRectF(r.right()-150, r.bottom()-27, 115, 12), Qt.AlignRight|Qt.AlignVCenter, "DIRECT DRIVE TURNTABLE")

        finally:
            if p.isActive():
                p.end()



class TurntableWidget(QWidget):
    """Responsive VirtualDJ-style jogwheel with playback and progress feedback."""
    END_ALERT_SECONDS = 15.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.angle = 0.0
        self.progress = 0.0
        self.playing = False
        self.track_key = ""
        self.track_length = 0.0
        self.remaining = None
        self.setMinimumSize(320, 240)
        self.timer = QTimer(self)
        self.timer.setInterval(16)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.timeout.connect(self.advance)
        self.timer.start()
        self._last = time.perf_counter()

    def set_playback(self, playing: bool, position=0.0, length=0.0, track_key=""):
        self.playing = bool(playing)
        key = str(track_key or "")
        if key and key != self.track_key:
            self.track_key = key
            self.progress = 0.0
            self.track_length = 0.0
            self.remaining = None

        try:
            pos = float(position)
            total = float(length)
        except (TypeError, ValueError):
            pos, total = -1.0, 0.0

        # RadioBOSS can briefly return incomplete samples during a refresh.
        # Ignore those and retain the last valid progress instead of jumping.
        if (
            math.isfinite(pos) and math.isfinite(total)
            and total >= 5.0 and 0.0 <= pos <= total * 1.05
        ):
            self.track_length = total
            self.progress = max(0.0, min(1.0, pos / total))
            self.remaining = max(0.0, total - pos)
        self.update()

    def advance(self):
        now = time.perf_counter()
        # Do not catch up missed UI frames with a visible angular jump.
        dt = max(0.0, min(1.0/60.0, now - self._last))
        self._last = now
        if self.playing:
            self.angle = (self.angle + dt * 200.0) % 360.0  # 33 1/3 rpm
            if self.track_length >= 5.0:
                self.progress = min(1.0, self.progress + dt / self.track_length)
            if self.remaining is not None:
                self.remaining = max(0.0, self.remaining - dt)
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        try:
            p.setRenderHint(QPainter.Antialiasing, True)
            r = self.rect().adjusted(7, 7, -7, -7)
            p.setPen(QPen(QColor("#1e2428"), 1))
            p.setBrush(QColor("#0b1115"))
            p.drawRoundedRect(r, 7, 7)

            # All elements derive from this one square, so resizing cannot
            # distort individual mechanical parts as the old tonearm did.
            label_h = 24.0
            diameter = min(r.width() * .72, max(80.0, r.height() - label_h - 24.0))
            radius = diameter / 2.0
            center = QPointF(r.center().x(), r.top() + 10.0 + radius)
            wheel = QRectF(center.x()-radius, center.y()-radius, diameter, diameter)
            ring = wheel.adjusted(-4, -4, 4, 4)

            # Dark base ring plus cyan title-progress ring.
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor("#26343b"), 7.0, Qt.SolidLine, Qt.RoundCap))
            p.drawEllipse(ring)
            end_alert = (
                self.playing and self.remaining is not None
                and 0.0 < self.remaining <= self.END_ALERT_SECONDS
            )
            blink_on = (not end_alert) or (int(time.monotonic() * 4.0) % 2 == 0)
            if blink_on and self.progress > 0.0:
                p.setPen(QPen(QColor(CYAN), 7.0, Qt.SolidLine, Qt.RoundCap))
                p.drawArc(ring, 90 * 16, int(-self.progress * 360.0 * 16))

            # Jogwheel body and subtle grip rings.
            p.setPen(QPen(QColor("#050708"), 4))
            p.setBrush(QColor("#252b30"))
            p.drawEllipse(wheel)
            p.setBrush(Qt.NoBrush)
            for ratio, colour, width in ((.86, "#171c20", 2.0), (.69, "#31383d", 1.0)):
                rr = radius * ratio
                p.setPen(QPen(QColor(colour), width))
                p.drawEllipse(QRectF(center.x()-rr, center.y()-rr, rr*2, rr*2))

            # Long cyan marker rotates continuously while RadioBOSS is playing.
            p.save()
            p.translate(center)
            p.rotate(self.angle)
            p.setPen(QPen(QColor(CYAN), max(4.0, diameter*.026), Qt.SolidLine, Qt.RoundCap))
            p.drawLine(QPointF(0, radius*.18), QPointF(0, radius*.88))
            p.restore()

            # Stable center hub in the Studio Monitor colour scheme.
            hub_r = radius * .22
            p.setPen(QPen(QColor("#050708"), max(5.0, diameter*.028)))
            p.setBrush(QColor("#11161a"))
            p.drawEllipse(center, hub_r, hub_r)
            p.setPen(QPen(QColor(CYAN), max(4.0, diameter*.025)))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(center, hub_r*.57, hub_r*.57)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(CYAN))
            dot_r = max(3.0, diameter*.018)
            p.drawEllipse(center, dot_r, dot_r)

            p.setPen(QColor("#81939c"))
            f = p.font(); f.setPointSizeF(6.8); f.setBold(True); p.setFont(f)
            p.drawText(
                QRectF(r.left()+10, r.bottom()-22, 100, 14),
                Qt.AlignLeft|Qt.AlignVCenter,
                "VINYL · 33⅓ RPM",
            )
            p.setPen(QColor(CYAN if self.playing else "#81939c"))
            p.drawText(
                QRectF(r.right()-105, r.bottom()-22, 95, 14),
                Qt.AlignRight|Qt.AlignVCenter,
                "PLAY" if self.playing else "STOPPED",
            )
        finally:
            if p.isActive():
                p.end()


class StudioClockWidget(QWidget):
    """Classic studio clock that matches the analogue VU-meter design."""
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setFixedSize(160,160)

    def paintEvent(self,event):
        p=QPainter(self)
        try:
            p.setRenderHint(QPainter.Antialiasing,True)
            r=QRectF(self.rect()).adjusted(5,5,-5,-5)
            size=min(r.width(),r.height())
            dial=QRectF(r.center().x()-size/2,r.center().y()-size/2,size,size)
            center=dial.center(); radius=size/2

            p.setPen(QPen(QColor("#24404c"),3))
            p.setBrush(QColor("#071016"))
            p.drawEllipse(dial)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(CYAN),1.2))
            p.drawEllipse(dial.adjusted(3,3,-3,-3))

            for minute in range(60):
                angle=math.radians(minute*6-90)
                major=minute%5==0
                outer=radius-8
                inner=outer-(9 if major else 4)
                colour=QColor("#d9f7ff") if major else QColor("#496975")
                p.setPen(QPen(colour,2.0 if major else .8,Qt.SolidLine,Qt.RoundCap))
                p.drawLine(
                    QPointF(center.x()+math.cos(angle)*inner,center.y()+math.sin(angle)*inner),
                    QPointF(center.x()+math.cos(angle)*outer,center.y()+math.sin(angle)*outer),
                )

            now=time.localtime()
            hour_angle=math.radians(((now.tm_hour%12)+now.tm_min/60.0)*30-90)
            minute_angle=math.radians((now.tm_min+now.tm_sec/60.0)*6-90)
            second_angle=math.radians(now.tm_sec*6-90)

            p.setPen(QPen(QColor("#f2fbff"),5,Qt.SolidLine,Qt.RoundCap))
            p.drawLine(center,QPointF(center.x()+math.cos(hour_angle)*radius*.45,center.y()+math.sin(hour_angle)*radius*.45))
            p.setPen(QPen(QColor(CYAN),3.2,Qt.SolidLine,Qt.RoundCap))
            p.drawLine(center,QPointF(center.x()+math.cos(minute_angle)*radius*.68,center.y()+math.sin(minute_angle)*radius*.68))
            p.setPen(QPen(QColor(RED),1.6,Qt.SolidLine,Qt.RoundCap))
            p.drawLine(
                QPointF(center.x()-math.cos(second_angle)*radius*.13,center.y()-math.sin(second_angle)*radius*.13),
                QPointF(center.x()+math.cos(second_angle)*radius*.76,center.y()+math.sin(second_angle)*radius*.76),
            )
            p.setPen(Qt.NoPen); p.setBrush(QColor("#f3fbff")); p.drawEllipse(center,4,4)
            p.setBrush(QColor(RED)); p.drawEllipse(center,2,2)
        finally:
            if p.isActive(): p.end()


class WeatherSeaWidget(QWidget):
    """Compact QPainter weather + Black Sea graphic. No image files used."""
    def __init__(self, stacked=False, parent=None):
        super().__init__(parent)
        self.data = {}
        self.stacked = bool(stacked)
        if self.stacked:
            self.setFixedSize(220,195)
        else:
            self.setMinimumHeight(88)
            self.setMaximumHeight(112)

    def set_weather(self, data):
        self.data = dict(data or {})
        self.update()

    @staticmethod
    def _condition(code):
        try:
            code = int(code)
        except Exception:
            return "unknown", "Weather"
        if code == 0:
            return "sunny", "Sunny"
        if code in (1, 2):
            return "partly", "Partly cloudy"
        if code == 3:
            return "cloudy", "Cloudy"
        if code in (45, 48):
            return "fog", "Fog"
        if code in (51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 80, 81, 82):
            return "rain", "Rain"
        if code in (71, 73, 75, 77, 85, 86):
            return "snow", "Snow"
        if code in (95, 96, 99):
            return "storm", "Thunderstorm"
        return "unknown", "Weather"

    @staticmethod
    def _cloud(p, x, y, scale=1.0, color=QColor("#dce7eb")):
        p.setPen(Qt.NoPen)
        p.setBrush(color)
        p.drawEllipse(QRectF(x, y+12*scale, 44*scale, 22*scale))
        p.drawEllipse(QRectF(x+7*scale, y+3*scale, 25*scale, 25*scale))
        p.drawEllipse(QRectF(x+23*scale, y+7*scale, 28*scale, 28*scale))

    @staticmethod
    def _wind_text(deg):
        try:
            d = float(deg) % 360
        except Exception:
            return ""
        dirs = ("N","NE","E","SE","S","SW","W","NW")
        return dirs[int((d + 22.5)//45) % 8]

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        if self.stacked:
            self._paint_stacked(p,r)
            p.end()
            return

        gap = 5
        left = QRectF(r.left(), r.top(), r.width()*0.63, r.height())
        sea = QRectF(left.right()+gap, r.top(), r.right()-left.right()-gap, r.height())

        cond, label = self._condition(self.data.get("weather_code"))

        # WEATHER PANEL BACKGROUND
        sky = QLinearGradient(left.topLeft(), left.bottomLeft())
        if cond == "sunny":
            sky.setColorAt(0.0, QColor("#248ed4"))
            sky.setColorAt(1.0, QColor("#77c7ef"))
        elif cond == "partly":
            sky.setColorAt(0.0, QColor("#397fae"))
            sky.setColorAt(1.0, QColor("#8fb9cf"))
        elif cond in ("rain", "storm"):
            sky.setColorAt(0.0, QColor("#263945"))
            sky.setColorAt(1.0, QColor("#617783"))
        elif cond in ("cloudy", "fog", "snow"):
            sky.setColorAt(0.0, QColor("#586c78"))
            sky.setColorAt(1.0, QColor("#a7b4ba"))
        else:
            sky.setColorAt(0.0, QColor("#183545"))
            sky.setColorAt(1.0, QColor("#41677a"))

        p.setPen(QPen(QColor("#24566b"), 1))
        p.setBrush(sky)
        p.drawRoundedRect(left, 8, 8)

        # WEATHER SYMBOL
        icon_x = left.left()+34
        icon_y = left.top()+25

        if cond in ("sunny", "partly"):
            c = QPointF(icon_x, icon_y)
            p.setPen(QPen(QColor("#ffd95b"), 3))
            for deg in range(0,360,45):
                a=math.radians(deg)
                p.drawLine(
                    QPointF(c.x()+math.cos(a)*18,c.y()+math.sin(a)*18),
                    QPointF(c.x()+math.cos(a)*26,c.y()+math.sin(a)*26)
                )
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#ffd34d"))
            p.drawEllipse(c, 14, 14)

        if cond == "partly":
            self._cloud(p,left.left()+28,left.top()+25,.78,QColor("#e7eef1"))
        elif cond == "cloudy":
            self._cloud(p,left.left()+18,left.top()+17,1.0,QColor("#dbe4e8"))
        elif cond in ("rain","storm"):
            self._cloud(p,left.left()+18,left.top()+15,1.0,QColor("#aebcc3"))
            p.setPen(QPen(QColor("#68c9ff"),2.5,Qt.SolidLine,Qt.RoundCap))
            for dx in (30,44,58):
                p.drawLine(QPointF(left.left()+dx,left.top()+58),
                           QPointF(left.left()+dx-4,left.top()+69))
            if cond=="storm":
                bolt=QPainterPath()
                bolt.moveTo(left.left()+62,left.top()+53)
                bolt.lineTo(left.left()+53,left.top()+68)
                bolt.lineTo(left.left()+61,left.top()+66)
                bolt.lineTo(left.left()+54,left.top()+79)
                bolt.lineTo(left.left()+71,left.top()+61)
                bolt.lineTo(left.left()+63,left.top()+62)
                bolt.closeSubpath()
                p.setPen(Qt.NoPen)
                p.setBrush(QColor("#ffd34d"))
                p.drawPath(bolt)
        elif cond == "snow":
            self._cloud(p,left.left()+18,left.top()+15,1.0,QColor("#dfe8eb"))
            p.setPen(QPen(QColor("#ffffff"),2))
            for dx in (31,46,61):
                p.drawText(QPointF(left.left()+dx,left.top()+72),"✦")
        elif cond == "fog":
            p.setPen(QPen(QColor("#e0e8eb"),3,Qt.SolidLine,Qt.RoundCap))
            for yy in (30,44,58):
                p.drawLine(QPointF(left.left()+18,left.top()+yy),
                           QPointF(left.left()+72,left.top()+yy))

        # MAIN WEATHER TEXT
        temp=self.data.get("temperature")
        humidity=self.data.get("humidity")
        wind=self.data.get("wind_speed")
        wind_dir=self._wind_text(self.data.get("wind_direction"))
        stale=bool(self.data.get("stale"))

        temp_text="—°C"
        try: temp_text=f"{round(float(temp))}°C"
        except Exception: pass

        f=p.font()
        f.setBold(True)
        f.setPointSizeF(14)
        p.setFont(f)
        p.setPen(QColor("#ffffff"))
        p.drawText(QRectF(left.left()+80,left.top()+8,left.width()-90,27),
                   Qt.AlignLeft|Qt.AlignVCenter,temp_text)

        f.setBold(False)
        f.setPointSizeF(9)
        p.setFont(f)
        p.setPen(QColor("#f1fbff"))
        p.drawText(QRectF(left.left()+80,left.top()+25,left.width()-90,18),
                   Qt.AlignLeft|Qt.AlignVCenter,label+(" · STALE" if stale else ""))

        # compact divider
        p.setPen(QPen(QColor(255,255,255,70),1))
        p.drawLine(QPointF(left.left()+16,left.top()+61),
                   QPointF(left.right()-16,left.top()+61))

        # HUMIDITY + WIND as prominent values
        f.setBold(True)
        f.setPointSizeF(9)
        p.setFont(f)

        p.setPen(QColor("#dff7ff"))
        p.drawText(QRectF(left.left()+18,left.top()+66,left.width()*0.42,18),
                   Qt.AlignLeft|Qt.AlignVCenter,"HUMIDITY")
        hum_text="—"
        try: hum_text=f"{round(float(humidity))}%"
        except Exception: pass
        p.setPen(QColor("#ffd34d"))
        p.drawText(QRectF(left.left()+18,left.top()+82,left.width()*0.42,22),
                   Qt.AlignLeft|Qt.AlignVCenter,hum_text)

        p.setPen(QColor("#dff7ff"))
        p.drawText(QRectF(left.left()+left.width()*0.48,left.top()+66,left.width()*0.46,18),
                   Qt.AlignLeft|Qt.AlignVCenter,"WIND")
        wind_text="—"
        try:
            wind_text=f"{round(float(wind))} km/h"
            if wind_dir:
                wind_text += f" {wind_dir}"
        except Exception:
            pass
        p.setPen(QColor("#ffffff"))
        p.drawText(QRectF(left.left()+left.width()*0.48,left.top()+82,left.width()*0.46,22),
                   Qt.AlignLeft|Qt.AlignVCenter,wind_text)

        # BLACK SEA PANEL
        ocean=QLinearGradient(sea.topLeft(),sea.bottomLeft())
        ocean.setColorAt(0.0,QColor("#1675a6"))
        ocean.setColorAt(0.42,QColor("#0a84b8"))
        ocean.setColorAt(1.0,QColor("#05385b"))
        p.setPen(QPen(QColor("#226f91"),1))
        p.setBrush(ocean)
        p.drawRoundedRect(sea,8,8)

        f.setBold(True)
        f.setPointSizeF(9)
        p.setFont(f)
        p.setPen(QColor("#e9fbff"))
        p.drawText(QRectF(sea.left()+5,sea.top()+7,sea.width()-10,17),
                   Qt.AlignCenter,"BLACK SEA")

        # waves
        p.setBrush(Qt.NoBrush)
        for row,alpha in ((0,190),(1,130),(2,85)):
            path=QPainterPath()
            y=sea.top()+30+row*13
            path.moveTo(sea.left()+9,y)
            x=sea.left()+9
            while x<sea.right()-8:
                path.cubicTo(x+7,y-5,x+13,y+5,x+20,y)
                x+=20
            col=QColor("#b7f1ff")
            col.setAlpha(alpha)
            p.setPen(QPen(col,2))
            p.drawPath(path)

        sea_temp=self.data.get("sea_temperature")
        sea_text="— °C"
        try: sea_text=f"{float(sea_temp):.1f} °C"
        except Exception: pass

        f.setBold(True)
        f.setPointSizeF(13)
        p.setFont(f)
        p.setPen(QColor("#ffffff"))
        p.drawText(QRectF(sea.left()+5,sea.bottom()-37,sea.width()-10,25),
                   Qt.AlignCenter,sea_text)

        f.setBold(False)
        f.setPointSizeF(8)
        p.setFont(f)
        p.setPen(QColor("#bceeff"))
        p.drawText(QRectF(sea.left()+5,sea.bottom()-18,sea.width()-10,16),
                   Qt.AlignCenter,"WATER TEMPERATURE")

        p.end()

    def _paint_stacked(self,p,r):
        """Draw two small tiles vertically for the Studio Time panel."""
        gap=5.0
        weather_h=(r.height()-gap)*.56
        weather=QRectF(r.left(),r.top(),r.width(),weather_h)
        sea=QRectF(r.left(),weather.bottom()+gap,r.width(),r.bottom()-weather.bottom()-gap)
        cond,label=self._condition(self.data.get("weather_code"))

        sky=QLinearGradient(weather.topLeft(),weather.bottomLeft())
        if cond=="sunny":
            sky.setColorAt(0,QColor("#248ed4")); sky.setColorAt(1,QColor("#77c7ef"))
        elif cond=="partly":
            sky.setColorAt(0,QColor("#397fae")); sky.setColorAt(1,QColor("#8fb9cf"))
        elif cond in ("rain","storm"):
            sky.setColorAt(0,QColor("#263945")); sky.setColorAt(1,QColor("#617783"))
        else:
            sky.setColorAt(0,QColor("#385360")); sky.setColorAt(1,QColor("#849ba5"))
        p.setPen(QPen(QColor("#24566b"),1)); p.setBrush(sky)
        p.drawRoundedRect(weather,8,8)

        icon=QPointF(weather.left()+27,weather.top()+28)
        if cond in ("sunny","partly"):
            p.setPen(QPen(QColor("#ffd95b"),2))
            for deg in range(0,360,45):
                a=math.radians(deg)
                p.drawLine(
                    QPointF(icon.x()+math.cos(a)*11,icon.y()+math.sin(a)*11),
                    QPointF(icon.x()+math.cos(a)*16,icon.y()+math.sin(a)*16),
                )
            p.setPen(Qt.NoPen); p.setBrush(QColor("#ffd34d")); p.drawEllipse(icon,8,8)
        if cond=="partly":
            self._cloud(p,weather.left()+20,weather.top()+24,.45,QColor("#e7eef1"))
        elif cond in ("cloudy","fog","snow","rain","storm"):
            self._cloud(p,weather.left()+15,weather.top()+19,.55,QColor("#dbe4e8"))

        temp=self.data.get("temperature")
        temp_text="—°C"
        try: temp_text=f"{round(float(temp))}°C"
        except Exception: pass
        f=p.font(); f.setBold(True); f.setPointSizeF(18); p.setFont(f); p.setPen(QColor("#ffffff"))
        p.drawText(QRectF(weather.left()+53,weather.top()+8,weather.width()-59,25),Qt.AlignLeft|Qt.AlignVCenter,temp_text)
        f.setBold(False); f.setPointSizeF(8.5); p.setFont(f)
        p.drawText(QRectF(weather.left()+53,weather.top()+29,weather.width()-59,16),Qt.AlignLeft|Qt.AlignVCenter,label)

        humidity=self.data.get("humidity")
        wind=self.data.get("wind_speed")
        wind_dir=self._wind_text(self.data.get("wind_direction"))
        pressure=self.data.get("pressure")
        hum_text="—"
        try: hum_text=f"{round(float(humidity))}%"
        except Exception: pass
        wind_text="—"
        try:
            wind_text=f"{round(float(wind))} km/h"
            if wind_dir: wind_text+=f" {wind_dir}"
        except Exception: pass
        pressure_text="—"
        try: pressure_text=f"{round(float(pressure))} hPa"
        except Exception: pass
        columns=(("HUMIDITY",hum_text,QColor("#ffd34d")),("WIND",wind_text,QColor("#ffffff")),("PRESSURE",pressure_text,QColor("#ffffff")))
        col_w=(weather.width()-12)/3.0
        for index,(title,value,colour) in enumerate(columns):
            x=weather.left()+6+index*col_w
            f.setBold(True); f.setPointSizeF(6.5); p.setFont(f); p.setPen(QColor("#dff7ff"))
            p.drawText(QRectF(x,weather.bottom()-31,col_w,12),Qt.AlignCenter,title)
            f.setPointSizeF(7.7); p.setFont(f); p.setPen(colour)
            p.drawText(QRectF(x,weather.bottom()-19,col_w,14),Qt.AlignCenter,value)

        ocean=QLinearGradient(sea.topLeft(),sea.bottomLeft())
        ocean.setColorAt(0,QColor("#1675a6")); ocean.setColorAt(.45,QColor("#0a84b8")); ocean.setColorAt(1,QColor("#05385b"))
        p.setPen(QPen(QColor("#226f91"),1)); p.setBrush(ocean); p.drawRoundedRect(sea,8,8)
        f.setBold(True); f.setPointSizeF(9); p.setFont(f); p.setPen(QColor("#e9fbff"))
        p.drawText(QRectF(sea.left()+5,sea.top()+5,sea.width()-10,15),Qt.AlignCenter,"BLACK SEA")

        p.setBrush(Qt.NoBrush)
        for row,alpha in ((0,170),(1,100)):
            path=QPainterPath(); y=sea.top()+29+row*10; path.moveTo(sea.left()+8,y); x=sea.left()+8
            while x<sea.left()+sea.width()*.48:
                path.cubicTo(x+5,y-4,x+10,y+4,x+15,y); x+=15
            col=QColor("#b7f1ff"); col.setAlpha(alpha); p.setPen(QPen(col,1.7)); p.drawPath(path)

        sea_temp=self.data.get("sea_temperature")
        sea_text="— °C"
        try: sea_text=f"{float(sea_temp):.1f} °C"
        except Exception: pass
        right=QRectF(sea.left()+sea.width()*.48,sea.top()+20,sea.width()*.50,sea.height()-23)
        f.setBold(True); f.setPointSizeF(14); p.setFont(f); p.setPen(QColor("#ffffff"))
        p.drawText(QRectF(right.left(),right.top()+3,right.width(),22),Qt.AlignCenter,sea_text)
        f.setBold(False); f.setPointSizeF(7); p.setFont(f); p.setPen(QColor("#bceeff"))
        p.drawText(QRectF(right.left(),right.top()+24,right.width(),18),Qt.AlignCenter,"WATER TEMP")


class HourCountdownWidget(QWidget):
    """Lightweight countdown to the next full hour."""
    def __init__(self,parent=None):
        super().__init__(parent)
        self.setMinimumSize(118,118)
        self.setMaximumSize(138,138)

    def paintEvent(self,event):
        p=QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        now=time.localtime()
        elapsed=now.tm_min*60+now.tm_sec
        remaining=3600-elapsed if elapsed else 3600
        progress=elapsed/3600.0
        r=QRectF(self.rect()).adjusted(9,9,-9,-9)
        size=min(r.width(),r.height())
        ring=QRectF(r.center().x()-size/2,r.center().y()-size/2,size,size)
        if remaining<=60:
            colour=QColor(RED if int(time.monotonic()*2)%2==0 else "#541018")
        else:
            colour=QColor(AMBER if remaining<=180 else CYAN)

        p.setBrush(QColor("#02080d")); p.setPen(QPen(QColor("#20333c"),6,Qt.SolidLine,Qt.RoundCap)); p.drawEllipse(ring)
        p.setBrush(Qt.NoBrush); p.setPen(QPen(colour,6,Qt.SolidLine,Qt.RoundCap))
        p.drawArc(ring,90*16,int(-progress*360*16))

        f=p.font(); f.setBold(True); f.setFamily("Consolas"); f.setPointSizeF(16); p.setFont(f); p.setPen(colour)
        p.drawText(QRectF(ring.left()+5,ring.center().y()-20,ring.width()-10,28),Qt.AlignCenter,f"{remaining//60:02d}:{remaining%60:02d}")
        f.setFamily("Segoe UI"); f.setPointSizeF(6.8); p.setFont(f); p.setPen(QColor("#8fb7c5"))
        p.drawText(QRectF(ring.left()+5,ring.center().y()+8,ring.width()-10,19),Qt.AlignCenter,"FULL HOUR IN")
        p.end()



class Panel(QFrame):
    def __init__(self, title: str, parent=None):
        super().__init__(parent)
        self.setObjectName("panel")
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(10,8,10,8)
        self.layout.setSpacing(5)
        self.title_label=QLabel(title)
        self.title_label.setObjectName("panelTitle")
        self.layout.addWidget(self.title_label)

    def set_title(self,title):
        self.title_label.setText(str(title or ""))

class StudioMonitor(QMainWindow):
    SILENCE_ALARM_SECONDS=15.0
    SILENCE_LEVEL_THRESHOLD=0.001

    def __init__(self):
        super().__init__()
        self.config_doc=backend.load_public_config()
        self.active_station=str(self.config_doc.get("active_station") or "station-1")
        self._station_generation=0
        self._request_serial=0
        self._request_started=0.0
        self._weather_busy=False
        self._weather_started=0.0
        self._radioboss_playing=False
        self._silence_started=None
        self._silence_indicator_signature=None
        self._playlist_signature=None
        self._current_art_signature=object()
        self._next_art_signature=object()
        self._art_cache_lock=threading.Lock()
        self._art_cache={
            "current":{"key":"","data":b"","attempt":0.0},
            "next":{"key":"","data":b"","attempt":0.0},
        }
        self.setWindowTitle(str(self.config_doc.get("application_title") or "RadioBOSS Studio Monitor")+" v1.0.10")
        self.resize(1680, 940)
        self.setMinimumSize(900, 620)

        root=QWidget()
        root.setMinimumSize(1180,690)
        scroll=QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setWidget(root)
        self.setCentralWidget(scroll)

        # Remember the screen/window position between starts.
        self._window_settings = QSettings("RadioBOSSCommunity", "StudioMonitor")
        saved_pos = self._window_settings.value("window/pos")
        if saved_pos is not None:
            try:
                self.move(saved_pos)
            except Exception:
                pass
        grid=QGridLayout(root)
        grid.setContentsMargins(7,7,7,7)
        grid.setSpacing(6)

        # top: on air / brand / clock-weather
        self.onair = Panel("RADIOBOSS")
        self.onair_lbl=QLabel("OFF AIR"); self.onair_lbl.setObjectName("onAir")
        self.conn=QLabel("● NOT CONNECTED"); self.conn.setObjectName("status")
        self.silence_alarm=QLabel("SILENCE MONITOR · STANDBY")
        self.silence_alarm.setObjectName("silenceAlarm")
        self.silence_alarm.setAlignment(Qt.AlignCenter)
        self.silence_alarm.setMinimumHeight(30)
        self.api_info=QLabel("API —"); self.api_info.setObjectName("muted")
        self.api_error=QLabel(""); self.api_error.setObjectName("errorSmall")
        self.api_error.setWordWrap(True)
        self.onair.layout.addWidget(self.onair_lbl)
        self.onair.layout.addWidget(self.conn)
        self.onair.layout.addWidget(self.silence_alarm)
        self.onair.layout.addWidget(self.api_info)
        self.onair.layout.addWidget(self.api_error)
        self._set_silence_indicator("standby")
        grid.addWidget(self.onair,0,0)

        self.brand_panel=Panel("RADIO STATION")
        self.station_row=QHBoxLayout()
        self.station_row.setSpacing(6)
        self.brand_panel.layout.addLayout(self.station_row)
        vu_top=QHBoxLayout()
        vu_top.setSpacing(10)
        self.vu_left=AnalogVUMeter("L")
        self.vu_right=AnalogVUMeter("R")
        # A real analogue VU face needs enough height to keep its arc round.
        # The former short top row made the scale look horizontally stretched.
        self.vu_left.setMinimumHeight(135)
        self.vu_right.setMinimumHeight(135)
        vu_top.addWidget(self.vu_left)
        vu_top.addWidget(self.vu_right)
        self.brand_panel.layout.addLayout(vu_top)
        grid.addWidget(self.brand_panel,0,1,1,2)

        timep=Panel("STUDIO TIME / WEATHER")
        self.clock=QLabel("--:--:--"); self.clock.setObjectName("clock")
        self.date_label=QLabel("—"); self.date_label.setObjectName("muted")
        self.weather=QLabel("Weather disabled"); self.weather.setObjectName("cyan")
        self.weather_detail=QLabel(""); self.weather_detail.setObjectName("muted")
        self.weather_detail.setWordWrap(True)
        time_content=QHBoxLayout()
        time_content.setSpacing(8)
        time_text=QVBoxLayout()
        time_text.setSpacing(2)
        self.analog_clock=StudioClockWidget()
        time_text.addWidget(self.analog_clock,0,Qt.AlignHCenter)
        self.clock.setObjectName("clockSmall")
        self.clock.setAlignment(Qt.AlignCenter)
        self.date_label.setAlignment(Qt.AlignCenter)
        self.weather.setAlignment(Qt.AlignCenter)
        time_text.addWidget(self.clock)
        time_text.addWidget(self.date_label)
        time_text.addWidget(self.weather)
        time_text.setAlignment(Qt.AlignVCenter)
        time_content.addLayout(time_text,1)
        self.weather_visual=WeatherSeaWidget(stacked=True)
        time_content.addWidget(self.weather_visual,0,Qt.AlignVCenter|Qt.AlignRight)
        timep.layout.addLayout(time_content,1)
        grid.addWidget(timep,0,3)

        # current deck + info
        cur=Panel("CURRENT TRACK")
        ch=QHBoxLayout()
        ch.setSpacing(10)
        self.turntable=TurntableWidget()
        self.turntable.setMinimumWidth(280)
        self.turntable.setMaximumWidth(430)
        ch.addWidget(self.turntable)
        info=QVBoxLayout()
        info.setSpacing(3)
        self.current_cover=QLabel()
        self.current_cover.setObjectName("cover")
        self.current_cover.setFixedSize(82,82)
        self.current_cover.setAlignment(Qt.AlignCenter)
        self.current_cover.setText("NO ART")
        info.addWidget(self.current_cover, alignment=Qt.AlignLeft)

        self.cur_artist=QLabel("—"); self.cur_artist.setObjectName("artist")
        self.cur_title=QLabel("—"); self.cur_title.setObjectName("trackTitle")
        self.cur_album=QLabel("—"); self.cur_album.setObjectName("muted")
        self.remaining=QLabel("--:--"); self.remaining.setObjectName("bigCyan")
        self.bpm=QLabel("BPM —"); self.bpm.setObjectName("cyan")
        self.listeners=QLabel("LISTENERS —"); self.listeners.setObjectName("cyan")
        self.play_state=QLabel("STATE —"); self.play_state.setObjectName("cyan")
        self.progress=QProgressBar(); self.progress.setRange(0,100); self.progress.setTextVisible(False)
        for label in [self.cur_artist,self.cur_title,self.cur_album]:
            label.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Preferred)
        for w in [self.cur_artist,self.cur_title,self.cur_album,self.remaining,self.bpm,self.listeners,self.play_state,self.progress]:
            info.addWidget(w)
        info.addStretch()
        ch.addLayout(info,3)

        # Use the previously empty right side for the complete next title.
        # The card has its own width limit so it never pushes the jogwheel out.
        self.next_card=QFrame()
        self.next_card.setObjectName("nextCard")
        self.next_card.setMinimumWidth(250)
        self.next_card.setMaximumWidth(360)
        next_layout=QVBoxLayout(self.next_card)
        next_layout.setContentsMargins(9,8,9,8)
        next_layout.setSpacing(6)
        next_head=QLabel("NEXT TRACK")
        next_head.setObjectName("nextHeader")
        next_layout.addWidget(next_head)

        next_body=QHBoxLayout()
        next_body.setSpacing(9)
        self.next_cover=QLabel("NO ART")
        self.next_cover.setObjectName("coverSmall")
        self.next_cover.setFixedSize(96,96)
        self.next_cover.setAlignment(Qt.AlignCenter)
        next_body.addWidget(self.next_cover,0,Qt.AlignTop)

        next_info=QVBoxLayout()
        next_info.setSpacing(3)
        self.next_artist=QLabel("—")
        self.next_artist.setObjectName("nextArtist")
        self.next_artist.setWordWrap(True)
        self.next_title=QLabel("—")
        self.next_title.setObjectName("trackTitleSmall")
        self.next_title.setWordWrap(True)
        self.next_album=QLabel("—")
        self.next_album.setObjectName("muted")
        self.next_album.setWordWrap(True)
        for label in [self.next_artist,self.next_title,self.next_album]:
            label.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Preferred)
            next_info.addWidget(label)
        next_info.addStretch()
        next_body.addLayout(next_info,1)
        next_layout.addLayout(next_body)

        self.next_in=QLabel("START IN --:--")
        self.next_in.setObjectName("nextStart")
        next_layout.addWidget(self.next_in)
        next_layout.addStretch()
        ch.addWidget(self.next_card,2)
        cur.layout.addLayout(ch)
        grid.addWidget(cur,1,0,1,3)

        # Scheduler widgets move into the combined automation panel at right.
        self.event=QLabel("NEXT EVENT · —"); self.event.setObjectName("green")
        self.event_time=QLabel("AT —"); self.event_time.setObjectName("cyan")
        self.event_in=QLabel("IN —"); self.event_in.setObjectName("cyan")
        self.upcoming_title=QLabel("UPCOMING EVENTS"); self.upcoming_title.setObjectName("cyan")
        self.upcoming_events=[]
        for _ in range(3):
            lbl=QLabel("—")
            lbl.setObjectName("muted")
            lbl.setWordWrap(False)
            self.upcoming_events.append(lbl)

        # Combined scheduler + BroadcastVoice/hour-close status.
        bvp=Panel("SCHEDULER / BROADCASTVOICE · HOUR CLOSE")
        bvp.layout.setContentsMargins(8,6,8,6)
        bvp.layout.setSpacing(2)
        scheduler_head=QLabel("SCHEDULER / UPCOMING")
        scheduler_head.setObjectName("sectionTitle")
        bvp.layout.addWidget(scheduler_head)
        bvp.layout.addWidget(self.event)
        event_timing=QHBoxLayout()
        event_timing.addWidget(self.event_time)
        event_timing.addWidget(self.event_in)
        event_timing.addStretch()
        bvp.layout.addLayout(event_timing)
        bvp.layout.addWidget(self.upcoming_title)
        for lbl in self.upcoming_events:
            bvp.layout.addWidget(lbl)

        bv_head=QLabel("BROADCASTVOICE / HOUR CLOSE")
        bv_head.setObjectName("sectionTitle")
        bvp.layout.addWidget(bv_head)
        self.bv_state=QLabel("—"); self.bv_state.setObjectName("green")
        self.announcer=QLabel("ANNOUNCER: —")
        self.next_link=QLabel("NEXT LINK IN: —"); self.next_link.setObjectName("cyan")
        self.anchor=QLabel("FULL HOUR BLOCK IN —"); self.anchor.setObjectName("bigGreen")
        self.hour_block=QLabel("ANCHOR: —"); self.hour_block.setObjectName("cyan")
        self.stop_mode=QLabel("STOP: —")
        self.prepared=QLabel("PREPARED: —")
        self.max_cut=QLabel("MAX CUT: —"); self.max_cut.setObjectName("cyan")
        self.filler=QLabel("FILLER: —"); self.filler.setObjectName("green")

        bv_status=QHBoxLayout()
        bv_status.addWidget(self.bv_state)
        bv_status.addWidget(self.announcer)
        bv_status.addStretch()
        bvp.layout.addLayout(bv_status)
        bvp.layout.addWidget(self.next_link)
        bvp.layout.addWidget(self.anchor)
        bvp.layout.addWidget(self.hour_block)
        mode_row=QHBoxLayout()
        mode_row.addWidget(self.stop_mode)
        mode_row.addWidget(self.prepared)
        bvp.layout.addLayout(mode_row)
        final_row=QHBoxLayout()
        final_row.addWidget(self.max_cut)
        final_row.addWidget(self.filler)
        bvp.layout.addLayout(final_row)
        bvp.layout.addStretch()
        grid.addWidget(bvp,1,3)

        # playlist
        pp=Panel("PLAYLIST · CURRENT HOUR")
        self.playlist_meta=QLabel("—"); self.playlist_meta.setObjectName("cyan")
        pp.layout.addWidget(self.playlist_meta)
        self.table=QTableWidget(0,7)
        self.table.setHorizontalHeaderLabels(["#","TIME","ARTIST","TITLE","LENGTH","BPM","STATUS"])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionMode(QTableWidget.NoSelection)
        self.table.setShowGrid(False)
        self.table.horizontalHeader().setSectionResizeMode(0,QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(1,QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2,QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(3,QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4,QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5,QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(6,QHeaderView.ResizeToContents)
        pp.layout.addWidget(self.table)
        self.playlist_footer=QLabel("TOTAL — · TRACKS — · HOUR LEFT —")
        self.playlist_footer.setObjectName("muted")
        pp.layout.addWidget(self.playlist_footer)
        grid.addWidget(pp,2,0,1,3)

        # Compact system status. Maintenance buttons remain available,
        # but no longer consume the whole lower-right panel.
        sys=Panel("SYSTEM / TOOLS")
        self.system=QLabel("SYSTEM OK · RADIOBOSS — · BRIDGE NATIVE"); self.system.setObjectName("green")
        self.last_update=QLabel("LAST UPDATE —"); self.last_update.setObjectName("muted")

        status_row=QHBoxLayout()
        status_row.setSpacing(6)
        self.sys_state=QLabel("SYSTEM\nOK")
        self.rb_state=QLabel("RADIOBOSS\n—")
        self.bridge_state=QLabel("BRIDGE\nNATIVE")
        for w in [self.sys_state,self.rb_state,self.bridge_state]:
            w.setObjectName("statusBox")
            w.setAlignment(Qt.AlignCenter)
            w.setMaximumHeight(44)
            status_row.addWidget(w)
        sys.layout.addLayout(status_row)

        self.audio_status=QLabel("AUDIO —"); self.audio_status.setObjectName("cyan")
        self.audio_detail=QLabel(""); self.audio_detail.setObjectName("muted")
        self.audio_detail.setWordWrap(True)
        self.audio_detail.setMaximumHeight(34)

        compact_info=QHBoxLayout()
        compact_info.addWidget(self.last_update)
        compact_info.addStretch()
        compact_info.addWidget(self.audio_status)
        sys.layout.addLayout(compact_info)
        sys.layout.addWidget(self.audio_detail)

        self.btn_diag=QPushButton("DIAGNOSE")
        self.btn_api=QPushButton("API TEST")
        self.btn_audio=QPushButton("AUDIO METER")
        self.btn_config=QPushButton("SETTINGS")

        self.btn_diag.clicked.connect(self.run_diagnose)
        self.btn_api.clicked.connect(self.run_api_test)
        self.btn_audio.clicked.connect(self.install_audio_meter)
        self.btn_config.clicked.connect(self.open_config)

        tool_row=QHBoxLayout()
        tool_row.setSpacing(6)
        for button in [self.btn_diag,self.btn_api,self.btn_audio,self.btn_config]:
            button.setMaximumHeight(28)
            tool_row.addWidget(button)
        sys.layout.addLayout(tool_row)

        # The former weather area now shows programming information that is
        # useful during operation without any extra API or audio processing.
        hour_overview=QFrame()
        hour_overview.setObjectName("hourOverview")
        hour_layout=QHBoxLayout(hour_overview)
        hour_layout.setContentsMargins(7,5,7,5)
        hour_layout.setSpacing(8)
        self.hour_countdown=HourCountdownWidget()
        hour_layout.addWidget(self.hour_countdown,0,Qt.AlignVCenter)
        hour_events=QVBoxLayout()
        hour_events.setSpacing(4)
        hour_head=QLabel("NEXT SCHEDULER EVENTS")
        hour_head.setObjectName("nextHeader")
        hour_events.addWidget(hour_head)
        self.hour_scheduler_events=[]
        for prefix in ("NEXT","THEN"):
            label=QLabel(prefix+" · —")
            label.setObjectName("scheduleTile")
            label.setWordWrap(True)
            label.setMinimumHeight(44)
            label.setMaximumHeight(55)
            label.setSizePolicy(QSizePolicy.Ignored,QSizePolicy.Preferred)
            hour_events.addWidget(label)
            self.hour_scheduler_events.append(label)
        hour_layout.addLayout(hour_events,1)
        sys.layout.addWidget(hour_overview,1)
        grid.addWidget(sys,2,3)

        # Give the VU row a natural analogue-meter aspect ratio. The middle
        # and playlist/tools rows remain large enough and keep their scrolling.
        grid.setRowStretch(0,5); grid.setRowStretch(1,6); grid.setRowStretch(2,7)
        grid.setColumnStretch(0,3); grid.setColumnStretch(1,3); grid.setColumnStretch(2,3); grid.setColumnStretch(3,4)

        self.signals=DataSignals()
        self.signals.state.connect(self.apply_state)
        self.signals.weather.connect(self.apply_weather)
        self.signals.audio.connect(self.apply_audio)
        self.signals.error.connect(self.show_error)
        self.pool=ThreadPoolExecutor(max_workers=4)
        self.busy=False

        interval=max(750,int(self.config_doc.get("refresh_interval_ms") or 1500))
        self.timer=QTimer(self); self.timer.setInterval(interval); self.timer.timeout.connect(self.request_state); self.timer.start()
        self.audio_timer=QTimer(self); self.audio_timer.setInterval(100); self.audio_timer.timeout.connect(self.request_audio); self.audio_timer.start()
        self.clock_timer=QTimer(self); self.clock_timer.setInterval(250); self.clock_timer.timeout.connect(self.tick_clock); self.clock_timer.start()
        self.weather_timer=QTimer(self); self.weather_timer.setInterval(600000); self.weather_timer.timeout.connect(self.request_weather); self.weather_timer.start()
        self.watchdog_timer=QTimer(self); self.watchdog_timer.setInterval(1000); self.watchdog_timer.timeout.connect(self.watchdog_tick); self.watchdog_timer.start()

        if bool(self.config_doc.get("audio_meter_enabled",True)):
            threading.Thread(target=backend._audio_meter_worker,daemon=True,name="NativeAudioMeter").start()
        else:
            backend._audio_set(available=False,left=0.0,right=0.0,error="Audio meter disabled in Settings")
        self.rebuild_station_buttons()
        self.request_state()
        self.request_weather()

    def tick_clock(self):
        self.clock.setText(time.strftime("%H:%M:%S"))
        self.date_label.setText(time.strftime("%A · %d.%m.%Y"))
        self.analog_clock.update()
        self.hour_countdown.update()

    def rebuild_station_buttons(self):
        while self.station_row.count():
            item=self.station_row.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        stations=self.config_doc.get("stations") or []
        station=stations[0] if stations else {}
        self.active_station=str(station.get("id") or "station-1")
        self.brand_panel.set_title(str(station.get("name") or "RADIO STATION").upper())
        label=QLabel(str(station.get("short_name") or "LOCAL STATION"))
        label.setObjectName("green")
        self.station_row.addWidget(label)
        self.station_row.addStretch()

    def switch_station(self,station_id):
        if not station_id or station_id==self.active_station:return
        if not any(str(x.get("id"))==station_id for x in self.config_doc.get("stations") or []):return
        self.active_station=station_id
        self.config_doc["active_station"]=station_id
        self._station_generation+=1
        self.busy=False
        self._weather_busy=False
        self._reset_artwork_cache()
        try: backend.save_public_config(self.config_doc)
        except Exception: pass
        self.rebuild_station_buttons()
        self.api_error.setText("")
        self.conn.setText("● CONNECTING")
        self.request_state()
        self.request_weather()

    def _reset_artwork_cache(self):
        with self._art_cache_lock:
            for slot in ("current","next"):
                self._art_cache[slot]={"key":"","data":b"","attempt":0.0}
        self._current_art_signature=object()
        self._next_art_signature=object()

    def _cached_artwork(self,cfg,station_id,slot,track):
        fields=("artist","title","filename")
        track_key="\x1f".join(str((track or {}).get(name) or "").strip() for name in fields)
        key=f"{station_id}\x1f{track_key}" if track_key.strip("\x1f") else ""
        if not key:
            return b""

        now=time.monotonic()
        with self._art_cache_lock:
            cached=dict(self._art_cache[slot])
        # Successful artwork remains cached for the whole title. If artwork
        # was temporarily unavailable, wait 30 seconds before trying again.
        if cached["key"]==key and (cached["data"] or now-cached["attempt"]<30.0):
            return cached["data"]

        action="trackartwork" if slot=="current" else "nexttrackartwork"
        try:
            data=backend.fetch_bytes(backend.rb_url(cfg,action),timeout=1.5)
        except Exception:
            data=b""
        with self._art_cache_lock:
            self._art_cache[slot]={"key":key,"data":data,"attempt":now}
        return data

    def request_state(self):
        if self.busy: return
        self.busy=True
        self._request_started=time.monotonic()
        self._request_serial+=1
        serial=self._request_serial
        generation=self._station_generation
        station_id=self.active_station
        def job():
            try:
                cfg=backend.load_config(station_id)
                d=backend.rb_state(cfg)
                d["scheduler"]=backend.scheduler_state(cfg)
                d["broadcastvoice"]=backend.bv_state(cfg)
                if d.get("connected"):
                    d["playlist"]=backend.playlist_state(cfg,d.get("playback") or {},d.get("current") or {})

                if d.get("connected"):
                    d["_art_current_bytes"]=self._cached_artwork(
                        cfg,station_id,"current",d.get("current") or {}
                    )
                    d["_art_next_bytes"]=self._cached_artwork(
                        cfg,station_id,"next",d.get("next") or {}
                    )
                d["_station_id"]=station_id
                d["_generation"]=generation
                d["_serial"]=serial
                self.signals.state.emit(d)
            except Exception as e:
                self.signals.error.emit(repr(e))
            finally:
                if serial==self._request_serial:
                    self.busy=False
        self.pool.submit(job)

    def request_weather(self):
        if self._weather_busy:return
        self._weather_busy=True
        self._weather_started=time.monotonic()
        generation=self._station_generation
        station_id=self.active_station
        def job():
            try:
                data=backend.weather_state(backend.load_config(station_id))
                data["_generation"]=generation
                self.signals.weather.emit(data)
            except Exception as exc:
                self.signals.weather.emit({"ok":False,"error":str(exc),"_generation":generation})
            finally:
                self._weather_busy=False
        self.pool.submit(job)

    def watchdog_tick(self):
        now=time.monotonic()
        if self.busy and self._request_started and now-self._request_started>12:
            self._request_serial+=1
            self.busy=False
            self.api_error.setText("RadioBOSS request timed out; retrying…")
            self.api_error.setVisible(True)
        if self._weather_busy and self._weather_started and now-self._weather_started>15:
            self._weather_busy=False

    def request_audio(self):
        try:
            self.signals.audio.emit(backend.audio_state())
        except Exception:
            pass

    @staticmethod
    def fmt(sec):
        try: sec=max(0,int(round(float(sec or 0))))
        except: sec=0
        return f"{sec//60:02d}:{sec%60:02d}"

    def _run_helper(self, filename, title):
        """Launch one of the restored local maintenance tools."""
        path = BASE / filename
        if not path.exists():
            QMessageBox.warning(self, title, f"File not found:\n{path}")
            return
        try:
            if os.name == "nt":
                os.startfile(str(path))
            else:
                import subprocess
                subprocess.Popen([str(path)], cwd=str(BASE))
        except Exception as e:
            QMessageBox.critical(self, title, f"Could not start the tool:\n{e}")

    def open_config(self):
        old_audio=bool(self.config_doc.get("audio_meter_enabled",True))
        dialog=SettingsDialog(backend.load_public_config(),self)
        dialog.exec()
        if dialog.saved:
            old_active=self.active_station
            self.config_doc=backend.load_public_config()
            app=QApplication.instance()
            if app is not None:
                apply_theme(app,self.config_doc.get("theme","dark"))
            self.active_station=str(self.config_doc.get("active_station") or old_active)
            self._station_generation+=1
            self.timer.setInterval(max(750,int(self.config_doc.get("refresh_interval_ms") or 1500)))
            self._playlist_signature=None
            self._reset_artwork_cache()
            self.setWindowTitle(str(self.config_doc.get("application_title") or "RadioBOSS Studio Monitor")+" v1.0.10")
            self.rebuild_station_buttons()
            self.busy=False; self._weather_busy=False
            self.request_state(); self.request_weather()
            if old_audio!=bool(self.config_doc.get("audio_meter_enabled",True)):
                QMessageBox.information(self,"Audio Meter","Restart Studio Monitor to apply the audio-meter change.")

    def run_diagnose(self):
        cfg=backend.load_config(self.active_station)
        details=[
            "Studio Monitor v1.0.10",
            f"Configuration: {backend.CONFIG}",
            f"Station: {cfg.get('_station_name') or '—'}",
            f"RadioBOSS: {cfg.get('radioboss_host')}:{cfg.get('radioboss_port')}",
            f"API user: {cfg.get('radioboss_user') or '(global password)'}",
            f"Password loaded: {'YES' if cfg.get('radioboss_password') else 'NO'}",
            f"Theme: {str(cfg.get('theme') or 'dark').upper()}",
            f"Weather: {'ENABLED' if cfg.get('weather_enabled') else 'DISABLED'}",
            f"Config error: {cfg.get('_config_error') or 'none'}",
        ]
        QMessageBox.information(self,"Studio Monitor Diagnostics","\n".join(details))

    def run_api_test(self):
        result=backend.rb_state(backend.load_config(self.active_station))
        if result.get("connected"):
            current=result.get("current") or {}
            title=" - ".join(x for x in (current.get("artist"),current.get("title")) if x)
            QMessageBox.information(self,"RadioBOSS API Test","Connection successful."+("\nCurrent: "+title if title else ""))
        else:
            QMessageBox.warning(self,"RadioBOSS API Test",str(result.get("error") or "Connection failed."))

    def install_audio_meter(self):
        if getattr(sys,"frozen",False):
            QMessageBox.information(self,"Audio Meter","Audio meter support is included in the public EXE.\nEnable it in Settings and restart the monitor.")
        else:
            self._run_helper("Install Audio Meter.bat", "Audio Meter Installation")

    def closeEvent(self, event):
        # Save the current position, including the selected monitor.
        try:
            self._window_settings.setValue("window/pos", self.pos())
            self._window_settings.sync()
        except Exception:
            pass
        try:
            self.pool.shutdown(wait=False,cancel_futures=True)
        except Exception:
            pass
        super().closeEvent(event)

    @staticmethod
    def _set_art(label, data):
        if not data:
            label.setPixmap(QPixmap())
            label.setText("NO ART")
            return
        pix=QPixmap()
        if not pix.loadFromData(data):
            label.setPixmap(QPixmap())
            label.setText("NO ART")
            return
        label.setText("")
        label.setPixmap(
            pix.scaled(label.size(), Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        )

    def _set_art_cached(self, label, data, signature_attr):
        signature=(len(data),hash(data)) if data else None
        if getattr(self,signature_attr,object())==signature:
            return
        setattr(self,signature_attr,signature)
        self._set_art(label,data)

    def apply_state(self,d):
        if int(d.get("_generation",-1))!=self._station_generation:return
        if str(d.get("_station_id") or "")!=self.active_station:return
        self.last_update.setText("LAST UPDATE "+time.strftime("%H:%M:%S"))
        online=bool(d.get("connected"))
        play=online and (d.get("playback") or {}).get("state")=="play"
        self._radioboss_playing=bool(play)
        if not play:
            self._silence_started=None
        self.onair_lbl.setText("ON AIR" if online else "OFFLINE")
        self.onair_lbl.setStyleSheet(
            f"color:{GREEN if online else RED}; "
            f"background:{ACTIVE_BG if online else ALERT_BG}; "
            f"border:1px solid {GREEN if online else RED}; "
            "border-radius:9px; font-size:34px; font-weight:800; padding:5px 14px;"
        )
        self.conn.setText("● CONNECTED" if online else "● NOT CONNECTED")
        self.conn.setStyleSheet(f"color:{GREEN if online else RED}")
        self.api_info.setText("API "+str(d.get("api") or "—"))
        self.api_error.setText(str(d.get("error") or ""))
        self.api_error.setVisible(bool(d.get("error")))
        self.system.setText(f"SYSTEM OK · RADIOBOSS {'OK' if online else 'OFFLINE'} · BRIDGE NATIVE")
        self.sys_state.setText("SYSTEM\nOK")
        self.sys_state.setStyleSheet(f"color:{GREEN}")
        self.rb_state.setText("RADIOBOSS\n"+("OK" if online else "OFFLINE"))
        self.rb_state.setStyleSheet(f"color:{GREEN if online else RED}")
        self.bridge_state.setText("BRIDGE\nNATIVE")
        self.bridge_state.setStyleSheet(f"color:{GREEN}")

        c=d.get("current") or {}; n=d.get("next") or {}; p=d.get("playback") or {}
        artist_key=str(c.get("artist") or "").strip()
        title_key=str(c.get("title") or "").strip()
        track_key=f"{artist_key}\x1f{title_key}" if title_key else ""
        self.turntable.set_playback(play,p.get("pos"),p.get("len"),track_key)
        self.cur_artist.setText(c.get("artist") or "—")
        self.cur_title.setText(c.get("title") or "—")
        self.cur_album.setText(" · ".join(x for x in [c.get("album"),c.get("year")] if x) or "—")
        self.remaining.setText(self.fmt(p.get("track_remaining")))
        self.bpm.setText("BPM "+(c.get("bpm") or "—"))
        self.listeners.setText("LISTENERS "+str(c.get("listeners") or "—"))
        self._set_art_cached(self.current_cover,d.get("_art_current_bytes"),"_current_art_signature")
        state_text=str(p.get("state") or "—").upper()
        self.play_state.setText("STATE "+state_text)
        self.play_state.setStyleSheet(f"color:{GREEN if state_text == 'PLAY' else AMBER}")
        length=float(p.get("len") or 0); pos=float(p.get("pos") or 0)
        self.progress.setValue(int(max(0,min(100,(pos/length*100) if length else 0))))
        next_artist=str(n.get("artist") or "—")
        next_title=str(n.get("title") or "—")
        next_album=" · ".join(str(x) for x in [n.get("album"),n.get("year")] if x) or "—"
        self.next_artist.setText(next_artist)
        self.next_title.setText(next_title)
        self.next_album.setText(next_album)
        self.next_artist.setToolTip(next_artist)
        self.next_title.setToolTip(next_title)
        self.next_album.setToolTip(next_album)
        self.next_in.setText("START IN "+self.fmt(p.get("track_remaining")))
        self._set_art_cached(self.next_cover,d.get("_art_next_bytes"),"_next_art_signature")

        sc=d.get("scheduler") or {}
        self.event.setText("NEXT EVENT · "+(sc.get("name") or "—"))
        self.event_time.setText("AT "+str(sc.get("time") or "—"))
        self.event_in.setText("IN "+(self.fmt(sc.get("seconds")) if sc.get("seconds") is not None else "—"))
        source=str(sc.get("source") or "—")
        self.event.setToolTip("SOURCE: "+source)

        upcoming=sc.get("upcoming") or []
        for i,lbl in enumerate(self.upcoming_events):
            if i < len(upcoming):
                ev=upcoming[i]
                secs=ev.get("seconds")
                lbl.setText(
                    f"{i+1}. {ev.get('time') or '—'}  {ev.get('name') or 'Scheduler Event'}"
                    + (f"   IN {self.fmt(secs)}" if secs is not None else "")
                )

                # Scheduler warning colours:
                # > 5 min = normal/muted, <= 5 min = amber, <= 1 min = red.
                try:
                    remaining=float(secs)
                except (TypeError,ValueError):
                    remaining=None

                if remaining is not None and remaining <= 60:
                    lbl.setStyleSheet("color:#ff3b30;font-weight:700;")
                elif remaining is not None and remaining <= 300:
                    lbl.setStyleSheet("color:#ffb000;font-weight:700;")
                else:
                    lbl.setStyleSheet("")
                    lbl.setObjectName("muted")
                    lbl.style().unpolish(lbl)
                    lbl.style().polish(lbl)
            else:
                lbl.setText("—")
                lbl.setStyleSheet("")
                lbl.setObjectName("muted")
                lbl.style().unpolish(lbl)
                lbl.style().polish(lbl)

        for i,lbl in enumerate(self.hour_scheduler_events):
            prefix="NEXT" if i==0 else "THEN"
            if i < len(upcoming):
                ev=upcoming[i]
                secs=ev.get("seconds")
                timing=f" · IN {self.fmt(secs)}" if secs is not None else ""
                name=str(ev.get("name") or "Scheduler Event")
                text=f"{prefix} · {ev.get('time') or '—'}{timing}\n{name}"
                lbl.setText(text)
                lbl.setToolTip(text.replace("\n"," · "))
            else:
                lbl.setText(prefix+" · —")
                lbl.setToolTip("")

        bv=d.get("broadcastvoice") or {}
        running=bool(bv.get("running"))
        connected=bool(bv.get("connected"))
        self.bv_state.setText("RUNNING" if running else ("STOPPED" if connected else "NOT CONNECTED"))
        self.bv_state.setStyleSheet(f"color:{GREEN if running else (AMBER if connected else RED)}")
        self.announcer.setText("ANNOUNCER: "+str(bv.get("announcer") or "—"))
        self.next_link.setText("NEXT LINK IN: "+str(bv.get("next_link") or "—"))
        self.anchor.setText("FULL HOUR BLOCK IN "+str(bv.get("anchor_in") or "—"))
        self.hour_block.setText("ANCHOR: "+str(bv.get("full_hour_block") or "—"))
        self.stop_mode.setText("STOP: "+str(bv.get("stop_mode") or "—"))
        self.prepared.setText("PREPARED: "+str(bv.get("prepared") or "—"))
        self.max_cut.setText("MAX CUT: "+str(bv.get("max_cut") or "—"))
        self.filler.setText("FILLER: "+str(bv.get("filler") or "—"))

        pl=d.get("playlist") or {}
        pl_source=str(pl.get("source") or "—")
        self.playlist_meta.setText(
            f"{pl.get('hour_label') or '—'} · TIME LEFT {self.fmt(pl.get('time_left_seconds'))} · SOURCE {pl_source}"
        )
        self.playlist_meta.setToolTip(str(pl.get("diagnostic") or pl.get("error") or ""))

        now=time.localtime()
        hour_left=(59-now.tm_min)*60 + (60-now.tm_sec)
        self.playlist_footer.setText(
            f"TOTAL {self.fmt(pl.get('total_seconds'))} · "
            f"TRACKS {pl.get('count') if pl.get('count') is not None else len(pl.get('tracks') or [])} · "
            f"HOUR LEFT {self.fmt(hour_left)}"
        )
        rows=(pl.get("tracks") or [])[:max(5,int(self.config_doc.get("playlist_rows") or 16))]
        row_values=[]
        for rix,row in enumerate(rows):
            row_values.append((
                str(rix+1).zfill(2),row.get("start_clock") or "—",
                row.get("artist") or "—",row.get("title") or "—",
                row.get("duration") or "—",row.get("bpm") or "—",
                row.get("status") or "",
            ))
        signature=tuple(tuple(str(value) for value in values) for values in row_values)
        if signature!=self._playlist_signature:
            self._playlist_signature=signature
            self.table.setUpdatesEnabled(False)
            try:
                self.table.setRowCount(len(rows))
                playing_row=-1
                for rix,(row,vals) in enumerate(zip(rows,row_values)):
                    for cix,val in enumerate(vals):
                        it=QTableWidgetItem(str(val))
                        if row.get("status")=="PLAYING":
                            it.setForeground(QColor(GREEN)); playing_row=rix
                        elif row.get("status")=="UP NEXT":
                            it.setForeground(QColor(AMBER))
                        elif row.get("status")=="PLAYED":
                            it.setForeground(QColor(TABLE_MUTED))
                        self.table.setItem(rix,cix,it)
                if playing_row>=0:
                    self.table.scrollToItem(self.table.item(playing_row,0),QTableWidget.PositionAtCenter)
            finally:
                self.table.setUpdatesEnabled(True)
                self.table.viewport().update()

    def apply_weather(self,w):
        if int(w.get("_generation",-1))!=self._station_generation:return
        self.weather_visual.set_weather(w)
        if w.get("ok"):
            self.weather.setText(str(w.get("location") or "Weather"))

            detail=[]
            if w.get("humidity") is not None:
                detail.append(f"Humidity {round(float(w['humidity']))}%")
            if w.get("wind_speed") is not None:
                detail.append(f"Wind {round(float(w['wind_speed']))} km/h")
            if w.get("sea_temperature") is not None:
                detail.append(f"Sea {round(float(w['sea_temperature']))}°C")
            if w.get("weather_text"):
                detail.insert(0, str(w.get("weather_text")))
            elif w.get("description"):
                detail.insert(0, str(w.get("description")))
            self.weather_detail.setText(" · ".join(detail))
        elif w.get("disabled"):
            self.weather.setText("Weather disabled")
            self.weather_detail.setText("")
        else:
            self.weather.setText(str(w.get("location") or "Weather unavailable"))
            self.weather_detail.setText(str(w.get("error") or ""))

    def _set_silence_indicator(self,mode,elapsed=0.0):
        if mode=="alarm":
            blink_on=int(time.monotonic()*2)%2==0
            seconds=max(int(self.SILENCE_ALARM_SECONDS),int(elapsed))
            text=f"SILENCE ALARM · {seconds} SEC"
            background="#c00022" if blink_on else "#51000d"
            style=(
                "color:#ffffff;"
                f"background:{background};"
                "border:2px solid #ff4055;border-radius:6px;"
                "padding:5px 7px;font-weight:900;font-size:13px;"
            )
            signature=(mode,seconds,blink_on)
        elif mode=="ok":
            text="SILENCE MONITOR · OK"
            style=(
                f"color:{GREEN};background:{ACTIVE_BG};border:1px solid {GREEN};"
                "border-radius:6px;padding:5px 7px;font-weight:700;"
            )
            signature=(mode,)
        elif mode=="off":
            text="SILENCE MONITOR · OFF"
            style=(
                f"color:{MUTED};background:transparent;border:1px solid {MUTED};"
                "border-radius:6px;padding:5px 7px;font-weight:700;"
            )
            signature=(mode,)
        else:
            text="SILENCE MONITOR · STANDBY"
            style=(
                f"color:{AMBER};background:transparent;border:1px solid {AMBER};"
                "border-radius:6px;padding:5px 7px;font-weight:700;"
            )
            signature=("standby",)
        if signature==self._silence_indicator_signature:
            return
        self._silence_indicator_signature=signature
        self.silence_alarm.setText(text)
        self.silence_alarm.setStyleSheet(style)

    def apply_audio(self,a):
        left=a.get("left") or 0
        right=a.get("right") or 0
        self.vu_left.set_level(left)
        self.vu_right.set_level(right)

        available=bool(a.get("available"))
        self.audio_status.setText("AUDIO LIVE" if available else "AUDIO OFF")
        self.audio_status.setStyleSheet(f"color:{GREEN if available else RED}")

        try: peak=max(float(left),float(right))
        except (TypeError,ValueError): peak=0.0
        if not available:
            self._silence_started=None
            self._set_silence_indicator("off")
        elif not self._radioboss_playing:
            self._silence_started=None
            self._set_silence_indicator("standby")
        elif peak>self.SILENCE_LEVEL_THRESHOLD:
            self._silence_started=None
            self._set_silence_indicator("ok")
        else:
            now=time.monotonic()
            if self._silence_started is None:
                self._silence_started=now
            elapsed=max(0.0,now-self._silence_started)
            self._set_silence_indicator(
                "alarm" if elapsed>=self.SILENCE_ALARM_SECONDS else "ok",elapsed
            )

        detail=[]
        if a.get("source"):
            detail.append(str(a.get("source")))
        if a.get("diagnostic"):
            detail.append(str(a.get("diagnostic")))
        elif a.get("error"):
            detail.append(str(a.get("error")))
        self.audio_detail.setText(" · ".join(detail))

    def show_error(self,msg):
        self.system.setText("ERROR · "+msg)

def stylesheet(theme="dark"):
    c=_theme_palette(theme)
    transparent_labels="QLabel { background:transparent; }" if str(theme).lower()=="light" else ""
    return f"""
    QWidget {{ background:{c['bg']}; color:{c['text']}; font-family:'Segoe UI'; }}
    {transparent_labels}
    QFrame#panel {{ background:{c['panel']}; border:1px solid {c['border']}; border-radius:12px; }}
    QLabel#panelTitle {{ color:{c['cyan']}; font-weight:700; font-size:12px; letter-spacing:1px; }}
    QLabel#onAir {{ color:{c['onair_text']}; background:{c['onair_bg']}; border:1px solid {c['red']}; border-radius:9px; font-size:34px; font-weight:800; padding:5px 14px; }}
    QLabel#brand {{ color:{c['brand']}; font-family:Georgia; font-size:32px; font-weight:700; }}
    QLabel#brandSub {{ color:{c['brand_sub']}; font-size:10px; letter-spacing:2px; }}
    QLabel#clock {{ color:{c['cyan']}; font-family:Consolas; font-size:31px; }}
    QLabel#clockSmall {{ color:{c['cyan']}; font-family:Consolas; font-size:17px; font-weight:700; }}
    QLabel#artist {{ color:{c['title']}; font-size:18px; font-weight:600; }}
    QLabel#trackTitle {{ color:{c['title']}; font-size:25px; }}
    QLabel#trackTitleSmall {{ color:{c['title']}; font-size:20px; }}
    QLabel#bigCyan {{ color:{c['cyan']}; font-family:Consolas; font-size:31px; }}
    QLabel#bigGreen {{ color:{c['green']}; font-family:Consolas; font-size:27px; }}
    QLabel#cyan {{ color:{c['cyan']}; }}
    QLabel#green {{ color:{c['green']}; }}
    QLabel#sectionTitle {{ color:{c['cyan']}; font-weight:700; font-size:10px; border-top:1px solid {c['soft_border']}; padding-top:3px; }}
    QFrame#nextCard {{ background:{c['status_bg']}; border:1px solid {c['soft_border']}; border-radius:8px; }}
    QFrame#hourOverview {{ background:{c['status_bg']}; border:1px solid {c['soft_border']}; border-radius:8px; }}
    QLabel#nextHeader {{ color:{c['cyan']}; font-size:11px; font-weight:700; letter-spacing:1px; }}
    QLabel#nextArtist {{ color:{c['title']}; font-size:14px; font-weight:600; }}
    QLabel#nextStart {{ color:{c['amber']}; font-family:Consolas; font-size:19px; font-weight:700; padding-top:3px; }}
    QLabel#scheduleTile {{ color:{c['text']}; background:{c['input_bg']}; border:1px solid {c['soft_border']}; border-radius:5px; padding:4px 7px; font-size:10px; }}
    QLabel#muted {{ color:{c['muted']}; }}
    QLabel#errorSmall {{ color:{c['red']}; font-size:9px; }}
    QLabel#cover, QLabel#coverSmall {{ background:{c['cover_bg']}; color:{c['cover_text']}; border:1px solid {c['soft_border']}; border-radius:7px; font-size:9px; }}
    QLabel#statusBox {{ background:{c['status_bg']}; border:1px solid {c['soft_border']}; border-radius:7px; padding:6px; font-family:Consolas; font-weight:700; }}


    QPushButton {{ background:{c['button_bg']}; color:{c['button_text']}; border:1px solid {c['border']}; border-radius:6px; padding:7px 10px; font-weight:600; }}
    QPushButton:hover {{ background:{c['button_hover']}; border-color:{c['cyan']}; }}
    QPushButton:pressed {{ background:{c['button_pressed']}; }}
    QPushButton[stationActive="true"] {{ background:{c['station_active_bg']}; color:{c['green']}; border:2px solid {c['green']}; }}
    QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QListWidget {{ background:{c['input_bg']}; color:{c['text']}; border:1px solid {c['input_border']}; border-radius:5px; padding:5px; }}
    QComboBox QAbstractItemView {{ background:{c['input_bg']}; color:{c['text']}; selection-background-color:{c['button_hover']}; }}
    QTabWidget::pane, QGroupBox {{ border:1px solid {c['input_border']}; border-radius:6px; margin-top:7px; }}
    QTabBar::tab {{ background:{c['tab_bg']}; color:{c['tab_text']}; padding:7px 13px; }}
    QTabBar::tab:selected {{ color:{c['cyan']}; border-bottom:2px solid {c['cyan']}; }}
    QProgressBar {{ background:{c['progress_bg']}; border:1px solid {c['soft_border']}; border-radius:5px; height:12px; }}
    QProgressBar::chunk {{ background:{c['cyan']}; border-radius:4px; }}
    QTableWidget {{ background:{c['table_bg']}; color:{c['text']}; border:0; gridline-color:{c['table_grid']}; }}
    QHeaderView::section {{ background:{c['header_bg']}; color:{c['cyan']}; border:0; border-bottom:1px solid {c['border']}; padding:5px; font-size:10px; }}
    QTableWidget::item {{ padding:3px; border-bottom:1px solid {c['row_border']}; }}
    QScrollBar:vertical {{ background:{c['scroll_bg']}; width:9px; margin:0; }}
    QScrollBar::handle:vertical {{ background:{c['scroll_handle']}; min-height:30px; border-radius:4px; }}
    """

def main():
    app=QApplication(sys.argv)
    document=backend.load_public_config()
    apply_theme(app,document.get("theme","dark"))
    if not bool(document.get("configured",False)):
        setup=SettingsDialog(document,first_run=True)
        if not setup.exec():
            return
        document=backend.load_public_config()
        apply_theme(app,document.get("theme","dark"))
    w=StudioMonitor()
    if bool(backend.load_public_config().get("start_maximized",True)):
        w.showMaximized()
    else:
        w.show()
    sys.exit(app.exec())

if __name__=="__main__":
    main()
