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

# --- Firebase Admin Setup ---
import firebase_admin
from firebase_admin import credentials, firestore
cred = credentials.Certificate('/home/ada/de/app_server/smart-hat-4002d-firebase-adminsdk-fbsvc-51ab38bd62.json')
firebase_admin.initialize_app(cred)
db = firestore.client()

app = Flask(__name__)

# Paths & Configurations
CONFIG_FILE = "/home/ada/de/detection/config.json"
MODEL_PATH = "/home/ada/de/mobilenet_v2.tflite"
LABEL_PATH = "/home/ada/de/coco_labels.txt"
PANEL_PATH = "/home/ada/de/app_server"
VIDEO_LOG_DIR = "/home/ada/de/videolog"
PERF_LOG_FILE = "/home/ada/de/logs/performance_log.csv"

normalSize = (1920, 1080)
lowresSize = (300, 300)
latest_frame = None
frame_lock = threading.Lock()

detection_active = True
config_data = {"filter_classes": ["person"], "logging": True}

os.makedirs(VIDEO_LOG_DIR, exist_ok=True)
os.makedirs("/home/ada/de/logs", exist_ok=True)
if not os.path.exists(PERF_LOG_FILE):
    with open(PERF_LOG_FILE, "w") as f:
        f.write("timestamp,event,label,actual_distance_cm,estimated_distance_cm,ultrasonic_cm,confidence,FPS,issue\n")

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

def read_label_file(file_path):
    with open(file_path, 'r') as f:
        lines = f.readlines()
    return {int(line.split()[0]): line.strip().split(maxsplit=1)[1] for line in lines}

def load_config():
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    return {"filter_classes": ["person"], "logging": True}

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

@app.route("/")
def index():
    return "<h1>Welcome to the Detection App</h1>"

@app.route('/favicon.ico')
def favicon():
    return send_from_directory(os.path.join(app.root_path, 'static'),
                               'favicon.ico', mimetype='image/vnd.microsoft.icon')

@app.route('/video_feed')
def video_feed():
    def generate():
        while True:
            with frame_lock:
                if latest_frame is None:
                    continue
                frame = latest_frame
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
            time.sleep(0.5)
    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/stream')
def stream():
    return """<html><head><title>Detection Video Stream</title></head>
              <body><h1>Live Video Feed</h1><img src='/video_feed' width='640' height='480'></body></html>"""

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
    os.system(f"espeak '{message}'")
    return jsonify({"status": "spoken", "message": message})

def ultrasonic_loop():
    global ultrasonic_readings
    h = lgpio.gpiochip_open(CHIP)
    for sensor in SENSORS.values():
        lgpio.gpio_claim_output(h, sensor["trigger"])
        lgpio.gpio_claim_input(h, sensor["echo"])
    try:
        while True:
            temp_readings = {}
            for name, sensor in SENSORS.items():
                dist = measure_distance(h, sensor["trigger"], sensor["echo"])
                temp_readings[name] = dist
            ultrasonic_readings = temp_readings
            time.sleep(0.2)
    except Exception as e:
        print("[Ultrasonic Error]", e)
    finally:
        lgpio.gpiochip_close(h)

def detection_loop():
    global latest_frame
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

    video_frames = []
    video_start_time = time.time()
    fps = 10

    try:
        while True:
            if not detection_active:
                time.sleep(0.5)
                continue

            loop_start = time.time()

            try:
                img = picam2.capture_array("lores")
                if stream_format == "YUV420":
                    img = cv2.cvtColor(img, cv2.COLOR_YUV420p2RGB)
                height, width = input_details[0]['shape'][1:3]
                img_resized = cv2.resize(img, (width, height)).astype(np.uint8)
                input_data = np.expand_dims(img_resized, axis=0)
                interpreter.set_tensor(input_details[0]['index'], input_data)
                interpreter.invoke()

                boxes = interpreter.get_tensor(output_details[0]['index'])[0]
                classes = interpreter.get_tensor(output_details[1]['index'])[0]
                scores = interpreter.get_tensor(output_details[2]['index'])[0]
                num_detections = int(interpreter.get_tensor(output_details[3]['index'])[0])

                frame = picam2.capture_array("main")
                if len(frame.shape) == 3 and frame.shape[2] == 4:
                    frame = cv2.cvtColor(frame, cv2.COLOR_BGRA2BGR)
                output_frame = frame.copy()

                for i in range(num_detections):
                    score = scores[i]
                    if score > 0.5:
                        class_id = int(classes[i])
                        label = labels.get(class_id, f"id:{class_id}")
                        if label in config_data.get("filter_classes", []):
                            ymin, xmin, ymax, xmax = boxes[i]
                            xmin = int(xmin * normalSize[0])
                            xmax = int(xmax * normalSize[0])
                            ymin = int(ymin * normalSize[1])
                            ymax = int(ymax * normalSize[1])
                            cv2.rectangle(output_frame, (xmin, ymin), (xmax, ymax), (0, 255, 0), 2)
                            cv2.putText(output_frame, f"{label} {score:.2f}", (xmin, ymin - 10),
                                        cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)

                            box_width = xmax - xmin
                            distance = calculate_distance(50, 800, box_width)
                            cv2.putText(output_frame, f"{distance:.2f} cm", (xmin, ymax + 30),
                                        cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 255), 2)

                            if distance < 10:
                                os.system("espeak 'Warning, object too close, please stop.'")

                            if config_data.get("logging", True):
                                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                                log_entry = {
                                    "timestamp": timestamp,
                                    "label": label,
                                    "score": float(round(score, 2)),
                                    "bbox": [xmin, ymin, xmax, ymax],
                                    "distance_cm": distance,
                                    "sensors": ultrasonic_readings.copy()
                                }
                                try:
                                    db.collection('detections').add(log_entry)
                                except Exception as e:
                                    print("Error writing to Firestore:", e)

                            loop_end = time.time()
                            fps_val = 1.0 / (loop_end - loop_start)
                            ultra_val = ultrasonic_readings.get("Left Front", "N/A")
                            perf_log = f"{datetime.now()},detection,{label},N/A,{distance},{ultra_val},{score:.2f},{fps_val:.2f},ok\n"
                            with open(PERF_LOG_FILE, "a") as f:
                                f.write(perf_log)

                ret, jpeg = cv2.imencode('.jpg', output_frame)
                if ret:
                    with frame_lock:
                        latest_frame = jpeg.tobytes()

                if int(time.time()) % 20 == 0:
                    cpu = psutil.cpu_percent()
                    mem = psutil.virtual_memory().percent
                    temp = subprocess.check_output(["vcgencmd", "measure_temp"]).decode().strip().split('=')[1]
                    with open(PERF_LOG_FILE, "a") as f:
                        f.write(f"{datetime.now()},system_stats,N/A,N/A,N/A,N/A,N/A,N/A,CPU:{cpu}%, MEM:{mem}%, TEMP:{temp}\n")

            except Exception as e:
                print(f"[Detection Error] {e}")

    except KeyboardInterrupt:
        print("[Detection] Stopped")
    finally:
        picam2.stop()

if __name__ == '__main__':
    threading.Thread(target=ultrasonic_loop, daemon=True).start()
    threading.Thread(target=detection_loop, daemon=True).start()
    from flask_socketio import SocketIO
    socketio = SocketIO(app)
    socketio.run(app, host='0.0.0.0', port=5000, debug=True, allow_unsafe_werkzeug=True, use_reloader=False)
