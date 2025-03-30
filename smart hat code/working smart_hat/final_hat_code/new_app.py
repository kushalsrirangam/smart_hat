# Smart Hat Backend Server with ngrok Integration
# Updated to support modular JS/CSS and static file serving

from flask import Flask, request, jsonify, redirect, render_template_string, Response, send_from_directory
import subprocess, os, json, threading, cv2, numpy as np, time, lgpio, psutil, shutil, requests, socket
import tflite_runtime.interpreter as tflite
from picamera2 import Picamera2
from datetime import datetime
import pandas as pd
from dash import Dash, dcc, html, Input, Output
import dash_bootstrap_components as dbc
import plotly.express as px
from flask_socketio import SocketIO
import firebase_admin
from firebase_admin import credentials, firestore, storage
import subprocess
import time
import threading


# Initialize Firebase
if not firebase_admin._apps:
    cred = credentials.Certificate('/home/ada/de/smartaid-6c5c0-firebase-adminsdk-fbsvc-cee03b08da.json')
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://smartaid-6c5c0-default-rtdb.firebaseio.com/',
        'storageBucket': 'smartaid-6c5c0.appspot.com'
    })

# Flask app setup
app = Flask(__name__, static_folder="/home/ada/de/app_server/web_app")
app.config["PROPAGATE_EXCEPTIONS"] = True
app.config["DEBUG"] = True
socketio = SocketIO(app, cors_allowed_origins="*")

db = firestore.client()

frame_lock = threading.Lock()

# Global config
health_status = "OK"
detection_active = True
config_data = {"indoor_mode": False}
LABEL_PATH = "/home/ada/de/coco_labels.txt"
MODEL_PATH = "/home/ada/de/mobilenet_v2.tflite"
CONFIG_FILE = "/home/ada/de/detection/config.json"
voice_alert_enabled = True
normalSize = (2028, 1520)
lowresSize = (300, 300)
latest_frame = None
indoor_mode = False
logging_paused = False  # ✅ Define it once here, no need for global outside




# --- Static file and UI routes ---
@app.route('/')
def index():
    return redirect('/control_panel')

@app.route('/control_panel')
def serve_control_panel():
    return send_from_directory(app.static_folder, 'control_panel.html')

@app.route('/<path:filename>')
def serve_static(filename):
    return send_from_directory(app.static_folder, filename)

# --- Remaining backend logic and routes unchanged ---
voice_alert_enabled = True
health_status = "OK"
detection_active = True
normalSize = (2028, 1520)
lowresSize = (300, 300)

latest_frame = None
frame_lock = threading.Lock()   # ✅ Add this here!
indoor_mode = False


from dash import Dash, dcc, html, Input, Output
import dash_bootstrap_components as dbc
import plotly.express as px
import pandas as pd

# Dash setup
dash_app = Dash(__name__, server=app, url_base_pathname='/analytics/', external_stylesheets=[dbc.themes.DARKLY])
dash_app.title = "Smart Hat Analytics"

# Refresh interval
_dash_interval = dcc.Interval(id='interval', interval=10*1000, n_intervals=0)

# Layout with 6 graphs
dash_app.layout = dbc.Container(fluid=True, children=[
    html.H2("Smart Hat Analytics Dashboard", className="text-center my-4"),
    _dash_interval,
    dbc.Row([
        dbc.Col(dcc.Graph(id='battery-graph'), md=6),
        dbc.Col(dcc.Graph(id='ultrasonic-graph'), md=6),
    ], className="mb-4"),
    dbc.Row([
        dbc.Col(dcc.Graph(id='system-health-graph'), md=6),
        dbc.Col(dcc.Graph(id='motion-status-graph'), md=6),
    ], className="mb-4"),
    dbc.Row([
        dbc.Col(dcc.Graph(id='detection-log-graph'), md=6),
        dbc.Col(dcc.Graph(id='system-health-heatmap'), md=6),
    ], className="mb-4")
])

# --- CALLBACKS ---

@dash_app.callback(Output('battery-graph', 'figure'), Input('interval', 'n_intervals'))
def update_battery(n):
    df = fetch_battery_data()
    if df.empty or 'battery_percentage' not in df.columns:
        return px.line(title="No battery data available")
    df['formatted_time'] = df['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')
    return px.line(df, x='formatted_time', y='battery_percentage', title='Battery Level Over Time')

