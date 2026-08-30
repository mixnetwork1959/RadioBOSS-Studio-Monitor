# RadioBOSS Studio Monitor v1.0.11

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
- Animated VU meters, a responsive DJ jogwheel and a playback-aware 15-second silence alarm
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
RadioBOSS-Studio-Monitor-v1.0.11-Windows.zip
```

The generated public ZIP contains only the EXE, README and notice. It deliberately excludes configuration and log files.

### Changes in v1.0.11

- removed the misleading separate BroadcastVoice status-file selector
- BroadcastVoice status is now always calculated from its selected local directory
- legacy `runtime/state.json` selections no longer bypass the full BroadcastVoice display and cause empty fields
- removed the duplicated first Scheduler event from the Upcoming Events list
- the compact Upcoming Events list now shows the two events following the highlighted Next Event

### Changes in v1.0.10

- enlarged the classic studio clock to use the full available top-row height
- enlarged both stacked weather tiles and their temperature, pressure and sea-temperature text
- vertically centred the clock and weather group to remove the remaining empty lower area
- increased the Scheduler event-card text and padding for better readability

### Changes in v1.0.9

- replaced the large digital clock with a classic studio clock and a smaller precise digital readout
- enlarged the stacked weather and Black Sea tiles
- added sea-level air pressure in hPa to the existing weather request
- added a 15-second silence monitor directly below the RadioBOSS connection status
- silence monitoring is armed only while RadioBOSS is playing and Windows audio metering is available
- a confirmed silence alarm flashes bright red and clears automatically when audio returns

### Changes in v1.0.8

- moved the weather and Black Sea displays beside the studio clock as two compact stacked tiles
- added a circular countdown to the next full hour
- the countdown turns amber during the final three minutes and flashes red during the final minute
- added compact NEXT and THEN cards for the next two Scheduler events
- all new countdown graphics are calculated locally without extra network or audio processing

### Changes in v1.0.7

- added a complete Next Track card beside the current-title information
- restored next-track artwork without repeated network requests
- current and next artwork are cached until the corresponding track changes
- long next-track titles can wrap without pushing the jogwheel out of place
- removed the temporary one-line Next Track strip

### Changes in v1.0.6

- next track is now a compact text line inside the Current Track panel
- removed the separate next-track cover and its repeated artwork request
- Current Track expands across three columns while the jogwheel keeps a sensible width
- Scheduler, upcoming events, BroadcastVoice and Hour Close share one compact right panel
- rebalanced row heights to use the reclaimed middle-row space

### Changes in v1.0.5

- taller top row gives both VU meters a natural analogue aspect ratio
- compacted middle and playlist/tools rows to reclaim unused vertical space
- weather graphic keeps its existing size
- audio-device detail is height-limited to avoid wasted space

### Changes in v1.0.4

- wider classic VU scale using nearly the complete meter face
- all scale numbers are kept inside the display
- thin face outline replaces the heavy dark housing border
- clearer red overload arc based on a traditional analogue VU meter

### Changes in v1.0.3

- jogwheel no longer catches up delayed frames with large visible jumps
- playlist rows and artwork are redrawn only when their contents change
- Windows build excludes unused PySide6 modules for a smaller, faster-starting EXE

### Changes in v1.0.2

- replaced the scale-sensitive tonearm with a responsive DJ jogwheel
- rotating cyan marker shows platter movement during playback
- outer cyan ring shows the current title progress
- progress ring blinks during the final 15 seconds of a title
- incomplete RadioBOSS position samples keep the last valid progress value

### Changes in v1.0.1

- redrawn SL-1200/1210-style tonearm based on a real top-view reference
- counterweight aligned with the rear arm shaft
- flatter, mechanically continuous S-curve
- headshell, cartridge and stylus aligned with the record groove
- latitude and longitude can be typed or pasted with a decimal point or comma
- Save keeps the normal Settings window open; Close returns to the dashboard
- Browse buttons for Scheduler and BroadcastVoice integration paths
- separate Scheduler and BroadcastVoice integration paths for every station profile
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

This is the first neutral public build derived from the original private Studio Monitor. Test the Windows EXE with a non-production RadioBOSS installation before publishing it broadly. Select a source/binary licence before the first external source-code release.

RadioBOSS is a trademark of DJSoft.net. This independent community project is not affiliated with or supported by DJSoft.net.
