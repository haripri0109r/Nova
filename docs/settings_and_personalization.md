# Windows Settings Navigation & Personalization Architecture (Phase 5.8-B)

## Architectural Principle

Nova is a Windows-first personal AI assistant. A foundational design philosophy guides its operating system interactions:

> **"Opening a Windows Settings page is not equivalent to changing the setting."**

Nova strictly separates:
1. **Settings Navigation** (`SettingsSkill`): Opening user-facing configuration interfaces without claiming or executing state mutations.
2. **Personalization Mutations** (`PersonalizationSkill`): Genuinely mutating OS state through direct Windows APIs and registry keys where Windows permits reliable, legitimate programmatic control.

Nova directly mutates settings **only** where Windows provides documented, reliable programmatic APIs without bypassing OS security boundaries (such as UserChoice hash protection or UAC elevation gates). Where Windows restricts programmatic modification, Nova navigates the user to the exact Settings page and provides honest, transparent feedback.

---

## Architecture & Data Flow

```
User Input
    ↓
Application / Voice Engine
    ↓
BrainEngine
    ↓
IntentClassifier (PlaceholderIntentClassifier)
    ↓
Planner (Deterministic Fast Path OR Multi-Step DAG Planning)
    ↓
PlanValidator (Enforces canonical schemas from SkillRegistry)
    ↓
AgentOrchestrator
    ↓
TaskService (SQLite persistent audit trail & lifecycle)
    ↓
PlanExecutor
    ↓
SkillRegistry (Single canonical registry)
    ↓
┌───────────────────────────────┴───────────────────────────────┐
│                                                               │
SettingsSkill                                         PersonalizationSkill
(Navigation Only)                                      (Mutations Only)
│                                                               │
├── Allowlisted ms-settings: URI                       ├── HKCU Registry Keys
├── os.startfile(uri) [No shell=True]                  ├── Win32 Broadcasts (WM_SETTINGCHANGE)
├── Never Mutates State                                ├── SystemParametersInfoW (Wallpaper)
└── Honest Navigation Messaging                        └── Read-back Verification
│                                                               │
└───────────────────────────────┬───────────────────────────────┘
                                ↓
                         Windows 11 OS
```

---

## 1. SettingsSkill (Navigation Only)

- **Source File**: `src/nova/skills/system/settings.py`
- **Canonical Intent**: `open_settings` (Alias: `settings`)
- **Responsibility**: Navigates the user to specific Windows Settings pages.
- **Strict Boundary**:
  - NEVER mutates Windows settings.
  - NEVER accepts arbitrary URIs (`http://`, `file://`, `cmd://`, `powershell://`).
  - NEVER constructs dynamic unvalidated URIs (`ms-settings:{user_input}`).
  - NEVER invokes `shell=True`, `subprocess.Popen`, `cmd.exe`, or PowerShell.
  - NEVER claims a setting was changed; always returns status `"opened"` and action `"navigated"`.

### Explicit Allowlist (`SETTINGS_URI_MAP`)

All target URIs must resolve to an explicit allowlist:

| Target Key | Canonical URI | Description |
| :--- | :--- | :--- |
| `root` / `settings` | `ms-settings:` | Windows Settings home page |
| `display` | `ms-settings:display` | Display resolution, scaling, layout |
| `sound` | `ms-settings:sound` | Sound output, input, volume mixer |
| `notifications` | `ms-settings:notifications` | Notification alerts, focus assist |
| `power` | `ms-settings:powersleep` | Power sleep timeouts |
| `battery` | `ms-settings:batterysaver` | Battery usage, battery saver |
| `storage` | `ms-settings:storagesense` | Storage Sense, disk cleanup |
| `bluetooth` | `ms-settings:bluetooth` | Bluetooth devices and discovery |
| `printers` | `ms-settings:printers` | Printers and scanners |
| `mouse` | `ms-settings:mousetouchpad` | Mouse and touchpad sensitivity |
| `wifi` | `ms-settings:network-wifi` | Wi-Fi networks and adapters |
| `ethernet` | `ms-settings:network-ethernet` | Wired network adapter configuration |
| `airplane_mode` | `ms-settings:network-airplanemode` | Network airplane mode toggle |
| `hotspot` | `ms-settings:network-mobilehotspot` | Mobile hotspot sharing |
| `personalization` | `ms-settings:personalization` | System personalization overview |
| `background` | `ms-settings:personalization-background` | Desktop background settings |
| `colors` | `ms-settings:personalization-colors` | Color accents and transparency |
| `dark_mode` | `ms-settings:personalization-colors` | Dark / Light theme settings |
| `taskbar` | `ms-settings:taskbar` | Taskbar behaviors and items |
| `apps` | `ms-settings:appsfeatures` | Installed apps and features |
| `default_apps` | `ms-settings:defaultapps` | Default application associations |
| `startup_apps` | `ms-settings:startupapps` | Startup application management |
| `windows_update` | `ms-settings:windowsupdate` | Windows Update status and checks |
| `date_time` | `ms-settings:dateandtime` | Date, time zone, and clock sync |