@dash_app.callback(Output('ultrasonic-graph', 'figure'), Input('interval', 'n_intervals'))
def update_ultrasonic(n):
    df = fetch_ultrasonic_data()
    if df.empty or df.shape[1] <= 1:
        return px.line(title="No ultrasonic data available")
    df['formatted_time'] = df['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')
    return px.line(df, x='formatted_time', y=df.columns.drop(['timestamp', 'formatted_time']), title='Ultrasonic Sensor Readings')

@dash_app.callback(Output('system-health-graph', 'figure'), Input('interval', 'n_intervals'))
def update_system_health(n):
    df = fetch_system_health_data()
    if df.empty:
        return px.line(title="No system health data")
    cols = [col for col in ['cpu', 'memory', 'temperature'] if col in df.columns]
    if not cols:
        return px.line(title="No system metrics available")
    df['formatted_time'] = df['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')
    return px.line(df, x='formatted_time', y=cols, title='System Health Over Time')

@dash_app.callback(Output('motion-status-graph', 'figure'), Input('interval', 'n_intervals'))
def update_motion(n):
    df = fetch_motion_data()
    if df.empty or 'motion_status' not in df.columns:
        return px.line(title="No motion data")
    df['motion_binary'] = df['motion_status'].apply(lambda x: 1 if str(x).lower() == 'active' else 0)
    df['formatted_time'] = df['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')
    return px.line(df, x='formatted_time', y='motion_binary', title='Motion Activity Over Time')

@dash_app.callback(Output('detection-log-graph', 'figure'), Input('interval', 'n_intervals'))
def update_detection_log(n):
    df = fetch_detection_data()
    if df.empty or 'detection_count' not in df.columns:
        return px.bar(title="No detection log available")
    df['formatted_time'] = df['timestamp'].dt.strftime('%Y-%m-%d %H:%M:%S')
    return px.bar(df, x='formatted_time', y='detection_count', title='Detections Over Time')

@dash_app.callback(Output('system-health-heatmap', 'figure'), Input('interval', 'n_intervals'))
def update_health_heatmap(n):
    df = fetch_system_health_data()
    if df.empty or 'timestamp' not in df.columns:
        return px.imshow([[0]], title="No heatmap data available")
    df.set_index('timestamp', inplace=True)
    df = df.select_dtypes(include='number')
    return px.imshow(df.T, aspect='auto', color_continuous_scale='Viridis', title='System Health Heatmap')

# --- FETCH FUNCTIONS ---

def fetch_motion_data():
    if logging_paused:
        return pd.DataFrame()
    try:
        docs = [doc.to_dict() for doc in db.collection('motion_logs').stream()]
        df = pd.DataFrame(docs)
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', errors='coerce')
            df = df.dropna(subset=['timestamp'])
        return df
    except Exception as e:
        print("[Fetch Error] Motion:", e)
        return pd.DataFrame()


def fetch_battery_data():
    if logging_paused:
        return pd.DataFrame()
    try:
        docs = [doc.to_dict() for doc in db.collection('battery_logs').stream()]
        df = pd.DataFrame(docs)
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', errors='coerce')
            df = df.dropna(subset=['timestamp'])
        return df
    except Exception as e:
        print("[Fetch Error] Battery:", e)
        return pd.DataFrame()


def fetch_ultrasonic_data():
    if logging_paused:
        return pd.DataFrame()
    try:
        docs = [doc.to_dict() for doc in db.collection('ultrasonic_logs').stream()]
        rows = []
        for doc in docs:
            if 'timestamp' in doc and 'readings' in doc:
                row = {'timestamp': doc['timestamp']}
                row.update(doc['readings'])
                rows.append(row)
        df = pd.DataFrame(rows)
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', errors='coerce')
            df = df.dropna(subset=['timestamp'])
        return df
    except Exception as e:
        print("[Fetch Error] Ultrasonic:", e)
        return pd.DataFrame()


