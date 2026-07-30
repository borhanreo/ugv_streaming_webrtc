import argparse
import asyncio
import json
import logging
import os
import subprocess
import uuid
from datetime import datetime, timezone
import firebase_admin
from firebase_admin import credentials, firestore
from aiortc.contrib.media import MediaPlayer
from lib.resized_video_track import ResizedVideoTrack
from lib.mqtt_client import MqttClient, MqttConfig
from lib.serial_controller import SerialController
from aiortc import RTCRtpCodecCapability
serial_ctrl = SerialController(port="/dev/ttyACM0", baudrate=9600)
serial_ctrl.open()
##Motor control library for Raspberry Pi (Adafruit Motor Shield compatible)
from lib.AFMotor import (
    af_motor_backward,
    af_motor_forward,
    af_motor_stop,
    af_motor_turn_left,
    af_motor_turn_right,
    af_servo1_angle,
    af_servo1_step,
    af_servo2_angle,
    af_servo2_step,
)
from lib import Constant
from lib.config import (
    DEFAULT_ROOM_ID,
    MQTT_HOST,
    MQTT_PORT,
    MQTT_USERNAME,
    MQTT_PASSWORD,
    MQTT_SUBSCRIBE_TOPIC,
    MQTT_PUBLISH_TOPIC,
    DEVICE_MAC,
    DEVICE_IP,
)
from lib.json_payload import getValueByKey, try_parse_json_payload
from aiortc import (
    RTCConfiguration,
    RTCIceCandidate,
    RTCIceServer,
    RTCPeerConnection,
    RTCSessionDescription,
)

_effective_room_id: str | None = None
LOGGER = logging.getLogger("ugv_webrtc")
_cpu_last_total: int | None = None
_cpu_last_idle: int | None = None


def _utc_ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def _log_event(event: str, **fields) -> None:
    payload = {
        "ts": _utc_ts(),
        "event": event,
        **fields,
    }
    LOGGER.info(json.dumps(payload, ensure_ascii=True, default=str))


def _setup_logging(log_file: str, log_level: str) -> None:
    numeric_level = getattr(logging, log_level.upper(), logging.INFO)
    handlers = [logging.StreamHandler()]
    if log_file:
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))

    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
    )


def _run_cmd_text(command: list[str]) -> str | None:
    try:
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            return None
        return result.stdout.strip()
    except Exception:
        return None


def _read_cpu_stat() -> tuple[int, int] | None:
    try:
        with open("/proc/stat", "r", encoding="utf-8") as f:
            first = f.readline().strip()
        if not first.startswith("cpu "):
            return None
        parts = first.split()[1:]
        values = [int(x) for x in parts]
        total = sum(values)
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        return total, idle
    except Exception:
        return None


def _get_cpu_usage_percent() -> float | None:
    global _cpu_last_total, _cpu_last_idle

    sample = _read_cpu_stat()
    if sample is None:
        return None

    total, idle = sample
    if _cpu_last_total is None or _cpu_last_idle is None:
        _cpu_last_total, _cpu_last_idle = total, idle
        return None

    dt = total - _cpu_last_total
    di = idle - _cpu_last_idle
    _cpu_last_total, _cpu_last_idle = total, idle
    if dt <= 0:
        return None

    usage = 100.0 * (1.0 - (di / dt))
    return round(usage, 2)


def _get_ram_usage_percent() -> float | None:
    try:
        mem = {}
        with open("/proc/meminfo", "r", encoding="utf-8") as f:
            for line in f:
                if ":" not in line:
                    continue
                key, rest = line.split(":", 1)
                value = int(rest.strip().split()[0])
                mem[key] = value

        total = mem.get("MemTotal")
        available = mem.get("MemAvailable")
        if not total or available is None or total <= 0:
            return None

        used = total - available
        return round((used / total) * 100.0, 2)
    except Exception:
        return None


def _parse_vcgencmd_kv(output: str | None) -> str | None:
    if not output:
        return None
    if "=" not in output:
        return output
    return output.split("=", 1)[1].strip()


def _parse_vcgencmd_volts(output: str | None) -> float | None:
    # Example: "volt=0.8637V"
    value = _parse_vcgencmd_kv(output)
    if not value:
        return None
    try:
        return float(value.rstrip("Vv"))
    except Exception:
        return None


def _get_vcgencmd_voltage(domain: str = "") -> float | None:
    command = ["vcgencmd", "measure_volts"]
    if domain:
        command.append(domain)
    return _parse_vcgencmd_volts(_run_cmd_text(command))


