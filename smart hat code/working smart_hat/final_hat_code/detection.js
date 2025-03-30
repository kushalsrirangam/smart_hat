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
const socket = io(window.location.origin);


socket.on('speak', (data) => {
  if (data.message) {
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
  if (lastDetectionMessage) {
    speak(lastDetectionMessage);
  } else {
    speak("No detection has been received yet.");
  }
}

function clearDetectionLog() {
  const logList = document.getElementById("detectionList");
  logList.innerHTML = "<li id='placeholder'>No detections yet.</li>";
  lastDetectionMessage = "";
  speak("Detection log cleared.");
}

function updateMode() {
  const mode = document.getElementById("modeSelect").value;
  speak(mode === "home" ? "Home mode activated" : "Public mode activated");

  // 🔄 Also inform backend to apply system-wide mode
  fetch("/mode", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode })
  })
  .then(res => res.json())
  .then(data => {
    console.log("Mode confirmed by server:", data);
  })
  .catch(err => {
    speak("Failed to update mode on server.");
    console.error("Mode update failed:", err);
  });
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
    speak(`Detection config updated for ${mode} mode.`);
    console.log("Updated config:", data);
  })
  .catch(err => {
    speak("Failed to update detection config.");
    console.error("Update failed:", err);
  });
}

document.addEventListener("DOMContentLoaded", () => {
  updateMode();
});
