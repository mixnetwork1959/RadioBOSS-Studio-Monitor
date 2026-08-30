from __future__ import annotations
import copy, json, os, sys, threading, time, urllib.parse, urllib.request, re
import xml.etree.ElementTree as ET
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from datetime import datetime, timedelta
import glob
import math
import queue
import atexit

from secret_store import protect_secret, unprotect_secret

BASE = (
    Path(sys.executable).resolve().parent
    if getattr(sys,"frozen",False)
    else Path(__file__).resolve().parent
)
BOOT_LOG = BASE / "studio-monitor-bootstrap.log"
if getattr(sys,"frozen",False):
    try:
        with BOOT_LOG.open("a", encoding="utf-8") as _f:
            _f.write("\n=== Studio Monitor bootstrap ===\n")
            _f.write("Python: " + sys.executable + "\n")
            _f.write("Version: " + sys.version.replace("\n"," ") + "\n")
            _f.write("Script: " + str(Path(__file__).resolve()) + "\n")
            _f.write("Time: " + datetime.now().isoformat() + "\n")
    except Exception:
        pass
CONFIG = BASE / "studio_monitor_config.json"
PID_FILE=BASE/'studio_monitor.pid'

_BROWSER_HEARTBEAT_LOCK=threading.Lock()
_BROWSER_LAST_SEEN=0.0
_BROWSER_SEEN_ONCE=False

def _cleanup_pid_file():
    try:
        PID_FILE.unlink(missing_ok=True)
    except Exception:
        pass

def browser_heartbeat():
    global _BROWSER_LAST_SEEN, _BROWSER_SEEN_ONCE
    with _BROWSER_HEARTBEAT_LOCK:
        _BROWSER_LAST_SEEN=time.time()
        _BROWSER_SEEN_ONCE=True

def browser_last_seen():
    with _BROWSER_HEARTBEAT_LOCK:
        return _BROWSER_LAST_SEEN, _BROWSER_SEEN_ONCE


HTML = BASE / "studio-monitor.html"

CONFIG_VERSION = 2

DEFAULT_STATION = {
  "id": "station-1",
  "name": "My Radio Station",
  "short_name": "STATION 1",
  "radioboss_host": "127.0.0.1",
  "radioboss_port": 9000,
  "radioboss_user": "",
  "radioboss_password": "",
  "accent_color": "#27ff72",
  "scheduler_events_file": "",
  "scheduler_admin_sdl": "",
  "broadcastvoice_dir": ""
}

DEFAULT_DOCUMENT = {
  "config_version": CONFIG_VERSION,
  "configured": False,
  "application_title": "RadioBOSS Studio Monitor",
  "theme": "dark",
  "active_station": "station-1",
  "stations": [DEFAULT_STATION],
  "refresh_interval_ms": 1500,
  "start_maximized": True,
  "playlist_rows": 16,
  "audio_meter_enabled": True,
  "weather_enabled": False,
  "weather_location": "",
  "weather_latitude": 0.0,
  "weather_longitude": 0.0,
  "weather_show_sea_temperature": False,
  "monitor_port": 8765
}

RUNTIME_DEFAULT = {
  "radioboss_host": "127.0.0.1",
  "radioboss_port": 9000,
  "radioboss_user": "",
  "radioboss_password": "",
  "monitor_port": 8765,
  "scheduler_events_file": "",
  "scheduler_admin_sdl": "",
  "broadcastvoice_dir": "",
  "weather_enabled": False,
  "weather_location": "",
  "weather_latitude": 0.0,
  "weather_longitude": 0.0,
  "weather_show_sea_temperature": False,
}


def _new_document():
    return copy.deepcopy(DEFAULT_DOCUMENT)


def _normalise_station(profile, index=0):
    result=copy.deepcopy(DEFAULT_STATION)
    if isinstance(profile,dict):
        result.update(profile)
    result["id"]=str(result.get("id") or f"station-{index+1}").strip()
    result["name"]=str(result.get("name") or f"Station {index+1}").strip()
    result["short_name"]=str(result.get("short_name") or result["name"]).strip()[:20]
    result["radioboss_host"]=str(result.get("radioboss_host") or "127.0.0.1").strip()
    try:
        result["radioboss_port"]=int(result.get("radioboss_port") or 9000)
    except Exception:
        result["radioboss_port"]=9000
    protected=str(result.get("radioboss_password_protected") or "")
    if protected:
        result["radioboss_password"]=unprotect_secret(protected)
    else:
        # Supports the earlier flat/plain configuration during one migration.
        result["radioboss_password"]=str(result.get("radioboss_password") or "")
    # v1.0.10 exposed runtime/state.json as a status file even though that file
    # is only BroadcastVoice's internal counter state. Directory discovery now
    # reads every required runtime/config source itself.
    result.pop("broadcastvoice_status_file",None)
    return result


def _legacy_document(data):
    """Convert the earlier single-station JSON shape without copying branding."""
    doc=_new_document()
    station=copy.deepcopy(DEFAULT_STATION)
    for key in station:
        if key in data:
            station[key]=data[key]
    station["name"]=str(data.get("station_name") or "My Radio Station")
    station["short_name"]=str(data.get("station_short_name") or "STATION 1")
    doc["stations"]=[station]
    for key in doc:
        if key in data and key not in ("stations",):
            doc[key]=data[key]
    doc["configured"]=bool(str(station.get("radioboss_password") or "").strip())
    return doc


def load_public_config():
    doc=_new_document()
    try:
        raw=CONFIG.read_text(encoding="utf-8-sig")
        data=json.loads(raw)
        if not isinstance(data,dict):
            raise ValueError("Configuration must be a JSON object")
        if not isinstance(data.get("stations"),list):
            data=_legacy_document(data)
        doc.update(data)
        stations=[]
        used_ids=set()
        for index,profile in enumerate(doc.get("stations") or []):
            item=_normalise_station(profile,index)
            base_id=item["id"]
            suffix=2
            while item["id"] in used_ids:
                item["id"]=f"{base_id}-{suffix}"; suffix+=1
            used_ids.add(item["id"])
            stations.append(item)
        if not stations:
            stations=[_normalise_station(DEFAULT_STATION,0)]
        # Single-station edition: one installation controls one local RadioBOSS station.
        stations=stations[:1]
        used_ids={stations[0]["id"]}
        doc["stations"]=stations
        if str(doc.get("active_station") or "") not in used_ids:
            doc["active_station"]=stations[0]["id"]
        doc["_config_error"]=""
    except FileNotFoundError:
        doc["_config_error"]=""
    except Exception as e:
        doc["_config_error"]=f"Configuration error: {type(e).__name__}: {e}"
    return doc