def _read_power_supply_metric(metric_file: str) -> tuple[str, int] | None:
    base = "/sys/class/power_supply"
    try:
        if not os.path.isdir(base):
            return None
        for name in os.listdir(base):
            path = os.path.join(base, name, metric_file)
            if not os.path.isfile(path):
                continue
            try:
                with open(path, "r", encoding="utf-8") as f:
                    raw = f.read().strip()
                value = int(raw)
                return name, value
            except Exception:
                continue
    except Exception:
        return None
    return None


def _get_power_supply_snapshot() -> dict:
    current = _read_power_supply_metric("current_now")
    voltage = _read_power_supply_metric("voltage_now")

    source_name = None
    current_a = None
    voltage_v = None
    power_w = None

    if current:
        source_name = current[0]
        # power_supply current_now is usually in microamps.
        current_a = round(current[1] / 1_000_000.0, 3)

    if voltage:
        source_name = source_name or voltage[0]
        # power_supply voltage_now is usually in microvolts.
        voltage_v = round(voltage[1] / 1_000_000.0, 3)

    if current_a is not None and voltage_v is not None:
        power_w = round(current_a * voltage_v, 3)

    return {
        "power_source": source_name,
        "supply_voltage_v": voltage_v,
        "supply_current_a": current_a,
        "supply_power_w": power_w,
    }


def _get_pi_health_snapshot() -> dict:
    temp_out = _run_cmd_text(["vcgencmd", "measure_temp"])
    throttled_out = _run_cmd_text(["vcgencmd", "get_throttled"])
    ps = _get_power_supply_snapshot()

    return {
        "pi_temp": _parse_vcgencmd_kv(temp_out),
        "pi_throttled": _parse_vcgencmd_kv(throttled_out),
        "pi_core_voltage_v": _get_vcgencmd_voltage("core"),
        "pi_arm_voltage_v": _get_vcgencmd_voltage("arm"),
        "power_source": ps.get("power_source"),
        "supply_voltage_v": ps.get("supply_voltage_v"),
        "supply_current_a": ps.get("supply_current_a"),
        "supply_power_w": ps.get("supply_power_w"),
        "cpu_usage_percent": _get_cpu_usage_percent(),
        "ram_usage_percent": _get_ram_usage_percent(),
    }


def _get_firestore_client():
    # Lazy init so `python main.py --help` works even when credentials are missing.
    if not firebase_admin._apps:
        cred = credentials.Certificate("/home/pi/serviceAccountKey.json")
        firebase_admin.initialize_app(cred)
    return firestore.client()

_mqtt_client: MqttClient | None = None

DEFAULT_ICE_SERVERS = [
    RTCIceServer(urls=["stun:stun1.l.google.com:19302", "stun:stun2.l.google.com:19302"]),
    RTCIceServer(
        urls=["turn:103.197.206.61:3478?transport=udp", "turn:103.197.206.61:3478?transport=tcp"],
        username="turnuser",
        credential="Aa12341!" ##password
    )
]

def _coerce_int(value):
    if value is None:
        return None
    if isinstance(value, bool):
        # Prevent True/False from becoming 1/0.
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        s = value.strip()
        if s.isdigit() or (s.startswith("-") and s[1:].isdigit()):
            try:
                return int(s)
            except Exception:
                return value
    return value


def _candidate_to_firestore(candidate: RTCIceCandidate):
    # Mirrors browser's event.candidate.toJSON() shape.
    return {
        "candidate": candidate.candidate,
        "sdpMid": candidate.sdpMid,
        "sdpMLineIndex": candidate.sdpMLineIndex,
    }


def _candidate_from_firestore(data):
    return RTCIceCandidate(
        candidate=data["candidate"],
        sdpMid=data.get("sdpMid"),
        sdpMLineIndex=data.get("sdpMLineIndex"),
    )


def _create_peer_connection() -> RTCPeerConnection:
    return RTCPeerConnection(configuration=RTCConfiguration(iceServers=DEFAULT_ICE_SERVERS))


def _forward_control_to_serial_and_mqtt(message) -> None:
    if isinstance(message, (bytes, bytearray)):
        message = message.decode("utf-8", errors="replace")

    _log_event("datachannel_message", message=str(message))
    parsed = try_parse_json_payload(message)
    if not parsed.ok or not isinstance(parsed.value, dict):
        return

    t_raw = getValueByKey(parsed.value, 't', None)
    t = _coerce_int(t_raw)
    v_raw = getValueByKey(parsed.value, 'v', None)
    v = _coerce_int(v_raw)
    _log_event("control_command", t=t, v=v)
    serial_ctrl.handle_mqtt_command(t, v)

    if _mqtt_client is not None and MQTT_PUBLISH_TOPIC:
        _mqtt_client.publish(MQTT_PUBLISH_TOPIC, json.dumps({"t": t, "v": v}))


