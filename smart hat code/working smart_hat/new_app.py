# Smart Hat Backend Server with ngrok Integration
# Features:
# - Real-time ultrasonic monitoring with voice alerts
# - Battery level check with spoken warning
# - Configurable thresholds via web UI
# - AI object detection using TFLite + Picamera2
# - Firebase + Flask SocketIO + ngrok tunnel

from flask import Flask, request, jsonify, redirect, render_template_string, Response
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
import shutil
import requests  # <-- Added for ngrok tunnel fetch

# --- Firebase Admin Setup ---
import firebase_admin
from firebase_admin import credentials, firestore
from flask_socketio import SocketIO

# Initialize Firebase and Flask app
cred = credentials.Certificate('/home/ada/de/smartaid-6c5c0-firebase-adminsdk-fbsvc-cee03b08da.json')
firebase_admin.initialize_app(cred)
db = firestore.client()

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

# --- Configuration Files and Global State ---
CONFIG_FILE = "/home/ada/de/detection/config.json"
LABEL_PATH = "/home/ada/de/coco_labels.txt"
MODEL_PATH = "/home/ada/de/mobilenet_v2.tflite"

voice_alert_enabled = True
health_status = "OK"
detection_active = True
normalSize = (2028, 1520)
lowresSize = (300, 300)
latest_frame = None
frame_lock = threading.Lock()

# Default config
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

SENSORS = {
    "Left Front":  {"trigger": 4,  "echo": 17},
    "Left Middle": {"trigger": 27, "echo": 22},
    "Left Rear":   {"trigger": 23, "echo": 24},
    "Right Front": {"trigger": 5,  "echo": 6},
    "Right Middle": {"trigger": 12, "echo": 13},
    "Right Rear":   {"trigger": 19, "echo": 26}
}

CHIP = 4
ultrasonic_readings = {}
last_ultra_speak_time = {}

# --- Utility Functions ---
def read_label_file(path):
    with open(path, 'r') as f:
        return {int(line.split()[0]): line.strip().split(maxsplit=1)[1] for line in f}

def push_message_to_clients(message):
    socketio.emit('speak', {'message': message})

def measure_distance(h, trig, echo, timeout=0.02):
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

# --- Background Threads ---
def ultrasonic_loop():
    global ultrasonic_readings, health_status
    try:
        h = lgpio.gpiochip_open(CHIP)
        for s in SENSORS.values():
            try:
                lgpio.gpio_free(h, s["trigger"])
                lgpio.gpio_free(h, s["echo"])
            except:
                pass
            lgpio.gpio_claim_output(h, s["trigger"])
            lgpio.gpio_claim_input(h, s["echo"])

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
    global latest_frame, detection_active
    labels = read_label_file(LABEL_PATH)
    interpreter = tflite.Interpreter(model_path=MODEL_PATH)
    interpreter.allocate_tensors()
    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()

    while True:
        if not detection_active:
            time.sleep(0.5)
            continue

        try:
            picam2 = Picamera2()
            camera_config = picam2.create_preview_configuration(
                main={"size": normalSize, "format": "RGB888"},
                lores={"size": lowresSize, "format": "RGB888"}
            )
            picam2.configure(camera_config)
            picam2.start()
            break
        except Exception as e:
            print(f"[Camera Retry] {e}")
            time.sleep(10)

    try:
        while True:
            lores = picam2.capture_array("lores")
            frame = picam2.capture_array("main")

            resized = cv2.resize(lores, (input_details[0]['shape'][2], input_details[0]['shape'][1]))
            input_tensor = np.expand_dims(resized, axis=0)
            interpreter.set_tensor(input_details[0]['index'], input_tensor)
            interpreter.invoke()

            boxes = interpreter.get_tensor(output_details[0]['index'])[0]
            classes = interpreter.get_tensor(output_details[1]['index'])[0]
            scores = interpreter.get_tensor(output_details[2]['index'])[0]

            for i in range(len(scores)):
                if scores[i] > 0.5:
                    ymin, xmin, ymax, xmax = boxes[i]
                    class_id = int(classes[i])
                    label = labels.get(class_id, f"id:{class_id}")
                    x1, y1 = int(xmin * normalSize[0]), int(ymin * normalSize[1])
                    x2, y2 = int(xmax * normalSize[0]), int(ymax * normalSize[1])
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    cv2.putText(frame, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)

            ret, jpeg = cv2.imencode('.jpg', frame)
            if ret:
                with frame_lock:
                    latest_frame = jpeg.tobytes()

    except Exception as e:
        print("[Detection Error]", e)
    finally:
        picam2.stop()

# --- API Routes ---
@app.route("/")
def index():
    return redirect("/control_panel")

@app.route("/control_panel")
def control_panel():
    try:
        with open("/home/ada/de/app_server/control_panel.html", "r") as f:
            html = f.read()
        return render_template_string(html)
    except Exception as e:
        return f"Error loading control panel: {e}"

@app.route("/video_feed")
def video_feed():
    def generate():
        while True:
            with frame_lock:
                if latest_frame is None:
                    continue
                frame = latest_frame
            yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
            time.sleep(0.05)
    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

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

@app.route('/log_location', methods=['POST'])
def log_location():
    try:
        data = request.get_json()
        lat = data.get('lat')
        lng = data.get('lng')
        speed = data.get('speed')
        distance = data.get('distance')
        timestamp = datetime.utcnow().isoformat()

        # Create Firestore document
        db.collection('location_logs').add({
            'lat': lat,
            'lng': lng,
            'speed_kmh': speed,
            'distance_m': distance,
            'timestamp': timestamp
        })
        return jsonify({"status": "success"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/motion", methods=["POST"])
def receive_motion():
    data = request.get_json()
    motion = data.get("moving")
    global motion_active
    motion_active = motion
    return jsonify({"status": "received", "motion": motion})

# --- Ngrok Tunnel ---
def start_ngrok():
    try:
        process = subprocess.Popen([
            "ngrok", "http", "--domain=smartaid.ngrok.io", "5000"
        ])
        time.sleep(3)
        print("[NGROK] Public URL: https://smartaid.ngrok.io")
        return process
    except Exception as e:
        print(f"[NGROK] Failed to start: {e}")
        return None

# --- Start Services ---
def run_flask_and_ngrok():
    def run_ngrok_when_ready():
        time.sleep(5)
        ngrok_proc = start_ngrok()
        if ngrok_proc:
            app.ngrok_proc = ngrok_proc

    threading.Thread(target=ultrasonic_loop, daemon=True).start()
    threading.Thread(target=battery_monitor, daemon=True).start()
    threading.Thread(target=detection_loop, daemon=True).start()
    threading.Thread(target=run_ngrok_when_ready, daemon=True).start()
    socketio.run(app, host='0.0.0.0', port=5000, debug=False, use_reloader=False, allow_unsafe_werkzeug=True)

try:
    run_flask_and_ngrok()
except KeyboardInterrupt:
    if hasattr(app, "ngrok_proc"):
        app.ngrok_proc.terminate()
        print("[NGROK] Tunnel closed")
