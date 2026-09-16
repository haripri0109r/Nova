# Phase 5.8-F: Windows Power, Battery & Energy Management

## Overview

Nova provides direct, native control and inspection of Windows power telemetry, active power schemes, display/sleep timeouts, energy saver status, and hibernation.

Nova interacts with Windows via `kernel32.GetSystemPowerStatus`, Win32 Power APIs (`powrprof.dll`), and fixed `powercfg.exe` parameter invocations. All mutations are strictly read-back verified, and non-elevated restricted settings report honest status with deep links to Windows Settings (`ms-settings:powersleep`).

---

## Ownership Boundary

`PowerSkill` owns strictly:
- Battery telemetry (percentage, charging state, AC status, remaining run time).
- Active power scheme discovery and dynamic OEM enumeration.
- Power scheme switching with read-back verification.
- Display and sleep timeout inspection and mutation.
- Battery saver / Energy saver status query.
- System hibernation (capability check and controlled invocation).

**What PowerSkill does NOT own**:
- Sleep, shutdown, restart, and workstation lock are owned by their existing dedicated skills (`SleepSkill`, `ShutdownSkill`, `RestartSkill`, `LockSkill`) and remain completely untouched.

---

## Canonical Skill: `PowerSkill`

- **Class**: `PowerSkill(BaseSkill)` (`src/nova/skills/system/power.py`)
- **Canonical Intent**: `power`
- **Aliases**: `power_control`, `battery`, `hibernate`
- **Supported Actions**:
  1. `get_battery_status` — Query battery %, charging state, AC power, and remaining lifetime.
  2. `get_power_scheme` — Query the current active Windows power plan and enumerate all available schemes (including OEM plans).
  3. `set_power_scheme` — Switch the active Windows power plan dynamically by name.
  4. `get_timeouts` — Query display and sleep idle timeouts for AC and DC power.
  5. `set_timeout` — Set display or sleep idle timeout for AC, DC, or both.
  6. `get_battery_saver` — Query current battery saver / energy saver status.
  7. `hibernate` — Hibernate the computer via `C:\Windows\System32\shutdown.exe /h`.

---

## Parameter Schema

The skill enforces a strict JSON Schema (`additionalProperties: False`):

```json
{
  "type": "object",
  "properties": {
    "action": {
      "type": "string",
      "enum": [
        "get_battery_status",
        "get_power_scheme",
        "set_power_scheme",
        "get_timeouts",
        "set_timeout",
        "get_battery_saver",
        "hibernate"
      ],
      "description": "Power or battery management action."
    },
    "scheme": {
      "type": "string",
      "description": "Name or keyword of power scheme (e.g., 'balanced', 'high performance', 'turbo', 'silent'). Dynamically resolved; GUIDs not accepted."
    },
    "target": {
      "type": "string",
      "enum": ["display", "sleep"],
      "description": "Target setting for timeout adjustment."
    },
    "minutes": {
      "type": "integer",
      "minimum": 0,
      "maximum": 1440,
      "description": "Timeout in minutes (0 means never)."
    },
    "source": {
      "type": "string",
      "enum": ["ac", "dc", "both"],
      "description": "Power source to apply timeout to (default: both)."
    }
  },
  "required": ["action"],
  "additionalProperties": false
}
```

---

## Windows APIs and Mechanisms

### 1. Battery Telemetry
- **API**: `kernel32.GetSystemPowerStatus(LPSYSTEM_POWER_STATUS lpSystemPowerStatus)`
- **Execution Speed**: Sub-millisecond (< 0.2ms).
- **Truthful Status Handling**:
  - `ACLineStatus`: `1` (AC online), `0` (AC offline / on battery), `255` (Unknown).
  - `BatteryFlag`: `128` (No battery / desktop), `8` (Charging), `255` (Unknown).
  - `BatteryLifePercent`: `0..100`, or `255` (Unknown / desktop).
  - `SystemStatusFlag`: `1` (Battery saver active), `0` (Battery saver inactive).
  - `BatteryLifeTime`: Remaining seconds on battery, or `-1` (charging / desktop).

