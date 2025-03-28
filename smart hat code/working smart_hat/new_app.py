from flask import Flask, request, jsonify, Response, render_template_string, send_from_directory, redirect
import subprocess
import os
import json
import threading
import cv2
import numpy as np
import tflite_runtime.interpreter as tflite
from picamera2 import Picamera2, Platform
from datetime import datetime
import time
import lgpio
import psutil
import requests

# --- Firebase Admin Setup ---
import firebase_admin
from firebase_admin import credentials, firestore
cred = credentials.Certificate('/home/ada/de/smartaid-6c5c0-firebase-adminsdk-fbsvc-cee03b08da.json')
firebase_admin.initialize_app(cred)
db = firestore.client()

app = Flask(__name__)

# Paths & Configurations
CONFIG_FILE = "/home/ada/de/detection/config.json"
MODEL_PATH = "/home/ada/de/mobilenet_v2.tflite"
LABEL_PATH = "/home/ada/de/coco_labels.txt"
PANEL_PATH = "/home/ada/de/app_server"
VIDEO_LOG_DIR = "/home/ada/de/videolog"
LOG_DIR = "/home/ada/de/logs"
UNIFIED_LOG_FILE = f"{LOG_DIR}/unified_log.csv"

normalSize = (1920, 1080)
lowresSize = (300, 300)
latest_frame = None
frame_lock = threading.Lock()

DETECTION_THRESHOLD_CM = 10
TTS_ENDPOINT = "http://localhost:5000/speak"
voice_alert_enabled = True

CHIP = 4
SENSORS = {
    "Left Front":  {"trigger": 4,  "echo": 17},
    "Left Middle": {"trigger": 27, "echo": 22},
    "Left Rear":   {"trigger": 23, "echo": 24},
    "Right Front": {"trigger": 5,  "echo": 6},
    "Right Middle": {"trigger": 12, "echo": 13},
    "Right Rear":   {"trigger": 19, "echo": 26}
}

ultrasonic_readings = {}
detection_active = True
config_data = {"filter_classes": ["person"], "logging": True}

os.makedirs(VIDEO_LOG_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)
if not os.path.exists(UNIFIED_LOG_FILE):
    with open(UNIFIED_LOG_FILE, "w") as f:
        f.write("timestamp,event_type,label,confidence,estimated_distance_cm,ultrasonic_cm,actual_distance_cm,sensor_side,FPS,CPU,MEM,TEMP,video_filename,action,issue\n")

def read_label_file(file_path):
    with open(file_path, 'r') as f:
        lines = f.readlines()
    return {int(line.split()[0]): line.strip().split(maxsplit=1)[1] for line in lines}

def calculate_distance(actual_width, focal_length, bounding_box_width):
    if bounding_box_width == 0:
        return float('inf')
    return (actual_width * focal_length) / bounding_box_width

def measure_distance(h, trigger_pin, echo_pin, timeout=0.02):
    lgpio.gpio_write(h, trigger_pin, 1)
    time.sleep(0.00001)
    lgpio.gpio_write(h, trigger_pin, 0)
    start_time = time.time()
    stop_time = time.time()
    timeout_start = time.time()
    while lgpio.gpio_read(h, echo_pin) == 0:
        start_time = time.time()
        if time.time() - timeout_start > timeout:
            return "No Echo"
    timeout_start = time.time()
    while lgpio.gpio_read(h, echo_pin) == 1:
        stop_time = time.time()
        if time.time() - timeout_start > timeout:
            return "Echo Timeout"
    time_elapsed = stop_time - start_time
    distance = (time_elapsed * 34300) / 2
    if distance <= 2 or distance > 400:
        return "Out of Range"
    return round(distance, 2)

def ultrasonic_loop():
    global ultrasonic_readings
    h = lgpio.gpiochip_open(CHIP)
    for sensor in SENSORS.values():
        lgpio.gpio_claim_output(h, sensor["trigger"])
        lgpio.gpio_claim_input(h, sensor["echo"])
    try:
        while True:
            readings = {}
            for name, sensor in SENSORS.items():
                dist = measure_distance(h, sensor["trigger"], sensor["echo"])
                readings[name] = dist
            ultrasonic_readings = readings
            time.sleep(0.2)
    except Exception as e:
        print("[Ultrasonic Error]", e)
    finally:
        lgpio.gpiochip_close(h)