def save_public_config(document):
    """Atomically save the public configuration with protected passwords."""
    doc=copy.deepcopy(document if isinstance(document,dict) else {})
    doc.pop("_config_error",None)
    doc["config_version"]=CONFIG_VERSION
    stations=[]
    for index,raw in enumerate((doc.get("stations") or [])[:1]):
        supplied_secret=(
            str(raw.get("radioboss_password") or "")
            if isinstance(raw,dict) and "radioboss_password" in raw else None
        )
        profile=_normalise_station(raw,index)
        secret=supplied_secret if supplied_secret is not None else str(profile.get("radioboss_password") or "")
        profile.pop("radioboss_password",None)
        profile["radioboss_password_protected"]=protect_secret(secret)
        stations.append(profile)
    if not stations:
        stations=[_normalise_station(DEFAULT_STATION,0)]
        stations[0]["radioboss_password_protected"]=""
        stations[0].pop("radioboss_password",None)
    doc["stations"]=stations
    valid={str(x.get("id")) for x in stations}
    if str(doc.get("active_station") or "") not in valid:
        doc["active_station"]=stations[0]["id"]
    CONFIG.parent.mkdir(parents=True,exist_ok=True)
    temp=CONFIG.with_suffix(".json.tmp")
    temp.write_text(json.dumps(doc,ensure_ascii=False,indent=2),encoding="utf-8")
    temp.replace(CONFIG)


def set_active_station(station_id):
    doc=load_public_config()
    if any(str(x.get("id"))==str(station_id) for x in doc.get("stations") or []):
        doc["active_station"]=str(station_id)
        save_public_config(doc)


def runtime_config_from_document(document,station_id=None):
    """Build a flat runtime configuration from an editable config document."""
    doc=copy.deepcopy(document if isinstance(document,dict) else _new_document())
    wanted=str(station_id or doc.get("active_station") or "")
    station=next(
        (x for x in doc.get("stations") or [] if str(x.get("id"))==wanted),
        (doc.get("stations") or [DEFAULT_STATION])[0],
    )
    cfg=copy.deepcopy(RUNTIME_DEFAULT)
    for key,value in doc.items():
        if key not in ("stations",):
            cfg[key]=value
    cfg.update(station)
    cfg["_station_id"]=str(station.get("id") or "station-1")
    cfg["_station_name"]=str(station.get("name") or "My Radio Station")
    cfg["_station_short_name"]=str(station.get("short_name") or "STATION")
    cfg["_stations"]=copy.deepcopy(doc.get("stations") or [])
    cfg["_config_error"]=str(doc.get("_config_error") or "")
    return cfg


def load_config(station_id=None):
    """Return the flat runtime view expected by the existing monitor services."""
    return runtime_config_from_document(load_public_config(),station_id)

def rb_url(cfg, action):
    # RadioBOSS supports both authentication forms:
    #   global API password: ?pass=PASSWORD&action=ACTION
    #   API user account:    ?user=USERNAME&pass=PASSWORD&action=ACTION
    q={"pass": str(cfg.get("radioboss_password", "")).strip(), "action": action}
    user=str(cfg.get("radioboss_user", "")).strip()
    if user:
        q["user"] = user
    return f'http://{cfg["radioboss_host"]}:{cfg["radioboss_port"]}/?'+urllib.parse.urlencode(q)

def rb_url_params(cfg, action, **params):
    q={"pass": str(cfg.get("radioboss_password", "")).strip(), "action": action}
    user=str(cfg.get("radioboss_user", "")).strip()
    if user:
        q["user"] = user
    for k,v in params.items():
        if v is not None:
            q[str(k)] = str(v)
    return f'http://{cfg["radioboss_host"]}:{cfg["radioboss_port"]}/?'+urllib.parse.urlencode(q)

def fetch_bytes(url, timeout=1.5):
    req=urllib.request.Request(url,headers={"User-Agent":"RadioBOSSStudioMonitor/1.0"})
    with urllib.request.urlopen(req,timeout=timeout) as r:
        return r.read()

def track(node):
    if node is None: return {}
    t=node.find("TRACK")
    if t is None: return {}
    a=t.attrib
    return {k.lower():a.get(k,"") for k in [
        "ARTIST","TITLE","ALBUM","YEAR","GENRE","FILENAME","DURATION","CASTTITLE",
        "BPM","LISTENERS","BITRATE","SAMPLERATE","CHANNELS","ITEMTYPE","STARTTIME"
    ]}

def rb_state(cfg):
    api=f'{cfg["radioboss_host"]}:{cfg["radioboss_port"]}'
    if cfg.get("_config_error"):
        return {"connected":False,"api":api,"error":cfg["_config_error"]}
    if not str(cfg.get("radioboss_password", "")):
        return {"connected":False,"api":api,"error":"No RadioBOSS API password configured"}
    try:
        raw=fetch_bytes(rb_url(cfg,"playbackinfo"))
        root=ET.fromstring(raw)
        pb=root.find("Playback")
        playback={}
        if pb is not None:
            # RadioBOSS:
            #   pos / len = current item position and length in milliseconds
            #   playingtimeleft = remaining time of the PLAYLIST, not current track
            try:
                raw_pos=float(pb.attrib.get("pos",0))
            except:
                raw_pos=0.0
            try:
                raw_len=float(pb.attrib.get("len",0))
            except:
                raw_len=0.0
            try:
                raw_playlist_left=float(pb.attrib.get("playingtimeleft",0))
            except:
                raw_playlist_left=0.0

            playback["pos"]=raw_pos / 1000.0
            playback["len"]=raw_len / 1000.0
            playback["track_remaining"]=max(0.0, raw_len - raw_pos) / 1000.0
            playback["playingtimeleft"]=raw_playlist_left / 1000.0

            try: playback["playlistpos"]=float(pb.attrib.get("playlistpos",0))
            except: playback["playlistpos"]=0
            playback["state"]=pb.attrib.get("state","")
            playback["timestamp"]=pb.attrib.get("timestamp","")
        return {
          "connected":True,"api":api,
          "current":track(root.find("CurrentTrack")),
          "next":track(root.find("NextTrack")),
          "playback":playback,
          "artwork_current":"/api/artwork/current",
          "artwork_next":"/api/artwork/next",
        }
    except urllib.error.HTTPError as e:
        msg = f"RadioBOSS HTTP {e.code}"
        if e.code in (401,403):
            if str(cfg.get("radioboss_user", "")).strip():
                msg += " - user/password rejected or API access is not allowed"
            else:
                msg += " - API password rejected. Enter the API user name when an API user account is used"
        return {"connected":False,"api":api,"error":msg}
    except urllib.error.URLError as e:
        return {"connected":False,"api":api,"error":"RadioBOSS is not reachable: "+str(e.reason)}
    except Exception as e:
        return {"connected":False,"api":api,"error":str(e)}



