from __future__ import annotations

import copy
import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

import studio_monitor_backend as backend
from secret_store import storage_description


def _coordinate_text(value) -> str:
    try:
        text=f"{float(value):.6f}".rstrip("0").rstrip(".")
        return text or "0"
    except (TypeError,ValueError):
        return "0"


def _coordinate_value(text: str, label: str, minimum: float, maximum: float, required: bool) -> float:
    raw=str(text or "").strip().replace(",",".")
    if not raw:
        if required:
            raise ValueError(f"{label} is required when weather is enabled.")
        return 0.0
    try:
        value=float(raw)
    except ValueError as exc:
        raise ValueError(f"{label} must be a number, for example 43.36957.") from exc
    if not minimum <= value <= maximum:
        raise ValueError(f"{label} must be between {minimum:g} and {maximum:g}.")
    return value


class SettingsDialog(QDialog):
    """First-run wizard and reusable settings window in one compact dialog."""

    def __init__(self, document, parent=None, first_run=False):
        super().__init__(parent)
        self.document=copy.deepcopy(document)
        self.first_run=bool(first_run)
        self.saved=False
        self.current_station=0
        self.setWindowTitle("Studio Monitor Setup" if first_run else "Studio Monitor Settings")
        self.resize(820,610)
        self.setMinimumSize(720,540)

        outer=QVBoxLayout(self)
        if first_run:
            intro=QLabel(
                "Welcome to RadioBOSS Studio Monitor. Configure the local RadioBOSS station "
                "on this computer below."
            )
            intro.setWordWrap(True)
            intro.setObjectName("settingsIntro")
            outer.addWidget(intro)

        self.tabs=QTabWidget()
        outer.addWidget(self.tabs,1)
        self._build_general_tab()
        self._build_station_tab()
        self._build_weather_tab()
        self._build_integrations_tab()

        note=QLabel("RadioBOSS password storage: "+storage_description())
        note.setWordWrap(True)
        note.setObjectName("muted")
        outer.addWidget(note)

        self.save_status=QLabel("")
        self.save_status.setObjectName("muted")
        outer.addWidget(self.save_status)

        close_button=QDialogButtonBox.Cancel if self.first_run else QDialogButtonBox.Close
        self.buttons=QDialogButtonBox(QDialogButtonBox.Save|close_button)
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)
        outer.addWidget(self.buttons)

        self._load_document()

    def _build_general_tab(self):
        tab=QWidget(); form=QFormLayout(tab)
        self.app_title=QLineEdit()
        self.theme=QComboBox()
        self.theme.addItem("Dark","dark")
        self.theme.addItem("Light","light")
        self.refresh_ms=QSpinBox(); self.refresh_ms.setRange(750,10000); self.refresh_ms.setSingleStep(250); self.refresh_ms.setSuffix(" ms")
        self.playlist_rows=QSpinBox(); self.playlist_rows.setRange(5,50)
        self.start_maximized=QCheckBox("Start maximized")
        self.audio_meter=QCheckBox("Enable Windows output audio meters")
        form.addRow("Application title",self.app_title)
        form.addRow("Theme",self.theme)
        form.addRow("RadioBOSS refresh",self.refresh_ms)
        form.addRow("Maximum playlist rows",self.playlist_rows)
        form.addRow("",self.start_maximized)
        form.addRow("",self.audio_meter)
        self.tabs.addTab(tab,"General")

    def _build_station_tab(self):
        tab=QWidget(); form=QFormLayout(tab)
        self.station_name=QLineEdit()
        self.station_short=QLineEdit(); self.station_short.setMaxLength(20)
        self.station_host=QLineEdit()
        self.station_port=QSpinBox(); self.station_port.setRange(1,65535)
        self.station_user=QLineEdit()
        self.station_password=QLineEdit(); self.station_password.setEchoMode(QLineEdit.Password)
        reveal=QCheckBox("Show password")
        reveal.toggled.connect(lambda on:self.station_password.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password))
        self.station_accent=QLineEdit(); self.station_accent.setMaxLength(7)
        color=QPushButton("Choose…"); color.clicked.connect(self._choose_color)
        color_row=QHBoxLayout(); color_row.addWidget(self.station_accent); color_row.addWidget(color)
        test=QPushButton("Test RadioBOSS connection"); test.clicked.connect(self._test_connection)
        info=QLabel("This Studio Monitor installation controls one local station. Install Studio Monitor on the other RadioBOSS computer for a second station.")
        info.setWordWrap(True); info.setObjectName("muted")
        form.addRow("Station name",self.station_name)
        form.addRow("Button label",self.station_short)
        form.addRow("RadioBOSS host",self.station_host)
        form.addRow("RadioBOSS API port",self.station_port)
        form.addRow("API user (optional)",self.station_user)
        form.addRow("API password",self.station_password)
        form.addRow("",reveal)
        form.addRow("Accent colour",color_row)
        form.addRow("",test)
        form.addRow("",info)
        self.tabs.addTab(tab,"Station")

    def _build_weather_tab(self):
        tab=QWidget(); form=QFormLayout(tab)
        self.weather_enabled=QCheckBox("Show current weather")
        self.weather_location=QLineEdit(); self.weather_location.setPlaceholderText("e.g. London")
        # Plain text fields make pasted coordinates work independently of the
        # Windows decimal locale. Both 43.36957 and 43,36957 are accepted.
        self.weather_lat=QLineEdit(); self.weather_lat.setPlaceholderText("e.g. 43.36957")
        self.weather_lon=QLineEdit(); self.weather_lon.setPlaceholderText("e.g. 28.08081")
        self.weather_sea=QCheckBox("Show sea-surface temperature (coastal stations)")
        info=QLabel(
            "Weather data is requested from Open-Meteo. Latitude and longitude are required "
            "when weather is enabled. Coordinates can be typed or pasted with a decimal point or comma."
        )
        info.setWordWrap(True); info.setObjectName("muted")
        form.addRow("",self.weather_enabled)
        form.addRow("Location label",self.weather_location)
        form.addRow("Latitude",self.weather_lat)
        form.addRow("Longitude",self.weather_lon)
        form.addRow("",self.weather_sea)
        form.addRow("",info)
        self.tabs.addTab(tab,"Weather")

    def _build_integrations_tab(self):
        tab=QWidget(); outer=QVBoxLayout(tab)

        scheduler_group=QGroupBox("RadioBOSS Scheduler")
        scheduler_form=QFormLayout(scheduler_group)
        self.scheduler_sdl=QLineEdit()
        scheduler_sdl_button=QPushButton("Browse…")
        scheduler_sdl_button.clicked.connect(
            lambda:self._browse_file(
                self.scheduler_sdl,
                "Select RadioBOSS Scheduler SDL file",
                "RadioBOSS Scheduler files (*.sdl);;All files (*.*)",
            )
        )
        scheduler_sdl_row=QHBoxLayout(); scheduler_sdl_row.addWidget(self.scheduler_sdl,1); scheduler_sdl_row.addWidget(scheduler_sdl_button)
        scheduler_form.addRow("Scheduler SDL file",scheduler_sdl_row)
        outer.addWidget(scheduler_group)

        broadcastvoice_group=QGroupBox("BroadcastVoice")
        broadcastvoice_form=QFormLayout(broadcastvoice_group)
        self.broadcastvoice_dir=QLineEdit()
        broadcastvoice_dir_button=QPushButton("Browse…")
        broadcastvoice_dir_button.clicked.connect(
            lambda:self._browse_directory(self.broadcastvoice_dir,"Select BroadcastVoice directory")
        )
        broadcastvoice_dir_row=QHBoxLayout(); broadcastvoice_dir_row.addWidget(self.broadcastvoice_dir,1); broadcastvoice_dir_row.addWidget(broadcastvoice_dir_button)
        broadcastvoice_form.addRow("BroadcastVoice directory",broadcastvoice_dir_row)
        outer.addWidget(broadcastvoice_group)

        info=QLabel(
            "These integration paths belong to this local station only. Select the RadioBOSS "
            "Scheduler SDL file and the local BroadcastVoice folder. Leave an integration empty when unused."
        )
        info.setWordWrap(True); info.setObjectName("muted")
        outer.addWidget(info)
        outer.addStretch(1)
        self.tabs.addTab(tab,"Integrations")

    def _browse_file(self,field,title,file_filter):
        selected,_=QFileDialog.getOpenFileName(self,title,field.text().strip(),file_filter)
        if selected:
            field.setText(selected)

    def _browse_directory(self,field,title):
        selected=QFileDialog.getExistingDirectory(self,title,field.text().strip())
        if selected:
            field.setText(selected)

    def _load_document(self):
        d=self.document
        self.app_title.setText(str(d.get("application_title") or "RadioBOSS Studio Monitor"))
        theme_index=self.theme.findData(str(d.get("theme") or "dark").lower())
        self.theme.setCurrentIndex(theme_index if theme_index>=0 else 0)
        self.refresh_ms.setValue(int(d.get("refresh_interval_ms") or 1500))
        self.playlist_rows.setValue(int(d.get("playlist_rows") or 16))
        self.start_maximized.setChecked(bool(d.get("start_maximized",True)))
        self.audio_meter.setChecked(bool(d.get("audio_meter_enabled",True)))
        self.weather_enabled.setChecked(bool(d.get("weather_enabled",False)))
        self.weather_location.setText(str(d.get("weather_location") or ""))
        self.weather_lat.setText(_coordinate_text(d.get("weather_latitude") or 0))
        self.weather_lon.setText(_coordinate_text(d.get("weather_longitude") or 0))
        self.weather_sea.setChecked(bool(d.get("weather_show_sea_temperature",False)))

        stations=d.get("stations") or [copy.deepcopy(backend.DEFAULT_STATION)]
        # Single-station edition: keep only the first/local station profile.
        self.document["stations"]=[copy.deepcopy(stations[0])]
        self.document["active_station"]=str(self.document["stations"][0].get("id") or "station-1")
        self._load_station_fields(self.document["stations"][0])

    def _load_station_fields(self,s):
        self.station_name.setText(str(s.get("name") or "My Radio Station"))
        self.station_short.setText(str(s.get("short_name") or "STATION"))
        self.station_host.setText(str(s.get("radioboss_host") or "127.0.0.1"))
        self.station_port.setValue(int(s.get("radioboss_port") or 9000))
        self.station_user.setText(str(s.get("radioboss_user") or ""))
        self.station_password.setText(str(s.get("radioboss_password") or ""))
        self.station_accent.setText(str(s.get("accent_color") or "#27ff72"))
        self.scheduler_sdl.setText(str(s.get("scheduler_admin_sdl") or ""))
        self.broadcastvoice_dir.setText(str(s.get("broadcastvoice_dir") or ""))

    def _store_station(self,index=0):
        stations=self.document.setdefault("stations",[])
        if not stations:
            stations.append(copy.deepcopy(backend.DEFAULT_STATION))
        s=stations[0]
        # v1.0.11 uses the BroadcastVoice directory as the single source of
        # truth. Remove the misleading legacy status-file setting on save.
        s.pop("broadcastvoice_status_file",None)
        s.update({
            "name":self.station_name.text().strip() or "My Radio Station",
            "short_name":self.station_short.text().strip() or "STATION",
            "radioboss_host":self.station_host.text().strip() or "127.0.0.1",
            "radioboss_port":self.station_port.value(),
            "radioboss_user":self.station_user.text().strip(),
            "radioboss_password":self.station_password.text(),
            "accent_color":self.station_accent.text().strip() or "#27ff72",
            "scheduler_events_file":"",
            "scheduler_admin_sdl":self.scheduler_sdl.text().strip(),
            "broadcastvoice_dir":self.broadcastvoice_dir.text().strip(),
        })
        self.document["stations"]=[s]
        self.document["active_station"]=str(s.get("id") or "station-1")

    def _choose_color(self):
        colour=QColorDialog.getColor(parent=self)
        if colour.isValid(): self.station_accent.setText(colour.name())

    def _test_connection(self):
        self._store_station(self.current_station)
        station=(self.document.get("stations") or [{}])[0]
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            cfg=backend.runtime_config_from_document(self.document,station.get("id"))
            result=backend.rb_state(cfg)
        finally:
            QApplication.restoreOverrideCursor()
        if result.get("connected"):
            current=result.get("current") or {}
            title=" - ".join(x for x in (current.get("artist"),current.get("title")) if x)
            QMessageBox.information(self,"RadioBOSS connection","Connection successful."+("\nCurrent: "+title if title else ""))
        else:
            QMessageBox.warning(self,"RadioBOSS connection",str(result.get("error") or "Connection failed."))

    def _accept(self):
        self._store_station(self.current_station)
        stations=self.document.get("stations") or []
        if not stations:
            QMessageBox.warning(self,"Settings","A station configuration is required."); return
        for station in stations:
            if not str(station.get("name") or "").strip() or not str(station.get("radioboss_host") or "").strip():
                QMessageBox.warning(self,"Settings","The station needs a name and RadioBOSS host."); return
            colour=str(station.get("accent_color") or "")
            if not re.fullmatch(r"#[0-9a-fA-F]{6}",colour):
                QMessageBox.warning(self,"Settings",f"Invalid accent colour for {station.get('name')}: {colour}"); return

        try:
            weather_required=self.weather_enabled.isChecked()
            weather_latitude=_coordinate_value(self.weather_lat.text(),"Latitude",-90,90,weather_required)
            weather_longitude=_coordinate_value(self.weather_lon.text(),"Longitude",-180,180,weather_required)
        except ValueError as exc:
            self.tabs.setCurrentIndex(2)
            QMessageBox.warning(self,"Weather settings",str(exc))
            return

        self.document.update({
            "configured":True,
            "application_title":self.app_title.text().strip() or "RadioBOSS Studio Monitor",
            "theme":str(self.theme.currentData() or "dark"),
            "refresh_interval_ms":self.refresh_ms.value(),
            "playlist_rows":self.playlist_rows.value(),
            "start_maximized":self.start_maximized.isChecked(),
            "audio_meter_enabled":self.audio_meter.isChecked(),
            "weather_enabled":self.weather_enabled.isChecked(),
            "weather_location":self.weather_location.text().strip(),
            "weather_latitude":weather_latitude,
            "weather_longitude":weather_longitude,
            "weather_show_sea_temperature":self.weather_sea.isChecked(),
        })
        if str(self.document.get("active_station") or "") not in {str(x.get("id")) for x in stations}:
            self.document["active_station"]=str(stations[0].get("id"))
        try:
            backend.save_public_config(self.document)
        except Exception as exc:
            QMessageBox.critical(self,"Settings",f"Could not save configuration:\n{exc}"); return
        self.saved=True
        if self.first_run:
            self.accept()
        else:
            self.save_status.setText("Settings saved. You can continue editing or close this window.")