def _install_datachannel_handlers(channel, source: str):
    _log_event("datachannel_created", source=source, label=getattr(channel, "label", "unknown"))

    @channel.on("open")
    def on_open():
        _log_event("datachannel_open", source=source, label=getattr(channel, "label", "unknown"))

    @channel.on("close")
    def on_close():
        _log_event("datachannel_close", source=source, label=getattr(channel, "label", "unknown"))

    @channel.on("error")
    def on_error(error):
        _log_event(
            "datachannel_error",
            source=source,
            label=getattr(channel, "label", "unknown"),
            error=str(error),
        )

    @channel.on("message")
    def on_message(message):
        _forward_control_to_serial_and_mqtt(message)


def _send_telemetry_over_datachannel(channel, payload: dict) -> None:
    try:
        if channel is None:
            return
        if getattr(channel, "readyState", None) != "open":
            return
        channel.send(json.dumps(payload, ensure_ascii=True, default=str))
    except Exception as e:
        _log_event("datachannel_telemetry_send_error", error=str(e))


def _install_peer_handlers(pc: RTCPeerConnection, *, room_ref, local_candidates_collection: str):
    stats = {
        "local_candidate_count": 0,
        "remote_candidate_count": 0,
        "reconnect_count": 0,
        "telemetry_channel": None,
    }
    state = {
        "connection": None,
        "ice_connection": None,
        "ice_gathering": None,
        "signaling": None,
        "ever_connected": False,
    }

    @pc.on("datachannel")
    def on_datachannel(channel):
        _log_event("datachannel_received", label=getattr(channel, "label", "unknown"))
        stats["telemetry_channel"] = channel
        _install_datachannel_handlers(channel, source="remote")

    @pc.on("track")
    def on_track(track):
        _log_event("track_received", kind=getattr(track, "kind", "unknown"), track_id=getattr(track, "id", "unknown"))

        @track.on("ended")
        async def on_ended():
            _log_event(
                "track_ended",
                kind=getattr(track, "kind", "unknown"),
                track_id=getattr(track, "id", "unknown"),
            )

    @pc.on("signalingstatechange")
    async def on_signalingstatechange():
        old = state["signaling"]
        state["signaling"] = pc.signalingState
        _log_event("signaling_state_change", old=old, new=pc.signalingState)

    @pc.on("icegatheringstatechange")
    async def on_icegatheringstatechange():
        old = state["ice_gathering"]
        state["ice_gathering"] = pc.iceGatheringState
        _log_event("ice_gathering_state_change", old=old, new=pc.iceGatheringState)

    @pc.on("iceconnectionstatechange")
    async def on_iceconnectionstatechange():
        old = state["ice_connection"]
        new = pc.iceConnectionState
        state["ice_connection"] = new
        _log_event("ice_connection_state_change", old=old, new=new)

        if new == "connected":
            if state["ever_connected"] and old in {"disconnected", "failed"}:
                stats["reconnect_count"] += 1
                _log_event("peer_reconnected", reconnect_count=stats["reconnect_count"])
            state["ever_connected"] = True

        if new in {"disconnected", "failed", "closed"}:
            _log_event("peer_disconnect_detected", state=new)

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        old = state["connection"]
        new = pc.connectionState
        state["connection"] = new
        _log_event("connection_state_change", old=old, new=new)

        if new == "connected":
            state["ever_connected"] = True

        if new in {"disconnected", "failed", "closed"}:
            _log_event("connection_problem", state=new)

    @pc.on("icecandidate")
    def on_icecandidate(candidate):
        if candidate is None:
            _log_event("local_ice_gathering_complete")
            return
        stats["local_candidate_count"] += 1
        _log_event(
            "local_ice_candidate",
            count=stats["local_candidate_count"],
            sdpMid=candidate.sdpMid,
            sdpMLineIndex=candidate.sdpMLineIndex,
        )
        room_ref.collection(local_candidates_collection).add(_candidate_to_firestore(candidate))

    return stats