_PLAYLIST_LOCK = threading.Lock()
_PLAYLIST_CACHE = {"ok":False,"tracks":[],"hour_label":"","total_seconds":0.0,"time_left_seconds":0.0,"updated":0.0,"error":"Reading playlist..."}

def _dur_to_seconds(value):
    text=str(value or "").strip()
    if not text: return 0.0
    try:
        parts=[float(x) for x in text.split(":")]
        if len(parts)==3: return parts[0]*3600+parts[1]*60+parts[2]
        if len(parts)==2: return parts[0]*60+parts[1]
        return float(text)
    except Exception:
        return 0.0

def _clock_to_seconds(value):
    text=str(value or "").strip()
    if not text: return None
    # RadioBOSS STARTTIME may contain HH:MM:SS or a full date/time string.
    m=re.search(r'(\d{1,2}):(\d{2})(?::(\d{2}))?', text)
    if not m: return None
    h=int(m.group(1)); mi=int(m.group(2)); sec=int(m.group(3) or 0)
    return h*3600+mi*60+sec


def _safe_int(value, default=0):
    try:
        text=str(value if value is not None else "").strip()
        if not text:
            return default
        return int(float(text))
    except Exception:
        return default

def _tag_name(node):
    return str(getattr(node, "tag", "") or "").split("}")[-1].upper()

def _track_nodes(root):
    # Normal RadioBOSS getplaylist/getplaylist2 output uses direct TRACK children.
    # Iterate recursively/case-insensitively as a defensive fallback.
    return [
        node for node in root.iter()
        if _tag_name(node) == "TRACK" and getattr(node, "attrib", None)
    ]

def _attr_map(node):
    return {str(k).upper(): str(v) for k,v in (node.attrib or {}).items()}

def _read_playlist_action(cfg, action, cnt=None):
    params={"cnt":cnt} if cnt is not None else {}
    raw=fetch_bytes(rb_url_params(cfg, action, **params), timeout=2.5)
    root=ET.fromstring(raw)
    rows=[]
    for node in _track_nodes(root):
        a=_attr_map(node)
        filename=a.get("FILENAME","")
        duration=a.get("DURATION","")
        rows.append({
            "artist":a.get("ARTIST",""),
            "title":a.get("TITLE","") or a.get("CASTTITLE","") or Path(filename).stem,
            "album":a.get("ALBUM",""),
            "year":a.get("YEAR",""),
            "filename":filename,
            "duration":duration,
            "duration_seconds":_dur_to_seconds(duration),
            "bpm":a.get("BPM",""),
            "starttime":a.get("STARTTIME",""),
            "playlist_index":_safe_int(a.get("PLAYLISTINDEX"), _safe_int(a.get("INDEX"),0)),
            "index":_safe_int(a.get("INDEX"),0),
            "itemtype":a.get("ITEMTYPE",""),
        })
    return rows

def playlist_state(cfg, playback=None, current=None):
    """Read RadioBOSS playlist, read-only, and expose the current clock-hour slice."""
    source="getplaylist2"
    diagnostics=[]
    try:
        try:
            rows=_read_playlist_action(cfg,"getplaylist2",cnt=120)
            diagnostics.append(f"getplaylist2={len(rows)}")
        except Exception as e:
            rows=[]
            diagnostics.append("getplaylist2 error: "+type(e).__name__+": "+str(e))

        # RadioBOSS documents getplaylist as deprecated, but it is useful as a
        # compatibility fallback on installations where getplaylist2 returns
        # no usable TRACK nodes for any reason. BPM/STARTTIME may be absent.
        if not rows:
            source="getplaylist"
            try:
                rows=_read_playlist_action(cfg,"getplaylist")
                diagnostics.append(f"getplaylist={len(rows)}")
            except Exception as e:
                diagnostics.append("getplaylist error: "+type(e).__name__+": "+str(e))

        if not rows:
            return {
                "ok":False,"tracks":[],"hour_label":"","total_seconds":0,
                "time_left_seconds":0,"updated":time.time(),"count":0,
                "source":source,"error":"; ".join(diagnostics) or "RadioBOSS returned no playlist tracks"
            }

        # Determine current row by exact normalized filename first.
        current_idx=None
        cur_file=str((current or {}).get("filename","") or "").replace("/","\\").lower()
        if cur_file:
            for i,r in enumerate(rows):
                rf=str(r.get("filename","") or "").replace("/","\\").lower()
                if rf and rf==cur_file:
                    current_idx=i
                    break

        # Then use RadioBOSS playlist position/index, allowing 0/1 based variants.
        if current_idx is None:
            pos=_safe_int((playback or {}).get("playlistpos"),0)
            scored=[]
            for i,r in enumerate(rows):
                vals=(r.get("playlist_index",0),r.get("index",0))
                dist=min(abs(_safe_int(v)-pos) for v in vals)
                scored.append((dist,i))
            if scored:
                dist,current_idx=min(scored)

        if current_idx is None:
            current_idx=0

        now=datetime.now()
        now_seconds=now.hour*3600+now.minute*60+now.second
        hour_start=now.hour*3600
        hour_end=hour_start+3600

        # Prefer RadioBOSS STARTTIME. Fill missing times outward from Current.
        starts=[_clock_to_seconds(r.get("starttime")) for r in rows]
        cur_remaining=float((playback or {}).get("track_remaining",0) or 0)
        cur_len=float((playback or {}).get("len",0) or 0)
        cur_elapsed=max(0.0,cur_len-cur_remaining)
        if starts[current_idx] is None:
            starts[current_idx]=max(0.0,now_seconds-cur_elapsed)

        for i in range(current_idx+1,len(rows)):
            if starts[i] is None:
                starts[i]=(starts[i-1] or now_seconds)+float(rows[i-1].get("duration_seconds",0) or 0)
        for i in range(current_idx-1,-1,-1):
            if starts[i] is None:
                starts[i]=(starts[i+1] or now_seconds)-float(rows[i].get("duration_seconds",0) or 0)

        # Build the current clock-hour view. If RadioBOSS no longer returns
        # already-played tracks, current + future tracks still appear.
        hour_rows=[]
        for i,r in enumerate(rows):
            st=starts[i]
            if st is None:
                continue
            in_hour=(hour_start <= st < hour_end)
            if i==current_idx:
                in_hour=True
            if not in_hour:
                continue
            x=dict(r)
            x["start_seconds"]=st
            x["start_clock"]=f"{int(st//3600)%24:02d}:{int((st%3600)//60):02d}:{int(st%60):02d}"
            if i<current_idx: x["status"]="PLAYED"
            elif i==current_idx: x["status"]="PLAYING"
            elif i==current_idx+1: x["status"]="UP NEXT"
            else: x["status"]=""
            hour_rows.append(x)

        # Absolute safety fallback: never show an empty table when RadioBOSS
        # actually returned playlist rows. Show Current + following items.
        if not hour_rows:
            for i,r in enumerate(rows[max(0,current_idx):max(0,current_idx)+13]):
                x=dict(r)
                ri=max(0,current_idx)+i
                st=starts[ri] if ri < len(starts) else None
                x["start_clock"]=(
                    f"{int(st//3600)%24:02d}:{int((st%3600)//60):02d}:{int(st%60):02d}"
                    if st is not None else "—"
                )
                x["status"]="PLAYING" if i==0 else ("UP NEXT" if i==1 else "")
                hour_rows.append(x)

        total=sum(float(r.get("duration_seconds",0) or 0) for r in hour_rows)
        to_hour=max(0,3600-(now.minute*60+now.second))
        return {
            "ok":True,
            "tracks":hour_rows,
            "hour_label":f"{now.hour:02d}:00 - {(now.hour+1)%24:02d}:00",
            "total_seconds":total,
            "time_left_seconds":to_hour,
            "current_playlist_index":current_idx,
            "updated":time.time(),
            "count":len(hour_rows),
            "source":source,
            "diagnostic":"; ".join(diagnostics),
        }
    except Exception as e:
        return {
            "ok":False,"tracks":[],"hour_label":"","total_seconds":0,
            "time_left_seconds":0,"updated":time.time(),"count":0,
            "source":source,"error":type(e).__name__+": "+str(e)
        }

