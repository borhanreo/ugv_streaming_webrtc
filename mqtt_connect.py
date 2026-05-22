# ============================================
# MQTT Connection Example - Raspberry Pi
# Author: MD Borhan Uddin
# ============================================

import paho.mqtt.client as mqtt

# --- MQTT Broker Configuration ---
BROKER = "emq.safeprotechnologiesportal.com"   # You can replace this with your broker's IP or hostname
PORT = 1883  
USERNAME = "safeproMQTT"  # Replace with your MQTT username
PASSWORD = "safepro)*-&$@911@74R^"  # Replace with your MQTT password
TOPIC = "v301/raspberrypi/test"     # Your topic name
CLIENT_ID = "RaspberryPiClient"  # A unique client ID

# --- Callback when the client connects to broker ---
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("✅ Connected successfully to MQTT Broker!")
        client.subscribe(TOPIC)
    else:
        print(f"❌ Failed to connect, return code {rc}")

# --- Callback when a message is received ---
def on_message(client, userdata, msg):
    print(f"📩 Received: {msg.payload.decode()} from topic: {msg.topic}")

# --- Create an MQTT client instance ---
client = mqtt.Client(CLIENT_ID)

# Attach callback functions
client.on_connect = on_connect
client.on_message = on_message

# --- Connect to the broker ---
print("🔌 Connecting to MQTT Broker...")
client.connect(BROKER, PORT, keepalive=60)

# --- Publish a test message ---
client.publish(TOPIC, "Hello from Raspberry Pi ✅")

# --- Keep the client running and listening for messages ---
try:
    print("📡 Listening for messages... Press Ctrl+C to exit.")
    client.loop_forever()
except KeyboardInterrupt:
    print("\n🔒 Disconnecting from broker...")
    client.disconnect()