async def _webrtc_heartbeat(pc: RTCPeerConnection, *, room_id: str, stats: dict, interval_s: int = 10):
    while True:
        health = _get_pi_health_snapshot()
        telemetry_payload = {
            "event": "pi_telemetry",
            "ts": _utc_ts(),
            "room_id": room_id,
            "pi_temp": health.get("pi_temp"),
            "pi_throttled": health.get("pi_throttled"),
            "pi_core_voltage_v": health.get("pi_core_voltage_v"),
            "pi_arm_voltage_v": health.get("pi_arm_voltage_v"),
            "power_source": health.get("power_source"),
            "supply_voltage_v": health.get("supply_voltage_v"),
            "supply_current_a": health.get("supply_current_a"),
            "supply_power_w": health.get("supply_power_w"),
            "cpu_usage_percent": health.get("cpu_usage_percent"),
            "ram_usage_percent": health.get("ram_usage_percent"),
        }

        _send_telemetry_over_datachannel(stats.get("telemetry_channel"), telemetry_payload)

        _log_event(
            "webrtc_heartbeat",
            room_id=room_id,
            connection=pc.connectionState,
            ice_connection=pc.iceConnectionState,
            ice_gathering=pc.iceGatheringState,
            signaling=pc.signalingState,
            local_candidates=stats.get("local_candidate_count", 0),
            remote_candidates=stats.get("remote_candidate_count", 0),
            reconnect_count=stats.get("reconnect_count", 0),
            pi_temp=health.get("pi_temp"),
            pi_throttled=health.get("pi_throttled"),
            pi_core_voltage_v=health.get("pi_core_voltage_v"),
            pi_arm_voltage_v=health.get("pi_arm_voltage_v"),
            power_source=health.get("power_source"),
            supply_voltage_v=health.get("supply_voltage_v"),
            supply_current_a=health.get("supply_current_a"),
            supply_power_w=health.get("supply_power_w"),
            cpu_usage_percent=health.get("cpu_usage_percent"),
            ram_usage_percent=health.get("ram_usage_percent"),
        )
        await asyncio.sleep(interval_s)


