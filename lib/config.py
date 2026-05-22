"""Static configuration constants.

Keep runtime settings here so application scripts (e.g. main.py) stay focused on logic.
"""

from __future__ import annotations

import os
import socket
import uuid
import re

# Firestore room
DEFAULT_ROOM_ID = "borhan123"

# MQTT (static configuration)
# Set MQTT_SUBSCRIBE_TOPIC to a topic string to enable MQTT.
MQTT_HOST = "emq.safeprotechnologiesportal.com"
MQTT_PORT = 1883
MQTT_USERNAME = "safeproMQTT"  # e.g. "my-user"
MQTT_PASSWORD = "safepro)*-&$@911@74R^"  # e.g. "my-pass"


def _normalize_mac(value: str) -> str:
	# Return a plain 12-hex string (no ':' / '-').
	return re.sub(r"[^0-9a-fA-F]", "", value).lower()


def _read_mac_from_sysfs(interface: str) -> str | None:
	path = f"/sys/class/net/{interface}/address"
	try:
		with open(path, "r", encoding="utf-8") as f:
			mac = f.read().strip()
	except OSError:
		return None
	if not mac or mac == "00:00:00:00:00:00":
		return None
	normalized = _normalize_mac(mac)
	if len(normalized) != 12:
		return None
	return normalized


def get_device_mac(prefer_interfaces: tuple[str, ...] = ("wlan0", "eth0")) -> str:
	# Prefer Raspberry Pi interfaces when available.
	for iface in prefer_interfaces:
		mac = _read_mac_from_sysfs(iface)
		if mac:
			return mac

	# Cross-platform fallback.
	node = uuid.getnode()
	mac = f"{node:012x}"
	# If the multicast bit is set, uuid.getnode() may be randomized.
	if (node >> 40) % 2:
		return os.environ.get("UGV_DEVICE_ID", "unknown")
	return mac


def get_device_ip() -> str:
	"""Best-effort local IP detection.

	Prefers an explicit environment override, otherwise detects the primary outbound
	interface IP using a UDP "connect" probe (no packets need to be received).
	"""
	env_ip = os.environ.get("UGV_DEVICE_IP") or os.environ.get("DEVICE_IP")
	if env_ip:
		return env_ip

	# UDP probe to determine which local IP would be used to reach the internet.
	# This does not require the remote host to be reachable; it just needs routing.
	try:
		with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
			s.connect(("8.8.8.8", 80))
			ip = s.getsockname()[0]
			if ip:
				return ip
	except OSError:
		pass

	return "127.0.0.1"


DEVICE_MAC = get_device_mac()
DEVICE_IP = get_device_ip()

# Backward-compatible alias (older code had a typo).
DEVIC_IP = DEVICE_IP
MQTT_SUBSCRIBE_TOPIC = f"v301/ugv/commands/{DEVICE_MAC}"  # v301/ugv/commands/{mac}
MQTT_PUBLISH_TOPIC = f"v301/ugv/telemetry/{DEVICE_MAC}"  # e.g. "ugv/telemetry/{mac}" (set to None to publish to <incoming>/ack)
