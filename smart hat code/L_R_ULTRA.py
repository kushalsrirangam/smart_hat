import lgpio
import time
import curses  # For updating terminal output

# Define the correct GPIO chip number (Raspberry Pi 5 uses gpiochip4)
CHIP = 4

# Correct GPIO pin mapping for left and right ultrasonic sensors
SENSORS = {
    "Left Front":  {"trigger": 4,  "echo": 17},  # Pin 7  -> GPIO 4,  Pin 11 -> GPIO 17
    "Left Middle": {"trigger": 27, "echo": 22},  # Pin 13 -> GPIO 27, Pin 15 -> GPIO 22
    "Left Rear":   {"trigger": 23, "echo": 24},  # Pin 16 -> GPIO 23, Pin 18 -> GPIO 24

    "Right Front":  {"trigger": 5,  "echo": 6},   # Pin 29 -> GPIO 5,  Pin 31 -> GPIO 6
    "Right Middle": {"trigger": 12, "echo": 13},  # Pin 32 -> GPIO 12, Pin 33 -> GPIO 13
    "Right Rear":   {"trigger": 19, "echo": 26}   # Pin 35 -> GPIO 19, Pin 37 -> GPIO 26
}

try:
    # Open GPIO chip
    h = lgpio.gpiochip_open(CHIP)

    # Initialize each sensor's trigger and echo pins
    for sensor in SENSORS.values():
        lgpio.gpio_claim_output(h, sensor["trigger"])
        lgpio.gpio_claim_input(h, sensor["echo"])

    def measure_distance(trigger_pin, echo_pin, timeout=0.02):
        """Measures distance using an ultrasonic sensor with fault detection."""
        # Send a short pulse to trigger
        lgpio.gpio_write(h, trigger_pin, 1)
        time.sleep(0.00001)  # 10µs pulse
        lgpio.gpio_write(h, trigger_pin, 0)

        start_time = time.time()
        stop_time = time.time()

        # Wait for the echo to go HIGH (start time)
        timeout_start = time.time()
        while lgpio.gpio_read(h, echo_pin) == 0:
            start_time = time.time()
            if time.time() - timeout_start > timeout:
                return "Fault: No Echo Received"

        # Wait for the echo to go LOW (stop time)
        timeout_start = time.time()
        while lgpio.gpio_read(h, echo_pin) == 1:
            stop_time = time.time()
            if time.time() - timeout_start > timeout:
                return "Fault: Echo Timeout"

        # Calculate the distance in cm
        time_elapsed = stop_time - start_time
        distance = (time_elapsed * 34300) / 2  # Speed of sound = 343 m/s

        # Check for faulty distance readings
        if distance <= 2 or distance > 400:
            return "Fault: Abnormal Distance"

        return round(distance, 2)

    def main(stdscr):
        """Curses-based display to update readings dynamically."""
        curses.curs_set(0)  # Hide cursor
        stdscr.nodelay(1)  # Make getch() non-blocking
        stdscr.timeout(500)  # Refresh rate (500ms)

        while True:
            stdscr.clear()  # Clear screen for updated values
            stdscr.addstr(0, 0, "Ultrasonic Sensor Readings (Left & Right)", curses.A_BOLD)

            row = 2  # Start displaying from row 2
            for name, sensor in SENSORS.items():
                distance = measure_distance(sensor["trigger"], sensor["echo"])
                display_text = f"{name}: {distance} cm" if isinstance(distance, (int, float)) else f"{name}: {distance}"
                stdscr.addstr(row, 0, display_text)
                row += 1

            stdscr.refresh()  # Refresh screen with new data

            # Exit if 'q' is pressed
            key = stdscr.getch()
            if key == ord('q'):
                break

    # Run the curses interface
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        print("\nMeasurement stopped by user")

finally:
    lgpio.gpiochip_close(h)
    print("GPIO resources released")
