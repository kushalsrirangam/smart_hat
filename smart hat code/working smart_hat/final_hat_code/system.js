// system.js - Enhanced with Smart Voice Commands + Log Deletion Prompt

function toggleIndoorMode() {
  const enabled = document.getElementById("indoorToggle").checked;
  fetch("/config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ indoor_mode: enabled })
  })
    .then(res => res.json())
    .then(() => {
      speak(enabled ? "Indoor mode enabled" : "Indoor mode disabled");
    });
}

function checkStatus() {
  fetch("/status")
    .then(res => res.json())
    .then(data => {
      document.getElementById("deviceName").textContent = navigator.userAgent;
      document.getElementById("currentMode").textContent = data.mode || "--";
      document.getElementById("quietStatus").textContent = data.quiet_mode_enabled ? "ON" : "OFF";
      speak(`Battery at ${data.battery} percent. Mode is ${data.mode}. Quiet mode is ${data.quiet_mode_enabled ? 'on' : 'off'}. Health status is ${data.health}`);
    });
}


function toggleLog() {
  const log = document.getElementById("log");
  log.style.display = log.style.display === "none" ? "block" : "none";
  if (log.style.display === "block") {
    log.textContent = "Loading...";
    fetch("/status")
      .then(res => res.json())
      .then(data => {
        log.innerHTML = `<strong>Status:</strong><br>Battery: ${data.battery}%<br>Health: ${data.health}`;
      });
  }
}

// 🎯 Delete Logs with Prompt
function deleteLogs() {
  const logs = [
    { key: "battery_logs", label: "Battery Logs" },
    { key: "motion_logs", label: "Motion Logs" },
    { key: "detection_logs", label: "Detection Logs" },
    { key: "location_logs", label: "Location Logs" },
    { key: "system_health_logs", label: "System Health Logs" },
    { key: "video_logs", label: "Video Logs" }
  ];

  const selected = prompt("🧹 Which logs do you want to delete?\nOptions:\n- all\n- battery, ultrasonic, detection...\n\n(Type comma-separated keys or 'all')");

  if (!selected) return speak("Log deletion cancelled.");
  const keys = selected.trim().toLowerCase() === "all"
    ? logs.map(l => l.key)
    : selected.split(",").map(k => k.trim());

  fetch("/delete_logs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ keys })
  })
    .then(res => res.json())
    .then(res => {
      if (res.status === "success") {
        const deleted = logs.filter(l => keys.includes(l.key)).map(l => l.label).join(", ");
        speak(`Deleted logs: ${deleted}`);
      } else {
        speak(`Failed to delete logs. ${res.message}`);
      }
    })
    .catch(() => speak("Error while deleting logs"));
}

// 🗂 Section Labels
const sectionNames = {
  dashboard: "Dashboard",
  nav: "Navigation Mode",
  detect: "Detection Panel",
  sensor: "Sensor Settings",
  system: "System Tools",
  voice: "Voice Commands"
};

// 🔀 UI Tab Switching + Feedback
function switchSection(id, el = null) {
  document.querySelectorAll(".section").forEach(sec => sec.classList.remove("active"));
  const target = document.getElementById(id);
  if (target) target.classList.add("active");

  document.querySelectorAll(".nav-btn").forEach(btn => btn.classList.remove("active"));
  if (el) el.classList.add("active");

  const label = sectionNames[id] || id;
  speak(`${label} activated`);
}

// 🎤 Voice Setup
const recognition = new (window.SpeechRecognition || window.webkitSpeechRecognition)();
recognition.lang = "en-US";
recognition.interimResults = false;
recognition.maxAlternatives = 1;

function startListening() {
  speak("Listening. Please say a command.");
  recognition.start();
}

recognition.onresult = function (event) {
  const transcript = event.results[0][0].transcript.toLowerCase().trim();
  console.log("🎤 Heard:", transcript);
  handleVoiceCommand(transcript);
};

recognition.onerror = function (event) {
  console.error("Speech recognition error:", event.error);
  speak("Sorry, I didn't catch that.");
};

// 🤖 Voice Commands
const voiceCommands = {
  // Tabs
  "dashboard": () => switchSection("dashboard"),
  "open dashboard": () => switchSection("dashboard"),

  "navigation": () => switchSection("nav"),
  "open navigation": () => switchSection("nav"),

  "detection": () => switchSection("detect"),
  "open detection": () => switchSection("detect"),

  "sensor": () => switchSection("sensor"),
  "open sensors": () => switchSection("sensor"),

  "system": () => switchSection("system"),
  "open system": () => switchSection("system"),

  "voice": () => switchSection("voice"),
  "voice commands": () => switchSection("voice"),

  // Smart Actions
  "check battery": () => checkStatus(),
  "enable indoor mode": () => {
    document.getElementById("indoorToggle").checked = true;
    toggleIndoorMode();
  },
  "disable indoor mode": () => {
    document.getElementById("indoorToggle").checked = false;
    toggleIndoorMode();
  },
  "shut down": () => {
    shutdownPi();
    speak("Shutting down the system");
  },
  "delete logs": () => deleteLogs(),
  "repeat detection": () => speakLastDetection(),
  "repeat message": () => speak(lastSpokenMessage),

  // Navigation
  "where am i": () => speakDetailedLocation(),
  "get location": () => speakDetailedLocation(),
  "start voice navigation": () => startVoiceSearch(),
  "navigate to": () => startVoiceSearch(),
  "pause navigation": () => {
    toggleTracking();
    speak("Navigation paused");
  },
  "resume navigation": () => {
    toggleTracking();
    speak("Navigation resumed");
  }
};

// 🎯 Match & Execute
function handleVoiceCommand(transcript) {
  for (const phrase in voiceCommands) {
    if (transcript.includes(phrase)) {
      voiceCommands[phrase]();
      return;
    }
  }
  speak("Sorry, I didn't understand that command.");
}
