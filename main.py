
import argparse
import asyncio
import json
import logging
import os
import signal
import threading
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Set, Tuple

from aiortc import (
	RTCConfiguration,
	RTCIceCandidate,
	RTCIceServer,
	RTCPeerConnection,
	RTCSessionDescription,
)
from aiortc.contrib.media import MediaPlayer

import firebase_admin
from firebase_admin import credentials, firestore


LOGGER = logging.getLogger("ugv_webrtc")


DEFAULT_ICE_SERVERS = [
	RTCIceServer(urls=["stun:stun1.l.google.com:19302", "stun:stun2.l.google.com:19302"])
]


@dataclass(frozen=True)
class RoleConfig:
	local_candidates_collection: str
	remote_candidates_collection: str
	local_description_field: str
	remote_description_field: str


CALLER = RoleConfig(
	local_candidates_collection="callerCandidates",
	remote_candidates_collection="calleeCandidates",
	local_description_field="offer",
	remote_description_field="answer",
)

CALLEE = RoleConfig(
	local_candidates_collection="calleeCandidates",
	remote_candidates_collection="callerCandidates",
	local_description_field="answer",
	remote_description_field="offer",
)


def _candidate_to_firestore(candidate: RTCIceCandidate) -> Dict[str, Any]:
	# Mirrors browser's event.candidate.toJSON() shape.
	return {
		"candidate": candidate.candidate,
		"sdpMid": candidate.sdpMid,
		"sdpMLineIndex": candidate.sdpMLineIndex,
	}


def _candidate_from_firestore(data: Dict[str, Any]) -> RTCIceCandidate:
	return RTCIceCandidate(
		candidate=data["candidate"],
		sdpMid=data.get("sdpMid"),
		sdpMLineIndex=data.get("sdpMLineIndex"),
	)


class FirestoreRoomSignaling:
	def __init__(self, db: firestore.Client, room_id: str):
		self._db = db
		self._room_ref = db.collection("rooms").document(room_id)

	@property
	def room_id(self) -> str:
		return self._room_ref.id

	@property
	def room_ref(self):
		return self._room_ref

	def candidates_ref(self, name: str):
		return self._room_ref.collection(name)


async def _wait_for_event(loop: asyncio.AbstractEventLoop, event: asyncio.Event, timeout_s: Optional[float]) -> None:
	if timeout_s is None:
		await event.wait()
		return
	await asyncio.wait_for(event.wait(), timeout=timeout_s)


def _install_signaling_doc_listener(
	loop: asyncio.AbstractEventLoop,
	room_ref,
	desired_field: str,
	result_future: "asyncio.Future[Dict[str, Any]]",
) -> Tuple[threading.Event, Any]:
	done = threading.Event()

	def on_snapshot(doc_snapshot, changes, read_time):
		if done.is_set():
			return
		if not doc_snapshot:
			return
		data = doc_snapshot[0].to_dict() or {}
		payload = data.get(desired_field)
		if not payload:
			return
		done.set()
		loop.call_soon_threadsafe(lambda: (not result_future.done()) and result_future.set_result(payload))

	unsubscribe = room_ref.on_snapshot(on_snapshot)
	return done, unsubscribe


def _install_candidates_listener(
	loop: asyncio.AbstractEventLoop,
	candidates_ref,
	queue: "asyncio.Queue[Dict[str, Any]]",
) -> Tuple[threading.Event, Any]:
	done = threading.Event()
	seen: Set[str] = set()

	def on_snapshot(col_snapshot, changes, read_time):
		if done.is_set():
			return
		for change in changes:
			if change.type.name != "ADDED":
				continue
			doc = change.document
			if doc.id in seen:
				continue
			seen.add(doc.id)
			data = doc.to_dict() or {}
			loop.call_soon_threadsafe(queue.put_nowait, data)

	unsubscribe = candidates_ref.on_snapshot(on_snapshot)
	return done, unsubscribe


