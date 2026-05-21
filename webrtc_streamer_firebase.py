import argparse
import asyncio
import firebase_admin
from firebase_admin import credentials, firestore
from aiortc import (
    RTCConfiguration,
    RTCIceCandidate,
    RTCIceServer,
    RTCPeerConnection,
    RTCSessionDescription,
)
from aiortc.contrib.media import MediaPlayer

# 🔹 1. Initialize Firebase
cred = credentials.Certificate("/home/pi/serviceAccountKey.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

DEFAULT_ROOM_ID = "borhan123"

DEFAULT_ICE_SERVERS = [
    RTCIceServer(urls=["stun:stun1.l.google.com:19302", "stun:stun2.l.google.com:19302"])
]


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
    player = MediaPlayer("/dev/video0", format="v4l2", options={"video_size": "320x240","input_format":"mjpeg", "framerate": "8"})
    pc.addTrack(player.video)

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

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="WebRTC webcam streamer using Firebase Firestore signaling")
    parser.add_argument("--room-id", default=DEFAULT_ROOM_ID, help="Firestore room id")
    args = parser.parse_args()

    asyncio.run(main(args.room_id))