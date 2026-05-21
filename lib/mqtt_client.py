from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Any
import uuid

import paho.mqtt.client as mqtt


OnMessageCallback = Callable[[str, bytes], None]


@dataclass(frozen=True)
class MqttConfig:
    host: str
    port: int = 1883
    username: Optional[str] = None
    password: Optional[str] = None
    keepalive: int = 60
    client_id: Optional[str] = None


class MqttClient:
    def __init__(self, config: MqttConfig):
        self._config = config
        self._client: Optional[mqtt.Client] = None
        self._is_started = False

    def start(
        self,
        *,
        on_message: OnMessageCallback,
        on_connect: Optional[Callable[[int], None]] = None,
        on_disconnect: Optional[Callable[[int], None]] = None,
    ) -> None:
        if self._is_started:
            return

        client_id = self._config.client_id or f"ugv-{uuid.uuid4().hex[:8]}"
        client = mqtt.Client(client_id=client_id, protocol=mqtt.MQTTv311)

        if self._config.username is not None:
            client.username_pw_set(self._config.username, self._config.password)

        def _on_connect(client: mqtt.Client, userdata: Any, flags: Any, rc: Any, properties: Any = None):
            # paho-mqtt v1: rc is int
            # paho-mqtt v2: rc can be a ReasonCode-like object
            try:
                rc_value = int(getattr(rc, "value", rc))
            except Exception:
                rc_value = 0
            if on_connect is not None:
                on_connect(rc_value)

        def _on_disconnect(client: mqtt.Client, userdata: Any, rc: Any, properties: Any = None):
            try:
                rc_value = int(getattr(rc, "value", rc))
            except Exception:
                rc_value = 0
            if on_disconnect is not None:
                on_disconnect(rc_value)

        def _on_message(client: mqtt.Client, userdata, msg: mqtt.MQTTMessage):
            on_message(msg.topic, msg.payload)

        client.on_connect = _on_connect
        client.on_disconnect = _on_disconnect
        client.on_message = _on_message

        client.connect(self._config.host, self._config.port, keepalive=self._config.keepalive)
        client.loop_start()

        self._client = client
        self._is_started = True

    def stop(self) -> None:
        if not self._is_started or self._client is None:
            return

        self._client.loop_stop()
        self._client.disconnect()
        self._client = None
        self._is_started = False

    def subscribe(self, topic: str, qos: int = 0) -> None:
        if self._client is None:
            raise RuntimeError("MQTT client is not started")
        self._client.subscribe(topic, qos=qos)

    def publish(self, topic: str, payload: str | bytes, qos: int = 0, retain: bool = False) -> None:
        if self._client is None:
            raise RuntimeError("MQTT client is not started")
        self._client.publish(topic, payload=payload, qos=qos, retain=retain)
