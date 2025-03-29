# Smart Hat Backend Server with ngrok Integration
# Features:
# - Real-time ultrasonic monitoring with voice alerts
# - Battery level check with spoken warning
# - Configurable thresholds via web UI
# - AI object detection using TFLite + Picamera2
# - Firebase + Flask SocketIO + ngrok tunnel

from flask import Flask, request, jsonify, redirect, render_template_string, Response
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

# Initialize Firebase
if not firebase_admin._apps:
    cred = credentials.Certificate('/home/ada/de/smartaid-6c5c0-firebase-adminsdk-fbsvc-cee03b08da.json')
    firebase_admin.initialize_app(cred, {
        'databaseURL': 'https://smartaid-6c5c0-default-rtdb.firebaseio.com/',
        'storageBucket': 'smartaid-6c5c0.firebasestorage.app'
    })

# Flask + SocketIO
app = Flask(__name__)
app.config["PROPAGATE_EXCEPTIONS"] = True
app.config["DEBUG"] = True
socketio = SocketIO(app, cors_allowed_origins="*")

db = firestore.client()

frame_lock = threading.Lock()

# Global states
health_status = "OK"
detection_active = True
config_data = {"indoor_mode": False}


# --- Configuration Files and Global Paths ---


LABEL_PATH = "/home/ada/de/coco_labels.txt"
MODEL_PATH = "/home/ada/de/mobilenet_v2.tflite"
CONFIG_FILE = "/home/ada/de/detection/config.json"


voice_alert_enabled = True
health_status = "OK"
detection_active = True
normalSize = (2028, 1520)
lowresSize = (300, 300)

latest_frame = None
frame_lock = threading.Lock()   # ✅ Add this here!
indoor_mode = False


# --- Dash Setup ---
dash_app = Dash(__name__, server=app, url_base_pathname='/analytics/', external_stylesheets=[dbc.themes.DARKLY])
dash_app.title = "Smart Hat Analytics"

# Dash auto-refresh interval
_dash_interval = dcc.Interval(id='interval', interval=10*1000, n_intervals=0)

dash_app.layout = dbc.Container(fluid=True, children=[
    html.H1("Smart Hat Analytics Dashboard", className="text-center my-4"),
    _dash_interval,  # Interval to auto-update graphs
    # Battery Level Graph
    dcc.Graph(id='battery-graph'),
    # Ultrasonic Sensor Data Graph
    dcc.Graph(id='ultrasonic-graph'),
    # System Health Metrics Graph
    dcc.Graph(id='system-health-graph'),
    # Motion Status Graph
    dcc.Graph(id='motion-status-graph'),
    # Detection Logs Graph (Bar and Pie)
    dcc.Graph(id='detection-log-graph'),
    # System Health Data (Heatmap)
    dcc.Graph(id='system-health-heatmap')
])

# --- Callback for Battery Level ---
@dash_app.callback(
    Output('battery-graph', 'figure'),
    Input('interval', 'n_intervals')
)
def update_battery(n):
    df = fetch_battery_data()
    if df.empty or 'timestamp' not in df.columns or 'battery_percentage' not in df.columns:
        return px.line()
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', errors='coerce')
    return px.line(df, x='timestamp', y='battery_percentage', title='Battery Level Over Time')

# --- Callback for Ultrasonic Data ---
@dash_app.callback(
    Output('ultrasonic-graph', 'figure'),
    Input('interval', 'n_intervals')
)
def update_ultrasonic_data(n):
    df = fetch_ultrasonic_data()
    if df.empty or 'timestamp' not in df.columns:
        return px.line()
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', errors='coerce')
    return px.line(df, x='timestamp', y=df.columns.difference(['timestamp']), title='Ultrasonic Sensor Data')