_STATE_LOCK = threading.Lock()
_STATE_CACHE = {"connected": False, "api": "127.0.0.1:9000", "error": "Connecting to RadioBOSS..."}

def update_state_cache():
    """Poll RadioBOSS independently so browser requests never wait for RadioBOSS."""
    global _STATE_CACHE
    while True:
        cfg = load_config()
        state = rb_state(cfg)
        with _STATE_LOCK:
            _STATE_CACHE = state
        time.sleep(1.0)

def cached_rb_state():
    with _STATE_LOCK:
        return dict(_STATE_CACHE)



_AUDIO_LOCK=threading.Lock()
_AUDIO_STATE={"available":False,"left":0.0,"right":0.0,"source":"","error":"Starting audio meter..."}

def _audio_set(**kwargs):
    with _AUDIO_LOCK:
        _AUDIO_STATE.update(kwargs)

def audio_state():
    with _AUDIO_LOCK:
        return dict(_AUDIO_STATE)

def _dbfs_to_level(db):
    # Map -60..0 dBFS to 0..1 for the 28-segment studio meter.
    if db <= -60.0:
        return 0.0
    if db >= 0.0:
        return 1.0
    return (db + 60.0) / 60.0

def _audio_meter_worker():
    """Read Windows Core Audio peak levels (read-only). Compatible with multiple pycaw APIs."""
    try:
        from ctypes import POINTER, cast, c_float
        from comtypes import CLSCTX_ALL
        from pycaw.pycaw import AudioUtilities, IAudioMeterInformation
    except Exception as e:
        _audio_set(
            available=False,left=0.0,right=0.0,
            error="pycaw/comtypes is not installed: "+str(e)
        )
        return

    try:
        speakers=AudioUtilities.GetSpeakers()
        if speakers is None:
            _audio_set(
                available=False,left=0.0,right=0.0,
                error="No Windows output device found"
            )
            return

        # pycaw API differs between releases:
        # older versions expose Activate() on the device,
        # newer versions expose the raw IMMDevice through _dev.
        interface=None

        activate=getattr(speakers, "Activate", None)
        if callable(activate):
            interface=activate(
                IAudioMeterInformation._iid_, CLSCTX_ALL, None
            )
        else:
            raw_dev=getattr(speakers, "_dev", None)
            raw_activate=getattr(raw_dev, "Activate", None) if raw_dev is not None else None
            if callable(raw_activate):
                interface=raw_activate(
                    IAudioMeterInformation._iid_, CLSCTX_ALL, None
                )

        if interface is None:
            # Last compatibility path used by some pycaw releases.
            endpoint_volume=getattr(speakers, "EndpointVolume", None)
            meter_candidate=getattr(speakers, "AudioMeterInformation", None)
            if meter_candidate is not None:
                meter=meter_candidate
            else:
                raise RuntimeError(
                    "AudioDevice besitzt weder Activate noch eine zugängliche Core-Audio-Meter-Schnittstelle"
                )
        else:
            meter=cast(interface, POINTER(IAudioMeterInformation))

        source=(
            getattr(speakers, "FriendlyName", None)
            or getattr(speakers, "friendly_name", None)
            or getattr(speakers, "id", None)
            or "Windows Audio"
        )

        smooth_l=0.0
        smooth_r=0.0

        while True:
            # Master peak is broadly supported.
            peak_fn=getattr(meter, "GetPeakValue", None)
            if not callable(peak_fn):
                raise RuntimeError("IAudioMeterInformation.GetPeakValue ist nicht verfügbar")

            master=float(peak_fn())
            raw_l=master
            raw_r=master

            # Try channel-specific peaks where supported.
            try:
                count_fn=getattr(meter, "GetMeteringChannelCount", None)
                values_fn=getattr(meter, "GetChannelsPeakValues", None)
                if callable(count_fn) and callable(values_fn):
                    channels=int(count_fn())
                    if channels >= 2:
                        arr=(c_float * channels)()
                        values_fn(channels, arr)
                        raw_l=float(arr[0])
                        raw_r=float(arr[1])
            except Exception:
                pass

            raw_l=max(0.0,min(1.0,raw_l))
            raw_r=max(0.0,min(1.0,raw_r))

            smooth_l=raw_l if raw_l > smooth_l else smooth_l*0.82 + raw_l*0.18
            smooth_r=raw_r if raw_r > smooth_r else smooth_r*0.82 + raw_r*0.18

            _audio_set(
                available=True,
                left=max(0.0,min(1.0,smooth_l)),
                right=max(0.0,min(1.0,smooth_r)),
                source=str(source),
                error=""
            )
            time.sleep(0.05)

    except Exception as e:
        _audio_set(
            available=False,left=0.0,right=0.0,
            error=type(e).__name__+": "+str(e)
        )


