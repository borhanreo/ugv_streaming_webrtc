
# install 

## install
```sudo apt update && sudo apt upgrade -y```

```sudo apt install python3 python3-pip v4l-utils -y```

```python3 -m pip install aiortc firebase-admin```


### 1️⃣ Install the venv tool if missing
```sudo apt install python3-venv -y```

### 2️⃣ Create a virtual environment
```python3 -m venv ~/webrtc-env```

### 3️⃣ Activate it
```source ~/webrtc-env/bin/activate```

### 4️⃣ Now install packages inside the virtual env
```pip install aiortc firebase-admin```

### install opencd
```pip install opencv-python```
### check ioencv
```python3 -c "import cv2; print(cv2.__version__)"```

### mqtt install
```pip install paho-mqtt```

### RPI GPIO
```pip install RPi.GPIO```

### install pyserial
```pip install pyserial```


### add firebase json
```/home/pi/serviceAccountKey.json```
### location
google drive robot/rescue

### need to add credential in config.py
```nano lib/config.py```
add here mqtt usr,pass and host, port
### Run python 
```python3 main.py --room-id borhan12```

### Run without --room-id (default uses MAC)
```python3 main.py```

### Run without --room-id but use a random room id (published to MQTT) for
```python3 main.py --use-mac-room-id false```



### test ip
```192.168.24.42```


# Auto starty in Rpi

```sudo nano /usr/local/bin/start_gcs_ugv.sh```
<pre>
#!/bin/bash
#!--------------------------------------
#!Script: start_gcs_ugv.sh
#!Purpose: ugc Server start
#!--------------------------------------
cd /home/pi/ugv/ugv_streaming_webrtc || exit
#! 1️⃣ Start FGCS-UGV and wait until it exits
echo "Starting Firebase GCS..."
cd /home/pi/ugv/ugv_streaming_webrtc
#! Active env
source ~/webrtc-env/bin/activate
python3 main.py --use-mac-room-id false
echo "AGC Done"
#! 2️⃣ Start AGC completes
</pre>

## Permission
```sudo chmod +x /usr/local/bin/start_gcs_ugv.sh```

### for systemctk  service
```sudo nano /etc/systemd/system/acs_ugv.service```

<pre>
[Unit]
Description=ACS Service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=pi
WorkingDirectory=/home/pi/ugv/ugv_streaming_webrtc

ExecStart=/usr/local/bin/start_gcs_ugv.sh

Restart=on-failure

[Install]
WantedBy=multi-user.target
</pre>

###⚡ Step 3 – Enable and Start the Service
 #### load file to systemctl

```sudo systemctl daemon-reload```

```sudo systemctl enable acs_ugv.service```

```sudo systemctl start acs_ugv.service```

```sudo systemctl status acs_ugv.service```


```sudo systemctl restart acs_ugv.service```

# Show recent logs for this boot
```journalctl -u acs_ugv.service -b -n 200 --no-pager```
```sudo journalctl -u acs_ugv.service -f```

## WebRTC event logging

The Python streamer writes detailed event logs for:
- peer connect, disconnect, reconnect
- signaling state changes
- ICE gathering and ICE connection changes
- local and remote ICE candidate events
- DataChannel lifecycle (created/open/close/error/message)
- track lifecycle and periodic heartbeat

### Run with log options

```python3 main.py --room-id borhan12 --log-file /home/pi/webrtc_events.log --log-level INFO```

### Follow log output in real-time

```tail -f /home/pi/webrtc_events.log```


# If Any 'dev/Video' related error 

```sudo apt update```
```sudo apt install -y ffmpeg libavcodec-extra```

I fany problem with video
### 2 | Install FFmpeg With H.264 Support
Raspberry Pi OS Bookworm/Bullseye usually ships a minimal FFmpeg without libx264.
Install the “extra” build:
```bash
sudo apt update
sudo apt install -y ffmpeg libavcodec-extra
```
Now confirm again:

```bash
ffmpeg -codecs | grep 264
```
You should see at least one encoder line (DEV.LS … h264).

### 🧩 3 | Relink aiortc to the Updated Libraries
aiortc loads codec capabilities from the FFmpeg libraries present at install time,
so reinstall it after updating FFmpeg:

```bash
source ~/webrtc-env/bin/activate```
pip install --force-reinstall aiortc```
```
### 🔍 4 | Confirm aiortc Sees H.264
Within your virtual environment, open Python and run:

bash
#!/bin/bash
# Script 3: Simple system backup function python
```from aiortc import RTCRtpSender```
```caps = RTCRtpSender.getCapabilities("video")```
```for c in caps.codecs:```
    ```print(c.mimeType, c.clockRate, c.name)```

Expected good output:
```bash
video/VP8 90000 VP8
video/H264 90000 H264
```
...
If you now see "video/H264", you’re done 🎉 — the earlier ValueError won’t reappear.

### 🧠 5 | If H.264 Still Missing
That means your distribution’s FFmpeg still lacks libx264.

Two alternatives:

Use hardware H.264 encoder (v4l2m2m)

```bash
sudo apt install -y v4l2loopback-utils
Enable camera acceleration in /boot/firmware/config.txt (or /boot/config.txt):
```

Copy
```bash
start_x=1
gpu_mem=128
```
Reboot, reinstall aiortc again.
Stay with VP8 (stable fallback)
Just remove setCodecPreferences() and stick to MJPEG → VP8 capture:

python
```bash
player = MediaPlayer("/dev/video0", format="v4l2",
                     options={"input_format":"mjpeg", "framerate":"10", "video_size":"320x240"})
pc.addTrack(player.video)
```
This works reliably even without H.264 support.

## ⚙️ 1 | Correct H.264 Configuration
Here’s a clean, minimal snippet that matches your current environment:

```bash
from aiortc import RTCRtpCodecCapability
from aiortc.contrib.media import MediaPlayer

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

```