"""
Reset Servos — Sets all 6 servos (5 fingers + wrist) to 90° (neutral position).

Usage:
    python reset_servos.py

Connects to the ESP32 using the settings in config.py (serial or WiFi),
sends the 90° command for all finger channels, then exits.
"""

import sys
import time

# Allow running from the python_client directory
sys.path.insert(0, ".")

import config
from esp32_client import create_client


NEUTRAL_ANGLE = 90


def main():
    print("=" * 50)
    print("  InMoov Hand — Reset All Servos to 90°")
    print("=" * 50)
    print(f"  Mode : {config.COMM_MODE.upper()}")
    if config.COMM_MODE.lower() == "serial":
        print(f"  Port : {config.SERIAL_PORT} @ {config.SERIAL_BAUD}")
    else:
        print(f"  Host : {config.ESP32_IP}:{config.ESP32_PORT}")
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

    # Build the angle dict — all 6 servos (5 fingers + wrist) to 90°
    angles = {
        "thumb":  NEUTRAL_ANGLE,
        "index":  NEUTRAL_ANGLE,
        "middle": NEUTRAL_ANGLE,
        "ring":   NEUTRAL_ANGLE,
        "pinky":  NEUTRAL_ANGLE,
        "wrist":  NEUTRAL_ANGLE,
    }

    # Send all servos to neutral using the public API with force=True
    # to bypass rate limiting and deadband checks
    try:
        client.send_all_servos(angles, force=True)
        print(f"[✓] Sent: F{NEUTRAL_ANGLE},{NEUTRAL_ANGLE},{NEUTRAL_ANGLE},"
              f"{NEUTRAL_ANGLE},{NEUTRAL_ANGLE},{NEUTRAL_ANGLE}")
        print("[✓] All servos set to 90°.")
    except Exception as e:
        print(f"[!] Send failed: {e}")
        sys.exit(1)

    # Brief pause to let the command reach the ESP32
    time.sleep(0.3)

    client.disconnect()
    print("[✓] Done.")


if __name__ == "__main__":
    main()