async def main(room_id: str):
    _log_event("session_start", room_id=room_id)
    db = _get_firestore_client()
    # 🔹 2. Define Firestore document path (room)
    room_ref = db.collection("rooms").document(room_id)

    room_doc = room_ref.get()
    room_data = room_doc.to_dict() if room_doc.exists else {}

    # If the browser already created an offer in this room, join as callee; otherwise create the offer.
    is_callee = bool(room_data and "offer" in room_data and "answer" not in room_data)
    local_candidates = "calleeCandidates" if is_callee else "callerCandidates"
    remote_candidates = "callerCandidates" if is_callee else "calleeCandidates"
    _log_event(
        "signaling_role_selected",
        room_id=room_id,
        role="callee" if is_callee else "caller",
        local_candidates=local_candidates,
        remote_candidates=remote_candidates,
    )

    pc = _create_peer_connection()
    stats = _install_peer_handlers(pc, room_ref=room_ref, local_candidates_collection=local_candidates)
    heartbeat_task = asyncio.create_task(_webrtc_heartbeat(pc, room_id=room_id, stats=stats))


    # 🔹 4. Grab webcam video
    #player = MediaPlayer("/dev/video0", format="v4l2", options={"video_size": "320x240","input_format":"mjpeg", "framerate": "8"})
    # player = MediaPlayer("/dev/video0", format="v4l2", options={"video_size": "320x240","input_format": "yuyv422", "framerate": "10"})
    # pc.addTrack(player.video)

    # player = MediaPlayer("/dev/video0", format="v4l2", options={"framerate": "10"})
    # scaled = ResizedVideoTrack(player.video, 320, 240)
    # pc.addTrack(scaled)
    # _log_event("local_video_track_added", device="/dev/video0", width=320, height=240, fps=4)
    # Use MJPEG input so camera handles compression
    # Configure camera source
    player = MediaPlayer(
        "/dev/video0",
        format="v4l2",
        options={
            "video_size": "320x240",
            "framerate": "10",
            "input_format": "mjpeg"  # camera handles compression
        }
    )

    # Add your track
    video_track = player.video
    pc.addTrack(video_track)

    # Prefer H.264
    for transceiver in pc.getTransceivers():
        if transceiver.kind == "video":
            h264_caps = [
                c for c in
                transceiver.sender.getCapabilities("video").codecs
                if "H264" in c.mimeType
            ]
            if h264_caps:
                transceiver.setCodecPreferences(h264_caps)
            break

    _log_event("local_video_track_added", device="/dev/video0", width=320, height=240, fps=10)

    
    try:
        if is_callee:
            _log_event("callee_wait_offer", room_id=room_id)
            offer = room_data["offer"]
            await pc.setRemoteDescription(RTCSessionDescription(sdp=offer["sdp"], type=offer["type"]))
            _log_event("remote_description_set", type=offer["type"], role="callee")

            answer = await pc.createAnswer()
            await pc.setLocalDescription(answer)
            _log_event("local_description_set", type=pc.localDescription.type, role="callee")

            room_ref.update(
                {
                    "answer": {
                        "sdp": pc.localDescription.sdp,
                        "type": pc.localDescription.type,
                    }
                }
            )
            _log_event("answer_uploaded", room_id=room_id)
        else:
            _log_event("caller_create_offer", room_id=room_id)

            # Caller creates the DataChannel.
            channel = pc.createDataChannel("chat")
            stats["telemetry_channel"] = channel
            _install_datachannel_handlers(channel, source="local")

            offer = await pc.createOffer()
            await pc.setLocalDescription(offer)
            _log_event("local_description_set", type=pc.localDescription.type, role="caller")

            room_ref.set(
                {
                    "offer": {
                        "sdp": pc.localDescription.sdp,
                        "type": pc.localDescription.type,
                    }
                },
                merge=True,
            )
            _log_event("offer_uploaded", room_id=room_id)

            _log_event("caller_wait_answer", room_id=room_id)
            while True:
                doc = room_ref.get()
                data = doc.to_dict() or {}
                if "answer" in data:
                    answer = data["answer"]
                    await pc.setRemoteDescription(RTCSessionDescription(sdp=answer["sdp"], type=answer["type"]))
                    _log_event("remote_description_set", type=answer["type"], role="caller")
                    break
                await asyncio.sleep(2)

        # Listen for ICE candidates from the browser
        candidates_ref = room_ref.collection(remote_candidates)
        seen_candidate_docs = set()
        while True:
            docs = candidates_ref.stream()
            for doc in docs:
                if doc.id in seen_candidate_docs:
                    continue
                seen_candidate_docs.add(doc.id)
                data = doc.to_dict() or {}
                if "candidate" not in data:
                    continue
                try:
                    await pc.addIceCandidate(_candidate_from_firestore(data))
                    stats["remote_candidate_count"] += 1
                    _log_event("remote_ice_candidate_added", count=stats["remote_candidate_count"], doc_id=doc.id)
                except Exception as e:
                    _log_event("remote_ice_candidate_error", error=str(e), doc_id=doc.id)
            await asyncio.sleep(5)
    finally:
        heartbeat_task.cancel()
        try:
            await heartbeat_task
        except asyncio.CancelledError:
            pass
        except Exception as e:
            _log_event("heartbeat_task_error", error=str(e))
        try:
            await pc.close()
        except Exception as e:
            _log_event("pc_close_error", error=str(e))
        try:
            player.stop()
        except Exception as e:
            _log_event("media_player_stop_error", error=str(e))
        _log_event("session_end", room_id=room_id)






    