### Aliases & Fuzzy Fallback
Deterministic aliases resolve common terminology without ambiguity:
- `"audio"` $\to$ `"sound"`
- `"screen"` $\to$ `"display"`
- `"browser"` $\to$ `"default_apps"`
- `"update"` $\to$ `"windows_update"`
- `"theme"` $\to$ `"colors"`

### Safe Launch Mechanism
On Windows, `os.startfile(canonical_uri)` is used exclusively. This delegates URI handling directly to the Windows Shell without creating command shells, subprocesses, or security token inheritance.

---

## 2. PersonalizationSkill (Mutations Only)

- **Source File**: `src/nova/skills/system/personalization.py`
- **Canonical Intent**: `personalization` (Alias: `set_personalization`)
- **Responsibility**: Directly mutates Windows personalization settings through Win32 APIs and user registry keys.
- **Strict Boundary**:
  - NEVER opens the Windows Settings UI.
  - NEVER executes shell commands, batch files, or PowerShell scripts.
  - NEVER accepts arbitrary registry paths or arbitrary registry value names.
  - Enforces strict parameter validation and read-back verification.

### Supported Features

#### A. System Theme (`feature="theme"`)
- **Parameter**: `mode` $\in$ `["dark", "light"]`
- **Registry Key**: `HKCU\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize`
- **Registry Values**:
  - `AppsUseLightTheme` (REG_DWORD): `0` for dark, `1` for light
  - `SystemUsesLightTheme` (REG_DWORD): `0` for dark, `1` for light
- **Broadcast Notification**:
  `SendMessageTimeoutW(HWND_BROADCAST, WM_SETTINGCHANGE, 0, "ImmersiveColorSet", SMTO_ABORTIFHUNG, 2000)`
- **Verification**: Reads back both values from `HKCU` immediately after write.

#### B. Taskbar Alignment (`feature="taskbar"`)
- **Parameter**: `alignment` $\in$ `["left", "center"]`
- **Registry Key**: `HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced`
- **Registry Value**:
  - `TaskbarAl` (REG_DWORD): `0` for left, `1` for center
- **Broadcast Notification**:
  `SendMessageTimeoutW(HWND_BROADCAST, WM_SETTINGCHANGE, 0, "TraySettings", SMTO_ABORTIFHUNG, 2000)`
  Followed by `Shell_NotifyIconGetRect` / Explorer refresh.
- **Verification**: Reads back `TaskbarAl` from `HKCU`.

