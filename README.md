# UGV software (Raspberry Pi) — WebRTC camera publisher

This folder contains a Python script that publishes the Raspberry Pi webcam (e.g. `/dev/video0`) to the existing FirebaseRTC WebRTC app in `rescue_ugv/public/`.

It **reuses the same Cloud Firestore signaling format** as the browser code:
- `rooms/{roomId}` document contains `offer` / `answer`
- `callerCandidates` and `calleeCandidates` subcollections contain ICE candidates

## Requirements

- Raspberry Pi 3 (or similar Linux SBC)
- A USB webcam visible as `/dev/video0` (V4L2)
- `ffmpeg` installed (used by `aiortc.contrib.media.MediaPlayer`)
- A Firebase project with Firestore enabled (your web app already uses this)

Python packages are listed in `requirements.txt`.

## Install (Raspberry Pi)

Recommended: use a virtual environment so installs are isolated.

From this folder (where `main.py` and `requirements.txt` live):

```bash
sudo apt update
sudo apt install -y python3-venv python3-pip ffmpeg

python3 -m venv .venv
source .venv/bin/activate

python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### If you see: `ModuleNotFoundError: No module named 'aiortc'`

It means `aiortc` is not installed in the Python environment you’re running.

- Make sure the venv is active: `source .venv/bin/activate`
- Install dependencies: `python -m pip install -r requirements.txt`

Verify you installed into the **same** Python you run:

```bash
source .venv/bin/activate
python -V
python -m pip -V
python -m pip show aiortc
python -c "import aiortc; print('aiortc OK', aiortc.__version__)"
```

If `python -m pip show aiortc` shows nothing, it isn’t installed in that environment.

> Note (Windows vs Raspberry Pi): this script is meant to run on the Raspberry Pi.
> If you’re testing on Windows, use Windows commands (e.g. `py -m pip install -r requirements.txt`)
> and run with `py main.py ...`.

### If `pip install aiortc` fails (missing build deps)

On Raspberry Pi OS, you may need native build libraries:

If you see errors like:
- `failed with error code 1` while installing `cffi`

start by installing the compiler + Python headers + libffi:

```bash
sudo apt install -y build-essential python3-dev pkg-config libffi-dev
```

Then (often needed for WebRTC/TLS/media):

```bash
sudo apt install -y build-essential python3-dev pkg-config \
  libssl-dev libffi-dev \
  libsrtp2-dev \
  libavcodec-dev libavdevice-dev libavformat-dev libavutil-dev libswscale-dev libswresample-dev
```

Then retry inside the venv:

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Firebase service account JSON

The browser uses Firebase Hosting client SDK, but this Python publisher needs server credentials.

1. Firebase Console → Project Settings → Service accounts
2. Generate a new **private key** JSON
3. Copy it onto the Raspberry Pi (keep it private)

## Run

### Option A (recommended): Browser creates room, Pi joins

1. Open the web UI, click **Open camera & microphone**, then **Create room**.
2. Copy the room ID.
3. On the Raspberry Pi:

```bash
python3 main.py \
  --service-account /home/pi/ugv_software/service-akey.json \
  --join borhan \
  --device /dev/video0
```

### Option B: Pi creates room, browser joins

On the Raspberry Pi:

```bash
python3 main.py \
  --service-account /home/pi/firebase-service-account.json \
  --create
```

The script prints a room ID. In the browser, click **Join room** and paste that ID.

## Camera tuning

Use `--width`, `--height`, `--fps` if your webcam needs it:

```bash
python3 main.py --service-account ... --join <ROOM_ID> --width 1280 --height 720 --fps 30
```


# New install 

## install
```sudo apt update && sudo apt upgrade -y```

```sudo apt install python3 python3-pip v4l-utils -y```

```python3 -m pip install aiortc firebase-admin```

```pip install opencv-python```

### 1️⃣ Install the venv tool if missing
```sudo apt install python3-venv -y```

### 2️⃣ Create a virtual environment
```python3 -m venv ~/webrtc-env```

### 3️⃣ Activate it
```source ~/webrtc-env/bin/activate```

### 4️⃣ Now install packages inside the virtual env
```pip install aiortc firebase-admin```

### Run python 
```python3 webrtc_streamer_firebase.py --room-id borhan12```

### add firebase json
```/home/pi/serviceAccountKey.json```