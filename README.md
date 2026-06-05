
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