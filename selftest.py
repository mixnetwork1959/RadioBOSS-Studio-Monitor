from __future__ import annotations

import base64
import copy
import json
import py_compile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile
import threading
import urllib.parse


BASE=Path(__file__).resolve().parent
sys.path.insert(0,str(BASE))

import studio_monitor_backend as backend


PLAYBACK=b'''<?xml version="1.0" encoding="utf-8"?>
<Info>
  <CurrentTrack><TRACK ARTIST="Test Artist" TITLE="Current Song" ALBUM="Album" YEAR="2026" FILENAME="C:\\Music\\current.mp3" DURATION="03:20" BPM="120" LISTENERS="4" /></CurrentTrack>
  <Playback pos="30000" len="200000" state="play" playlistpos="1" playingtimeleft="800000" timestamp="2026-08-29 12:00:00" volume="80" />
  <NextTrack><TRACK ARTIST="Next Artist" TITLE="Next Song" FILENAME="C:\\Music\\next.mp3" DURATION="03:00" /></NextTrack>
</Info>'''

TINY_PNG=base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9Wl2QH8AAAAASUVORK5CYII="
)

PLAYLIST=b'''<?xml version="1.0" encoding="utf-8"?>
<Playlist COUNT="3" TS="1">
  <TRACK STARTTIME="12:00:00" DURATION="03:20" FILENAME="C:\\Music\\current.mp3" PLAYLISTINDEX="1" INDEX="2" ARTIST="Test Artist" TITLE="Current Song" BPM="120" />
  <TRACK STARTTIME="12:03:20" DURATION="03:00" FILENAME="C:\\Music\\next.mp3" PLAYLISTINDEX="2" INDEX="3" ARTIST="Next Artist" TITLE="Next Song" />
  <TRACK STARTTIME="12:06:20" DURATION="04:00" FILENAME="C:\\Music\\third.mp3" PLAYLISTINDEX="3" INDEX="4" ARTIST="Third Artist" TITLE="Third Song" />
</Playlist>'''


class MockRadioBOSS(BaseHTTPRequestHandler):
    def log_message(self,*args):
        return

    def do_GET(self):
        query=urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        if query.get("pass",[""])[0]!="test-secret":
            self.send_response(403); self.end_headers(); return
        action=query.get("action",[""])[0]
        if action=="playbackinfo":
            payload=PLAYBACK
        elif action in ("getplaylist2","getplaylist"):
            payload=PLAYLIST
        elif action in ("trackartwork","nexttrackartwork"):
            # Simulate an API artwork miss/non-image response so the v1.0.16
            # readtag fallback is exercised.
            payload=b"NO ART"
        elif action=="readtag":
            payload=(
                b'<TagInfo><File Artwork_Base64="'
                + base64.b64encode(TINY_PNG)
                + b'" /></TagInfo>'
            )
        else:
            payload=b""
        self.send_response(200)
        self.send_header("Content-Type","text/xml")
        self.send_header("Content-Length",str(len(payload)))
        self.end_headers(); self.wfile.write(payload)


def check(condition,message):
    if not condition:
        raise AssertionError(message)


