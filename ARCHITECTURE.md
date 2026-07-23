# ARCHITECTURE.md — Nova Analysis

## 1. Function Table

| Function | Line Range | Purpose | Inputs | Outputs / Side Effects | Category |
|----------|------------|---------|--------|------------------------|----------|
| `block_samples` | 117–119 | Compute block size in samples from `SAMPLE_RATE` and `BLOCK_MS` | None | `int` samples per block | audio-input |
| `rms_mono` | 122–129 | Compute RMS amplitude of a mono or stereo audio block | `np.ndarray` block | `float` RMS value | clap-detection-dsp |
| `_input_devices` | 132–137 | Enumerate available input audio devices | None | `list[tuple[int, dict]]` of (index, device_info) | audio-input |
| `_resolve_input_device_index` | 140–150 | Resolve device spec (index or name substring) to device index | `str` spec | `int` device index | audio-input |
| `_probe_input_max_rms` | 153–169 | Probe a device for peak RMS over `INPUT_PROBE_S` seconds | `int` device, `int` blocksize | `float\|None` peak RMS or `None` on error | audio-input |
| `_choose_input_device` | 172–246 | Select input device: env override → default mic probe → auto-scan loudest | `int` blocksize | `int` selected device index | audio-input |
| `_elevenlabs_pcm_sample_rate` | 249–258 | Derive PCM sample rate from ElevenLabs output_format or env override | `str` output_format | `int` sample rate | tts |
| `elevenlabs_env_config` | 261–267 | Read ElevenLabs config from env vars (voice, model, format, rate) | None | `tuple[voice_id, model_id, output_format, pcm_rate]` | tts |
| `_NOVA_welcome_cache_dir` | 270–275 | Resolve cache directory for ElevenLabs WAV cache (env override or `.cache/NOVA_welcome`) | None | `Path` cache directory | tts / config |
| `_NOVA_welcome_cache_path` | 278–283 | Compute deterministic cache file path from text/voice/model/format hash | `str` text, voice_id, model_id, output_format | `Path` cache file path | tts / config |
| `_play_pcm_wav_file` | 286–309 | Play a mono 16-bit PCM WAV file via `sounddevice` | `Path` wav path | `bool` success | tts |
| `_save_pcm_wav_file` | 312–325 | Atomically write mono 16-bit PCM bytes to WAV file | `Path` path, `bytes` pcm, `int` sample_rate | `None` (writes file) | tts |
| `say_NOVA_welcome` | 328–381 | Speak welcome phrase via ElevenLabs TTS with WAV caching; plays async in thread | None | `None` (plays audio, spawns thread) | tts |
| `play_song` | 383–393 | Open `SONG_URI` via `os.startfile` (Windows) or `webbrowser.open` (else) | `str` uri | `None` (opens browser/Spotify) | spotify |
| `_chrome_executable` | 396–408 | Locate Chrome executable on Windows (Program Files, LocalAppData) or PATH | None | `str\|None` chrome path | chrome-automation |
| `_win32_sorted_monitor_rects` | 411–442 | Enumerate monitors via `EnumDisplayMonitors`, return sorted (L,T,R,B) rects | None | `list[tuple[int,int,int,int]]` | chrome-automation / win32 |
| `_chrome_monitor_top_left` | 445–448 | Get top-left corner of monitor N (1-based) | `int` 1-based index | `tuple[int,int]` (left, top) | chrome-automation / win32 |
| `_chrome_monitor_bounds` | 451–466 | Get monitor bounds (L,T,R,B) for monitor N (1-based, clamped) | `int` 1-based index | `tuple[int,int,int,int]` | chrome-automation / win32 |
| `_chrome_monitor_pixel_size` | 469–471 | Get monitor pixel width/height for monitor N | `int` 1-based index | `tuple[int,int]` (w, h) | chrome-automation / win32 |
| `_chrome_window_size` | 474–480 | Read `CHROME_WINDOW_WIDTH`/`CHROME_WINDOW_HEIGHT` env or default 1400×900 | None | `tuple[int,int]` | chrome-automation / config |
| `_chrome_site_user_data_dir` | 483–486 | Create temp user-data-dir under `%TEMP%/clap-trigger-chrome/<site_key>` | `str` site_key | `str` path | chrome-automation / config |
| `_chrome_new_window_wait_timeout_s` | 489–493 | Read `CHROME_NEW_WINDOW_WAIT_S` env or default 25s | None | `float` timeout seconds | chrome-automation / config |
| `_chrome_top_level_browser_hwnds_win32` | 496–544 | Enumerate top-level Chrome browser HWNDs via `EnumWindows` + process check | None | `set[int]` HWNDs | chrome-automation / win32 |
| `_wait_new_chrome_hwnd_win32` | 547–570 | Poll for new Chrome HWND after launch, return largest new window | `set[int]` before_set, `float` timeout | `int\|None` new HWND | chrome-automation / win32 |
| `_chrome_snap_window_to_monitor_win32` | 573–617 | Move/resize Chrome HWND to monitor N, optionally fullscreen via F11 | `int` hwnd, `int` monitor, `bool` fullscreen, `tuple\|None` windowed_size | `None` (moves window, sends F11) | chrome-automation / win32 |
| `_open_url_in_chrome` | 619–684 | Launch Chrome with URL, window positioning, fullscreen, user-data-dir, win32 snap | `str` url, `bool` new_window, `str` label, `tuple\|None` pos, `tuple\|None` size, `bool` fullscreen, `int\|None` win32_monitor, `str\|None` user_data_dir | `None` (launches process) | chrome-automation |
| `open_claude_in_chrome` | 687–718 | Open `CLAUDE_CODE_URL` (env or default) in Chrome on `CLAUDE_CHROME_MONITOR` | None | `None` (launches Chrome) | chrome-automation |
| `open_binance_btc_in_chrome` | 721–755 | Open `BINANCE_BTC_URL` (env or default) in Chrome on `BINANCE_CHROME_MONITOR` | None | `None` (launches Chrome) | chrome-automation |
| `_cursor_executable` | 758–766 | Locate Cursor executable (Windows LocalAppData or PATH) | None | `str\|None` path | cursor-automation |
| `_cursor_largest_main_hwnd_win32` | 769–821 | Find largest visible Cursor.exe HWND via `EnumWindows` + process check | None | `int\|None` HWND | cursor-automation / win32 |
| `_cursor_foreground_hwnd_win32` | 824–838 | Bring Cursor HWND to foreground with thread input attachment | `int` hwnd | `None` (sets foreground) | cursor-automation / win32 |
| `_cursor_send_f11_fullscreen_win32` | 841–851 | Send F11 key to Cursor HWND to toggle fullscreen | `int` hwnd | `None` (sends keystroke) | cursor-automation / win32 |
| `_focus_existing_cursor_window_win32` | 854–862 | Find and foreground existing Cursor window (Windows only) | None | `bool` success | cursor-automation / win32 |
| `run_double_clap_actions` | 865–875 | Orchestrate full double-clap sequence: song, Chrome tabs, TTS (thread), Cursor | None | `None` (spawns thread for TTS, launches apps) | main-loop |
| `open_cursor_window` | 878–912 | Focus existing Cursor or launch new; optionally send F11 for fullscreen (Win32) | None | `None` (launches/focuses Cursor) | cursor-automation |
| `main` | 915–1047 | Main loop: device select → audio stream → RMS loop → double-clap detection → spawn actions | None | `int` exit code | main-loop |

