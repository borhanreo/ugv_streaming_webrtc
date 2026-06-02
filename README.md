
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



### add firebase json
```/home/pi/serviceAccountKey.json```

### Run python 
```python3 main.py --room-id borhan12```

### Run without --room-id (default uses MAC)
```python3 main.py```

### Run without --room-id but use a random room id (published to MQTT)
```python3 main.py --use-mac-room-id false```

### test ip
```192.168.24.42```


# Auto starty in Rpi

```sudo nano /usr/local/bin/start_gcs_ugv.sh```
<pre>
#!/bin/bash
#!--------------------------------------
#!Script: start_firebase_and_proxy.sh
#!Purpose: Start Firebase and then Proxy Server
#!--------------------------------------
cd /home/pi/ugv/ugv_streaming_webrtc || exit
#! 1️⃣ Start FGCS-UGV and wait until it exits
echo "Starting Firebase GCS..."
cd /home/pi/ugv/ugv_streaming_webrtc
#! Active env
source ~/webrtc-env/bin/activate
python3 main.py --use-mac-room-id false
echo "Firebase Done"
#! 2️⃣ Start proxy server only after Firebase process completes
</pre>

## Permission
```sudo chmod +x /usr/local/bin/start_gcs_ugv.sh```

### for systemctk  service
```sudo nano /etc/systemd/system/acs_ugv.service```

###⚡ Step 3 – Enable and Start the Service
 #### load file to systemctl

```sudo systemctl daemon-reload```

```sudo systemctl enable acs_ugv.service```

```sudo systemctl start acs_ugv.service```

```sudo systemctl status acs_ugv.service```

```sudo systemctl restart acs_ugv.service```