from flask import Flask, Response, render_template_string
from flask_socketio import SocketIO
from flask_cors import CORS
import subprocess
import time

app = Flask(__name__)
CORS(app)  # Allow cross-origin access
socketio = SocketIO(app, cors_allowed_origins="*")  # WebSocket support

# Function to capture frames using rpicam-vid with AI model
def generate_frames(camera_id, use_ai=False):
    command = [
        "rpicam-vid",  
        "--camera", str(camera_id),
        "--width", "1920", "--height", "1080",
        "--framerate", "30",
        "--codec", "mjpeg",
        "--timeout", "0",  
        "-o", "-"
    ]

    if use_ai:
        command += ["--post-process-file", "/usr/share/rpi-camera-assets/imx500_mobilenet_ssd.json"]

    try:
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=10**8)
        while True:
            frame = process.stdout.read(40960)  
            if not frame:
                print(f"⚠️ Camera {camera_id} stopped. Restarting...")
                process.kill()
                time.sleep(2)
                break  

            yield (b'--frame\r\n'
                   b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')

    except Exception as e:
        print(f"❌ Error with Camera {camera_id}: {e}")
    finally:
        process.kill()


# 🏠 Web Interface with Video Streams
@app.route('/')
def home():
    return render_template_string('''
    <html>
    <head>
        <title>Raspberry Pi Camera Stream</title>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/socket.io/4.0.1/socket.io.js"></script>
        <script>
            var socket = io.connect('http://' + document.domain + ':' + location.port);
            
            function sendCommand(command) {
                socket.emit('control_command', {cmd: command});
            }

            socket.on('ai_status', function(data) {
                document.getElementById("ai_status").innerText = data.status;
            });
        </script>
        <style>
            body { text-align: center; font-family: Arial, sans-serif; }
            h1, h3 { color: #333; }
            img { border: 2px solid black; }
            .container { display: flex; justify-content: center; gap: 20px; }
        </style>
    </head>
    <body>
        <h1>📷 Raspberry Pi Camera Streaming</h1>
        
        <h3>Live Streams:</h3>
        <div class="container">
            <div>
                <h4>🔍 AI Camera:</h4>
                <img id="ai_stream" src="{{ url_for('ai_camera') }}" width="640" height="480">
            </div>

            <div>
                <h4>🌙 Night Vision Camera:</h4>
                <img id="night_stream" src="{{ url_for('night_camera') }}" width="640" height="480">
            </div>
        </div>

        <h3>📡 AI Model Status: <span id="ai_status">Waiting...</span></h3>
        <button onclick="sendCommand('start_ai')">Start AI Processing</button>
        <button onclick="sendCommand('stop_ai')">Stop AI Processing</button>
    </body>
    </html>
    ''')


# 🎥 AI Camera Stream (With Object Detection)
@app.route('/ai_camera')
def ai_camera():
    return Response(generate_frames(0, use_ai=True), mimetype="multipart/x-mixed-replace; boundary=frame")


# 🌙 Night Vision Camera Stream
@app.route('/night_camera')
def night_camera():
    return Response(generate_frames(1, use_ai=False), mimetype="multipart/x-mixed-replace; boundary=frame")


# 🔄 Handle WebSocket Events
@socketio.on('control_command')
def handle_control_command(data):
    command = data.get('cmd', '')
    
    if command == "start_ai":
        print("✅ Starting AI processing...")
        socketio.emit('ai_status', {'status': 'AI Enabled'})
    
    elif command == "stop_ai":
        print("⛔ Stopping AI processing...")
        socketio.emit('ai_status', {'status': 'AI Disabled'})


# 🚀 Run Flask with WebSocket Support
if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5000, debug=True, allow_unsafe_werkzeug=True, use_reloader=False)
