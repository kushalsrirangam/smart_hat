import subprocess
import threading

# Define commands for each task
commands = {
    "Ultrasonic Sensors": "sudo python3 L_R_ULTRA.py",
    "Dual Camera Preview": "sudo python3 dual_camera_preview.py",
    "AI Camera": "rpicam-hello -t 0s --post-process-file /usr/share/rpi-camera-assets/imx500_mobilenet_ssd.json --viewfinder-width 1920 --viewfinder-height 1080 --framerate 30",
}

# Function to run camera-related commands in the background
def run_background_command(name, cmd):
    print(f"Starting {name} in the background...")
    with open(f"{name.lower().replace(' ', '_')}.log", "w") as log:
        subprocess.Popen(cmd, shell=True, stdout=log, stderr=log)

# Function to run ultrasonic sensors in the foreground
def run_ultrasonic_command():
    print("Starting Ultrasonic Sensors...")
    subprocess.run(commands["Ultrasonic Sensors"], shell=True)

# Main execution
try:
    # Start Dual Camera Preview and AI Camera in the background
    run_background_command("Dual Camera Preview", commands["Dual Camera Preview"])
    run_background_command("AI Camera", commands["AI Camera"])

    # Start Ultrasonic Sensors in the foreground (live terminal output)
    run_ultrasonic_command()

except KeyboardInterrupt:
    print("\nStopping all processes...")
finally:
    print("All processes stopped.")