def _find_admin_sdl(cfg):
    """Return configured or auto-detected RadioBOSS Admin.sdl path (read-only)."""
    configured=str(cfg.get("scheduler_admin_sdl","") or "").strip()
    if configured:
        return Path(os.path.expandvars(os.path.expanduser(configured)))

    appdata=os.environ.get("APPDATA","")
    if not appdata:
        return None

    patterns=[
        os.path.join(appdata,"djsoft.net","RadioBOSS_*","Presets","Schedule","Admin.sdl"),
        os.path.join(appdata,"djsoft.net","RadioBOSS*","Presets","Schedule","Admin.sdl"),
    ]
    found=[]
    for pat in patterns:
        for fn in glob.glob(pat):
            p=Path(fn)
            if p.is_file():
                found.append(p)
    if not found:
        return None
    # Prefer the SDL RadioBOSS touched most recently.
    found.sort(key=lambda p:p.stat().st_mtime, reverse=True)
    return found[0]


def _parse_admin_sdl(path):
    """Minimal parser matching BroadcastScheduler fields; never writes the SDL."""
    events=[]
    current=None
    with open(path,"r",encoding="utf-8",errors="ignore") as f:
        for raw in f:
            line=raw.strip()
            if not line:
                continue
            if line.lower().startswith("[event"):
                if current is not None:
                    events.append(current)
                current={}
                continue
            if current is None or "=" not in line:
                continue
            k,v=line.split("=",1)
            current[k.strip()]=v.strip()
    if current is not None:
        events.append(current)
    return events


def _sdl_weekday_enabled(days, dt):
    # RadioBOSS SDL order: Su Mo Tu We Th Fr Sa.
    if not days or len(days) != 7:
        return True
    py_to_sdl={0:1,1:2,2:3,3:4,4:5,5:6,6:0}
    idx=py_to_sdl[dt.weekday()]
    return days[idx] == "1"


def _decode_hours(hours):
    if not hours:
        return []
    return [i for i,ch in enumerate(hours[:24]) if ch=="1"]


def _decode_minutes(minutes):
    if minutes is None or str(minutes).strip()=="":
        return [0]
    out=[]
    for part in str(minutes).split(","):
        try:
            m=int(part.strip())
            if 0 <= m <= 59:
                out.append(m)
        except:
            pass
    return out or [0]


def _next_sdl_event(path):
    now=datetime.now()
    events=_parse_admin_sdl(path)
    candidates=[]
    enabled_count=0

    for ev in events:
        if str(ev.get("EnabledEvent","0")) != "1":
            continue
        enabled_count += 1
        name=ev.get("TaskName") or ev.get("FileName") or "RadioBOSS Event"
        try:
            time_type=int(ev.get("TimeType","0") or 0)
        except:
            time_type=0

        if time_type == 1:
            hours=_decode_hours(ev.get("Hours",""))
            minutes=_decode_minutes(ev.get("Minutes",""))
            try:
                second=int(ev.get("Seconds","0") or 0)
            except:
                second=0
            second=max(0,min(59,second))
            if not hours:
                continue

            for day_offset in range(0,8):
                day=now + timedelta(days=day_offset)
                if not _sdl_weekday_enabled(ev.get("Days",""), day):
                    continue
                for hour in hours:
                    for minute in minutes:
                        dt=day.replace(hour=hour,minute=minute,second=second,microsecond=0)
                        if dt > now:
                            candidates.append((dt,name,ev))

        elif time_type == 2:
            raw=ev.get("DateTime","").strip()
            try:
                base=datetime.strptime(raw,"%Y-%m-%d %H:%M:%S")
            except:
                base=None
            if base:
                every_year=str(ev.get("EveryYear","0"))=="1"
                if every_year:
                    for year in (now.year, now.year+1):
                        try:
                            dt=base.replace(year=year)
                        except:
                            continue
                        if dt > now:
                            candidates.append((dt,name,ev))
                elif base > now:
                    candidates.append((base,name,ev))

    if not candidates:
        return {
            "connected": True,
            "configured": True,
            "name": "No upcoming event found",
            "time": "—",
            "seconds": None,
            "source": str(path),
            "events": len(events),
            "enabled_events": enabled_count,
            "upcoming": [],
            "read_only": True
        }

    candidates.sort(key=lambda x:x[0])
    upcoming=[]
    for dt,name,ev in candidates[:3]:
        upcoming.append({
            "name": name,
            "time": dt.strftime("%H:%M:%S"),
            "date": dt.strftime("%d.%m.%Y"),
            "seconds": max(0,(dt-now).total_seconds()),
            "group": ev.get("GroupName","")
        })

    dt,name,ev=candidates[0]
    return {
        "connected": True,
        "configured": True,
        "name": name,
        "time": dt.strftime("%H:%M:%S"),
        "date": dt.strftime("%d.%m.%Y"),
        "seconds": max(0,(dt-now).total_seconds()),
        "source": str(path),
        "group": ev.get("GroupName",""),
        "events": len(events),
        "enabled_events": enabled_count,
        "upcoming": upcoming,
        "read_only": True
    }


def scheduler_state(cfg):
    # Preferred: direct read-only view of RadioBOSS Admin.sdl.
    sdl=_find_admin_sdl(cfg)
    if sdl and sdl.is_file():
        try:
            return _next_sdl_event(sdl)
        except Exception as e:
            return {
                "connected": False,
                "configured": True,
                "name": "Admin.sdl could not be read",
                "time": "—",
                "seconds": None,
                "source": str(sdl),
                "error": str(e),
                "read_only": True
            }

    # Optional fallback for installations that export scheduler events as JSON.
    p=str(cfg.get("scheduler_events_file","") or "").strip()
    if p:
        pp=Path(p)
        if not pp.is_file():
            return {
                "connected": False,
                "configured": True,
                "name": "Scheduler file not found",
                "time": "—",
                "seconds": None,
                "source": str(pp),
                "read_only": True
            }
        try:
            data=json.loads(pp.read_text(encoding="utf-8-sig"))
        except Exception as e:
            return {
                "connected": False,
                "configured": True,
                "name": "Scheduler JSON is invalid",
                "time": "—",
                "seconds": None,
                "error": str(e),
                "source": str(pp),
                "read_only": True
            }

        events=data if isinstance(data,list) else data.get("events",[]) if isinstance(data,dict) else []
        now=time.time()
        candidates=[]
        for ev in events:
            if not isinstance(ev,dict):
                continue
            raw=ev.get("timestamp") or ev.get("start") or ev.get("datetime") or ev.get("time")
            epoch=None
            if isinstance(raw,(int,float)):
                epoch=float(raw)
            elif isinstance(raw,str):
                try:
                    epoch=datetime.fromisoformat(raw.replace("Z","+00:00")).timestamp()
                except:
                    pass
            if epoch and epoch > now:
                candidates.append((epoch,ev))
        if not candidates:
            return {
                "connected": True,
                "configured": True,
                "name": "No upcoming event found",
                "time": "—",
                "seconds": None,
                "source": str(pp),
                "read_only": True
            }
        epoch,ev=min(candidates,key=lambda x:x[0])
        return {
            "connected": True,
            "configured": True,
            "name":ev.get("name") or ev.get("title") or ev.get("event_name") or "Scheduler Event",
            "time":time.strftime("%H:%M:%S",time.localtime(epoch)),
            "seconds":max(0,epoch-now),
            "source":str(pp),
            "read_only":True
        }

    return {
        "connected": False,
        "configured": False,
        "name": "Admin.sdl not found",
        "time": "—",
        "seconds": None,
        "read_only": True
    }


