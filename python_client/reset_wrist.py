"""
Reset Wrist Servo — Sets only the wrist servo (channel 5) to a specified angle.

Usage:
    python reset_wrist.py          # Reset to 0° (default)
    python reset_wrist.py 90       # Reset to a specific angle

Connects to the ESP32 using the settings in config.py (serial or WiFi),
sends the angle command for the wrist channel only, then exits.
"""

import sys
import time

# Allow running from the python_client directory
sys.path.insert(0, ".")

import config
from esp32_client import create_client


def main():
    # Parse optional angle argument
    target_angle = 0
    if len(sys.argv) > 1:
        try:
            target_angle = int(sys.argv[1])
            if not 0 <= target_angle <= 180:
                print(f"[!] Angle must be 0–180, got {target_angle}")
                sys.exit(1)
        except ValueError:
            print(f"[!] Invalid angle: '{sys.argv[1]}' — must be an integer 0–180")
            sys.exit(1)

    wrist_channel = config.SERVO_CHANNELS["wrist"]

    print("=" * 50)
    print(f"  InMoov Hand — Reset Wrist Servo to {target_angle}°")
    print("=" * 50)
    print(f"  Mode    : {config.COMM_MODE.upper()}")
    if config.COMM_MODE.lower() == "serial":
        print(f"  Port    : {config.SERIAL_PORT} @ {config.SERIAL_BAUD}")
    else:
        print(f"  Host    : {config.ESP32_IP}:{config.ESP32_PORT}")
    print(f"  Channel : {wrist_channel} (wrist)")
    print(f"  Angle   : {target_angle}°")
    print()

    client = create_client()

    print("[*] Connecting to ESP32 ...")
    if not client.connect():
        print("[!] Failed to connect. Check your cable / WiFi and config.py.")
        sys.exit(1)

    # Ping to verify communication
    if client.ping():
        print("[✓] ESP32 responded to PING.")
    else:
        print("[!] No PONG received — continuing anyway.")

    # Send wrist servo to target angle using single-servo command
    try:
        client.send_single_servo(wrist_channel, target_angle)
        print(f"[✓] Sent: C{wrist_channel},{target_angle}")
        print(f"[✓] Wrist servo set to {target_angle}°.")
    except Exception as e:
        print(f"[!] Send failed: {e}")
        sys.exit(1)

    # Brief pause to let the command reach the ESP32
    time.sleep(0.3)

    client.disconnect()
    print("[✓] Done.")


if __name__ == "__main__":
    main()