def _create_peer_connection() -> RTCPeerConnection:
	config = RTCConfiguration(iceServers=DEFAULT_ICE_SERVERS)
	return RTCPeerConnection(configuration=config)


def _create_camera_player(device: str, width: int, height: int, fps: int):
	# Uses ffmpeg under the hood. On Raspberry Pi, install `ffmpeg` and v4l2 support.
	options = {
		"video_size": f"{width}x{height}",
		"framerate": str(fps),
	}
	return MediaPlayer(device, format="v4l2", options=options)


async def _run_peer(
	db: firestore.Client,
	role: RoleConfig,
	room_id: str,
	device: str,
	width: int,
	height: int,
	fps: int,
	timeout_s: Optional[float],
) -> None:
	loop = asyncio.get_running_loop()
	pc = _create_peer_connection()
	signaling = FirestoreRoomSignaling(db, room_id)

	# Camera
	player = _create_camera_player(device=device, width=width, height=height, fps=fps)
	if player.video:
		pc.addTrack(player.video)
	else:
		raise RuntimeError("Camera video track not available (is /dev/video0 accessible?)")

	remote_candidates_queue: "asyncio.Queue[Dict[str, Any]]" = asyncio.Queue()
	remote_description_set = asyncio.Event()
	pending_remote_candidates: List[Dict[str, Any]] = []

	@pc.on("datachannel")
	def on_datachannel(channel):
		LOGGER.info("DataChannel received: %s", channel.label)

		@channel.on("message")
		def on_message(message):
			try:
				if isinstance(message, (bytes, bytearray)):
					message = message.decode("utf-8", errors="replace")
				LOGGER.info("DataChannel message: %s", message)
			except Exception:
				LOGGER.exception("Failed to process DataChannel message")

	@pc.on("connectionstatechange")
	async def on_connectionstatechange():
		LOGGER.info("Connection state: %s", pc.connectionState)
		if pc.connectionState in {"failed", "closed", "disconnected"}:
			await pc.close()

	@pc.on("icecandidate")
	def on_icecandidate(candidate):
		if candidate is None:
			return
		try:
			signaling.candidates_ref(role.local_candidates_collection).add(_candidate_to_firestore(candidate))
		except Exception:
			LOGGER.exception("Failed to write local ICE candidate")

	# Remote candidates listener
	candidates_done, candidates_unsub = _install_candidates_listener(
		loop,
		signaling.candidates_ref(role.remote_candidates_collection),
		remote_candidates_queue,
	)

	async def remote_candidates_consumer():
		while True:
			data = await remote_candidates_queue.get()
			if not remote_description_set.is_set():
				pending_remote_candidates.append(data)
				continue
			try:
				await pc.addIceCandidate(_candidate_from_firestore(data))
			except Exception:
				LOGGER.exception("Failed to add remote ICE candidate")

	consumer_task = asyncio.create_task(remote_candidates_consumer())

	try:
		room_ref = signaling.room_ref
		snap = room_ref.get()
		room_data = snap.to_dict() if snap.exists else None

		if role is CALLEE:
			if not room_data or "offer" not in room_data:
				raise RuntimeError(
					"Room has no offer yet. Create a room in the browser first, then pass its roomId to this script."
				)

			offer = room_data["offer"]
			await pc.setRemoteDescription(RTCSessionDescription(sdp=offer["sdp"], type=offer["type"]))
			remote_description_set.set()
			for cand in pending_remote_candidates:
				try:
					await pc.addIceCandidate(_candidate_from_firestore(cand))
				except Exception:
					LOGGER.exception("Failed to add queued remote ICE candidate")
			pending_remote_candidates.clear()

			answer = await pc.createAnswer()
			await pc.setLocalDescription(answer)
			room_ref.update({"answer": {"type": pc.localDescription.type, "sdp": pc.localDescription.sdp}})

		else:  # CALLER
			# Create offer and write it to Firestore
			offer = await pc.createOffer()
			await pc.setLocalDescription(offer)
			room_ref.set({"offer": {"type": pc.localDescription.type, "sdp": pc.localDescription.sdp}})
			LOGGER.info("Room created: %s", signaling.room_id)

			# Wait for answer
			answer_future: "asyncio.Future[Dict[str, Any]]" = loop.create_future()
			doc_done, doc_unsub = _install_signaling_doc_listener(loop, room_ref, "answer", answer_future)
			try:
				answer = await asyncio.wait_for(answer_future, timeout=timeout_s) if timeout_s else await answer_future
			finally:
				doc_done.set()
				try:
					doc_unsub()
				except Exception:
					pass

			await pc.setRemoteDescription(RTCSessionDescription(sdp=answer["sdp"], type=answer["type"]))
			remote_description_set.set()
			for cand in pending_remote_candidates:
				try:
					await pc.addIceCandidate(_candidate_from_firestore(cand))
				except Exception:
					LOGGER.exception("Failed to add queued remote ICE candidate")
			pending_remote_candidates.clear()

		# Keep the process alive while connected.
		stop_event = asyncio.Event()

		def _handle_stop(*_args):
			stop_event.set()

		for sig in (signal.SIGINT, signal.SIGTERM):
			try:
				loop.add_signal_handler(sig, _handle_stop)
			except NotImplementedError:
				# Windows / some environments
				signal.signal(sig, lambda *_: _handle_stop())

		await _wait_for_event(loop, stop_event, timeout_s)

	finally:
		candidates_done.set()
		try:
			candidates_unsub()
		except Exception:
			pass
		consumer_task.cancel()
		try:
			await consumer_task
		except Exception:
			pass
		await pc.close()
		try:
			player.stop()
		except Exception:
			pass


