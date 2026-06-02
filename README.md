
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

### Run python 
```python3 main.py --room-id borhan12```

### Run without --room-id (default uses MAC)
```python3 main.py```

### Run without --room-id but use a random room id (published to MQTT)
```python3 main.py --use-mac-room-id false```

### add firebase json
```/home/pi/serviceAccountKey.json```

### test ip
```192.168.24.42```