def _fmt_seconds(value):
    try:
        sec=max(0,int(round(float(value))))
    except Exception:
        return "—"
    m,ss=divmod(sec,60)
    h,m=divmod(m,60)
    return f"{h:d}:{m:02d}:{ss:02d}" if h else f"{m:02d}:{ss:02d}"

def _find_broadcastvoice_dir(cfg):
    explicit=str(cfg.get("broadcastvoice_dir","") or "").strip()
    candidates=[]
    if explicit:
        candidates.append(Path(explicit))
    # Typical local/private BroadcastVoice locations. Read-only discovery only.
    for base in (Path("D:/"), BASE.parent):
        try:
            candidates.extend(sorted(base.glob("BroadcastVoice-AI-Prototype-v*-private"), reverse=True))
        except Exception:
            pass
    seen=set()
    for p in candidates:
        key=str(p).lower()
        if key in seen: continue
        seen.add(key)
        if p.is_dir() and (p/"config.json").is_file():
            return p
    return None

def bv_state(cfg):
    """Read BroadcastVoice state/config only. Never sends commands."""
    root=_find_broadcastvoice_dir(cfg)
    if root is None:
        return {
            "connected":False,"running":False,"announcer":"—","next_link":"—",
            "anchor_in":"—","max_cut":"—","filler":"—","full_hour_block":"—",
            "stop_mode":"—","prepared":"—","source":"not found"
        }

    try:
        bv_cfg=json.loads((root/"config.json").read_text(encoding="utf-8-sig"))
    except Exception as e:
        return {
            "connected":False,"running":False,"announcer":"—","next_link":"—",
            "anchor_in":"—","max_cut":"—","filler":"—","full_hour_block":"—",
            "stop_mode":"—","prepared":"—","source":str(root),"error":str(e)
        }

    hc=bv_cfg.get("hour_close") or {}
    service=bv_cfg.get("service") or {}
    announcer=(
        bv_cfg.get("announcer")
        or bv_cfg.get("announcer_name")
        or service.get("announcer")
        or service.get("announcer_name")
        or "—"
    )

    # worker.lock is only observed. If absent, no claim that BV is running.
    # BroadcastVoice's own background module uses these exact runtime files:
    #   runtime/broadcastvoice.pid
    #   runtime/broadcastvoice-worker.lock
    # We only observe them; no writes or commands.
    runtime_dir=root/"runtime"
    pid_file=runtime_dir/"broadcastvoice.pid"
    worker_lock=runtime_dir/"broadcastvoice-worker.lock"

    running=False
    pid=None

    if pid_file.is_file():
        try:
            pid=int(pid_file.read_text(encoding="ascii", errors="ignore").strip())
        except Exception:
            pid=None

    # A live worker lock is also a valid running signal. This mirrors
    # BroadcastVoice's own "running without pid" fallback.
    if worker_lock.exists():
        running=True

    if pid:
        try:
            # Windows read-only process existence check via tasklist.
            import subprocess
            check=subprocess.run(
                ["tasklist","/FI",f"PID eq {pid}","/NH"],
                capture_output=True,text=False,timeout=2,
                creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0),
            )
            text=(check.stdout or b"").decode("utf-8", errors="replace").strip()
            if str(pid) in text and "No tasks" not in text and "Keine Aufgaben" not in text:
                running=True
        except Exception:
            # Keep worker-lock result if process probing is unavailable.
            pass

    # Read optional runtime/status JSONs if BroadcastVoice provides them.
    runtime={}
    for rp in (
        root/"status.json", root/"runtime"/"status.json",
        root/"broadcastvoice_status.json", root/"runtime"/"broadcastvoice_status.json"
    ):
        if rp.is_file():
            try:
                x=json.loads(rp.read_text(encoding="utf-8-sig"))
                if isinstance(x,dict):
                    runtime.update(x)
            except Exception:
                pass

    running=bool(runtime.get("running",running))

    # BroadcastVoice v0.4.3: determine the active announcer with the same
    # shift/default rule used by its schedule.py. An optional override file
    # wins when present.
    announcers=bv_cfg.get("announcers") or []
    override=""
    for op in (
        runtime_dir/"announcer-override.txt",
        root/"announcer-override.txt",
    ):
        if op.is_file():
            try:
                override=op.read_text(encoding="utf-8",errors="ignore").strip()
            except Exception:
                override=""
            if override:
                break

    selected=None
    if override:
        selected=next(
            (a for a in announcers if str(a.get("id","")).casefold()==override.casefold()),
            None
        )

    if selected is None and announcers:
        now_dt=datetime.now()
        weekday=now_dt.strftime("%A").casefold()
        now_minutes=now_dt.hour*60+now_dt.minute

        def _shift_matches(shift):
            days=[str(x).casefold() for x in (shift.get("days") or [])]
            if days and weekday not in days:
                return False
            try:
                sh,sm=map(int,str(shift.get("start","00:00")).split(":")[:2])
                eh,em=map(int,str(shift.get("end","00:00")).split(":")[:2])
            except Exception:
                return False
            start_m=sh*60+sm
            end_m=eh*60+em
            if start_m==end_m:
                return True
            if start_m < end_m:
                return start_m <= now_minutes < end_m
            # Overnight shift.
            return now_minutes >= start_m or now_minutes < end_m

        for profile in announcers:
            if any(_shift_matches(s) for s in (profile.get("shifts") or [])):
                selected=profile
                break
        if selected is None:
            selected=next((a for a in announcers if a.get("default") is True),announcers[0])

    if selected:
        announcer=selected.get("name") or selected.get("id") or announcer
        announcer_id=selected.get("id") or ""
    else:
        announcer_id=""

    # BroadcastVoice v0.4.3 cadence is track based, not wall-clock based.
    # Reproduce dashboard.tracks_until_next_link() from runtime/state.json.
    next_link=runtime.get("next_link") or runtime.get("next_link_in")
    if not next_link:
        try:
            state_data={}
            state_file=runtime_dir/"state.json"
            if state_file.is_file():
                x=json.loads(state_file.read_text(encoding="utf-8-sig"))
                if isinstance(x,dict):
                    state_data=x
            counter=max(0,int(state_data.get("track_counter",0)))
            every=max(1,int((bv_cfg.get("safety") or {}).get("break_every_tracks",4)))
            remainder=counter % every
            tracks_left=every if remainder==0 else every-remainder
            pending=bool(state_data.get("link_pending",False))
            next_link=("JETZT" if pending else f"{tracks_left} TRACK"
                       if tracks_left==1 else f"{tracks_left} TRACKS")
        except Exception:
            next_link="—"
    # BroadcastVoice v0.4.3 does not publish live Hour-Close fields in
    # runtime/state.json. Read its real config names and derive only values
    # that are unambiguous for display.
    enabled=bool(hc.get("enabled",False))
    observe_only=bool(hc.get("observe_only",False))
    mode=str(hc.get("mode") or ("observe" if observe_only else "live")).strip()
    stop=bool(hc.get("stop_after_final_element",False))

    max_cut=hc.get("maximum_song_cut_seconds","—")
    prepare_before=float(hc.get("prepare_before_seconds",0) or 0)
    filler_folder=str(hc.get("filler_music_folder") or "").strip()
    filler=filler_folder if filler_folder else "AUS"

    # v0.4.3 uses the named RadioBOSS anchor event rather than a fixed
    # full_hour_block_seconds value. The scheduler state already resolves
    # that event from Admin.sdl, so use its countdown when names match.
    anchor_name=str(hc.get("anchor_event") or "").strip()
    anchor_in="—"
    anchor_seconds=None
    if enabled and anchor_name:
        try:
            sc=scheduler_state(cfg)
            if str(sc.get("name") or "").strip().lower() == anchor_name.lower():
                anchor_seconds=sc.get("seconds")
                anchor_in=_fmt_seconds(anchor_seconds)
        except Exception:
            pass

    # If the exact anchor is not the very next scheduler event, search the
    # same read-only Admin.sdl for that named event.
    if enabled and anchor_name and anchor_seconds is None:
        try:
            sdl=_find_admin_sdl(cfg)
            if sdl and sdl.is_file():
                now_dt=datetime.now()
                matches=[]
                for ev in _parse_admin_sdl(sdl):
                    if str(ev.get("EnabledEvent","0")) != "1":
                        continue
                    name=ev.get("TaskName") or ev.get("FileName") or "RadioBOSS Event"
                    if str(name).strip().lower() != anchor_name.lower():
                        continue
                    try:
                        time_type=int(ev.get("TimeType","0") or 0)
                    except:
                        time_type=0
                    if time_type == 1:
                        hours=_decode_hours(ev.get("Hours",""))
                        minutes=_decode_minutes(ev.get("Minutes",""))
                        try:
                            second=max(0,min(59,int(ev.get("Seconds","0") or 0)))
                        except:
                            second=0
                        for day_offset in range(0,8):
                            day=now_dt+timedelta(days=day_offset)
                            if not _sdl_weekday_enabled(ev.get("Days",""),day):
                                continue
                            for hour in hours:
                                for minute in minutes:
                                    dt=day.replace(hour=hour,minute=minute,second=second,microsecond=0)
                                    if dt>now_dt:
                                        matches.append(dt)
                    elif time_type == 2:
                        try:
                            dt=datetime.strptime(str(ev.get("DateTime","")).strip(),"%Y-%m-%d %H:%M:%S")
                            if dt>now_dt:
                                matches.append(dt)
                        except:
                            pass
                if matches:
                    anchor_seconds=max(0,(min(matches)-now_dt).total_seconds())
                    anchor_in=_fmt_seconds(anchor_seconds)
        except Exception:
            pass

    prepared=runtime.get("hour_close_prepared")
    if prepared is None:
        prepared=runtime.get("prepared")
    if prepared is True:
        prepared_text="YES"
    elif prepared is False:
        prepared_text="NO"
    elif anchor_seconds is not None and prepare_before>0:
        prepared_text="YES" if anchor_seconds <= prepare_before else "NO"
    else:
        prepared_text="—"

    # There is no fixed full-hour-block duration in v0.4.3 config.
    # Show the actual configured anchor instead of the misleading old "0 s".
    block_text=anchor_name if anchor_name else "—"

    return {
        "connected":True,
        "running":running,
        "announcer":str(announcer),
        "announcer_id":str(announcer_id),
        "next_link":str(next_link),
        "anchor_in":str(anchor_in),
        "max_cut":str(max_cut) if max_cut not in (None,"") else "—",
        "filler":str(filler),
        "full_hour_block":block_text,
        "stop_mode":"ACTIVE" if stop else "OFF",
        "mode":mode.upper() if enabled else "OFF",
        "prepared":prepared_text,
        "source":str(root),
        "pid":pid,
        "worker_lock":worker_lock.exists(),
    }


