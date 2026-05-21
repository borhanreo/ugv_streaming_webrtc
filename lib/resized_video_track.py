import av
import cv2
from aiortc.contrib.media import MediaStreamTrack


class ResizedVideoTrack(MediaStreamTrack):
    kind = "video"

    def __init__(self, track: MediaStreamTrack, width: int, height: int):
        super().__init__()
        self.track = track
        self.width = width
        self.height = height

    async def recv(self) -> av.VideoFrame:
        frame = await self.track.recv()
        img = frame.to_ndarray(format="bgr24")
        img = cv2.resize(img, (self.width, self.height))
        new_frame = av.VideoFrame.from_ndarray(img, format="bgr24")
        new_frame.pts, new_frame.time_base = frame.pts, frame.time_base
        return new_frame
