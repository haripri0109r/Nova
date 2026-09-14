"""
Network skill – diagnostics and status (Windows netsh, ipconfig, ping).

Phase 5.8-D. Nova is "Siri for Windows" – this skill provides network diagnostics
and interface reporting without arbitrary shell execution.

Actions
-------
status     – Overall network health, primary IP, default gateway, connection status.
ping       – Ping a remote host or IP with strict sanitization and parsed metrics.
dns        – Query configured DNS servers.
interfaces – List all network interfaces, status, and adapter types.

Design rules
------------
* NO shell=True.
* Subprocess calls use explicit list arguments.
* Strict regex validation on host names / IPs (no command injection possible).
* Clean parsing of standard Windows CLI tool output (ipconfig, netsh, ping).
"""

from __future__ import annotations

import logging
import re
import subprocess
import sys
from typing import Any, Dict, List, Optional

from nova.skills.base import BaseSkill
from nova.skills.registry import registry

logger = logging.getLogger("nova.skills.system.network")

# Strict regex for valid hostnames, FQDNs, or IPv4 addresses
_IPV4_RE = re.compile(
    r"^(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)$"
)
_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)(?:\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*$"
)


def _validate_host(host: str) -> str:
    """
    Validate that host is a well-formed IPv4 or hostname/domain.
    Raises ValueError on malicious or invalid formats.
    """
    h = host.strip()
    if not h:
        raise ValueError("Host cannot be empty.")
    if _IPV4_RE.match(h) or _HOSTNAME_RE.match(h):
        return h
    raise ValueError(f"Invalid host or IP address format: {host!r}")


def _run(args: List[str], timeout: int = 15) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        check=False,
        timeout=timeout,
    )


def _parse_ipconfig() -> List[Dict[str, Any]]:
    """Parse `ipconfig` output to extract network adapter information."""
    adapters: List[Dict[str, Any]] = []
    current_adapter: Optional[Dict[str, Any]] = None

    try:
        res = _run(["ipconfig"])
        if res.returncode != 0:
            return adapters

        for line in res.stdout.splitlines():
            line_str = line.strip()
            # Adapter header line, e.g.: "Ethernet adapter Ethernet:" or "Wireless LAN adapter Wi-Fi:"
            if "adapter" in line.lower() and line.endswith(":"):
                if current_adapter and current_adapter.get("name"):
                    adapters.append(current_adapter)
                name = line.split("adapter", 1)[1].rstrip(":").strip()
                adapter_type = "wifi" if any(k in line.lower() for k in ("wireless", "wi-fi", "wlan")) else "ethernet"
                current_adapter = {
                    "name": name,
                    "type": adapter_type,
                    "connected": True,
                    "ipv4": None,
                    "subnet_mask": None,
                    "gateway": None,
                }
            elif current_adapter is not None:
                if "media disconnected" in line.lower():
                    current_adapter["connected"] = False
                elif "ipv4 address" in line.lower():
                    parts = line.split(":", 1)
                    if len(parts) == 2:
                        current_adapter["ipv4"] = parts[1].replace("(Preferred)", "").strip()
                elif "subnet mask" in line.lower():
                    parts = line.split(":", 1)
                    if len(parts) == 2:
                        current_adapter["subnet_mask"] = parts[1].strip()
                elif "default gateway" in line.lower():
                    parts = line.split(":", 1)
                    if len(parts) == 2:
                        gw = parts[1].strip()
                        if gw:
                            current_adapter["gateway"] = gw

        if current_adapter and current_adapter.get("name"):
            adapters.append(current_adapter)

    except Exception as exc:  # noqa: BLE001
        logger.debug("Failed to parse ipconfig: %s", exc)

    return adapters


def _parse_dns_servers() -> List[str]:
    """Parse configured DNS servers via netsh or ipconfig /all."""
    dns_servers: List[str] = []
    # Try netsh first
    try:
        res = _run(["netsh", "interface", "ip", "show", "dns"])
        if res.returncode == 0:
            for line in res.stdout.splitlines():
                if "statically configured dns servers:" in line.lower() or "dns servers configured through dhcp:" in line.lower():
                    parts = line.split(":", 1)
                    if len(parts) == 2 and parts[1].strip():
                        dns_servers.append(parts[1].strip())
                elif re.match(r"^\s+\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\s*$", line):
                    dns_servers.append(line.strip())
            if dns_servers:
                return dns_servers
    except Exception:  # noqa: BLE001
        pass

    # Fallback to ipconfig /all
    try:
        res = _run(["ipconfig", "/all"])
        if res.returncode == 0:
            dns_block = False
            for line in res.stdout.splitlines():
                if "dns servers" in line.lower():
                    parts = line.split(":", 1)
                    if len(parts) == 2 and parts[1].strip():
                        val = parts[1].strip()
                        if _IPV4_RE.match(val):
                            dns_servers.append(val)
                    dns_block = True
                elif dns_block:
                    stripped = line.strip()
                    if _IPV4_RE.match(stripped):
                        dns_servers.append(stripped)
                    elif line and not line.startswith(" "):
                        dns_block = False
    except Exception:  # noqa: BLE001
        pass

    return dns_servers