def detection_loop():
    global latest_frame, detection_active

    labels = read_label_file(LABEL_PATH)
    interpreter = tflite.Interpreter(model_path=MODEL_PATH)
    interpreter.allocate_tensors()
    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()

    picam2 = Picamera2()
    stream_format = "YUV420"
    if Picamera2.platform == Platform.PISP:
        stream_format = "RGB888"

    camera_config = picam2.create_preview_configuration(
        main={"size": normalSize},
        lores={"size": lowresSize, "format": stream_format}
    )
    picam2.configure(camera_config)
    picam2.start()

    try:
        while True:
            if not detection_active:
                time.sleep(0.5)
                continue

            img = picam2.capture_array("lores")
            if stream_format == "YUV420":
                img = cv2.cvtColor(img, cv2.COLOR_YUV420p2RGB)

            resized_img = cv2.resize(img, (input_details[0]['shape'][2], input_details[0]['shape'][1]))
            input_tensor = np.expand_dims(resized_img, axis=0)
            interpreter.set_tensor(input_details[0]['index'], input_tensor)
            interpreter.invoke()

            boxes = interpreter.get_tensor(output_details[0]['index'])[0]
            classes = interpreter.get_tensor(output_details[1]['index'])[0]
            scores = interpreter.get_tensor(output_details[2]['index'])[0]

            frame = picam2.capture_array("main")
            output_frame = frame.copy()
            for i in range(len(scores)):
                if scores[i] > 0.5:
                    ymin, xmin, ymax, xmax = boxes[i]
                    class_id = int(classes[i])
                    label = labels.get(class_id, f"id:{class_id}")
                    cv2.putText(output_frame, label, (int(xmin*normalSize[0]), int(ymin*normalSize[1])), cv2.FONT_HERSHEY_SIMPLEX, 1, (255,255,255), 2)

            ret, jpeg = cv2.imencode('.jpg', output_frame)
            if ret:
                with frame_lock:
                    latest_frame = jpeg.tobytes()

    except Exception as e:
        print(f"[Detection Error] {e}")
    finally:
        picam2.stop()

@app.route("/")
def index():
    return redirect("/control_panel")

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'), 'favicon.ico', mimetype='image/vnd.microsoft.icon')

@app.route('/manifest.json')
def manifest():
    return send_from_directory('static', 'manifest.json')

@app.route('/service-worker.js')
def service_worker():
    return send_from_directory('static', 'service-worker.js')

@app.route('/video_feed')
def video_feed():
    def generate():
        while True:
            with frame_lock:
                if latest_frame is None:
                    continue
                frame = latest_frame
            yield (b'--frame\r\n' b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
            time.sleep(0.5)
    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/feed')
def feed_panel():
    return redirect("/control_panel")

@app.route('/control_panel')
def control_panel():
    try:
        with open(os.path.join(PANEL_PATH, "control_panel.html"), "r") as f:
            html = f.read()
        return render_template_string(html)
    except Exception as e:
        return f"Error loading control panel: {e}"

@app.route('/start', methods=['POST'])
def start_detection():
    global detection_active
    detection_active = True
    return jsonify({"status": "Detection started"})

@app.route('/stop', methods=['POST'])
def stop_detection():
    global detection_active
    detection_active = False
    return jsonify({"status": "Detection stopped"})

@app.route('/status', methods=['GET'])
def status():
    return jsonify({"detection_active": detection_active})

@app.route('/voice_alert_toggle', methods=['POST'])
def alias_voice_toggle():
    return toggle_voice_alert()

@app.route('/voice_alert', methods=['POST'])
def toggle_voice_alert():
    global voice_alert_enabled
    data = request.get_json()
    voice_alert_enabled = data.get("enabled", True)
    return jsonify({"voice_alert_enabled": voice_alert_enabled})

@app.route('/config', methods=['POST'])
def update_config():
    global config_data
    data = request.get_json()
    config_data.update(data)
    with open(CONFIG_FILE, 'w') as f:
        json.dump(config_data, f)
    return jsonify({"status": "Configuration updated", "config": config_data})

@app.route('/log', methods=['GET'])
def get_log():
    try:
        logs = db.collection('detections').order_by('timestamp', direction=firestore.Query.DESCENDING).limit(10).stream()
        log_list = [json.dumps(log.to_dict()) for log in logs]
        return jsonify(log_list[::-1])
    except Exception as e:
        return jsonify({"error": str(e)})

@app.route('/speak', methods=['POST'])
def speak_message():
    message = request.json.get("message", "")
    print(f"[TTS] Message: {message}")
    return jsonify({"status": "spoken", "message": message})

def start_ngrok():
    try:
        process = subprocess.Popen(["ngrok", "http", "5000"])
        print("[NGROK] Tunnel started at http://localhost:4040")
        return process
    except FileNotFoundError:
        print("[NGROK] Ngrok not found. Make sure it's installed and in PATH.")
        return None

if __name__ == '__main__':
    ngrok_proc = start_ngrok()
    try:
        threading.Thread(target=ultrasonic_loop, daemon=True).start()
        threading.Thread(target=detection_loop, daemon=True).start()
        from flask_socketio import SocketIO
        socketio = SocketIO(app)
        socketio.run(app, host='0.0.0.0', port=5000, debug=True, allow_unsafe_werkzeug=True, use_reloader=False)
    finally:
        if ngrok_proc:
            ngrok_proc.terminate()
            print("[NGROK] Process terminated")