_WEATHER_LOCK=threading.Lock()
_WEATHER_CACHE={}

def weather_state(cfg):
    """Fetch current weather from Open-Meteo. Read-only; cached for 10 minutes."""
    if not bool(cfg.get("weather_enabled",False)):
        return {"ok":False,"disabled":True,"location":"","error":"Weather is disabled"}
    lat=float(cfg.get("weather_latitude",0) or 0)
    lon=float(cfg.get("weather_longitude",0) or 0)
    name=str(cfg.get("weather_location","") or "Weather")
    cache_key=(round(lat,5),round(lon,5),bool(cfg.get("weather_show_sea_temperature",False)))
    with _WEATHER_LOCK:
        entry=_WEATHER_CACHE.get(cache_key) or {}
        cached=entry.get("data")
        age=time.time()-float(entry.get("at",0) or 0)
        if cached is not None and age < 600:
            return cached
    try:
        q=urllib.parse.urlencode({
            "latitude":lat,
            "longitude":lon,
            "current":"temperature_2m,relative_humidity_2m,apparent_temperature,pressure_msl,weather_code,wind_speed_10m,wind_direction_10m",
            "timezone":"auto",
            "wind_speed_unit":"kmh",
        })
        req=urllib.request.Request(
            "https://api.open-meteo.com/v1/forecast?"+q,
            headers={"User-Agent":"RadioBOSSStudioMonitor/1.0"}
        )
        with urllib.request.urlopen(req,timeout=5) as r:
            raw=json.loads(r.read().decode("utf-8"))
        cur=raw.get("current") or {}
        sea_temp=None
        try:
            if not bool(cfg.get("weather_show_sea_temperature",False)):
                raise RuntimeError("Sea temperature is disabled")
            mq=urllib.parse.urlencode({
                "latitude":lat,
                "longitude":lon,
                "current":"sea_surface_temperature",
                "timezone":"auto",
                "cell_selection":"sea",
            })
            mreq=urllib.request.Request(
                "https://marine-api.open-meteo.com/v1/marine?"+mq,
                headers={"User-Agent":"RadioBOSSStudioMonitor/1.0"}
            )
            with urllib.request.urlopen(mreq,timeout=5) as mr:
                marine=json.loads(mr.read().decode("utf-8"))
            sea_temp=(marine.get("current") or {}).get("sea_surface_temperature")
        except Exception:
            sea_temp=None

        data={
            "ok":True,
            "location":name,
            "temperature":cur.get("temperature_2m"),
            "feels_like":cur.get("apparent_temperature"),
            "humidity":cur.get("relative_humidity_2m"),
            "pressure":cur.get("pressure_msl"),
            "wind_speed":cur.get("wind_speed_10m"),
            "wind_direction":cur.get("wind_direction_10m"),
            "weather_code":cur.get("weather_code"),
            "sea_temperature":sea_temp,
            "time":cur.get("time"),
        }
        with _WEATHER_LOCK:
            _WEATHER_CACHE[cache_key]={"at":time.time(),"data":data}
        return data
    except Exception as e:
        # Keep stale data if the internet/API is temporarily unavailable.
        with _WEATHER_LOCK:
            stale=(_WEATHER_CACHE.get(cache_key) or {}).get("data")
        if stale:
            x=dict(stale); x["stale"]=True; x["error"]=str(e); return x
        return {"ok":False,"location":name,"error":str(e)}