def main():
    for name in ("StudioMonitorNative.py","meter_widgets.py","studio_monitor_backend.py","settings_dialog.py","secret_store.py","test_radioboss_api.py"):
        py_compile.compile(str(BASE/name),doraise=True)

    check((BASE/"studio_monitor_icon.png").is_file(),"application PNG icon missing")
    check((BASE/"studio_monitor_icon.ico").is_file(),"application ICO icon missing")
    build_text=(BASE/"BUILD-EXE.bat").read_text(encoding="utf-8",errors="replace")
    check('--icon "%~dp0studio_monitor_icon.ico"' in build_text,"PyInstaller EXE icon flag missing")
    check('--add-data "%~dp0studio_monitor_icon.png;."' in build_text,"bundled window icon resource missing")

    server=ThreadingHTTPServer(("127.0.0.1",0),MockRadioBOSS)
    thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    original_config=backend.CONFIG
    try:
        with tempfile.TemporaryDirectory() as folder:
            backend.CONFIG=Path(folder)/"studio_monitor_config.json"
            document=backend.load_public_config()
            check(not document.get("configured"),"new configuration must start unconfigured")
            check(document.get("theme")=="dark","new configuration must use the dark theme")
            station=document["station"]
            station.update({
                "name":"Test Station",
                "radioboss_host":"127.0.0.1",
                "radioboss_port":server.server_port,
                "radioboss_password":"test-secret",
                "scheduler_admin_sdl":r"C:\RadioBOSS-Main\Admin.sdl",
                "broadcastvoice_dir":r"D:\BroadcastVoice-Main",
            })
            document["configured"]=True
            document["theme"]="light"
            backend.save_public_config(document)

            saved=backend.CONFIG.read_text(encoding="utf-8")
            check("test-secret" not in saved,"plain password leaked into JSON")
            check("radioboss_password_protected" in saved,"protected password missing")

            loaded=backend.load_public_config()
            check(loaded.get("theme")=="light","theme selection did not survive configuration save")
            check(loaded["station"]["radioboss_password"]=="test-secret","password roundtrip failed")
            check("stations" not in loaded and "active_station" not in loaded,"legacy multi-station fields survived migration")
            check(loaded["station"]["broadcastvoice_dir"]==r"D:\BroadcastVoice-Main","local BroadcastVoice path was not retained")
            cfg=backend.load_config()
            state=backend.rb_state(cfg)
            check(state.get("connected"),state.get("error") or "mock RadioBOSS did not connect")
            check(state["current"]["title"]=="Current Song","current title parse failed")
            check(round(state["playback"]["track_remaining"])==170,"remaining-time calculation failed")

            playlist=backend.playlist_state(cfg,state.get("playback"),state.get("current"))
            check(playlist.get("ok"),playlist.get("error") or "playlist parse failed")
            check(any(x.get("status")=="PLAYING" for x in playlist.get("tracks") or []),"playing row not detected")

            fallback_next=backend.merge_next_track({},playlist)
            check(fallback_next.get("title")=="Next Song","playlist fallback did not restore missing NextTrack")
            art=backend.rb_artwork(cfg,"current",state.get("current") or {})
            check(backend._looks_like_image(art),"readtag artwork fallback did not return image bytes")
            check(backend.weather_state(cfg).get("disabled"),"weather-disabled mode failed")

            loaded["station"]["radioboss_password"]="changed-secret"
            backend.save_public_config(loaded)
            check(backend.load_public_config()["station"]["radioboss_password"]=="changed-secret","edited password was replaced by the previous protected value")

            # A legacy runtime/state.json path must not bypass the complete
            # directory-based BroadcastVoice status calculation.
            bv_root=Path(folder)/"BroadcastVoice"
            (bv_root/"runtime").mkdir(parents=True)
            (bv_root/"config.json").write_text(
                json.dumps({"announcer":"RIGHT-CONFIG"}),
                encoding="utf-8",
            )
            legacy_state=bv_root/"runtime"/"state.json"
            legacy_state.write_text(json.dumps({"announcer":"WRONG-RAW-STATE"}),encoding="utf-8")
            bv=backend.bv_state({
                "broadcastvoice_dir":str(bv_root),
                "broadcastvoice_status_file":str(legacy_state),
            })
            check(bv.get("announcer")=="RIGHT-CONFIG","legacy BroadcastVoice status file bypassed directory discovery")

            # Hour Watch is read-only and derives its information only from
            # the RadioBOSS Scheduler file around the next full hour.
            now_dt=backend.datetime.now()
            next_hour=now_dt.replace(minute=0,second=0,microsecond=0)+backend.timedelta(hours=1)
            marker_dt=next_hour-backend.timedelta(seconds=10)
            hours=["0"]*24; hours[marker_dt.hour]="1"
            sdl_path=Path(folder)/"Admin.sdl"
            sdl_path.write_text(
                "[Event0]\n"
                "EnabledEvent=1\n"
                "TaskName=Full Hour Test Marker\n"
                "TimeType=1\n"
                f"Hours={''.join(hours)}\n"
                f"Minutes={marker_dt.minute}\n"
                f"Seconds={marker_dt.second}\n"
                "Days=1111111\n",
                encoding="utf-8",
            )
            hw=backend.hour_watch_state({"scheduler_admin_sdl":str(sdl_path)})
            check(hw.get("read_only") is True,"Hour Watch lost read-only flag")
            check(any(x.get("name")=="Full Hour Test Marker" for x in hw.get("events") or []),"Hour Watch did not find the full-hour Scheduler event")

            # v1.0.12 must import only the first profile from an older
            # two-station config and immediately expose the new singular form.
            backend.CONFIG.write_text(json.dumps({
                "configured":True,
                "active_station":"station-2",
                "stations":[
                    {"id":"station-1","short_name":"MAIN","name":"Legacy Main","radioboss_host":"127.0.0.1","radioboss_port":9000},
                    {"id":"station-2","short_name":"ROCK","name":"Legacy Rock","radioboss_host":"127.0.0.1","radioboss_port":9010},
                ],
            }),encoding="utf-8")
            migrated=backend.load_public_config()
            check(migrated["station"]["name"]=="Legacy Main","first legacy station was not migrated")
            check("stations" not in migrated and "active_station" not in migrated,"old station selector survived migration")
            check("id" not in migrated["station"] and "short_name" not in migrated["station"],"old station selector metadata survived migration")
            migrated_json=backend.CONFIG.read_text(encoding="utf-8")
            check('"stations"' not in migrated_json and '"active_station"' not in migrated_json,"old station selector remained in the saved JSON")
    finally:
        backend.CONFIG=original_config
        server.shutdown(); server.server_close()

    print("SELFTEST OK")
    print("- source syntax")
    print("- packaged application icon resources")
    print("- first-run configuration")
    print("- protected credential storage")
    print("- light/dark theme configuration")
    print("- single local station configuration and legacy migration")
    print("- RadioBOSS playback XML")
    print("- RadioBOSS playlist XML and NextTrack fallback")
    print("- artwork validation and readtag fallback")
    print("- weather-disabled mode")
    print("- directory-based BroadcastVoice status")
    print("- passive Hour Watch scheduler detection")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
