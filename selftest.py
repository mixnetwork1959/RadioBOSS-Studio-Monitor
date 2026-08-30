from __future__ import annotations

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
        payload=PLAYBACK if action=="playbackinfo" else PLAYLIST if action in ("getplaylist2","getplaylist") else b""
        self.send_response(200)
        self.send_header("Content-Type","text/xml")
        self.send_header("Content-Length",str(len(payload)))
        self.end_headers(); self.wfile.write(payload)


def check(condition,message):
    if not condition:
        raise AssertionError(message)


def main():
    for name in ("StudioMonitorNative.py","studio_monitor_backend.py","settings_dialog.py","secret_store.py","test_radioboss_api.py"):
        py_compile.compile(str(BASE/name),doraise=True)

    server=ThreadingHTTPServer(("127.0.0.1",0),MockRadioBOSS)
    thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
    original_config=backend.CONFIG
    try:
        with tempfile.TemporaryDirectory() as folder:
            backend.CONFIG=Path(folder)/"studio_monitor_config.json"
            document=backend.load_public_config()
            check(not document.get("configured"),"new configuration must start unconfigured")
            check(document.get("theme")=="dark","new configuration must use the dark theme")
            station=document["stations"][0]
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
            check(loaded["stations"][0]["radioboss_password"]=="test-secret","password roundtrip failed")
            check(len(loaded["stations"])==1,"single-station edition must retain exactly one station")
            check(loaded["stations"][0]["broadcastvoice_dir"]==r"D:\BroadcastVoice-Main","local BroadcastVoice path was not retained")
            cfg=backend.load_config(loaded["stations"][0]["id"])
            state=backend.rb_state(cfg)
            check(state.get("connected"),state.get("error") or "mock RadioBOSS did not connect")
            check(state["current"]["title"]=="Current Song","current title parse failed")
            check(round(state["playback"]["track_remaining"])==170,"remaining-time calculation failed")

            playlist=backend.playlist_state(cfg,state.get("playback"),state.get("current"))
            check(playlist.get("ok"),playlist.get("error") or "playlist parse failed")
            check(any(x.get("status")=="PLAYING" for x in playlist.get("tracks") or []),"playing row not detected")
            check(backend.weather_state(cfg).get("disabled"),"weather-disabled mode failed")

            # A legacy runtime/state.json path must not bypass the complete
            # directory-based BroadcastVoice status calculation.
            bv_root=Path(folder)/"BroadcastVoice"
            (bv_root/"runtime").mkdir(parents=True)
            (bv_root/"config.json").write_text(
                json.dumps({"announcer":"RIGHT-CONFIG","hour_close":{}}),
                encoding="utf-8",
            )
            legacy_state=bv_root/"runtime"/"state.json"
            legacy_state.write_text(json.dumps({"announcer":"WRONG-RAW-STATE"}),encoding="utf-8")
            bv=backend.bv_state({
                "broadcastvoice_dir":str(bv_root),
                "broadcastvoice_status_file":str(legacy_state),
            })
            check(bv.get("announcer")=="RIGHT-CONFIG","legacy BroadcastVoice status file bypassed directory discovery")
    finally:
        backend.CONFIG=original_config
        server.shutdown(); server.server_close()

    print("SELFTEST OK")
    print("- source syntax")
    print("- first-run configuration")
    print("- protected credential storage")
    print("- light/dark theme configuration")
    print("- single local station and integration paths")
    print("- RadioBOSS playback XML")
    print("- RadioBOSS playlist XML")
    print("- weather-disabled mode")
    print("- directory-based BroadcastVoice status")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