# --- Callback for System Health ---
@dash_app.callback(
    Output('system-health-graph', 'figure'),
    Input('interval', 'n_intervals')
)
def update_system_health(n):
    df = fetch_system_health_data()
    if df.empty or 'timestamp' not in df.columns:
        return px.line()
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', errors='coerce')
    return px.line(df, x='timestamp', y=['cpu', 'memory', 'temperature'], title='System Health Metrics')

@dash_app.callback(
    Output('motion-graph', 'figure'),
    Input('interval', 'n_intervals')
)
def update_motion_status(n):
    df = fetch_motion_data()
    if df.empty or 'timestamp' not in df.columns:
        fig = px.line()
        fig.add_annotation(text="No motion data available", x=0.5, y=0.5, showarrow=False)
        return fig

    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', errors='coerce')
    df['motion_value'] = df['motion_status'].apply(lambda x: 1 if x == 'active' else 0)
    df = df.sort_values('timestamp')

    return px.step(df, x='timestamp', y='motion_value', title='Motion Status Over Time', labels={'motion_value': 'Motion (1=Active)'})

# --- Callback for Motion Status ---
@dash_app.callback(
    Output('motion-status-graph', 'figure'),
    Input('interval', 'n_intervals')
)
def update_motion_status(n):
    df = fetch_motion_data()
    if df.empty or 'timestamp' not in df.columns:
        return px.line()
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', errors='coerce')
    return px.line(df, x='timestamp', y='motion_status', title='Motion Status Over Time')

# --- Callback for Detection Logs ---
@dash_app.callback(
    Output('detection-log-graph', 'figure'),
    Input('interval', 'n_intervals')
)
def update_detection_log(n):
    df = fetch_detection_data()
    if df.empty or 'timestamp' not in df.columns:
        return px.bar()
    return px.bar(df, x='timestamp', y='detection_count', title='Detections Over Time')


def fetch_motion_data():
    motion_ref = db.collection('motion_logs')
    docs = [doc.to_dict() for doc in motion_ref.stream()]
    return pd.DataFrame(docs) if docs else pd.DataFrame()


def fetch_battery_data():
    battery_ref = db.collection('battery_logs')
    docs = [doc.to_dict() for doc in battery_ref.stream()]
    print("Battery logs:", docs)
    return pd.DataFrame(docs) if docs else pd.DataFrame()

def fetch_ultrasonic_data():
    ultrasonic_ref = db.collection('ultrasonic_logs')
    docs = [doc.to_dict() for doc in ultrasonic_ref.stream()]
    print("Ultrasonic logs:", docs)
    rows = []
    for doc in docs:
        if 'timestamp' in doc and 'readings' in doc:
            row = {'timestamp': doc['timestamp']}
            row.update(doc['readings'])
            rows.append(row)
    return pd.DataFrame(rows) if rows else pd.DataFrame()

def fetch_system_health_data():
    system_ref = db.collection('system_health_logs')
    docs = [doc.to_dict() for doc in system_ref.stream()]
    print("System health logs:", docs)
    return pd.DataFrame(docs) if docs else pd.DataFrame()

def fetch_detection_data():
    detection_ref = db.collection('detection_logs')
    docs = [doc.to_dict() for doc in detection_ref.stream()]
    print("Detection logs:", docs)
    if not docs:
        return pd.DataFrame()
    df = pd.DataFrame(docs)
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms', errors='coerce')
    df['detection_count'] = 1
    df = df.dropna(subset=['timestamp'])
    return df.groupby(pd.Grouper(key='timestamp', freq='1min')).sum().reset_index()


# --- Flask route for control panel UI ---
@app.route('/')
def home():
    try:
        with open("/home/ada/de/app_server/control_panel.html", "r") as f:
            html = f.read()
        return render_template_string(html)
    except Exception as e:
        return f"Error loading control panel: {e}"


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
        lgpio.gpiochip_close(h)