---

## 2. Hardcoded Values That Should Be Configuration

**Audio / DSP (lines 60–74):**
- `SAMPLE_RATE = 44100`, `BLOCK_MS = 40`, `CHANNELS = 1`
- `SPIKE_RATIO = 7.0`, `COOLDOWN_S = 0.45`, `MIN_DOUBLE_GAP_S = 0.05`, `MAX_DOUBLE_GAP_S = 0.35`
- `RETRIGGER_RATIO = 0.55`, `NOISE_FLOOR_ALPHA = 0.992`, `MIN_RMS = 0.012`, `QUIET_GATE_MULT = 2.2`
- `INPUT_PROBE_S = 0.5`, `INPUT_SILENT_RMS = 0.001`

**Spotify (line 78):**
- `SONG_URI = "https://open.spotify.com/track/39shmbIHICJ2Wxnk1fPSdz?si=2900c75c2e2d4b82"`

**Cursor (lines 81–83):**
- `FOCUS_EXISTING_CURSOR_ON_DOUBLE_CLAP = True`, `OPEN_NEW_CURSOR_ON_DOUBLE_CLAP = False`, `CURSOR_OPEN_FULLSCREEN = True`

**Chrome (lines 86–93):**
- `OPEN_CLAUDE_CODE_IN_CHROME = True`, `OPEN_BINANCE_BTC_IN_CHROME = True`, `OPEN_CHROME_FULLSCREEN = True`
- `CHROME_SEPARATE_SITE_PROFILES = False`
- `CLAUDE_CHROME_MONITOR = 1`, `BINANCE_CHROME_MONITOR = 3` (1-based monitor indices, Windows sort order)

