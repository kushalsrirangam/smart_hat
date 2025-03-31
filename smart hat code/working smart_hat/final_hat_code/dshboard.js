// dashboard.js - Enhanced with real-time health monitoring and alerts

class DashboardManager {
  static init() {
    this.setupEventListeners();
    this.startLiveUpdates();
    this.checkSystemStatus();
  }

  static setupEventListeners() {
    document.getElementById('refreshDashboard').addEventListener('click', () => this.refreshDashboard());
    document.getElementById('dismissAlerts').addEventListener('click', () => this.dismissAlerts());
  }

  static startLiveUpdates() {
    // Initial update
    this.updateAllMetrics();
    
    // Periodic updates
    setInterval(() => {
      this.updateAllMetrics();
    }, 5000);

    // Socket.io for real-time updates
    const socket = io();
    socket.on('sensor_update', (data) => this.updateSensorData(data));
    socket.on('system_alert', (data) => this.showAlert(data));
    socket.on('battery_update', (data) => this.updateBattery(data));
  }

  static async updateAllMetrics() {
    try {
      const [system, sensors, battery] = await Promise.all([
        fetch('/system-status').then(r => r.json()),
        fetch('/sensor-status').then(r => r.json()),
        fetch('/battery-status').then(r => r.json())
      ]);
      
      this.updateSystemHealth(system);
      this.updateSensorGrid(sensors);
      this.updateBatteryInfo(battery);
    } catch (err) {
      console.error("Dashboard update failed:", err);
    }
  }

  static updateSystemHealth(data) {
    // Calculate health score (0-100)
    const healthScore = Math.max(0, 100 - 
      (data.temperature > 70 ? (data.temperature - 70) * 2 : 0) - 
      (data.cpu > 80 ? (data.cpu - 80) : 0) - 
      (data.memory > 90 ? (data.memory - 90) : 0));
    
    // Update UI
    document.getElementById('healthScore').textContent = healthScore;
    document.getElementById('healthGauge').style.width = `${healthScore}%`;
    
    // Color coding
    const gauge = document.getElementById('healthGauge');
    gauge.style.backgroundColor = 
      healthScore > 75 ? '#00ff00' : 
      healthScore > 50 ? '#ffa500' : '#ff0000';
    
    // Update individual metrics
    document.getElementById('cpuUsage').textContent = `${data.cpu}%`;
    document.getElementById('memUsage').textContent = `${data.memory}%`;
    document.getElementById('tempValue').textContent = `${data.temperature}°C`;
    document.getElementById('uptimeValue').textContent = this.formatUptime(data.uptime);
  }

  static updateBatteryInfo(data) {
    const batteryLevel = data.level;
    const isCharging = data.charging;
    
    document.getElementById('batteryLevel').textContent = `${batteryLevel}%`;
    document.getElementById('batteryGauge').style.width = `${batteryLevel}%`;
    
    const batteryElement = document.getElementById('batteryGauge');
    batteryElement.style.backgroundColor = 
      batteryLevel > 50 ? '#00ff00' : 
      batteryLevel > 20 ? '#ffa500' : '#ff0000';
    
    document.getElementById('chargingStatus').textContent = isCharging ? '🔌 Charging' : '🔋 Discharging';
    
    if (batteryLevel < 20 && !isCharging) {
      this.showAlert({
        type: 'battery',
        message: 'Low battery! Please charge soon.',
        priority: 'high'
      });
    }
  }

  static updateSensorGrid(data) {
    const sensors = [
      'Left Front', 'Left Middle', 'Left Rear',
      'Right Front', 'Right Middle', 'Right Rear'
    ];
    
    sensors.forEach(sensor => {
      const element = document.querySelector(`#sensor-${sensor.replace(' ', '')}`);
      if (!element) return;
      
      if (data[sensor] && data[sensor].distance) {
        const distance = data[sensor].distance;
        const threshold = data[sensor].threshold || 100;
        
        element.querySelector('.distance-value').textContent = `${distance} cm`;
        element.classList.toggle('warning', distance < threshold * 0.5);
        element.classList.toggle('critical', distance < threshold * 0.3);
      } else {
        element.querySelector('.distance-value').textContent = "OFFLINE";
        element.classList.add('error');
      }
    });
  }

  static showAlert(alert) {
    const alertContainer = document.getElementById('alertContainer');
    if (!alertContainer) return;
    
    const alertElement = document.createElement('div');
    alertElement.className = `alert ${alert.type} ${alert.priority}`;
    alertElement.innerHTML = `
      <span class="alert-icon">${this.getAlertIcon(alert.type)}</span>
      <span class="alert-message">${alert.message}</span>
      <button class="alert-dismiss" onclick="this.parentElement.remove()">×</button>
    `;
    
    alertContainer.prepend(alertElement);
    
    if (!Speech.quiet && alert.priority === 'high') {
      speak(alert.message);
    }
  }

  static getAlertIcon(type) {
    const icons = {
      battery: '🔋',
      sensor: '📡',
      system: '⚠️',
      detection: '🎯',
      navigation: '🗺️'
    };
    return icons[type] || '⚠️';
  }

  static formatUptime(seconds) {
    const days = Math.floor(seconds / 86400);
    const hours = Math.floor((seconds % 86400) / 3600);
    const mins = Math.floor((seconds % 3600) / 60);
    
    return `${days}d ${hours}h ${mins}m`;
  }

  static refreshDashboard() {
    speak("Refreshing dashboard");
    this.updateAllMetrics();
  }

  static dismissAlerts() {
    document.getElementById('alertContainer').innerHTML = '';
  }

  static checkSystemStatus() {
    fetch('/system-status')
      .then(r => r.json())
      .then(data => {
        if (data.health !== 'OK') {
          this.showAlert({
            type: 'system',
            message: `System issue: ${data.health}`,
            priority: 'high'
          });
        }
      });
  }
}

// Initialize on DOM ready
document.addEventListener("DOMContentLoaded", () => DashboardManager.init());
