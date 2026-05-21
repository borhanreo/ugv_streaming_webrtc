"""Static configuration constants.

Keep runtime settings here so application scripts (e.g. main.py) stay focused on logic.
"""

from __future__ import annotations

import os
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


DEVICE_MAC = get_device_mac()

MQTT_SUBSCRIBE_TOPIC = f"v301/ugv/commands/{DEVICE_MAC}"  # v301/ugv/commands/{mac}
MQTT_PUBLISH_TOPIC = "v301/ugv/telemetry"  # e.g. "ugv/telemetry" (set to None to publish to <incoming>/ack)