def _init_firestore(service_account_json: str):
	if not os.path.exists(service_account_json):
		raise FileNotFoundError(f"Service account JSON not found: {service_account_json}")
	if not firebase_admin._apps:
		cred = credentials.Certificate(service_account_json)
		firebase_admin.initialize_app(cred)
	return firestore.client()


async def main() -> None:
	parser = argparse.ArgumentParser(
		description=(
			"Raspberry Pi webcam -> WebRTC publisher using Firestore signaling (compatible with rescue_ugv/public/app.js)."
		)
	)
	parser.add_argument("--service-account", required=True, help="Path to Firebase service account JSON")

	group = parser.add_mutually_exclusive_group(required=True)
	group.add_argument("--join", metavar="ROOM_ID", help="Join existing room as CALLEE (recommended)")
	group.add_argument(
		"--create",
		action="store_true",
		help="Create new room as CALLER (prints room id; browser should Join room)",
	)

	parser.add_argument("--device", default="/dev/video0", help="V4L2 camera device (default: /dev/video0)")
	parser.add_argument("--width", type=int, default=640)
	parser.add_argument("--height", type=int, default=480)
	parser.add_argument("--fps", type=int, default=30)
	parser.add_argument(
		"--timeout",
		type=float,
		default=None,
		help="Optional timeout (seconds). If set, exits after this time.",
	)
	parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])

	args = parser.parse_args()
	logging.basicConfig(level=getattr(logging, args.log_level), format="%(asctime)s %(levelname)s %(message)s")

	db = _init_firestore(args.service_account)

	if args.create:
		room_ref = db.collection("rooms").document()
		room_id = room_ref.id
		LOGGER.info("Creating room %s", room_id)
		await _run_peer(
			db=db,
			role=CALLER,
			room_id=room_id,
			device=args.device,
			width=args.width,
			height=args.height,
			fps=args.fps,
			timeout_s=args.timeout,
		)
	else:
		room_id = args.join
		LOGGER.info("Joining room %s", room_id)
		await _run_peer(
			db=db,
			role=CALLEE,
			room_id=room_id,
			device=args.device,
			width=args.width,
			height=args.height,
			fps=args.fps,
			timeout_s=args.timeout,
		)


if __name__ == "__main__":
	try:
		asyncio.run(main())
	except KeyboardInterrupt:
		pass