### 2. Power Schemes
- **Enumeration**: `PowerEnumerate` (`ACCESS_SCHEME`) + `PowerReadFriendlyName` (`powrprof.dll`).
- **Active Query**: `PowerGetActiveScheme` + `PowerReadFriendlyName`.
- **Dynamic Resolution**:
  - No hardcoded GUIDs. Windows systems often have OEM-specific power plans (e.g. ASUS `Turbo`, `Silent`, `Performance`, Lenovo `Quiet`, `Extreme`).
  - Nova matches the requested scheme name case-insensitively against all enumerated schemes on the machine.
  - LLM and user cannot supply arbitrary GUIDs directly.
- **Switching**:
  - Native call: `PowerSetActiveScheme(NULL, &guid)`.
  - Fallback: `powercfg.exe /setactive <validated_guid>`.
  - Read-back verification: Confirms `PowerGetActiveScheme` matches the target GUID before reporting success.
  - Restriction: On modern Windows 11 under standard user permissions, returns `status="restricted"` with `ms-settings:powersleep`.

### 3. Display and Sleep Timeouts
- **Query**: `powercfg.exe /query SCHEME_CURRENT SUB_VIDEO VIDEOIDLE` and `powercfg.exe /query SCHEME_CURRENT SUB_SLEEP STANDBYIDLE`.
- **Setting**:
  - `powercfg.exe /change monitor-timeout-ac <minutes>`
  - `powercfg.exe /change monitor-timeout-dc <minutes>`
  - `powercfg.exe /change standby-timeout-ac <minutes>`
  - `powercfg.exe /change standby-timeout-dc <minutes>`
- **Security**:
  - Fixed argument lists passed to `subprocess.run()`.
  - `shell=True` is strictly forbidden.
  - Strict input validation: `minutes` must be `0..1440` (0 = never).
- **Read-Back Verification**:
  - After running `/change`, Nova re-queries powercfg to verify the value actually changed.
  - If Windows denies changing the timeout (non-elevated), reports `status="restricted"` with `ms-settings:powersleep`. Never reports fake success.

### 4. Hibernation
- **Capability Check**: `GetPwrCapabilities` (`SystemBatteriesPresent` / `HiberFilePresent`) or `powercfg /a`.
- **Execution**: `C:\Windows\System32\shutdown.exe /h`.
- **Risk Level**: Classified as `RiskLevel.HIGH` in `StepRiskPolicy`.
- **Confirmation Gating**:
  - Required confirmation via `ConfirmationManager`.
  - Cannot be bypassed by planner fast-paths or LLM DAG generation.

---

## Desktop vs Laptop Differences

| Feature | Laptop | Desktop |
| :--- | :--- | :--- |
| **Battery Level** | Real percentage (0-100%) | `None` (`has_battery: false`) |
| **Charging State** | True when plugged into AC | False (no battery to charge) |
| **AC Power** | True when plugged in, False on battery | True (mains power) |
| **Battery Saver** | Reflects active battery saver state | False |
| **DC Timeouts** | Independent DC battery timeouts | Mirrored or N/A |

---

## Brain & Natural Language Routing

### IntentCategory.POWER
Routing rules in `intent_classifier.py`:
- Battery questions: `"what is my battery"`, `"how much battery do I have"`, `"am I charging"` -> `action: get_battery_status`.
- Power scheme questions: `"what power plan am I using"`, `"current power mode"` -> `action: get_power_scheme`.
- Power scheme changes: `"switch to high performance"`, `"change to turbo mode"` -> `action: set_power_scheme, scheme: ...`.
- Timeout queries: `"when does screen turn off"`, `"sleep timeout"` -> `action: get_timeouts`.
- Timeout changes: `"turn off display after 10 minutes"` -> `action: set_timeout, target: display, minutes: 10`.
- Battery saver queries: `"is battery saver on"`, `"energy saver status"` -> `action: get_battery_saver`.
- Hibernate requests: `"hibernate computer"`, `"hibernate pc"` -> `action: hibernate`.

### Anti-Greedy Protections
- `"put my computer to sleep"` -> `IntentCategory.SLEEP` (SleepSkill).
- `"turn off my PC"` -> `IntentCategory.SHUTDOWN` (ShutdownSkill).
- `"restart the computer"` -> `IntentCategory.RESTART` (RestartSkill).
- `"open battery settings"` -> `IntentCategory.OPEN_SETTINGS` (SettingsSkill).
- `"dim the screen"` -> `IntentCategory.SET_BRIGHTNESS` (DisplaySkill).