**Chrome window sizing (lines 475–480, 489–493):**
- Default window size `1400×900` via `CHROME_WINDOW_WIDTH`/`CHROME_WINDOW_HEIGHT`
- New-window wait timeout default `25s` via `CHROME_NEW_WINDOW_WAIT_S`

**ElevenLabs TTS (lines 95–105):**
- `NOVA_WELCOME_ENABLED = True`
- `NOVA_WELCOME_PHRASE = "Welcome home sir. Congratulations on the new client..."` (lines 96–101)
- `NOVA_AFTER_SONG_DELAY_S = 1.0`
- `NOVA_WELCOME_CACHE_ENABLED = True`

**Environment-variable defaults baked in code:**
- `ELEVENLABS_MODEL_ID` default `"eleven_multilingual_v2"` (line 264)
- `ELEVENLABS_OUTPUT_FORMAT` default `"pcm_24000"` (line 265)
- `CLAUDE_CODE_URL` default `"https://claude.ai/new"` (line 690)
- `BINANCE_BTC_URL` default `"https://www.binance.com/en/trade/BTC_USDT"` (line 726)
- `NOVA_WELCOME_CACHE_DIR` default `.cache/NOVA_welcome` (line 274)
- `NOVA_INPUT_DEVICE` env override for mic selection (line 175)

**File paths:**
- Cache dir hardcoded to `.cache/NOVA_welcome` relative to script (line 274)
- Chrome temp profile dir hardcoded to `%TEMP%/clap-trigger-chrome/<site>` (line 484)
- Cursor exe search paths hardcoded to `%LOCALAPPDATA%/Programs/cursor/Cursor.exe` and `.../Cursor/Cursor.exe` (lines 760–765)

---

## 3. Windows-Specific Assumptions & Fallbacks

| Location | Windows-Specific Code | Non-Windows Fallback |
|----------|----------------------|---------------------|
| `play_song` (388–391) | `os.startfile(uri)` | `webbrowser.open(uri)` |
| `_chrome_executable` (397–408) | Searches `ProgramFiles`, `ProgramFiles(x86)`, `LOCALAPPDATA` for `chrome.exe` | Falls back to `shutil.which("google-chrome")` / `shutil.which("chrome")` |
| `_win32_sorted_monitor_rects` (411–442) | `ctypes.windll.user32.EnumDisplayMonitors` + `RECT` struct | Returns `[]` (empty list) on non-Windows |
| `_chrome_monitor_*` (445–471) | Call `_win32_sorted_monitor_rects` | Return fallback `(0,0,1920,1080)` or last monitor |
| `_chrome_top_level_browser_hwnds_win32` (496–544) | Full `EnumWindows` + `OpenProcess` + `QueryFullProcessImageNameW` to filter `chrome.exe` | Not called on non-Windows (guarded by `sys.platform == "win32"`) |
| `_wait_new_chrome_hwnd_win32` (547–570) | Polls Win32 HWNDs | Only called on Windows |
| `_chrome_snap_window_to_monitor_win32` (573–617) | `SetWindowPos`, `ShowWindow`, `AttachThreadInput`, `SetForegroundWindow`, `keybd_event(VK_F11)` | Not called on non-Windows; Chrome launched with `--start-fullscreen` instead |
| `_open_url_in_chrome` (619–684) | Win32 HWND detection + snap if `win32_post_fullscreen_monitor` set | Launches Chrome with `--start-fullscreen` flag; no positioning |
| `_cursor_executable` (758–766) | Searches `%LOCALAPPDATA%/Programs/cursor/Cursor.exe` and `.../Cursor/Cursor.exe` | Falls back to `shutil.which("cursor")` |
| `_cursor_largest_main_hwnd_win32` (769–821) | `EnumWindows` + process image name check for `cursor.exe` | Returns `None` on non-Windows |
| `_cursor_foreground_hwnd_win32` (824–838) | `ShowWindow`, `AttachThreadInput`, `SetForegroundWindow` | Not called on non-Windows |
| `_cursor_send_f11_fullscreen_win32` (841–851) | `keybd_event(VK_F11)` | Not called on non-Windows |
| `_focus_existing_cursor_window_win32` (854–862) | Calls Win32 helpers above | Returns `False` on non-Windows |
| `open_cursor_window` (906–910) | Calls `_cursor_send_f11_fullscreen_win32` after 0.5s sleep | No fullscreen toggle on non-Windows |
| `main` (944, 977) | Logs Windows-specific Cursor/Chrome monitor actions | Logs only generic actions on non-Windows |

