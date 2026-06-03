import argparse
import asyncio
import uuid
import firebase_admin
from firebase_admin import credentials, firestore
from aiortc.contrib.media import MediaPlayer
from lib.resized_video_track import ResizedVideoTrack
from lib.mqtt_client import MqttClient, MqttConfig
##Motor control library for Raspberry Pi (Adafruit Motor Shield compatible)
from lib.AFMotor import af_motor_backward, af_motor_forward, af_motor_stop
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


def _get_firestore_client():
    # Lazy init so `python main.py --help` works even when credentials are missing.
    if not firebase_admin._apps:
        cred = credentials.Certificate("/home/pi/serviceAccountKey.json")
        firebase_admin.initialize_app(cred)
    return firestore.client()

_mqtt_client: MqttClient | None = None

DEFAULT_ICE_SERVERS = [
    RTCIceServer(urls=["stun:stun1.l.google.com:19302", "stun:stun2.l.google.com:19302"])
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


def _install_peer_handlers(pc: RTCPeerConnection, *, room_ref, local_candidates_collection: str):
    @pc.on("datachannel")
    def on_datachannel(channel):
        print(f"DataChannel received: {channel.label}")

        @channel.on("message")
        def on_message(message):
            if isinstance(message, (bytes, bytearray)):
                message = message.decode("utf-8", errors="replace")
            print(f"DataChannel message: {message}")
            parsed = try_parse_json_payload(message)
            if parsed.ok:
                if isinstance(parsed.value, dict):
                               
                    t_raw = getValueByKey(parsed.value, 't')
                    t = _coerce_int(t_raw)
                    print(f"Value of 't': {t}")
                    match t:
                        case 1:
                            print("Received command: move forward")
                            af_motor_forward(speed=255)
                                                             
                        case 2:
                            print("Received command: move backward")
                            af_motor_backward(speed=255)
                        case 0:
                            print("Received command: stop")
                            af_motor_stop()
                        case _:
                            print("Received command: unknown")
                elif isinstance(parsed.value, list):
                    print(f"DataChannel JSON array: {parsed.value}")
                else:
                    print(f"DataChannel JSON value: {parsed.value!r}")
                text = parsed.text

    @pc.on("connectionstatechange")
    async def on_connectionstatechange():
        print(f"Connection state: {pc.connectionState}")

    @pc.on("icecandidate")
    def on_icecandidate(candidate):
        if candidate is None:
            return
        print("Uploading ICE candidate…")
        room_ref.collection(local_candidates_collection).add(_candidate_to_firestore(candidate))


async def main(room_id: str):
    db = _get_firestore_client()
    # 🔹 2. Define Firestore document path (room)
    room_ref = db.collection("rooms").document(room_id)

    room_doc = room_ref.get()
    room_data = room_doc.to_dict() if room_doc.exists else {}

    # If the browser already created an offer in this room, join as callee; otherwise create the offer.
    is_callee = bool(room_data and "offer" in room_data and "answer" not in room_data)
    local_candidates = "calleeCandidates" if is_callee else "callerCandidates"
    remote_candidates = "callerCandidates" if is_callee else "calleeCandidates"

    pc = _create_peer_connection()
    _install_peer_handlers(pc, room_ref=room_ref, local_candidates_collection=local_candidates)


    # 🔹 4. Grab webcam video
    #player = MediaPlayer("/dev/video0", format="v4l2", options={"video_size": "320x240","input_format":"mjpeg", "framerate": "8"})
    # player = MediaPlayer("/dev/video0", format="v4l2", options={"video_size": "320x240","input_format": "yuyv422", "framerate": "10"})
    # pc.addTrack(player.video)
    player = MediaPlayer("/dev/video0", format="v4l2", options={"framerate": "10"})
    scaled = ResizedVideoTrack(player.video, 426, 240)
    pc.addTrack(scaled)

    if is_callee:
        print(f"Joining room {room_id} as callee (offer already exists)")
        offer = room_data["offer"]
        await pc.setRemoteDescription(RTCSessionDescription(sdp=offer["sdp"], type=offer["type"]))
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)
        room_ref.update({
            "answer": {
                "sdp": pc.localDescription.sdp,
                "type": pc.localDescription.type,
            }
        })
        print("Answer uploaded — connection established.")
    else:
        print(f"Creating offer in room {room_id} as caller")

        # Caller creates the DataChannel.
        channel = pc.createDataChannel("chat")

        @channel.on("open")
        def on_open():
            print("DataChannel open")

        @channel.on("message")
        def on_message(message):
            if isinstance(message, (bytes, bytearray)):
                message = message.decode("utf-8", errors="replace")
            print(f"DataChannel message: {message}")

        offer = await pc.createOffer()
        await pc.setLocalDescription(offer)

        print("Uploading offer → Firebase…")
        room_ref.set(
            {
                "offer": {
                    "sdp": pc.localDescription.sdp,
                    "type": pc.localDescription.type,
                }
            },
            merge=True,
        )

        print("Waiting for answer from browser peer…")
        while True:
            doc = room_ref.get()
            data = doc.to_dict() or {}
            if "answer" in data:
                answer = data["answer"]
                await pc.setRemoteDescription(RTCSessionDescription(sdp=answer["sdp"], type=answer["type"]))
                print("Answer received — connection established.")
                break
            await asyncio.sleep(2)

    # 🔹 8. Listen for ICE candidates from the browser
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
            except Exception as e:
                print(f"Failed to add ICE candidate: {e}")
        await asyncio.sleep(5)


def device_restart() -> None:
    """Restart the device by executing system restart command."""
    import os
    import subprocess
    print("Initiating device restart...")
    try:
        subprocess.run(['sudo', 'reboot'], check=True)
    except subprocess.CalledProcessError as e:
        print(f"Error during restart: {e}")
    except Exception as e:
        print(f"Unexpected error during restart: {e}")


def _on_mqtt_message(topic: str, payload: bytes) -> None:
    parsed = try_parse_json_payload(payload)
    if parsed.ok:
        if isinstance(parsed.value, dict):
            print(f"MQTT JSON object on {topic}: {parsed.value}")            
            t_raw = getValueByKey(parsed.value, 't', None)
            t = _coerce_int(t_raw)
            print(f"Value of 't': {t}")

            match t:
                case Constant.MQTT_T_VAL_FORWARD:
                    print("Received command: move forward")
                    #af_motor_forward(speed=255)
                case Constant.MQTT_T_VAL_BACKWARD:
                    print("Received command: move backward")
                    #af_motor_backward(speed=255)
                case Constant.MQTT_T_VAL_STOP:
                    print("Received command: stop")
                    #af_motor_stop()
                case Constant.MQTT_T_VAL_RPI_RESTART:
                    print("Received command: restart Raspberry Pi")
                    device_restart()
                case _:
                    print("Received command: unknown")
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
    parser.add_argument(
        "--use-mac-room-id",
        type=_str_to_bool,
        default=True,
        help="When --room-id is not set: true=use device MAC, false=use random room id (published to MQTT).",
    )
    args = parser.parse_args()

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
        print(f"MQTT subscribed to: {MQTT_SUBSCRIBE_TOPIC}")

    try:
        asyncio.run(main(effective_room_id))
    finally:
        if mqtt_client is not None:
            mqtt_client.stop()
        _mqtt_client = None