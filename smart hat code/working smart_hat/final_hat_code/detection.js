// detection.js - Updated with Quiet Mode Support

const detectionModes = {
  home: [
    "person", "dog", "cat", "tv", "remote", "refrigerator", "microwave",
    "chair", "couch", "bed", "tree", "backpack", "cell phone", "umbrella"
  ],
  public: [
    "person", "car", "bus", "bicycle", "motorcycle", "traffic light", "stop sign",
    "bench", "truck", "tree", "backpack", "cell phone", "umbrella"
  ]
};

let lastDetectionMessage = "";
let quietMode = false;  // Flag for quiet mode
const socket = io(window.location.origin);

socket.on('speak', (data) => {
  if (data.message && !quietMode) {
    console.log("Speaking:", data.message);
    lastDetectionMessage = data.message;
    speak(data.message);
    const logList = document.getElementById("detectionList");
    const newItem = document.createElement("li");
    newItem.textContent = `${new Date().toLocaleTimeString()}: ${data.message}`;
    const placeholder = document.getElementById("placeholder");
    if (placeholder) placeholder.remove();
    logList.prepend(newItem);
    if (logList.children.length > 10) {
      logList.removeChild(logList.lastChild);
    }
  }
});

function speakLastDetection() {
  if (!quietMode && lastDetectionMessage) {
    speak(lastDetectionMessage);
  } else if (!quietMode) {
    speak("No detection has been received yet.");
  }
}

function clearDetectionLog() {
  const logList = document.getElementById("detectionList");
  logList.innerHTML = "<li id='placeholder'>No detections yet.</li>";
  lastDetectionMessage = "";
  if (!quietMode) speak("Detection log cleared.");
}

function updateMode() {
  const mode = document.getElementById("modeSelect").value;
  if (!quietMode) speak(mode === "home" ? "Home mode activated" : "Public mode activated");
}

function updateConfig() {
  const mode = document.getElementById("modeSelect").value;
  const selectedLabels = detectionModes[mode];

  fetch('config', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json'
    },
    body: JSON.stringify({ labels: selectedLabels })
  })
  .then(res => res.json())
  .then(data => {
    if (!quietMode) speak(`Detection config updated for ${mode} mode.`);
    console.log("Updated config:", data);
  })
  .catch(err => {
    if (!quietMode) speak("Failed to update detection config.");
    console.error("Update failed:", err);
  });
}

document.addEventListener("DOMContentLoaded", () => {
  updateMode();
  fetch("/status")
    .then(res => res.json())
    .then(data => {
      quietMode = !!data.quiet_mode_enabled;
    });
});