**Summary:** The script is **Windows-first**. All window management (monitor placement, fullscreen via F11, foreground focus) uses `ctypes.windll.user32`/`kernel32`. On non-Windows, Chrome falls back to `--start-fullscreen` flag (no monitor targeting), Cursor launches without fullscreen toggle, and Spotify/URLs open via `webbrowser.open`. No cross-platform window manager abstraction exists.

---

## 4. Risks

**Silent Failures**
- `_probe_input_max_rms` returns `None` on `PortAudioError`; `_choose_input_device` logs warning but continues with potentially silent device (lines 168, 186–195).
- `_wait_new_chrome_hwnd_win32` times out after 25s (configurable) and only logs a warning; sequence continues without the window (lines 574–579).
- `_focus_existing_cursor_window_win32` returns `False` silently if no Cursor window found; falls back to launching new instance (line 860).
- `say_NOVA_welcome` catches all exceptions from ElevenLabs and `sounddevice.play`, logs warning, returns silently (lines 362–380). Cache read failure falls back to API call silently (line 342).
- `play_song` catches `OSError` and only logs warning (line 392–393).
- `open_cursor_window` catches `OSError` on `Popen` and logs warning (lines 903–905).

**Secret Leakage**
- `ELEVENLABS_API_KEY` read from env and passed to `ElevenLabs(client)`; logged only as `(unset)` if missing (line 371). No logging of the key itself, but any exception traceback could leak it if `log.warning` includes exception repr (line 363).
- `.env` file loaded via `load_dotenv` at module level (line 107); if committed, secrets leak. `.gitignore` should exclude `.env`.

**Machine-Specific Assumptions**
- Monitor indices `CLAUDE_CHROME_MONITOR = 1`, `BINANCE_CHROME_MONITOR = 3` assume ≥3 monitors sorted left-to-right/top-to-bottom (lines 92–93). On different monitor counts/arrangements, windows open on wrong screen or fall back to last monitor with warning (lines 460–465).
- Chrome executable search paths hardcoded to standard Windows install locations (lines 398–407). Portable/non-standard installs missed.
- Cursor executable search assumes `%LOCALAPPDATA%/Programs/cursor/Cursor.exe` or `.../Cursor/Cursor.exe` (lines 760–765). Other install paths (e.g., `%USERPROFILE%/AppData/Local/Programs/Cursor/`) not checked.
- Chrome user-data-dir uses `%TEMP%/clap-trigger-chrome/<site>` (line 484). Temp dir cleared on reboot; profiles not persisted.
- `CHROME_NEW_WINDOW_WAIT_S` default 25s may be too short on slow machines; too long on fast ones (line 491).
- Audio device selection probes default mic for 0.5s at `INPUT_SILENT_RMS = 0.001` threshold (lines 73–74, 202). May misclassify quiet but valid mics.
- `SAMPLE_RATE = 44100` hardcoded; some devices only support 48000 (line 60). `PortAudioError` caught in `main` with suggestion (line 1043–1044).
- Double-clap timing constants (`MIN_DOUBLE_GAP_S = 0.05`, `MAX_DOUBLE_GAP_S = 0.35`, `COOLDOWN_S = 0.45`) tuned for author's clap style; may false-trigger or miss on different acoustics (lines 66–67, 65).

**Concurrency / Race Conditions**
- `run_double_clap_actions` spawns `say_NOVA_welcome` in a daemon thread (line 874) while launching Chrome/Cursor in main thread. No synchronization; TTS may play while windows still opening.
- `welcome_sequence_done` flag prevents re-trigger within same process (line 921, 1023), but script restart re-arms it.
- Audio callback runs in `sounddevice` callback thread; DSP logic runs inline in `main` loop (lines 987–1037). Blocking calls (`time.sleep` in `run_double_clap_actions` line 873) run in separate thread, so audio loop not stalled.

**Resource Leaks**
- `_chrome_top_level_browser_hwnd_win32` opens process handles via `OpenProcess` and closes in `finally` (lines 521, 531). Exception between open and close could leak (unlikely but possible).
- `subprocess.Popen` calls use `DEVNULL` for stdin/out/err; child processes detached but not tracked (lines 652–659, 887–891, 900, 902).
- WAV cache files accumulate in `.cache/NOVA_welcome/` indefinitely (line 370); no TTL or size limit.

**Portability**
- No macOS/Linux window management (no `wmctrl`, `xdotool`, AppleScript fallbacks).
- `os.startfile` only on Windows; `webbrowser.open` used elsewhere but may not open Spotify URI correctly on Linux/macOS without `xdg-open`/`open` handling Spotify protocol.
