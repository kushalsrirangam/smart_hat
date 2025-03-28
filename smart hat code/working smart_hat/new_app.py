# Smart Hat Backend Server
# Features:
# - Real-time ultrasonic monitoring with voice alerts
# - Battery level check with spoken warning
# - Configurable thresholds via web UI
# - Firebase logging (optional)
# - Flask SocketIO-based communication with phone/browser

from flask import Flask, request, jsonify, Response, render_template_string, send_from_directory, redirect
import subprocess
import os
import json
import threading
import cv2
import numpy as np
import tflite_runtime.interpreter as tflite
from picamera2 import Picamera2
from datetime import datetime
import time
import lgpio
import psutil
import requests
import signal
import shutil

# --- Firebase Admin Setup ---
import firebase_admin
from firebase_admin import credentials, firestore
from flask_socketio import SocketIO, emit

# Initialize Firebase and Flask app
cred = credentials.Certificate('/home/ada/de/smartaid-6c5c0-firebase-adminsdk-fbsvc-cee03b08da.json')
firebase_admin.initialize_app(cred)
db = firestore.client()

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

# --- Configuration Files and Global State ---
CONFIG_FILE = "/home/ada/de/detection/config.json"
LOG_DIR = "/home/ada/de/logs"
os.makedirs(LOG_DIR, exist_ok=True)

voice_alert_enabled = True
health_status = "OK"
detection_active = True

# Default configuration structure
config_data = {
    "filter_classes": ["person"],
    "logging": True,
    "ultrasonic_thresholds": {
        "Left Front": 70,
        "Left Middle": 70,
        "Left Rear": 70,
        "Right Front": 70,
        "Right Middle": 70,
        "Right Rear": 70
    }
}

# Sensor pin mapping (BCM GPIO numbering)
SENSORS = {
    "Left Front":  {"trigger": 4,  "echo": 17},
    "Left Middle": {"trigger": 27, "echo": 22},
    "Left Rear":   {"trigger": 23, "echo": 24},
    "Right Front": {"trigger": 5,  "echo": 6},
    "Right Middle": {"trigger": 12, "echo": 13},
    "Right Rear":   {"trigger": 19, "echo": 26}
}

CHIP = 4  # GPIO chip index
ultrasonic_readings = {}
last_ultra_speak_time = {}  # Used to throttle repeated alerts

# --- Utility Functions ---

def push_message_to_clients(message):
    """Send a real-time message to connected web clients."""
    socketio.emit('speak', {'message': message})

def measure_distance(h, trig, echo, timeout=0.02):
    """Measure distance using an ultrasonic sensor."""
    lgpio.gpio_write(h, trig, 1)
    time.sleep(0.00001)
    lgpio.gpio_write(h, trig, 0)
    start = time.time()
    timeout_start = time.time()
    while lgpio.gpio_read(h, echo) == 0:
        start = time.time()
        if time.time() - timeout_start > timeout:
            return "No Echo"
    timeout_start = time.time()
    while lgpio.gpio_read(h, echo) == 1:
        stop = time.time()
        if time.time() - timeout_start > timeout:
            return "Echo Timeout"
    elapsed = stop - start
    distance = (elapsed * 34300) / 2
    return round(distance, 2) if 2 < distance < 400 else "Out of Range"

# --- Background Loops ---

def ultrasonic_loop():
    """Continuously monitor all ultrasonic sensors and trigger alerts."""
    global ultrasonic_readings, health_status
    h = lgpio.gpiochip_open(CHIP)
    for s in SENSORS.values():
        lgpio.gpio_claim_output(h, s["trigger"])
        lgpio.gpio_claim_input(h, s["echo"])
    try:
        while True:
            now = time.time()
            failed = []
            readings = {}
            for name, pin in SENSORS.items():
                dist = measure_distance(h, pin["trigger"], pin["echo"])
                readings[name] = dist
                threshold = config_data.get("ultrasonic_thresholds", {}).get(name, 100)

                if isinstance(dist, (int, float)) and dist < threshold:
                    if voice_alert_enabled and now - last_ultra_speak_time.get(name, 0) > 4:
                        push_message_to_clients(f"Obstacle on {'left' if 'Left' in name else 'right'} at {dist} cm")
                        last_ultra_speak_time[name] = now
                        # vibration feedback skipped (no motor hardware connected)
                elif isinstance(dist, str):
                    failed.append(name)
            ultrasonic_readings = readings
            health_status = "OK" if not failed else f"Sensor fault: {', '.join(failed)}"
            time.sleep(1)
    except Exception as e:
        print("[Ultrasonic Error]", e)
    finally:
        lgpio.gpiochip_close(h)

def battery_monitor():
    """Check battery and alert user if it's low."""
    warned = False
    while True:
        battery = psutil.sensors_battery()
        percent = battery.percent if battery else 100
        if percent <= 20 and not warned:
            push_message_to_clients("Battery low. Please charge Smart Hat.")
            warned = True
        if percent > 30:
            warned = False
        time.sleep(60)

def detection_loop():
    """Placeholder for object detection loop."""
    while True:
        if not detection_active:
            time.sleep(1)
            continue
        # Add AI detection logic here
        time.sleep(0.2)

# --- Flask API Endpoints ---

@app.route("/")
def index():
    return redirect("/control_panel")

@app.route("/control_panel")
def control_panel():
    return "Smart Hat UI Loaded"

@app.route("/status")
def get_status():
    battery = psutil.sensors_battery()
    return jsonify({
        "battery": battery.percent if battery else -1,
        "health": health_status,
        "detection_active": detection_active
    })

@app.route("/start", methods=["POST"])
def start_detection():
    global detection_active
    detection_active = True
    return jsonify({"status": "Detection started"})

@app.route("/stop", methods=["POST"])
def stop_detection():
    global detection_active
    detection_active = False
    return jsonify({"status": "Detection stopped"})

@app.route("/voice_alert_toggle", methods=["POST"])
def voice_toggle():
    global voice_alert_enabled
    voice_alert_enabled = request.json.get("enabled", True)
    return jsonify({"voice_alert_enabled": voice_alert_enabled})

@app.route("/config", methods=["POST"])
def update_config():
    global config_data
    data = request.get_json()
    config_data.update(data)
    with open(CONFIG_FILE, "w") as f:
        json.dump(config_data, f)
    return jsonify({"status": "config updated", "config": config_data})

@app.route("/speak", methods=["POST"])
def speak():
    msg = request.json.get("message", "")
    push_message_to_clients(msg)
    return jsonify({"status": "spoken", "message": msg})

@app.route("/reset_wifi", methods=["POST"])
def reset_wifi():
    try:
        config_path = "/etc/wpa_supplicant/wpa_supplicant.conf"
        backup_path = f"{config_path}.bak"
        if os.path.exists(config_path):
            shutil.move(config_path, backup_path)
        os.system("sudo reboot")
        return jsonify({"message": "Wi-Fi reset. Rebooting..."})
    except Exception as e:
        return jsonify({"message": f"Failed: {e}"})

# --- Background Thread Launch ---
if __name__ == '__main__':
    threading.Thread(target=ultrasonic_loop, daemon=True).start()
    threading.Thread(target=battery_monitor, daemon=True).start()
    threading.Thread(target=detection_loop, daemon=True).start()
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