class NetworkSkill(BaseSkill):
    intent = "network"
    description = (
        "Diagnose and inspect Windows network status, ping hosts, "
        "query DNS configurations, and list active interfaces."
    )

    parameters_schema = {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["status", "ping", "dns", "interfaces"],
                "description": "Network operation: 'status', 'ping', 'dns', or 'interfaces'.",
            },
            "host": {
                "type": "string",
                "description": "Target hostname or IP for ping action (e.g. '8.8.8.8' or 'google.com').",
            },
            "count": {
                "type": "integer",
                "minimum": 1,
                "maximum": 10,
                "description": "Number of echo requests to send (default 4).",
            },
        },
        "required": ["action"],
        "additionalProperties": False,
    }

    def can_handle(self, intent_data: Dict[str, Any]) -> bool:
        return intent_data.get("intent") in ("network", "network_control", "network_status")

    def execute(self, intent_data: Dict[str, Any]) -> Dict[str, Any]:
        action = intent_data.get("action", "").strip().lower()
        if action not in ("status", "ping", "dns", "interfaces"):
            return {
                "status": "error",
                "message": f"Unknown network action: {action!r}. Valid: status, ping, dns, interfaces.",
            }

        if sys.platform != "win32":
            return {
                "status": "unsupported",
                "message": "Network diagnostics are only supported on Windows.",
            }

        if action == "status":
            return self._do_status()
        elif action == "interfaces":
            return self._do_interfaces()
        elif action == "dns":
            return self._do_dns()
        elif action == "ping":
            host = intent_data.get("host", "8.8.8.8")
            count = int(intent_data.get("count", 4))
            return self._do_ping(host, count)

    def _do_status(self) -> Dict[str, Any]:
        """Summarize active connection status and gateway."""
        adapters = _parse_ipconfig()
        active_adapters = [a for a in adapters if a.get("connected") and a.get("ipv4")]

        if not active_adapters:
            return {
                "status": "ok",
                "connected": False,
                "message": "No active network adapters with an assigned IPv4 address found.",
                "active_adapters": [],
            }

        primary = active_adapters[0]
        return {
            "status": "ok",
            "connected": True,
            "primary_interface": primary.get("name"),
            "interface_type": primary.get("type"),
            "ipv4": primary.get("ipv4"),
            "gateway": primary.get("gateway"),
            "adapter_count": len(adapters),
            "active_adapter_count": len(active_adapters),
            "detail": f"Connected via {primary.get('name')} ({primary.get('ipv4')})",
        }

    def _do_interfaces(self) -> Dict[str, Any]:
        """List all network adapters with detailed configuration."""
        adapters = _parse_ipconfig()
        return {
            "status": "ok",
            "interfaces": adapters,
            "count": len(adapters),
            "detail": f"Found {len(adapters)} network interfaces.",
        }

    def _do_dns(self) -> Dict[str, Any]:
        """Query configured DNS servers."""
        dns_servers = _parse_dns_servers()
        return {
            "status": "ok",
            "dns_servers": dns_servers,
            "count": len(dns_servers),
            "detail": f"Configured DNS servers: {', '.join(dns_servers) if dns_servers else 'None detected'}",
        }

    def _do_ping(self, host: str, count: int = 4) -> Dict[str, Any]:
        """
        Execute ping with strict host validation and output parsing.
        """
        try:
            valid_host = _validate_host(host)
        except ValueError as exc:
            return {"status": "error", "message": str(exc)}

        count = max(1, min(10, count))

        try:
            res = _run(["ping", "-n", str(count), "-w", "1000", valid_host], timeout=20)
        except subprocess.TimeoutExpired:
            return {
                "status": "error",
                "message": f"Ping request to {valid_host} timed out.",
            }
        except Exception as exc:  # noqa: BLE001
            return {"status": "error", "message": f"Ping execution failed: {exc}"}

        stdout = res.stdout or ""

        # Parse transmitted/received/loss
        packets_transmitted = count
        packets_received = 0
        loss_percent = 100

        m_packets = re.search(
            r"Packets:\s+Sent\s*=\s*(\d+),\s*Received\s*=\s*(\d+),\s*Lost\s*=\s*(\d+)\s*\(([\d\.]+)%\s*loss\)",
            stdout,
            re.IGNORECASE,
        )
        if m_packets:
            packets_transmitted = int(m_packets.group(1))
            packets_received = int(m_packets.group(2))
            loss_percent = float(m_packets.group(4))

        # Parse round-trip times
        avg_latency_ms: Optional[int] = None
        m_rtt = re.search(
            r"Minimum\s*=\s*(\d+)ms,\s*Maximum\s*=\s*(\d+)ms,\s*Average\s*=\s*(\d+)ms",
            stdout,
            re.IGNORECASE,
        )
        if m_rtt:
            avg_latency_ms = int(m_rtt.group(3))

        reachable = packets_received > 0

        return {
            "status": "ok",
            "host": valid_host,
            "reachable": reachable,
            "packets_sent": packets_transmitted,
            "packets_received": packets_received,
            "packet_loss_percent": loss_percent,
            "avg_latency_ms": avg_latency_ms,
            "detail": (
                f"Ping {valid_host}: {packets_received}/{packets_transmitted} replies, "
                f"{loss_percent:.0f}% loss"
                + (f", avg={avg_latency_ms}ms" if avg_latency_ms is not None else "")
            ),
        }


registry.register(NetworkSkill())
