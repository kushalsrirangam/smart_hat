// system.js - Enhanced with firmware updates, safe mode, and backup/restore

class SystemManager {
  static init() {
    this.bindEvents();
    this.loadSystemInfo();
    this.setupWakeWordToggle();
  }

  static bindEvents() {
    document.getElementById('indoorToggle').addEventListener('change', this.toggleIndoorMode);
    document.getElementById('quietToggle').addEventListener('change', this.toggleQuietMode);
    document.getElementById('wakeToggle').addEventListener('change', this.toggleWakeWord);
    document.getElementById('checkStatusBtn').addEventListener('click', this.checkSystemStatus);
    document.getElementById('updateBtn').addEventListener('click', this.checkForUpdates);
    document.getElementById('backupBtn').addEventListener('click', this.backupSystem);
    document.getElementById('restoreBtn').addEventListener('click', this.restoreSystem);
    document.getElementById('safeModeBtn').addEventListener('click', this.toggleSafeMode);
    document.getElementById('shutdownBtn').addEventListener('click', this.shutdownSystem);
    document.getElementById('rebootBtn').addEventListener('click', this.rebootSystem);
  }

  static async loadSystemInfo() {
    try {
      const response = await fetch('/system-info');
      const data = await response.json();
      
      document.getElementById('deviceName').textContent = data.deviceName || 'Smart Hat';
      document.getElementById('firmwareVersion').textContent = data.firmware || 'v1.0.0';
      document.getElementById('systemUptime').textContent = this.formatUptime(data.uptime);
      document.getElementById('networkStatus').textContent = data.network || 'Unknown';
      
      if (data.updateAvailable) {
        this.showUpdateNotification(data.latestVersion);
      }
    } catch (err) {
      console.error("Failed to load system info:", err);
    }
  }

  static async toggleIndoorMode() {
    const enabled = document.getElementById('indoorToggle').checked;
    try {
      const response = await fetch('/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ indoor_mode: enabled })
      });
      const result = await response.json();
      
      speak(enabled ? "Indoor mode enabled" : "Indoor mode disabled");
      document.getElementById('indoorStatus').textContent = enabled ? 'ON' : 'OFF';
    } catch (err) {
      console.error("Failed to toggle indoor mode:", err);
      speak("Failed to change mode");
      document.getElementById('indoorToggle').checked = !enabled;
    }
  }

  static async toggleQuietMode() {
    const enabled = document.getElementById('quietToggle').checked;
    try {
      const response = await fetch('/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ quiet_mode: enabled })
      });
      const result = await response.json();
      
      speak(enabled ? "Quiet mode enabled" : "Quiet mode disabled");
      document.getElementById('quietStatus').textContent = enabled ? 'ON' : 'OFF';
    } catch (err) {
      console.error("Failed to toggle quiet mode:", err);
      speak("Failed to change mode");
      document.getElementById('quietToggle').checked = !enabled;
    }
  }

  static async toggleWakeWord() {
    const enabled = document.getElementById('wakeToggle').checked;
    Speech.toggleWakeWord(enabled);
    document.getElementById('wakeStatus').textContent = enabled ? 'ON' : 'OFF';
    speak(enabled ? "Wake word enabled" : "Wake word disabled");
  }

  static async checkSystemStatus() {
    try {
      const response = await fetch('/system-status');
      const data = await response.json();
      
      let statusMessage = `System status: ${data.health}. `;
      statusMessage += `Battery: ${data.battery}%. `;
      statusMessage += `CPU: ${data.cpu}%. `;
      statusMessage += `Memory: ${data.memory}%. `;
      statusMessage += `Temperature: ${data.temperature}°C.`;
      
      speak(statusMessage);
      
      // Update UI
      document.getElementById('systemHealth').textContent = data.health;
      document.getElementById('batteryLevel').textContent = `${data.battery}%`;
      document.getElementById('cpuUsage').textContent = `${data.cpu}%`;
      document.getElementById('memUsage').textContent = `${data.memory}%`;
      document.getElementById('tempValue').textContent = `${data.temperature}°C`;
      
    } catch (err) {
      console.error("Failed to check system status:", err);
      speak("Unable to check system status");
    }
  }

  static async checkForUpdates() {
    speak("Checking for updates...");
    try {
      const response = await fetch('/system/updates');
      const data = await response.json();
      
      if (data.updateAvailable) {
        const confirmUpdate = confirm(`Version ${data.latestVersion} available. Install now?`);
        if (confirmUpdate) {
          this.performUpdate();
        }
      } else {
        speak("System is up to date");
      }
    } catch (err) {
      console.error("Failed to check updates:", err);
      speak("Unable to check for updates");
    }
  }

  static async performUpdate() {
    speak("Starting system update. Do not power off.");
    try {
      const response = await fetch('/system/update', { method: 'POST' });
      const data = await response.json();
      
      if (data.success) {
        speak("Update complete. Rebooting...");
        setTimeout(() => window.location.reload(), 5000);
      } else {
        speak(`Update failed: ${data.error}`);
      }
    } catch (err) {
      console.error("Update failed:", err);
      speak("Update failed. Please try again.");
    }
  }

  static async backupSystem() {
    speak("Creating system backup...");
    try {
      const response = await fetch('/system/backup', { method: 'POST' });
      const data = await response.json();
      
      if (data.success) {
        const backupTime = new Date(data.timestamp).toLocaleString();
        speak(`Backup created successfully at ${backupTime}`);
        
        // Create download link
        const link = document.createElement('a');
        link.href = data.downloadUrl;
        link.download = `smart-hat-backup-${data.timestamp}.zip`;
        link.click();
      } else {
        speak("Backup failed");
      }
    } catch (err) {
      console.error("Backup failed:", err);
      speak("Backup failed. Please try again.");
    }
  }

  static async restoreSystem() {
    const fileInput = document.createElement('input');
    fileInput.type = 'file';
    fileInput.accept = '.zip';
    
    fileInput.onchange = async (e) => {
      const file = e.target.files[0];
      if (!file) return;
      
      speak(`Restoring from ${file.name}...`);
      
      try {
        const formData = new FormData();
        formData.append('backup', file);
        
        const response = await fetch('/system/restore', {
          method: 'POST',
          body: formData
        });
        
        const data = await response.json();
        
        if (data.success) {
          speak("Restore complete. Rebooting...");
          setTimeout(() => window.location.reload(), 5000);
        } else {
          speak(`Restore failed: ${data.error}`);
        }
      } catch (err) {
        console.error("Restore failed:", err);
        speak("Restore failed. Please try again.");
      }
    };
    
    fileInput.click();
