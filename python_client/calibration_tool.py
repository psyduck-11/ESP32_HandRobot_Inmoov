"""
InMoov Hand — Servo Calibration Tool
Interactive tool to calibrate each servo's min/max positions.

Controls:
    1-6: Select servo    O: Set OPEN (min)    C: Set CLOSED (max)
    I: Toggle invert     T: Test selected     A: Test all (wave)
    S: Save calibration  Q: Quit
"""

import sys
import time
import json
import os
import cv2
import numpy as np

import config
from esp32_client import create_client


class CalibrationState:
    def __init__(self):
        self.fingers = ["thumb", "index", "middle", "ring", "pinky", "wrist"]
        self.channels = [config.SERVO_CHANNELS[f] for f in self.fingers]
        self.current_angles = {f: 90 for f in self.fingers}
        self.min_angles = dict(config.SERVO_MIN)
        self.max_angles = dict(config.SERVO_MAX)
        self.inverted = dict(config.SERVO_INVERTED)
        self.selected = 0
        self.testing = False

    @property
    def selected_finger(self):
        return self.fingers[self.selected]

    @property
    def selected_channel(self):
        return self.channels[self.selected]


def on_trackbar(val, finger, state):
    state.current_angles[finger] = val


def create_window(state):
    win = "InMoov Servo Calibration"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(win, 800, 600)
    for i, finger in enumerate(state.fingers):
        cv2.createTrackbar(
            f"{finger.capitalize()} (CH{state.channels[i]})", win, 90, 180,
            lambda val, f=finger: on_trackbar(val, f, state))
    return win


def draw_ui(state, client):
    canvas = np.zeros((600, 800, 3), dtype=np.uint8)
    cv2.putText(canvas, "InMoov Servo Calibration Tool", (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)

    color = (0, 255, 0) if client.connected else (0, 0, 255)
    cv2.circle(canvas, (700, 30), 8, color, -1)

    y_start = 80
    for i, finger in enumerate(state.fingers):
        y = y_start + i * 70
        if i == state.selected:
            cv2.rectangle(canvas, (10, y - 5), (790, y + 55), (40, 40, 80), -1)
            cv2.rectangle(canvas, (10, y - 5), (790, y + 55), (100, 100, 255), 1)

        label = f"[{i+1}] {finger.capitalize():8s} (CH{state.channels[i]})"
        cv2.putText(canvas, label, (20, y + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 1)

        angle = state.current_angles[finger]
        cv2.putText(canvas, f"Angle: {angle:3d}", (260, y + 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 200), 2)
        cv2.putText(canvas, f"MIN:{state.min_angles[finger]:3d}", (420, y + 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (100, 255, 100), 1)
        cv2.putText(canvas, f"MAX:{state.max_angles[finger]:3d}", (540, y + 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (100, 100, 255), 1)

        inv_text = "INV" if state.inverted[finger] else ""
        cv2.putText(canvas, inv_text, (660, y + 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 165, 255), 1)

        # Visual bar
        bx, by, bw, bh = 260, y + 32, 400, 12
        cv2.rectangle(canvas, (bx, by), (bx + bw, by + bh), (60, 60, 60), -1)
        fw = int(bw * angle / 180)
        cv2.rectangle(canvas, (bx, by), (bx + fw, by + bh), (0, 200, 100), -1)
        mnx = bx + int(bw * state.min_angles[finger] / 180)
        mxx = bx + int(bw * state.max_angles[finger] / 180)
        cv2.line(canvas, (mnx, by - 3), (mnx, by + bh + 3), (100, 255, 100), 2)
        cv2.line(canvas, (mxx, by - 3), (mxx, by + bh + 3), (100, 100, 255), 2)

    cy = 510
    cv2.putText(canvas, "1-6:Select  O:SetMin  C:SetMax  I:Invert  T:Test  A:TestAll  S:Save  Q:Quit",
                (20, cy + 15), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (160, 160, 160), 1)

    if state.testing:
        cv2.putText(canvas, "TESTING...", (350, cy + 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 255), 2)
    return canvas


def test_servo(client, state, finger):
    ch = config.SERVO_CHANNELS[finger]
    mn, mx = state.min_angles[finger], state.max_angles[finger]
    print(f"[TEST] {finger} (CH{ch}): {mn}° → {mx}° → {mn}°")
    client.send_single_servo(ch, mn)
    time.sleep(0.8)
    for a in range(mn, mx + 1, 2):
        client.send_single_servo(ch, a)
        time.sleep(0.015)
    time.sleep(0.5)
    for a in range(mx, mn - 1, -2):
        client.send_single_servo(ch, a)
        time.sleep(0.015)
    client.send_single_servo(ch, state.current_angles[finger])


def test_all(client, state):
    print("[TEST] Wave pattern")
    for f in state.fingers:
        client.send_single_servo(config.SERVO_CHANNELS[f], state.min_angles[f])
        time.sleep(0.15)
    time.sleep(0.5)
    for f in state.fingers:
        client.send_single_servo(config.SERVO_CHANNELS[f], state.max_angles[f])
        time.sleep(0.3)
    time.sleep(0.5)
    for f in reversed(state.fingers):
        client.send_single_servo(config.SERVO_CHANNELS[f], state.min_angles[f])
        time.sleep(0.3)
    for f in state.fingers:
        client.send_single_servo(config.SERVO_CHANNELS[f], state.current_angles[f])


def save_calibration(state):
    cal = {"servo_min": state.min_angles, "servo_max": state.max_angles,
           "servo_inverted": state.inverted}
    path = os.path.join(os.path.dirname(__file__), "calibration_data.json")
    with open(path, 'w') as f:
        json.dump(cal, f, indent=2)
    print(f"[SAVE] Saved to {path}")
    print(f"  SERVO_MIN = {state.min_angles}")
    print(f"  SERVO_MAX = {state.max_angles}")
    print(f"  SERVO_INVERTED = {state.inverted}")


def main():
    print("=" * 50)
    print("  InMoov Servo Calibration Tool")
    print("=" * 50)

    state = CalibrationState()
    client = create_client()
    print(f"Connecting ({config.COMM_MODE})...")
    if not client.connect():
        print("[WARN] No ESP32 connection — test functions disabled")

    win = create_window(state)

    try:
        while True:
            for finger in state.fingers:
                client.send_single_servo(config.SERVO_CHANNELS[finger],
                                         state.current_angles[finger])

            canvas = draw_ui(state, client)
            cv2.imshow(win, canvas)
            key = cv2.waitKey(50) & 0xFF

            if key == ord('q'):
                break
            elif key in range(ord('1'), ord('7')):
                state.selected = key - ord('1')
                print(f"[SEL] {state.selected_finger}")
            elif key == ord('o'):
                f = state.selected_finger
                state.min_angles[f] = state.current_angles[f]
                print(f"[CAL] {f} MIN = {state.min_angles[f]}°")
            elif key == ord('c'):
                f = state.selected_finger
                state.max_angles[f] = state.current_angles[f]
                print(f"[CAL] {f} MAX = {state.max_angles[f]}°")
            elif key == ord('i'):
                f = state.selected_finger
                state.inverted[f] = not state.inverted[f]
                print(f"[CAL] {f} inverted: {state.inverted[f]}")
            elif key == ord('t') and client.connected:
                state.testing = True
                test_servo(client, state, state.selected_finger)
                state.testing = False
            elif key == ord('a') and client.connected:
                state.testing = True
                test_all(client, state)
                state.testing = False
            elif key == ord('s'):
                save_calibration(state)
    except KeyboardInterrupt:
        pass
    finally:
        client.disconnect()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