def fetch_system_health_data():
    if logging_paused:
        return pd.DataFrame()
    try:
        docs = [doc.to_dict() for doc in db.collection('system_health_logs').stream()]
        df = pd.DataFrame(docs)
        if 'timestamp' in df.columns:
            df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', errors='coerce')
            df = df.dropna(subset=['timestamp'])
        return df
    except Exception as e:
        print("[Fetch Error] System Health:", e)
        return pd.DataFrame()


def fetch_detection_data():
    if logging_paused:
        return pd.DataFrame()
    try:
        docs = [doc.to_dict() for doc in db.collection('detection_logs').stream()]
        df = pd.DataFrame(docs)
        if 'timestamp' not in df.columns:
            return pd.DataFrame()
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', errors='coerce')
        df = df.dropna(subset=['timestamp'])
        df['detection_count'] = 1
        return df.groupby(pd.Grouper(key='timestamp', freq='1min')).sum(numeric_only=True).reset_index()
    except Exception as e:
        print("[Fetch Error] Detection:", e)
        return pd.DataFrame()


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
motion_active = False  # Track motion status
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


def ultrasonic_loop():
    global logging_paused, health_status, ultrasonic_readings

    h = None

    try:
        h = lgpio.gpiochip_open(4)
        for s in SENSORS.values():
            try:
                lgpio.gpio_free(h, s["trigger"])
                lgpio.gpio_free(h, s["echo"])
            except:
                pass
            lgpio.gpio_claim_output(h, s["trigger"])
            lgpio.gpio_claim_input(h, s["echo"])

        while True:
            if logging_paused:
                print("[ULTRASONIC] Skipping log due to paused flag")
                time.sleep(1)
                continue

            now = time.time()
            failed = []
            readings = {}
            successful_readings = 0

            for name, pin in SENSORS.items():
                dist = measure_distance(h, pin["trigger"], pin["echo"])
                readings[name] = dist if isinstance(dist, (int, float)) else None
                threshold = config_data.get("ultrasonic_thresholds", {}).get(name, 100)

                if isinstance(dist, (int, float)):
                    successful_readings += 1
                    if (ultrasonic_voice_enabled and voice_alert_enabled and not config_data.get("indoor_mode", False)
                        and dist < threshold and now - last_ultra_speak_time.get(name, 0) > 4):
                        push_message_to_clients(f"Obstacle on {'left' if 'Left' in name else 'right'} at {dist} cm")
                        last_ultra_speak_time[name] = now
                else:
                    failed.append(name)

            if successful_readings == 0:
                print("[SKIP] All ultrasonic sensors failed — not logging this cycle.")
                health_status = "All sensors unresponsive"

                if ultrasonic_voice_enabled and voice_alert_enabled and not config_data.get("indoor_mode", False) and now - last_ultra_speak_time.get("all_failed", 0) > 10:
                    push_message_to_clients("All ultrasonic sensors are offline. Please check connections.")
                    last_ultra_speak_time["all_failed"] = now

                time.sleep(1)
                continue

            ultrasonic_readings = readings
            db.collection('ultrasonic_logs').add({
                'timestamp': int(time.time() * 1000),
                'readings': readings,
                'faults': failed
            })
            health_status = "OK" if not failed else f"Sensor fault: {', '.join(failed)}"
            time.sleep(1)

    except Exception as e:
        print("[Ultrasonic Error]", e)
    finally:
        if h is not None:
            try:
                lgpio.gpiochip_close(h)
            except Exception as e:
                print("[ULTRASONIC] Failed to close gpiochip:", e)



# --- Example for logging with standardized timestamps ---
def battery_monitor():
    warned = False
    while True:
        battery = psutil.sensors_battery()
        percent = battery.percent if battery else 100

        # 🔋 Log to Firestore with standardized timestamp
        db.collection('battery_logs').add({
            'timestamp': int(time.time() * 1000),
            'readable_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            'battery_percentage': percent
})
        if percent <= 20 and not warned:
            push_message_to_clients("Battery low. Please charge Smart Hat.")
            warned = True
        if percent > 30:
            warned = False

        time.sleep(60)  # Log every minute

        