class Handler(SimpleHTTPRequestHandler):
    def log_message(self, fmt,*args): pass
    def do_GET(self):
        cfg=load_config()
        if self.path.startswith("/api/weather"):
            payload=json.dumps(weather_state(cfg),ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type","application/json; charset=utf-8")
            self.send_header("Content-Length",str(len(payload)))
            self.send_header("Cache-Control","no-store")
            self.end_headers()
            self.wfile.write(payload)
            return
        if self.path.startswith("/api/heartbeat"):
            browser_heartbeat()
            payload=b'{"ok":true}'
            self.send_response(200)
            self.send_header("Content-Type","application/json; charset=utf-8")
            self.send_header("Content-Length",str(len(payload)))
            self.send_header("Cache-Control","no-store")
            self.end_headers()
            self.wfile.write(payload)
            return
        if self.path.startswith("/api/audio"):
            payload=json.dumps(audio_state(), ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type","application/json; charset=utf-8")
            self.send_header("Content-Length",str(len(payload)))
            self.send_header("Cache-Control","no-store")
            self.end_headers()
            self.wfile.write(payload)
            return
        if self.path.startswith("/api/state"):
            d=cached_rb_state()
            d["scheduler"]=scheduler_state(cfg)
            d["broadcastvoice"]=bv_state(cfg)
            d["audio"]=audio_state()
            d["playlist"]=playlist_state(cfg, d.get("playback") or {}, d.get("current") or {})
            b=json.dumps(d,ensure_ascii=False).encode("utf-8")
            self.send_response(200); self.send_header("Content-Type","application/json; charset=utf-8"); self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(b))); self.end_headers(); self.wfile.write(b); return
        if self.path.startswith("/api/artwork/"):
            action="trackartwork" if self.path.endswith("/current") else "nexttrackartwork"
            try:
                b=fetch_bytes(rb_url(cfg,action))
                self.send_response(200); self.send_header("Content-Type","image/jpeg"); self.send_header("Cache-Control","no-store"); self.send_header("Content-Length",str(len(b))); self.end_headers(); self.wfile.write(b)
            except:
                self.send_response(404); self.end_headers()
            return
        if self.path=="/" or self.path.startswith("/?"):
            self.path="/"+HTML.name
        return super().do_GET()


def migrate_previous_config_if_needed():
    """Legacy hook retained for the optional browser backend; no implicit import."""
    return

def ensure_password(cfg):
    """The native setup dialog owns credential entry in the public edition."""
    return cfg


def _browser_watchdog(server, *, timeout_seconds=10.0):
    """Stop the bridge when the browser dashboard has been closed.

    The watchdog starts enforcing the timeout only after the dashboard has sent
    at least one heartbeat. This avoids killing the process during startup.
    A 10-second grace period also allows normal browser refreshes.
    """
    while True:
        time.sleep(2.0)
        last_seen, seen_once = browser_last_seen()
        if not seen_once:
            continue
        if (time.time() - last_seen) > timeout_seconds:
            _cleanup_pid_file()
            try:
                server.shutdown()
            except Exception:
                pass
            return

def startup_selftest():
    """Local startup construction test; does not contact RadioBOSS."""
    cfg=load_config()
    port=int(cfg.get("monitor_port",8765))
    test_server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
    test_server.server_close()
    print("SELFTEST OK")
    print("Configured monitor port:",port)
    return 0

def main():
    try:
        PID_FILE.write_text(str(os.getpid()), encoding="ascii")
    except Exception:
        pass
    atexit.register(_cleanup_pid_file)
    os.chdir(BASE)
    migrate_previous_config_if_needed()
    cfg=load_config()
    cfg=ensure_password(cfg)
    port=int(cfg.get("monitor_port",8765))
    url=f"http://127.0.0.1:{port}/"
    # First RadioBOSS request happens immediately at startup.
    global _STATE_CACHE
    _STATE_CACHE = rb_state(cfg)
    threading.Thread(target=update_state_cache, daemon=True, name="RadioBOSS-Poller").start()
    threading.Thread(target=_audio_meter_worker, daemon=True, name="Windows-Audio-Meter").start()
    server=ThreadingHTTPServer(("127.0.0.1",port),Handler)
    threading.Thread(
        target=_browser_watchdog,
        args=(server,),
        kwargs={"timeout_seconds":6.0},
        daemon=True,
        name="Browser-Heartbeat-Watchdog",
    ).start()
    print("="*68)
    print("RadioBOSS Studio Monitor v1.0.11")
    print("="*68)
    print("Studio Monitor:",url)
    print(f'RadioBOSS API : {cfg["radioboss_host"]}:{cfg["radioboss_port"]}')
    print("Press Ctrl+C to stop.")
    print()
    try:
        import webbrowser
        threading.Timer(.8,lambda:webbrowser.open(url)).start()
    except: pass
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        try:
            server.shutdown()
        except Exception:
            pass
        try:
            server.server_close()
        except Exception:
            pass
        _cleanup_pid_file()

if __name__=="__main__":
    try:
        if "--selftest" in sys.argv:
            raise SystemExit(startup_selftest())
        main()
    except SystemExit:
        raise
    except BaseException as exc:
        try:
            import traceback
            with BOOT_LOG.open("a", encoding="utf-8") as _f:
                _f.write("FATAL: " + repr(exc) + "\n")
                traceback.print_exc(file=_f)
        except Exception:
            pass
        raise
