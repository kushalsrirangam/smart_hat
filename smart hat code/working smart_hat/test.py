from flask import Flask, Response
from picamera2 import Picamera2, Platform
import cv2
import numpy as np
import tflite_runtime.interpreter as tflite
from threading import Lock
import time

app = Flask(__name__)
frame_lock = Lock()
latest_frame = None

# Camera Setup
normalSize = (2028, 1520)
lowresSize = (300, 300)
LABEL_PATH = "/home/ada/de/coco_labels.txt"
MODEL_PATH = "/home/ada/de/mobilenet_v2.tflite"

def read_label_file(path):
    with open(path, 'r') as f:
        return {int(l.split()[0]): l.strip().split(maxsplit=1)[1] for l in f.readlines()}

def detection_loop():
    global latest_frame
    labels = read_label_file(LABEL_PATH)
    interpreter = tflite.Interpreter(model_path=MODEL_PATH)
    interpreter.allocate_tensors()
    input_details = interpreter.get_input_details()
    output_details = interpreter.get_output_details()

    picam2 = Picamera2()
    camera_config = picam2.create_preview_configuration(
        main={"size": normalSize, "format": "RGB888"},
        lores={"size": lowresSize, "format": "RGB888"}
    )
    picam2.configure(camera_config)
    picam2.start()

    try:
        while True:
            frame = picam2.capture_array("main")
            lores = picam2.capture_array("lores")

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
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0,255,0), 2)
                    cv2.putText(frame, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 1, (255,255,255), 2)

            _, jpeg = cv2.imencode('.jpg', frame)
            with frame_lock:
                latest_frame = jpeg.tobytes()
    except Exception as e:
        print("[Detection Error]", e)
    finally:
        picam2.stop()

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
            time.sleep(0.05)
    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')

@app.route('/')
def index():
    return '<h1>Smart Hat Video Stream</h1><img src="/video_feed">'

if __name__ == '__main__':
    from threading import Thread
    Thread(target=detection_loop, daemon=True).start()
    app.run(host='0.0.0.0', port=5000)
