// sensor.js - Enhanced with visual feedback, error handling, and calibration support

class SensorManager {
  static SENSORS = [
    "Left Front", "Left Middle", "Left Rear", 
    "Right Front", "Right Middle", "Right Rear"
  ];

  static init() {
    this.createStatusGrid();
    this.bindEvents();
    setInterval(this.updateSensorStates, 5000);
  }

  static createStatusGrid() {
    const grid = document.getElementById('sensorStatusGrid');
    grid.innerHTML = this.SENSORS.map(sensor => `
      <div class="sensor-status-item" id="status-${sensor.replace(' ', '')}">
        <h4>${sensor}</h4>
        <div class="threshold-indicator"></div>
        <span class="distance-value">-- cm</span>
        <div class="calibration-bar"></div>
      </div>
    `).join('');
  }

  static bindEvents() {
    document.getElementById('calibrateBtn').addEventListener('click', this.runCalibration);
    document.querySelectorAll('input[type="range"]').forEach(input => {
      input.addEventListener('input', this.showLiveThreshold);
    });
  }

  static showLiveThreshold(e) {
    const sensor = e.target.id;
    const value = e.target.value;
    document.querySelector(`#status-${sensor.replace(' ', '')} .threshold-indicator`)
      .style.width = `${value}%`;
  }

  static async applyThresholds() {
    const thresholds = {};
    let hasError = false;
    
    this.SENSORS.forEach(sensor => {
      const value = parseInt(document.getElementById(sensor).value);
      if (isNaN(value) {
        document.getElementById(sensor).classList.add("error");
        hasError = true;
      } else {
        thresholds[sensor] = value;
      }
    });

    if (hasError) {
      speak("Invalid threshold values detected");
      return;
    }

    document.querySelectorAll("input[type='range']").forEach(el => el.disabled = true);
    
    try {
      const response = await fetch("/config", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ultrasonic_thresholds: thresholds })
      });
      
      const data = await response.json();
      this.SENSORS.forEach(sensor => {
        const indicator = document.querySelector(`#status-${sensor.replace(' ', '')} .threshold-indicator`);
        indicator.style.backgroundColor = "#00ff00";
        setTimeout(() => indicator.style.backgroundColor = "", 2000);
      });
      
      if (!Speech?.quiet) speak("Thresholds updated successfully");
    } catch (err) {
      console.error("Failed to update thresholds:", err);
      this.SENSORS.forEach(sensor => {
        document.querySelector(`#status-${sensor.replace(' ', '')} .threshold-indicator`)
          .style.backgroundColor = "#ff0000";
      });
      if (!Speech?.quiet) speak("Update failed");
    } finally {
      document.querySelectorAll("input[type='range']").forEach(el => el.disabled = false);
    }
  }

  static async runCalibration() {
    speak("Starting sensor calibration");
    try {
      const response = await fetch("/calibrate-sensors", { method: "POST" });
      const data = await response.json();
      
      data.results.forEach(result => {
        const element = document.querySelector(`#status-${result.sensor.replace(' ', '')} .calibration-bar`);
        element.style.width = `${result.accuracy}%`;
        element.style.backgroundColor = result.accuracy > 90 ? "green" : 
                                      result.accuracy > 70 ? "orange" : "red";
      });
      
      speak("Calibration complete");
    } catch (err) {
      console.error("Calibration failed:", err);
      speak("Calibration failed");
    }
  }

  static async updateSensorStates() {
    try {
      const response = await fetch("/sensor-status");
      const data = await response.json();
      
      this.SENSORS.forEach(sensor => {
        const statusElement = document.querySelector(`#status-${sensor.replace(' ', '')}`);
        const valueElement = statusElement.querySelector('.distance-value');
        
        if (data[sensor] && data[sensor].distance) {
          valueElement.textContent = `${data[sensor].distance} cm`;
          statusElement.classList.toggle("critical", data[sensor].critical);
        } else {
          valueElement.textContent = "OFFLINE";
          statusElement.classList.add("error");
        }
      });
    } catch (err) {
      console.error("Failed to fetch sensor states:", err);
    }
  }
}

// Initialize on DOM ready
document.addEventListener("DOMContentLoaded", () => SensorManager.init());

// Fullscreen toggle remains the same
function toggleFullScreen(el) {
  if (!document.fullscreenElement) {
    el.requestFullscreen().catch(err => {
      console.error(`Error attempting to enable full-screen mode: ${err.message}`);
    });
  } else {
    document.exitFullscreen();
  }
}
