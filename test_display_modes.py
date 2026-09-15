"""Offline Qt/configuration checks for the two meter renderers."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, QTimer, QPoint
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication
from shiboken6 import delete

import StudioMonitorNative as native
import studio_monitor_backend as backend
from meter_widgets import AudioLevelMeter
from settings_dialog import SettingsDialog


class OfflineMonitor(native.StudioMonitor):
    def request_state(self):
        pass

    def request_weather(self):
        pass


class DisplayModeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name)
        self.enterContext(patch.object(backend, "CONFIG", self.root / "studio_monitor_config.json"))
        self.document = backend._new_document()
        self.document["configured"] = True
        self.document["station"].update({
            "name": "Test Station",
            "radioboss_password": "test-password",
            "scheduler_admin_sdl": r"C:\TestRadioBOSS\Admin.sdl",
            "broadcastvoice_dir": r"C:\TestBroadcastVoice",
        })
        backend.save_public_config(self.document)
        native.apply_theme(self.app, "dark")

    def monitor(self):
        settings = QSettings(str(self.root / "window.ini"), QSettings.IniFormat)
        # All real UI widgets run, but tests never start a background audio
        # worker, watchdog thread, RadioBOSS request or weather request.
        with patch.object(native.threading.Thread, "start"), \
             patch.object(native, "QSettings", return_value=settings):
            monitor = OfflineMonitor()
        for timer in monitor.findChildren(QTimer):
            timer.stop()
        self.addCleanup(delete, monitor)
        self.addCleanup(monitor.close)
        return monitor

    def meter(self, mode="led"):
        meter = AudioLevelMeter("L", display_mode=mode)
        meter.timer.stop()
        self.addCleanup(delete, meter)
        return meter

    def test_default_and_legacy_values_resolve_to_led(self):
        self.assertEqual(backend._new_document()["meter_display_mode"], "led")
        for value in (None, "", "Classic", "classic", "unknown", 42):
            with self.subTest(value=value):
                doc = copy.deepcopy(self.document)
                doc["meter_display_mode"] = value
                backend.CONFIG.write_text(json.dumps(doc), encoding="utf-8")
                self.assertEqual(backend.load_public_config()["meter_display_mode"], "led")
        doc.pop("meter_display_mode")
        backend.CONFIG.write_text(json.dumps(doc), encoding="utf-8")
        monitor = self.monitor()
        self.assertEqual(monitor.vu_left.display_mode, "led")
        self.assertEqual(monitor.vu_right.display_mode, "led")

    def test_settings_offer_only_led_and_vu_and_save_without_losing_other_settings(self):
        before = backend.load_public_config()
        dialog = SettingsDialog(before)
        self.addCleanup(delete, dialog)
        combo = dialog.meter_display_mode
        self.assertEqual([(combo.itemText(i), combo.itemData(i)) for i in range(combo.count())],
                         [("LED", "led"), ("VU", "vu")])
        self.assertEqual(combo.currentData(), "led")
        combo.setCurrentIndex(combo.findData("vu"))
        dialog._accept()
        self.assertTrue(dialog.saved)
        loaded = backend.load_public_config()
        self.assertEqual(loaded["meter_display_mode"], "vu")
        self.assertEqual(loaded["station"]["radioboss_password"], "test-password")
        self.assertNotIn("test-password", backend.CONFIG.read_text(encoding="utf-8"))
        # DPAPI may re-encrypt the same password to different bytes on Windows.
        for doc in (before, loaded):
            doc.pop("meter_display_mode", None)
            doc["station"].pop("radioboss_password_protected", None)
        self.assertEqual(loaded, before)
        reopened = SettingsDialog(backend.load_public_config())
        self.addCleanup(delete, reopened)
        self.assertEqual(reopened.meter_display_mode.currentData(), "vu")

    def test_unsaved_setting_does_not_change_saved_mode(self):
        before = backend.CONFIG.read_bytes()
        dialog = SettingsDialog(backend.load_public_config())
        self.addCleanup(delete, dialog)
        dialog.meter_display_mode.setCurrentIndex(1)
        dialog.reject()
        self.assertFalse(dialog.saved)
        self.assertEqual(backend.CONFIG.read_bytes(), before)

    def test_settings_switch_existing_widgets_and_restore_mode_on_restart(self):
        monitor = self.monitor()
        monitor.apply_audio({"available": True, "left": 0.25, "right": 0.65})
        widgets = (monitor.vu_left, monitor.vu_right)
        timer_ids = [id(timer) for timer in monitor.findChildren(QTimer)]

        def choose_vu():
            dialog = next(w for w in self.app.topLevelWidgets() if isinstance(w, SettingsDialog))
            dialog.meter_display_mode.setCurrentIndex(dialog.meter_display_mode.findData("vu"))
            dialog._accept()
            dialog.reject()

        QTimer.singleShot(0, choose_vu)
        with patch.object(native.threading.Thread, "start") as start:
            monitor.open_config()
            start.assert_not_called()
        self.assertEqual((monitor.vu_left, monitor.vu_right), widgets)
        self.assertEqual([id(timer) for timer in monitor.findChildren(QTimer)], timer_ids)
        self.assertEqual((monitor.vu_left.target, monitor.vu_right.target), (0.25, 0.65))
        self.assertEqual((monitor.vu_left.display_mode, monitor.vu_right.display_mode), ("vu", "vu"))
        restarted = self.monitor()
        self.assertEqual((restarted.vu_left.display_mode, restarted.vu_right.display_mode), ("vu", "vu"))
        document = backend.load_public_config()
        document["meter_display_mode"] = "led"
        backend.save_public_config(document)
        led_restart = self.monitor()
        self.assertEqual((led_restart.vu_left.display_mode, led_restart.vu_right.display_mode), ("led", "led"))

    def test_same_feed_reaches_both_channels_in_both_modes(self):
        monitor = self.monitor()
        for mode in ("led", "vu", "led"):
            monitor.vu_left.set_display_mode(mode)
            monitor.vu_right.set_display_mode(mode)
            sample = {"available": True, "left": 0.12, "right": 0.81, "source": "Test audio"}
            untouched = dict(sample)
            monitor.signals.audio.emit(sample)
            self.assertEqual((monitor.vu_left.target, monitor.vu_right.target), (0.12, 0.81))
            self.assertEqual(sample, untouched)
            self.assertEqual(monitor.audio_status.text(), "AUDIO LIVE")
            self.assertEqual(monitor.audio_detail.text(), "Test audio")

    def test_silence_alarm_survives_switch_and_audio_recovery(self):
        monitor = self.monitor()
        monitor._radioboss_playing = True
        silent = {"available": True, "left": 0.0, "right": 0.0}
        with patch.object(native.time, "monotonic", return_value=100.0):
            monitor.apply_audio(silent)
        started = monitor._silence_started
        monitor.vu_left.set_display_mode("vu")
        monitor.vu_right.set_display_mode("vu")
        self.assertEqual(monitor._silence_started, started)
        with patch.object(native.time, "monotonic", return_value=116.0):
            monitor.apply_audio(silent)
        self.assertIn("ALARM", monitor.silence_alarm.text())
        monitor.vu_left.set_display_mode("led")
        monitor.vu_right.set_display_mode("led")
        self.assertIn("ALARM", monitor.silence_alarm.text())
        monitor.apply_audio({"available": True, "left": 0.2, "right": 0.3})
        self.assertIsNone(monitor._silence_started)
        self.assertNotIn("ALARM", monitor.silence_alarm.text())
        monitor.apply_audio({"available": False, "left": 0.0, "right": 0.0})
        self.assertEqual(monitor.audio_status.text(), "AUDIO OFF")
        self.assertIsNone(monitor._silence_started)

    def test_vu_motion_and_led_range_are_visualization_only(self):
        vu = self.meter("vu")
        vu.set_level(1.0)
        vu._animate()
        self.assertAlmostEqual(vu.value, 0.34)
        vu.set_level(0.0)
        vu._animate()
        self.assertAlmostEqual(vu.value, 0.34 * (1 - 0.095))
        led = self.meter()
        for value, count in ((0, 0), (0.001, 0), (0.01, 10), (0.1, 20), (1.0, 30)):
            led.set_level(value)
            led._animate()
            self.assertEqual(led.lit_segment_count(), count)
        for value in (None, "invalid", float("nan"), float("inf"), -1):
            led.set_level(value)
            led._animate()
            self.assertEqual(led.target, 0.0)
            self.assertEqual(led.lit_segment_count(), 0)
        led.set_level(2.0)
        led._animate()
        self.assertEqual(led.lit_segment_count(), 30)

    def test_rendering_changes_only_meter_area_and_keeps_branding(self):
        monitor = self.monitor()
        monitor.resize(1250, 780)
        monitor.apply_state({
            "connected": True,
            "_generation": monitor._config_generation, "_serial": monitor._request_serial,
            "current": {"artist": "Test Artist", "title": "Current Song"},
            "next": {"artist": "Next Artist", "title": "Next Song"},
            "playback": {"state": "play", "len": 200, "pos": 30, "track_remaining": 170},
        })
        monitor.apply_audio({"available": True, "left": 0.4, "right": 0.7})
        monitor.setWindowIcon(QIcon(str(native.resource_path("studio_monitor_icon.png"))))
        icon = monitor.windowIcon().cacheKey()
        monitor.show()
        self.app.processEvents()
        fixed_time = time.struct_time((2026, 9, 15, 12, 59, 30, 1, 258, -1))
        with patch.object(native.time, "localtime", return_value=fixed_time), \
             patch.object(native.time, "time", return_value=1800000000.0):
            monitor.tick_clock()
            for meter in (monitor.vu_left, monitor.vu_right):
                meter._animate()
            led = monitor.grab().toImage()
            for meter in (monitor.vu_left, monitor.vu_right):
                meter.set_display_mode("vu")
                meter._animate()
            vu = monitor.grab().toImage()
        self.assertEqual(monitor.windowIcon().cacheKey(), icon)
        self.assertEqual(monitor.cur_title.text(), "Current Song")
        self.assertEqual(monitor.onair_lbl.text(), "ON AIR")
        self.assertEqual(monitor.remaining.text(), "02:50")
        self.assertIn("IN 00:30", monitor.hour_watch_clock.text())
        self.assertNotEqual(led, vu)
        # Mask the two meter rectangles; every other dashboard pixel must
        # remain identical when switching renderers with a fixed clock/feed.
        from PySide6.QtGui import QPainter, QColor
        for image in (led, vu):
            painter = QPainter(image)
            for meter in (monitor.vu_left, monitor.vu_right):
                area = meter.rect().translated(meter.mapTo(monitor, QPoint(0, 0)))
                painter.fillRect(area, QColor("black"))
            painter.end()
        self.assertEqual(led, vu)


if __name__ == "__main__":
    unittest.main(verbosity=2)
