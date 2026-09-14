# Phase 5.8-D: Windows Network and Bluetooth Control

## Executive Summary

Phase 5.8-D implements genuine Windows hardware and networking stack control for Nova ("Siri for Windows"). Nova controls real network interfaces and hardware radios rather than merely opening Windows Settings pages.

## Architecture

```
User Command (Voice/Text)
  │
  ▼
BrainEngine
  │
  ▼
IntentClassifier ──► IntentCategory (WIFI, BLUETOOTH, NETWORK)
  │
  ▼
Planner ───────────► Deterministic Fast-Path (Single-step safe, <10ms)
  │
  ▼
TaskService ───────► PlanExecutor
  │
  ▼
SkillRegistry ─────► WifiSkill / BluetoothSkill / NetworkSkill
  │
  ▼
Windows API / CLI ──► netsh / PowerShell PnP Device / ipconfig / ping
  │
  ▼
Read-Back Verify ───► Query actual hardware/stack state & compare
  │
  ▼
Structured Result ──► Status (ok / restricted / unsupported / error)
```

## Component Details

### 1. `WifiSkill` (`src/nova/skills/system/wifi.py`)
- **Intent**: `wifi`, `wifi_control`
- **Actions**:
  - `status`: Queries `netsh wlan show interface` for interface name, connection state, and connected SSID.
  - `enable`: Enables the Wi-Fi interface via `netsh interface set interface <name> enable`, followed by settling delay and read-back state verification.
  - `disable`: Disables the Wi-Fi interface with read-back state verification.
  - `connect`: Connects to an **existing saved profile** (`netsh wlan connect name=<ssid>`).
    - **Safety Contract**: Validates and sanitizes SSID to prevent command injection. Does NOT create or mutate profiles. Verifies actual connected SSID via read-back. If the profile does not exist, returns `status="restricted"` with `settings_fallback="ms-settings:network-wifi"`.
- **Security**: No `shell=True`. All subprocess calls use explicit list arguments. Access-denied / elevation errors are mapped to `status="restricted"`.

### 2. `BluetoothSkill` (`src/nova/skills/system/bluetooth.py`)
- **Intent**: `bluetooth`, `bluetooth_control`
- **Actions**:
  - `status`: Queries primary Bluetooth radio controller status via targeted PnP device inspection.
  - `enable`: Targets the specific Bluetooth Radio Adapter by `InstanceId` using `Enable-PnpDevice`, avoiding peripheral disconnection. Verifies state read-back.
  - `disable`: Targets the specific adapter by `InstanceId` using `Disable-PnpDevice` with state read-back.
- **Hardware Targeting**: Specifically matches host controller adapters (`Intel`, `Realtek`, `Qualcomm`, `Broadcom`, `USB\Class_E0&SubClass_01&Prot_01`) rather than broad peripheral device classes.
- **Fallback**: WinRT `Windows.Devices.Radios` is dynamically detected; when unavailable (as audited in this environment), safely uses targeted PowerShell PnP commands without breaking peripheral state.

### 3. `NetworkSkill` (`src/nova/skills/system/network.py`)
- **Intent**: `network`, `network_control`, `network_status`
- **Actions**:
  - `status`: Parses `ipconfig` to return active interface name, IPv4 address, default gateway, and overall connectivity.
  - `interfaces`: Enumerates all network adapters, types (Wi-Fi vs Ethernet), connection status, and IP parameters.
  - `dns`: Queries configured DNS servers via `netsh interface ip show dns` and `ipconfig /all`.
  - `ping`: Executes `ping -n <count> -w 1000 <host>`.
    - **Safety Contract**: Strict regex validation on host (`_IPV4_RE` or `_HOSTNAME_RE`). Rejects command injection characters (`;`, `&`, `|`, spaces, quotes). Parses transmitted, received, loss percentage, and average round-trip latency.

## Test Validation Results

1. **Unit Test Suite** (`tests/unit/skills/test_network_bluetooth_skill.py`):
   - **18 passed out of 18** tests.
   - Verified schema enforcement, `can_handle`, injection prevention, access-denied handling, read-back verification, and output parsing.

2. **Skill Parameter Schema Suite** (`tests/unit/skills/test_skill_parameter_schemas.py`):
   - **11 passed out of 11** tests.
   - Verified all 20 concrete production skills have JSON-schema-compliant parameter specifications.

3. **Real Windows E2E Test Suite** (`tests/e2e/test_network_bluetooth_e2e.py`):
   - **8 passed out of 8** tests running against live Windows 11 stack.
   - Tested real network status, real interface enumeration, real DNS queries, real Wi-Fi status, real Bluetooth status, and full pipeline execution (`User Text -> BrainEngine -> TaskService -> Skill`).

4. **All E2E Test Suites** (`tests/e2e/`):
   - **42 passed out of 42** tests across Display, Audio, Settings, Personalization, Lifecycle, Network, Wi-Fi, and Bluetooth.