def system_metrics_monitor():
    while True:
        usage = {
            "timestamp": int(time.time() * 1000),
            "cpu": psutil.cpu_percent(),
            "memory": psutil.virtual_memory().percent,
            "temperature": psutil.sensors_temperatures().get("cpu-thermal", [{}])[0].get("current", 0)
        }
        db.collection("system_health_logs").add(usage)
        time.sleep(60)
        
def clear_all_logs(keys=None):
    global logging_paused
    logging_paused = True
    print("[LOGGING] Paused during log deletion")

    all_collections = {
        'battery_logs': 'Battery Logs',
        #'ultrasonic_logs': 'Ultrasonic Logs',
        'motion_logs': 'Motion Logs',
        'detection_logs': 'Detection Logs',
        'location_logs': 'Location Logs',
        'system_health_logs': 'System Health Logs',
        'video_logs': 'Video Logs'
    }

    if not keys or keys == ['all']:
        keys = list(all_collections.keys())

    deleted_summary = []

    for col in keys:
        if col not in all_collections:
            print(f"[SKIP] Unknown collection: {col}")
            continue

        docs = db.collection(col).stream()
        deleted = 0
        for doc in docs:
            doc.reference.delete()
            deleted += 1

        print(f"[CLEAR] Deleted {deleted} documents from {col}")
        deleted_summary.append(all_collections[col])

    logging_paused = False
    print("[LOGGING] Resumed after log deletion")
    return deleted_summary



# --- Video Recording and Upload ---
def record_video(picam2, duration_sec=2, fps=30):
    # Define the directory where videos are saved
    video_dir = "/home/ada/de/videos"

    # Ensure the directory exists, if not create it
    if not os.path.exists(video_dir):
        os.makedirs(video_dir)

    # Generate filename with a timestamp
    filename = f"{video_dir}/alert_{int(time.time())}.avi"

    # Initialize the video writer with XVID codec
    fourcc = cv2.VideoWriter_fourcc(*'XVID')
    out = cv2.VideoWriter(filename, fourcc, fps, normalSize)

    # Record the video for the specified duration with bounding boxes
    labels = read_label_file(LABEL_PATH)
    interpreter = tflite.Interpreter(model_path=MODEL_PATH)
    interpreter.allocate_tensors()
    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()

    for _ in range(int(duration_sec * fps)):
        lores = picam2.capture_array("lores")
        frame = picam2.capture_array("main")

        # Run inference
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

        out.write(frame)
        time.sleep(1 / fps)

    out.release()

    # Now upload the video to Firebase Storage
    bucket = storage.bucket()
    blob = bucket.blob(f"videos/{filename.split('/')[-1]}")
    blob.upload_from_filename(filename)
    blob.make_public()  # Make the file publicly accessible
    print(f"[VIDEO] Uploaded to Firebase Storage: {blob.public_url}")

    # Save metadata in Firestore
    db.collection('video_logs').add({
    'timestamp': int(time.time() * 1000),
    'readable_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    'video_url': blob.public_url  # Store public URL to access the video
})

    # Delete the video file from Raspberry Pi after upload
    if os.path.exists(filename):
        os.remove(filename)  # Delete the video file from the Pi
        print(f"[VIDEO] Deleted local video file: {filename}")
    else:
        print(f"[ERROR] Video file not found for deletion: {filename}")

def upload_to_firebase_storage(local_filename, remote_filename):
    bucket = storage.bucket()
    blob = bucket.blob(remote_filename)
    blob.upload_from_filename(local_filename)
    blob.make_public()
    print(f"File uploaded to {blob.public_url}")