def _on_mqtt_message(topic: str, payload: bytes) -> None:
    parsed = try_parse_json_payload(payload)
    if parsed.ok:
        if isinstance(parsed.value, dict):
            print(f"MQTT JSON object on {topic}: {parsed.value}")            
            t_raw = getValueByKey(parsed.value, 't', None)
            t = _coerce_int(t_raw)
            v_raw = getValueByKey(parsed.value, 'v', None)
            v = _coerce_int(v_raw)
            print(f"Value of 't': {t}")
            serial_ctrl.handle_mqtt_command(t, v)
            # match t:
            #     case Constant.MQTT_T_VAL_FORWARD:
            #         print("Received command: move forward")
            #         af_motor_forward(speed=255)
            #     case Constant.MQTT_T_VAL_BACKWARD:
            #         print("Received command: move backward")
            #         af_motor_backward(speed=255)
            #     case Constant.MQTT_T_VAL_LEFT:
            #         print("Received command: turn left")
            #         af_motor_turn_left(speed=255)
            #     case Constant.MQTT_T_VAL_RIGHT:
            #         print("Received command: turn right")
            #         af_motor_turn_right(speed=255)
                    
            #     case Constant.MQTT_T_VAL_STOP:
            #         print("Received command: stop")
            #         #af_motor_stop()
            #     case Constant.MQTT_T_VAL_CAMERA_UP:
            #         print("Received command: camera up")
            #         step = int(v) if isinstance(v, int) else 10
            #         af_servo2_step(delta=abs(step))
            #     case Constant.MQTT_T_VAL_CAMERA_DOWN:
            #         print("Received command: camera down")
            #         step = int(v) if isinstance(v, int) else 10
            #         af_servo2_step(delta=-abs(step))
            #     case Constant.MQTT_T_VAL_CAMERA_LEFT:
            #         print("Received command: camera left")
            #         step = int(v) if isinstance(v, int) else 10
            #         af_servo1_step(delta=-abs(step))
            #     case Constant.MQTT_T_VAL_CAMERA_RIGHT:
            #         print("Received command: camera right")
            #         step = int(v) if isinstance(v, int) else 10
            #         af_servo1_step(delta=abs(step))
            #     case Constant.MQTT_T_VAL_CAMERA_RESET:
            #         print("Received command: camera reset")
            #         af_servo1_angle(angle=90)
            #         af_servo2_angle(angle=90)
            #     case Constant.MQTT_T_VAL_RPI_RESTART:
            #         print("Received command: restart Raspberry Pi")
            #         device_restart()
            #     case Constant.MQTT_T_VAL_RPI_SHUTDOWN:
            #         print("Received command: shutdown Raspberry Pi")
            #         device_shutdown()
            #     case _:
            #         print("Received command: unknown")
        elif isinstance(parsed.value, list):
            print(f"MQTT JSON array on {topic}: {parsed.value}")
        else:
            print(f"MQTT JSON value on {topic}: {parsed.value!r}")
        text = parsed.text
    else:
        text = parsed.text
        print(f"MQTT message on {topic}: {text}")

    if _mqtt_client is None:
        return

    publish_topic = MQTT_PUBLISH_TOPIC or f"{topic}/ack/{DEVICE_MAC}"
    _mqtt_client.publish(publish_topic, f"ACK: {text}")
    


def _on_mqtt_connect(rc: int) -> None:
    print(f"MQTT connected (rc={rc})")
    room_part = f" room {_effective_room_id}" if _effective_room_id else ""
    _mqtt_client.publish(
        MQTT_PUBLISH_TOPIC,
        f"UGV {DEVICE_MAC}{room_part} ip {DEVICE_IP} connected with rc={rc}",
    )



def _on_mqtt_disconnect(rc: int) -> None:
    print(f"MQTT disconnected (rc={rc})")


def _str_to_bool(value: str) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "y", "on"}:
        return True
    if normalized in {"false", "0", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError("Expected true/false")


def _choose_room_id(room_id_arg: str | None, *, use_mac_when_missing: bool) -> str:
    if room_id_arg:
        return room_id_arg
    if use_mac_when_missing:
        return DEVICE_MAC
    return f"rnd_{uuid.uuid4().hex}"

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="WebRTC webcam streamer using Firebase Firestore signaling")
    parser.add_argument("--room-id", default=None, help="Firestore room id")
    parser.add_argument("--log-file", default="webrtc_events.log", help="Path to write event logs")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument(
        "--use-mac-room-id",
        type=_str_to_bool,
        default=True,
        help="When --room-id is not set: true=use device MAC, false=use random room id (published to MQTT).",
    )
    args = parser.parse_args()
    _setup_logging(args.log_file, args.log_level)
    _log_event("process_start", room_id_arg=args.room_id, use_mac_room_id=args.use_mac_room_id)

    effective_room_id = _choose_room_id(args.room_id, use_mac_when_missing=args.use_mac_room_id)
    _effective_room_id = effective_room_id

    mqtt_client = None
    if MQTT_SUBSCRIBE_TOPIC:
        mqtt_client = MqttClient(
            MqttConfig(
                host=MQTT_HOST,
                port=MQTT_PORT,
                username=MQTT_USERNAME,
                password=MQTT_PASSWORD,
            )
        )

        _mqtt_client = mqtt_client
        mqtt_client.start(
            on_message=_on_mqtt_message,
            on_connect=_on_mqtt_connect,
            on_disconnect=_on_mqtt_disconnect,
        )
        mqtt_client.subscribe(MQTT_SUBSCRIBE_TOPIC)
        _log_event("mqtt_subscribed", topic=MQTT_SUBSCRIBE_TOPIC)

    try:
        asyncio.run(main(effective_room_id))
    finally:
        if mqtt_client is not None:
            mqtt_client.stop()
        _log_event("process_end")
        _mqtt_client = None