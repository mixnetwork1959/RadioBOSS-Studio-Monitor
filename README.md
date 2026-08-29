# RadioBOSS Studio Monitor v1.0.1

RadioBOSS Studio Monitor is a portable Windows dashboard for one local RadioBOSS installation. It displays the current and next track, remaining time, artwork, current-hour playlist, studio clock, optional weather, optional RadioBOSS Scheduler information, optional BroadcastVoice status and Windows output-level meters.

This public edition contains no station-specific settings, passwords, logs or media.

## Highlights

- First-run setup inside the application
- One local station per Studio Monitor installation
- Separate installations can be used on separate RadioBOSS computers
- RadioBOSS `playbackinfo` and `getplaylist2` support with compatibility fallback
- Current/next artwork from the RadioBOSS API
- Responsive dashboard with scroll support for smaller displays
- Selectable dark and light interface themes
- RadioBOSS and weather requests run separately, with watchdog recovery
- Optional Open-Meteo weather and sea-surface temperature
- Optional read-only Scheduler and BroadcastVoice panels
- Animated VU meters and a redesigned SL-1210-style turntable
- RadioBOSS passwords protected with Windows DPAPI for the current Windows user

## RadioBOSS preparation

1. In RadioBOSS, open **Settings > Options > Remote Control API**.
2. Enable the API.
3. Select a port, for example `9000`.
4. Set an API password or create a Remote API user.
5. Allow access only from the local computer or a trusted local network.

Do not expose the RadioBOSS Remote Control API directly to the public internet.

## First start

1. Place `RadioBOSS-Studio-Monitor.exe` in a writable folder.
2. Start the EXE.
3. Enter a station name, RadioBOSS host, port and credentials.
4. Use **Test RadioBOSS connection**.
5. Configure weather and optional integrations if wanted.
6. Press **Save**.

The application creates `studio_monitor_config.json` beside the EXE. The password is stored as a Windows-protected value, not as readable text. The protected password can only be opened by the same Windows user account.

## Settings

Use the **SETTINGS** button inside the monitor to edit the theme, local station, weather, refresh speed and optional integrations. Scheduler and BroadcastVoice paths belong to this local installation and can be selected with **Browse**. Choose **Dark** or **Light** under **General**; the saved theme is applied after closing Settings.

Weather is disabled by default. Weather data is supplied by Open-Meteo; users are responsible for complying with the provider's current usage and licensing terms.

## Build the Windows EXE

Requirements:

- Windows 10 or Windows 11
- Python 3.11 or newer
- Internet access while installing Python packages

Run:

```text
BUILD-EXE.bat
```

The script installs the required packages, runs the self-test, builds the portable EXE and creates:

```text
RadioBOSS-Studio-Monitor-v1.0.1-Windows.zip
```

The generated public ZIP contains only the EXE, README and notice. It deliberately excludes configuration and log files.

### Changes in v1.0.1

- redrawn SL-1200/1210-style tonearm based on a real top-view reference
- counterweight aligned with the rear arm shaft
- flatter, mechanically continuous S-curve
- headshell, cartridge and stylus aligned with the record groove
- latitude and longitude can be typed or pasted with a decimal point or comma
- Save keeps the normal Settings window open; Close returns to the dashboard
- Browse buttons for Scheduler and BroadcastVoice integration paths
- integrations are configured for the one local station handled by this installation
- selectable Dark and Light themes under General settings

## Run from source

Install dependencies and start the application:

```text
py -m pip install -r requirements.txt
START-SOURCE.bat
```

Run the offline automated checks with `RUN-TESTS.bat`. Use `Test RadioBOSS API.bat` for a live connection diagnostic after completing setup.

## Optional integrations

- **Scheduler:** enter the path to RadioBOSS `Admin.sdl` or an exported scheduler JSON file.
- **BroadcastVoice:** enter the BroadcastVoice directory or a compatible status JSON file.
- **Audio meters:** require `pycaw` and `comtypes`; the public EXE build includes them.

All Scheduler and BroadcastVoice access is read-only.

## Privacy and security

- No credentials are included in this package.
- Passwords are never written to logs.
- Diagnostic output reports only whether a password was loaded.
- Station configuration remains local beside the EXE.
- Delete `studio_monitor_config.json` to reset the setup.

## Project status

This is the first neutral public build derived from the original private Studio Monitor. Test the Windows EXE with a non-production RadioBOSS installation before publishing it broadly.

No open-source licence has been selected yet; the repository is public for source review and development.

RadioBOSS is a trademark of DJSoft.net. This independent community project is not affiliated with or supported by DJSoft.net.