def detection_loop():
    global latest_frame, detection_active
    labels = read_label_file(LABEL_PATH)
    
    # Initialize interpreter once
    try:
        interpreter = tflite.Interpreter(model_path=MODEL_PATH)
        interpreter.allocate_tensors()
        input_details = interpreter.get_input_details()
        output_details = interpreter.get_output_details()
    except Exception as e:
        print("[ERROR] Failed to load TFLite model:", e)
        return

    last_video_time = 0
    last_speak_time = 0
    last_log_time = 0

    try:
        # Initialize camera once
        picam2 = Picamera2()
        camera_config = picam2.create_preview_configuration(
            main={"size": normalSize, "format": "RGB888"},
            lores={"size": lowresSize, "format": "RGB888"}
        )
        picam2.configure(camera_config)
        picam2.start()
        time.sleep(2)
        print("[CAMERA] Camera initialized successfully.")

        while True:
            if not detection_active:
                time.sleep(0.5)
                continue

            try:
                lores = picam2.capture_array("lores")
                frame = picam2.capture_array("main")
                display_frame = frame.copy()
            except Exception as e:
                print("[CAMERA ERROR] Frame capture failed:", e)
                continue

            try:
                resized = cv2.resize(lores, (input_details[0]['shape'][2], input_details[0]['shape'][1]))
                input_tensor = np.expand_dims(resized, axis=0).astype(np.uint8)
                interpreter.set_tensor(input_details[0]['index'], input_tensor)

                t0 = time.time()
                interpreter.invoke()
                print(f"[INFERENCE] Time: {time.time() - t0:.3f}s")

                boxes = interpreter.get_tensor(output_details[0]['index'])[0]
                classes = interpreter.get_tensor(output_details[1]['index'])[0]
                scores = interpreter.get_tensor(output_details[2]['index'])[0]
            except Exception as e:
                print("[INFERENCE ERROR]", e)
                continue

            now = time.time()

            allowed_labels = (["person", "tv", "chair", "bed"]
                              if config_data.get("indoor_mode", False)
                              else config_data.get("filter_classes", []))

            for i in range(len(scores)):
                if scores[i] > 0.5:
                    try:
                        ymin, xmin, ymax, xmax = boxes[i]
                        class_id = int(classes[i])
                        label = labels.get(class_id, f"id:{class_id}")

                        if label.lower() not in [x.lower() for x in allowed_labels]:
                            continue

                        x1 = max(0, int(xmin * normalSize[0]))
                        y1 = max(0, int(ymin * normalSize[1]))
                        x2 = min(normalSize[0], int(xmax * normalSize[0]))
                        y2 = min(normalSize[1], int(ymax * normalSize[1]))

                        if x2 <= x1 or y2 <= y1:
                            print(f"[SKIP] Invalid bounding box: ({x1},{y1}) to ({x2},{y2})")
                            continue

                        # Draw bounding box
                        cv2.rectangle(display_frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                        cv2.putText(display_frame, f"{label} ({scores[i]*100:.1f}%)", (x1, y1 - 10),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)

                        message = {
                            "person": "Person ahead, stay alert",
                            "car": "Car ahead, please wait before moving",
                            "dog": "Dog nearby, proceed cautiously"
                        }.get(label.lower(), f"{label} detected")

                        if now - last_speak_time > 5 and voice_alert_enabled and not config_data.get("indoor_mode", False):
                            push_message_to_clients(message)
                            last_speak_time = now

                        db.collection('detection_logs').add({
                            'timestamp': int(now * 1000),
                            'readable_time': datetime.fromtimestamp(now).strftime('%Y-%m-%d %H:%M:%S'),
                            'label': label,
                            'confidence': float(scores[i]),
                            'bounding_box': {'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2},
                            'source': 'camera',
                            'spoken_message': message if now - last_speak_time == 0 else ""
                        })

                        box_area = (x2 - x1) * (y2 - y1)
                        frame_area = normalSize[0] * normalSize[1]
                        rel_size = box_area / frame_area

                        if rel_size > 0.10 and 'person' in label.lower() and (now - last_video_time > 10):
                            video_frame_copy = display_frame.copy()
                            threading.Thread(target=record_video_with_frame, args=(video_frame_copy,), daemon=True).start()
                            last_video_time = now
                    except Exception as e:
                        print("[DETECTION LOOP ERROR]", e)
                        continue

            # Always draw a test box (debug)
            cv2.rectangle(display_frame, (50, 50), (200, 200), (255, 0, 0), 2)
            cv2.putText(display_frame, "TestBox", (60, 45), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)

            try:
                ret, jpeg = cv2.imencode('.jpg', display_frame)
                if ret:
                    with frame_lock:
                        latest_frame = jpeg.tobytes()
            except Exception as e:
                print("[FRAME ENCODE ERROR]", e)

            if now - last_log_time > 5:
                print("[DETECTION] Loop active...")
                last_log_time = now

    except Exception as e:
        print("[DETECTION THREAD ERROR]", e)
    finally:
        try:
            picam2.stop()
        except Exception as e:
            print("[CAMERA CLEANUP ERROR]", e)


# --- API Routes ---


@app.route("/shutdown", methods=["POST"])
def shutdown_pi():
    try:
        subprocess.run(["sudo", "shutdown", "now"], check=False)
        return jsonify({"message": "Shutdown command sent."})
    except Exception as e:
        return jsonify({"message": f"Shutdown failed: {e}"}), 500


@app.route("/video_feed")
def video_feed():
    def generate():
        while True:
            with frame_lock:
                if latest_frame is None:
                    continue
                frame = latest_frame
            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
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
        print("[LOG] Location data received:", data)
        lat = data.get('lat')
        lng = data.get('lng')
        speed = data.get('speed')
        distance = data.get('distance')
        timestamp = int(time.time() * 1000)

        db.collection('location_logs').add({
            'lat': lat,
            'lng': lng,
            'speed_kmh': speed,
            'distance_m': distance,
            'timestamp': timestamp,
            'readable_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        })
        return jsonify({"status": "success"}), 200
    except Exception as e:
        print("[ERROR] Failed to log location:", e)
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/motion", methods=["POST"])
def receive_motion():
    data = request.get_json()
    motion = data.get("moving")
    global motion_active
    motion_active = motion
    db.collection('motion_logs').add({
        'timestamp': int(time.time() * 1000),
        'readable_time': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'motion_status': 'active' if motion else 'inactive'
    })
    return jsonify({"status": "received", "motion": motion})

@app.route("/latest_video_url")
def latest_video_url():
    try:
        with open("/home/ada/de/latest_video.txt", "r") as f:
            url = f.read().strip()
        return jsonify({"url": url})
    except:
        return jsonify({"url": ""})
        
@app.route("/delete_logs", methods=["POST"])
def delete_logs():
    try:
        collections = [
            'battery_logs',
            #'ultrasonic_logs',
            'motion_logs',
            'detection_logs',
            'location_logs',
            'system_health_logs',
            'video_logs'
        ]
        for col in collections:
            docs = db.collection(col).stream()
            for doc in docs:
                doc.reference.delete()
        return jsonify({"status": "success", "message": "All logs deleted."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})
        


# --- Ngrok Tunnel ---

# Make sure `socketio` and `app` are already defined somewhere above

def start_flask():
    print("[FLASK] Starting Flask app...")
    socketio.run(app, host="0.0.0.0", port=5000, debug=False, use_reloader=False, allow_unsafe_werkzeug=True)

def start_ngrok():
    try:
        time.sleep(5)  # Give Flask time to bind to port 5000

        print("[NGROK] Launching tunnel to https://smartaid.ngrok.io ...")
        process = subprocess.Popen([
            "ngrok", "http", "--domain=smartaid.ngrok.io", "5000"
        ], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # Optional: Wait a bit and check logs for troubleshooting
        time.sleep(5)
        # Show last 10 lines of ngrok log for debugging (optional)
        print("[NGROK] Tunnel started. Check dashboard or browser: https://smartaid.ngrok.io")

        return process
    except Exception as e:
        print(f"[NGROK] Failed to start: {e}")
        return None

if __name__ == "__main__":
    try:
        # Start Flask server in a separate thread
        flask_thread = threading.Thread(target=start_flask, daemon=True)
        flask_thread.start()

        # Start ngrok after Flask binds
        ngrok_proc = start_ngrok()

        # Start your background monitoring threads
        threading.Thread(target=ultrasonic_loop, daemon=True).start()
        threading.Thread(target=battery_monitor, daemon=True).start()
        threading.Thread(target=detection_loop, daemon=True).start()
        threading.Thread(target=system_metrics_monitor, daemon=True).start()

        # Keep the main thread alive
        while True:
            time.sleep(10)

    except KeyboardInterrupt:
        print("[INFO] KeyboardInterrupt detected. Shutting down gracefully...")

        if 'ngrok_proc' in locals() and ngrok_proc:
            ngrok_proc.terminate()
            print("[NGROK] Tunnel closed")