# --- Example for logging with standardized timestamps ---
def battery_monitor():
    warned = False
    while True:
        battery = psutil.sensors_battery()
        percent = battery.percent if battery else 100

        # 🔋 Log to Firestore with standardized timestamp
        db.collection('battery_logs').add({
            'timestamp': int(time.time() * 1000),  # Standardized to milliseconds
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
        
def clear_all_logs():
    collections = [
        'battery_logs',
        'ultrasonic_logs',
        'motion_logs',
        'detection_logs',
        'location_logs',
        'system_health_logs'
    ]
    for col in collections:
        docs = db.collection(col).stream()
        deleted = 0
        for doc in docs:
            doc.reference.delete()
            deleted += 1
        print(f"[CLEAR] Deleted {deleted} documents from {col}")




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

    # Record the video for the specified duration
    for _ in range(int(duration_sec * fps)):
        frame = picam2.capture_array("main")
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
    interpreter = tflite.Interpreter(model_path=MODEL_PATH)
    interpreter.allocate_tensors()
    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()

    last_video_time = 0
    last_speak_time = 0
    picam2 = None  # so we can safely stop in finally block

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

                    now = time.time()

                    # Only speak every 5 seconds
                    if now - last_speak_time > 5:
                        push_message_to_clients(f"{label} detected")
                        last_speak_time = now

                    db.collection('detection_logs').add({
                        'timestamp': int(now * 1000),
                        'label': label,
                        'confidence': float(scores[i]),
                        'bounding_box': {
                            'x1': x1, 'y1': y1, 'x2': x2, 'y2': y2
                        }
                    })

                    box_area = (x2 - x1) * (y2 - y1)
                    frame_area = normalSize[0] * normalSize[1]
                    rel_size = box_area / frame_area

                    if rel_size > 0.10 and 'person' in label.lower() and (now - last_video_time > 10):
                        threading.Thread(target=record_video, args=(picam2,), daemon=True).start()
                        last_video_time = now

            ret, jpeg = cv2.imencode('.jpg', frame)
            if ret:
                with frame_lock:
                    latest_frame = jpeg.tobytes()

    except Exception as e:
        print("[Detection Error]", e)
    finally:
        if picam2:
            try:
                picam2.stop()
            except Exception as e:
                print("[Cleanup Error]", e)


# --- API Routes ---


@app.route("/shutdown", methods=["POST"])
def shutdown_pi():
    try:
        subprocess.run(["sudo", "shutdown", "now"], check=False)
        return jsonify({"message": "Shutdown command sent."})
    except Exception as e:
        return jsonify({"message": f"Shutdown failed: {e}"}), 500


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
        print("[LOG] Location data received:", data)  # Debug print
        lat = data.get('lat')
        lng = data.get('lng')
        speed = data.get('speed')
        distance = data.get('distance')
        timestamp = int(time.time() * 1000)  # Millisecond precision

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
        print("[ERROR] Failed to log location:", e)
        return jsonify({"status": "error", "message": str(e)}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/motion", methods=["POST"])
def receive_motion():
    data = request.get_json()
    motion = data.get("moving")
    global motion_active
    motion_active = motion
    db.collection('motion_logs').add({
        'timestamp': int(time.time() * 1000),
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
            'ultrasonic_logs',
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

# --- Start Flask with Ngrok ---
if __name__ == "__main__":
    try:
        ngrok_proc = start_ngrok()

        # Start background services
        threading.Thread(target=ultrasonic_loop, daemon=True).start()
        threading.Thread(target=battery_monitor, daemon=True).start()
        threading.Thread(target=detection_loop, daemon=True).start()
        threading.Thread(target=system_metrics_monitor, daemon=True).start()

        socketio.run(app, host="0.0.0.0", port=5000, debug=False, use_reloader=False, allow_unsafe_werkzeug=True)

    except KeyboardInterrupt:
        print("[INFO] KeyboardInterrupt detected. Shutting down gracefully...")

        if 'ngrok_proc' in locals():
            ngrok_proc.terminate()
            print("[NGROK] Tunnel closed")
