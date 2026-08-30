from __future__ import annotations

from pathlib import Path
import sys

BASE=Path(__file__).resolve().parent
sys.path.insert(0,str(BASE))

import studio_monitor_backend as backend


print("="*68)
print("RadioBOSS API Diagnostics - Studio Monitor v1.0.11")
print("="*68)
print("Configuration:",backend.CONFIG)

document=backend.load_public_config()
error=str(document.get("_config_error") or "")
if error:
    print("Configuration: ERROR")
    print(error)
    input("\nPress Enter to exit...")
    raise SystemExit(1)

stations=document.get("stations") or []
print("Station profiles:",len(stations))
failures=0
for index,station in enumerate(stations,1):
    station_id=str(station.get("id") or "")
    cfg=backend.runtime_config_from_document(document,station_id)
    print()
    print(f"[{index}] {station.get('name') or station_id}")
    print("Host/Port:",f"{cfg.get('radioboss_host')}:{cfg.get('radioboss_port')}")
    print("API user:",cfg.get("radioboss_user") or "(global API password)")
    print("Password loaded:","YES" if cfg.get("radioboss_password") else "NO")
    result=backend.rb_state(cfg)
    if result.get("connected"):
        current=result.get("current") or {}
        now=" - ".join(x for x in (current.get("artist"),current.get("title")) if x)
        print("RESULT: Connection successful")
        if now:print("Current:",now)
    else:
        failures+=1
        print("RESULT: Connection failed")
        print("Reason:",result.get("error") or "Unknown error")

print()
print("Diagnostics complete.","All stations connected." if failures==0 else f"Failed: {failures}")
input("\nPress Enter to exit...")