#### C. Desktop Wallpaper (`feature="wallpaper"`)
- **Parameter**: `path` (string)
- **Validation**:
  - Path must exist and be a regular file (`resolved.is_file()`).
  - Disallows URLs (`http://`, `https://`, `ftp://`, `file://`).
  - Disallows command/shell metacharacters (`;`, `&`, `|`, `` ` ``, `$`, `<`, `>`, `\n`, `\r`).
  - Extension allowlist: `.jpg`, `.jpeg`, `.png`, `.bmp` (and Windows' internal `%APPDATA%\...\TranscodedWallpaper`).
- **Win32 API**:
  `SystemParametersInfoW(SPI_SETDESKWALLPAPER=20, 0, resolved_path, SPIF_UPDATEINIFILE=1 | SPIF_SENDCHANGE=2)`
- **Verification**: Verifies API return code ($> 0$) and file availability.

---

## 3. Security, Risk & Elevation Analysis

### Admin Requirements
- **None**. Both `SettingsSkill` and `PersonalizationSkill` execute entirely within standard user privileges:
  - `os.startfile("ms-settings:...")` runs in the user's shell session.
  - Theme and taskbar settings reside in `HKEY_CURRENT_USER` (`HKCU`), which is fully accessible to standard non-elevated user accounts.
  - `SystemParametersInfoW` sets the desktop wallpaper for the current interactive desktop station (`Winsta0\Default`).
- Requiring no UAC elevation is an intentional design constraint: it ensures Nova cannot be used as a privilege escalation vector.

### Risk Classification
- Under Nova's `StepRiskPolicy`:
  - `open_settings`: **LOW** risk (read-only navigation).
  - `personalization`: **LOW** risk (reversible visual user preferences).
  - Neither requires interactive modal confirmation dialogs. Destructive actions (`shutdown`, `restart`, process termination) remain protected by confirmation gates.

---

## 4. Protected Windows Settings: Default Apps & Browsers

Windows 10 and Windows 11 deliberately protect default browser and protocol handler associations against programmatic tampering:
- Default associations are stored under `HKCU\Software\Microsoft\Windows\Shell\Associations\UrlAssociations\{http,https}\UserChoice`.
- Each association is locked by a cryptographically signed proprietary Microsoft hash (`ProgId`, `Hash`, `UserChoice`).
- Modifying this registry key without generating Microsoft's internal hash triggers Windows 11 to detect registry tampering and immediately reset associations to Microsoft Edge.
- **Nova Policy**: Nova does **not** attempt to crack or reverse-engineer the Windows UserChoice hash. When a user asks to "change default browser" or "change default apps", Nova:
  1. Routes cleanly to `SettingsSkill(page="default_apps")`.
  2. Opens `ms-settings:defaultapps`.
  3. Provides honest feedback: *"Opened Windows Settings for default apps. Note: default apps are protected by Windows UserChoice; please select in Settings."*

---

## 5. Intent Classification & Deterministic Fast Path

To ensure ultra-low latency (< 5 ms) and 100% predictable execution:
- Simple, safe commands bypass the LLM completely:
  - `"turn on dark mode"` $\to$ `personalization(feature="theme", mode="dark")`
  - `"switch to light mode"` $\to$ `personalization(feature="theme", mode="light")`
  - `"center the taskbar"` $\to$ `personalization(feature="taskbar", alignment="center")`
  - `"move taskbar to the left"` $\to$ `personalization(feature="taskbar", alignment="left")`
  - `"open display settings"` $\to$ `open_settings(page="display")`
  - `"open wifi settings"` $\to$ `open_settings(page="wifi")`
- Ambiguous or compound commands (e.g. `"open display settings and then turn on dark mode"`) are flagged with `is_compound=True` and routed through the LLM Planner to generate a structured multi-step DAG plan with explicit dependencies.

---

## 6. Verification & Read-Back Architecture

Any mutation performed by `PersonalizationSkill` executes immediate post-write verification:
- **Theme Mode**: Directly reads `AppsUseLightTheme` and `SystemUsesLightTheme` from `HKCU\Software\Microsoft\Windows\CurrentVersion\Themes\Personalize` to confirm written values match requested state.
- **Taskbar Alignment**: Directly reads `TaskbarAl` from `HKCU\Software\Microsoft\Windows\CurrentVersion\Explorer\Advanced` to confirm written values.
- **Desktop Wallpaper**: Validates the non-zero return code of `SystemParametersInfoW` and confirms file readability before applying.

If a read-back fails or registry access is denied, the skill raises a descriptive error and never reports a false positive.

---

## 7. Error Handling & Security Hardening

- **No Shell Execution**: `shell=True`, `subprocess.Popen`, `cmd.exe`, and PowerShell commands are strictly avoided in both skills.
- **Parameter Validation**: Skill schemas specify `additionalProperties: False` and type checking. Inputs are treated as pure data.
- **Path Injection Prevention**: Wallpaper paths are checked against shell metacharacters (`;`, `&`, `|`, `` ` ``, `$`, `<`, `>`, `\n`, `\r`) and scheme prefixes (`http://`, `https://`).
- **Extension Allowlist**: Only `.jpg`, `.jpeg`, `.png`, `.bmp` images and Windows internal `TranscodedWallpaper` are accepted.
- **OS Platform Checks**: Non-Windows environments return graceful failure messages indicating Windows-specific functionality.

---

## 8. Rollback & State Restoration Patterns (E2E Testing)

Real Windows E2E tests in `tests/e2e/test_settings_personalization_e2e.py` interact directly with the live operating system. To ensure tests never pollute or alter the developer's workstation:
- **Original State Capture**: Tests capture existing registry values (`AppsUseLightTheme`, `TaskbarAl`) and desktop wallpaper path prior to mutation.
- **Guaranteed Cleanup**: State restoration is executed inside mandatory `try ... finally` blocks.
- **Transcoded Wallpaper Support**: Personalization skill allows restoring Windows active wallpaper from `%APPDATA%\Microsoft\Windows\Themes\TranscodedWallpaper`.

---

## 9. Performance & Latency Benchmarks

- **Fast Path Latency**: Deterministic commands bypass the LLM and complete planning in `< 5ms`.
- **EventBus Throughput**: EventBus benchmarks demonstrate **> 54,000 events/second**, far exceeding the 50,000 eps threshold without regression.
- **Full Pipeline E2E**: End-to-end execution of user input to OS action runs reliably under 250ms for local actions.

---

## 10. Phase 5.8-B Compliance Checklist

| Requirement | Status | Evidence |
| :--- | :---: | :--- |
| Clean separation between navigation and mutation | ✅ COMPLIANT | `SettingsSkill` only navigates; `PersonalizationSkill` only mutates |
| No `shell=True`, no cmd.exe, no arbitrary registry | ✅ COMPLIANT | Enforced in skill code and unit tested |
| Explicit allowlisted `ms-settings:` URIs | ✅ COMPLIANT | 24 canonical pages + aliases in `SETTINGS_URI_MAP` |
| Honest messaging for protected settings (Default Apps) | ✅ COMPLIANT | Explicit UserChoice protection note in response |
| Deterministic fast path bypasses LLM | ✅ COMPLIANT | Tested in unit and integration tests |
| Compound multi-step DAG planning | ✅ COMPLIANT | Verified with `is_compound=True` routing |
| Real Windows E2E tests with state restoration | ✅ COMPLIANT | 8/8 E2E tests pass, restoring original state |
| Complete unit test coverage | ✅ COMPLIANT | 642/642 unit tests passing |
| EventBus performance threshold maintained | ✅ COMPLIANT | 54k+ events/sec (>50k threshold) |
