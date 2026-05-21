"""
InMoov Hand Gesture Control — Main Application
Captures webcam, detects hand gestures via MediaPipe, and sends
servo commands to ESP32 in real-time.

Controls:
    Q       — Quit
    P       — Pause/resume sending to ESP32
    R       — Reconnect to ESP32
    M       — Toggle mirror mode
    H       — Toggle hold mode (keep posture when hand removed)
    Space   — Toggle wrist control on/off
    G       — Cycle grip mode (DELICATE → LIGHT → NORMAL → FIRM)
    +/-     — Fine-adjust grip strength ±5%
"""

import sys
import time
import cv2
import numpy as np

import config
from hand_tracker import HandTracker
from esp32_client import create_client


# ---- Grip Protection State ----
class GripController:
    """
    Manages grip strength modes and per-finger force limiting.
    Prevents the robot hand from crushing objects.
    """

    MODE_ORDER = ["DELICATE", "LIGHT", "NORMAL", "FIRM"]

    def __init__(self):
        self.mode_index = self.MODE_ORDER.index(config.DEFAULT_GRIP_MODE)
        self._custom_strength = None  # Override from +/- keys

    @property
    def mode_name(self) -> str:
        return self.MODE_ORDER[self.mode_index]

    @property
    def mode_config(self) -> dict:
        return config.GRIP_MODES[self.mode_name]

    @property
    def label(self) -> str:
        return self.mode_config["label"]

    def get_strength(self, finger: str = None) -> float:
        """Get grip strength (0–100%) for a finger, respecting overrides."""
        # Check per-finger override first
        if finger and finger in config.FINGER_GRIP_OVERRIDE:
            override = config.FINGER_GRIP_OVERRIDE[finger]
            if override is not None:
                return float(override)

        # Custom strength from +/- keys
        if self._custom_strength is not None:
            return self._custom_strength

        return float(self.mode_config["strength"])

    @property
    def compliance_zone(self) -> float:
        return float(self.mode_config["compliance_zone"])

    def cycle_mode(self):
        """Cycle to the next grip mode."""
        self.mode_index = (self.mode_index + 1) % len(self.MODE_ORDER)
        self._custom_strength = None  # Reset custom override when changing modes
        return self.mode_name

    def adjust_strength(self, delta: int):
        """Fine-adjust grip strength by delta percent."""
        current = self.get_strength()
        self._custom_strength = float(np.clip(current + delta, 5, 100))
        return self._custom_strength


def curl_to_servo_angle(curl_pct: float, finger: str, grip: GripController) -> int:
    """
    Convert curl percentage (0–100) to servo angle (degrees).
    Applies grip strength limiting: the finger cannot close beyond
    (grip_strength)% of its full range.

    Compliance zone: as the finger approaches its grip limit,
    the mapped angle is progressively scaled back, simulating
    a "soft stop" to prevent sudden force spikes.
    """
    min_angle = config.SERVO_MIN[finger]
    max_angle = config.SERVO_MAX[finger]
    inverted = config.SERVO_INVERTED[finger]
    strength = grip.get_strength(finger)

    # Apply grip strength: limit the effective curl percentage
    # strength=75 means fingers can only close to 75% of their full range
    max_curl = strength  # e.g., 75% of full range

    # Compliance zone: soft deceleration near the grip limit
    # Within the compliance zone, progressively reduce the curl
    compliance = grip.compliance_zone
    if compliance > 0 and curl_pct > (max_curl - compliance):
        if curl_pct >= max_curl:
            # At or past limit — hard cap
            effective_curl = max_curl
        else:
            # Within compliance zone — ease into limit
            # Use cosine easing for smooth deceleration
            zone_progress = (curl_pct - (max_curl - compliance)) / compliance
            easing = 0.5 * (1 - np.cos(np.pi * zone_progress))
            effective_curl = (max_curl - compliance) + compliance * easing
    else:
        effective_curl = min(curl_pct, max_curl)

    # Map effective curl to servo angle
    if inverted:
        angle = np.interp(effective_curl, [0, 100], [max_angle, min_angle])
    else:
        angle = np.interp(effective_curl, [0, 100], [min_angle, max_angle])

    return int(np.clip(angle, min(min_angle, max_angle), max(min_angle, max_angle)))


def wrist_to_servo_angle(wrist_deg: float) -> int:
    """Convert wrist rotation (0–180) to servo angle."""
    min_angle = config.SERVO_MIN["wrist"]
    max_angle = config.SERVO_MAX["wrist"]
    inverted = config.SERVO_INVERTED["wrist"]

    if inverted:
        angle = np.interp(wrist_deg, [0, 180], [max_angle, min_angle])
    else:
        angle = np.interp(wrist_deg, [0, 180], [min_angle, max_angle])

    return int(np.clip(angle, min(min_angle, max_angle), max(min_angle, max_angle)))


def draw_ui_overlay(frame, curls, servo_angles, tracker, client, fps, paused, wrist_enabled, grip=None, hold_mode=False):
    """Draw the informational overlay on the camera frame."""
    h, w = frame.shape[:2]

    # --- Semi-transparent top bar (ROI-based to avoid full frame copy) ---
    bar_height = 50
    roi = frame[0:bar_height, :].copy()
    cv2.rectangle(roi, (0, 0), (w, bar_height), (20, 20, 20), -1)
    cv2.addWeighted(roi, 0.7, frame[0:bar_height], 0.3, 0, frame[0:bar_height])

    # Title
    cv2.putText(frame, "InMoov Hand Control", (10, 35),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)

    # FPS
    if config.SHOW_FPS:
        cv2.putText(frame, f"FPS: {fps:.0f}", (w - 140, 35),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 200), 2)

    # Connection status
    status_color = (0, 255, 0) if client.connected else (0, 0, 255)
    status_text = "CONNECTED" if client.connected else "DISCONNECTED"
    cv2.circle(frame, (w - 200, 28), 8, status_color, -1)
    cv2.putText(frame, status_text, (w - 188, 35),
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, status_color, 1)

    # Hold mode indicator (persistent badge, always visible)
    if hold_mode:
        hold_color = (0, 220, 160)
        cv2.putText(frame, "LOCKED (H to release)", (10, 70),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, hold_color, 2)
    else:
        hold_color = (100, 100, 100)
        cv2.putText(frame, "LIVE (H to lock)", (10, 70),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, hold_color, 2)

    # Hand detection status (only relevant when not holding)
    if not tracker.hand_detected and not hold_mode:
        cv2.putText(frame, "No hand detected \u2014 show your hand to the camera",
                    (w // 2 - 280, h // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 150, 255), 2)

    # Paused indicator
    if paused:
        cv2.putText(frame, "PAUSED (press P to resume)", (w // 2 - 180, 95),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 100, 255), 2)

    # --- Grip mode indicator (top-right area) ---
    if grip:
        strength = grip.get_strength()
        mode_label = grip.label

        # Grip mode badge
        grip_y = 70
        # Color based on strength: green (soft) → yellow → red (firm)
        gr = int(np.interp(strength, [0, 50, 100], [100, 200, 50]))
        gg = int(np.interp(strength, [0, 50, 100], [220, 220, 50]))
        gb = int(np.interp(strength, [0, 50, 100], [50, 50, 50]))
        grip_color = (gb, gg, gr)

        cv2.putText(frame, f"GRIP: {mode_label}", (w - 350, grip_y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, grip_color, 2)

        # Strength bar
        bar_x = w - 350
        bar_y = grip_y + 8
        bar_w = 200
        bar_h = 10
        cv2.rectangle(frame, (bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h),
                      (60, 60, 60), -1)
        fill_w = int(bar_w * strength / 100)
        cv2.rectangle(frame, (bar_x, bar_y), (bar_x + fill_w, bar_y + bar_h),
                      grip_color, -1)
        cv2.rectangle(frame, (bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h),
                      (140, 140, 140), 1)
        cv2.putText(frame, f"{strength:.0f}%", (bar_x + bar_w + 5, bar_y + 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)

    # --- Finger angle bars ---
    if config.SHOW_ANGLE_BARS:
        bar_x = 20
        bar_y_start = h - 180
        bar_width = 35
        bar_max_height = 130
        bar_spacing = 55
        finger_names = ["thumb", "index", "middle", "ring", "pinky"]

        if wrist_enabled:
            finger_names.append("wrist")

        for idx, name in enumerate(finger_names):
            x = bar_x + idx * bar_spacing
            y_base = bar_y_start + bar_max_height

            # Background bar
            cv2.rectangle(frame, (x, bar_y_start), (x + bar_width, y_base),
                          (50, 50, 50), -1)

            # Fill bar based on curl percentage
            if name == "wrist":
                fill_pct = curls.get(name, 90) / 180.0 * 100
            else:
                fill_pct = curls.get(name, 0)

            fill_height = int(bar_max_height * fill_pct / 100)

            # Color gradient: green (open) → orange → red (closed)
            r = int(np.interp(fill_pct, [0, 50, 100], [50, 255, 255]))
            g = int(np.interp(fill_pct, [0, 50, 100], [220, 200, 50]))
            b = 50
            color = (b, g, r)

            cv2.rectangle(frame, (x, y_base - fill_height), (x + bar_width, y_base),
                          color, -1)

            # Bar outline
            cv2.rectangle(frame, (x, bar_y_start), (x + bar_width, y_base),
                          (180, 180, 180), 1)

            # Finger label
            label = name[0].upper() if name != "wrist" else "W"
            cv2.putText(frame, label, (x + 8, y_base + 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200, 200, 200), 2)

            # Servo angle value
            angle = servo_angles.get(name, 0)
            cv2.putText(frame, f"{angle}", (x + 2, bar_y_start - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)

    # --- Controls hint ---
    controls = "Q:Quit  P:Pause  R:Reconnect  M:Mirror  H:Hold  Space:Wrist  G:Grip  +/-:Strength"
    cv2.putText(frame, controls, (10, h - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (140, 140, 140), 1)

    return frame


def main():
    print("=" * 60)
    print("  InMoov Hand Gesture Control System")
    print("  Mode:", config.COMM_MODE.upper())
    print("  Grip:", config.DEFAULT_GRIP_MODE)
    print("=" * 60)

    # Initialize hand tracker
    tracker = HandTracker()
    print("[INIT] Hand tracker ready")

    # Initialize grip controller
    grip = GripController()
    print(f"[INIT] Grip mode: {grip.mode_name} ({grip.label}) — strength {grip.get_strength():.0f}%")

    # Initialize ESP32 client
    client = create_client()
    print(f"[INIT] Connecting to ESP32 ({config.COMM_MODE})...")
    if client.connect():
        print("[INIT] ESP32 connection established!")
        # Sync configuration and grip strength
        client.sync_config()
        client.set_grip_strength(int(grip.get_strength()))
        # Send a ping to verify
        if client.ping():
            print("[INIT] ESP32 responded to ping — communication OK")
        else:
            print("[INIT] ESP32 did not respond to ping — check firmware")
    else:
        print("[INIT] Could not connect to ESP32 — running in preview mode")
        print("       (Hand tracking will work, servo commands won't be sent)")

    # Initialize camera
    cap = cv2.VideoCapture(config.CAMERA_INDEX)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.CAMERA_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.CAMERA_HEIGHT)

    if not cap.isOpened():
        print("[ERROR] Cannot open camera!")
        sys.exit(1)

    print(f"[INIT] Camera opened (index {config.CAMERA_INDEX})")
    print()
    print("Controls: Q=Quit, P=Pause, R=Reconnect, M=Mirror, H=Hold, Space=Wrist, G=Grip, +/-=Strength")
    print("-" * 60)

    # State
    paused = False
    wrist_enabled = True
    hold_mode = False       # When True, robot is locked to held_* posture
    mirror = config.MIRROR_MODE
    prev_time = time.perf_counter()
    fps = 0
    held_curls = None       # Snapshot captured when H is pressed
    held_servo_angles = None

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                print("[ERROR] Camera read failed!")
                break

            # Mirror the frame if needed
            if mirror:
                frame = cv2.flip(frame, 1)

            # Convert BGR → RGB for MediaPipe
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            # Process hand tracking
            curls = tracker.process_frame(frame_rgb)

            # --- Determine servo output ---
            if hold_mode and held_servo_angles is not None:
                # LOCKED: ignore live tracking, use frozen posture
                curls = dict(held_curls)
                servo_angles = dict(held_servo_angles)
            else:
                # LIVE: compute from hand tracking
                servo_angles = {}
                if tracker.hand_detected:
                    for finger in ["thumb", "index", "middle", "ring", "pinky"]:
                        servo_angles[finger] = curl_to_servo_angle(curls[finger], finger, grip)

                    if wrist_enabled:
                        servo_angles["wrist"] = wrist_to_servo_angle(curls["wrist"])
                    else:
                        servo_angles["wrist"] = 90  # Neutral
                else:
                    # No hand detected — reset to open
                    curls = {f: 0.0 for f in ["thumb", "index", "middle", "ring", "pinky"]}
                    curls["wrist"] = 90.0
                    servo_angles = {f: config.SERVO_MIN[f] for f in ["thumb", "index", "middle", "ring", "pinky"]}
                    servo_angles["wrist"] = 90

            # Send to ESP32 (if not paused)
            if not paused:
                client.send_all_servos(servo_angles)

            # Draw landmarks
            if config.SHOW_LANDMARKS:
                frame = tracker.draw_landmarks(frame)

            # Calculate FPS (perf_counter for high-resolution timing on Windows)
            current_time = time.perf_counter()
            dt = current_time - prev_time
            if dt > 0:
                fps = 0.9 * fps + 0.1 * (1.0 / dt)  # Smoothed FPS
            prev_time = current_time

            # Draw UI overlay
            frame = draw_ui_overlay(
                frame, curls, servo_angles, tracker, client,
                fps, paused, wrist_enabled, grip, hold_mode,
            )

            # Show frame
            cv2.imshow(config.WINDOW_NAME, frame)

            # Handle keyboard input
            key = cv2.waitKey(1) & 0xFF

            if key == ord('q') or key == ord('Q'):
                print("\n[EXIT] Quitting...")
                break
            elif key == ord('p') or key == ord('P'):
                paused = not paused
                print(f"[INFO] {'Paused' if paused else 'Resumed'} sending")
            elif key == ord('r') or key == ord('R'):
                print("[INFO] Reconnecting to ESP32...")
                client.disconnect()
                if client.connect():
                    client.sync_config()
                    client.set_grip_strength(int(grip.get_strength()))
                    print("[INFO] Reconnected!")
                else:
                    print("[INFO] Reconnection failed")
            elif key == ord('m') or key == ord('M'):
                mirror = not mirror
                print(f"[INFO] Mirror mode: {'ON' if mirror else 'OFF'}")
            elif key == ord('h') or key == ord('H'):
                if not hold_mode:
                    # Attempting to LOCK — only allow if hand is currently detected
                    if tracker.hand_detected:
                        hold_mode = True
                        held_curls = dict(curls)
                        held_servo_angles = dict(servo_angles)
                        print(f"[HOLD] LOCKED — posture frozen (press H again to release)")
                    else:
                        print(f"[HOLD] Cannot lock — no hand detected. Show your hand first.")
                else:
                    # UNLOCK
                    hold_mode = False
                    held_curls = None
                    held_servo_angles = None
                    print(f"[HOLD] RELEASED — back to live tracking")
            elif key == ord(' '):
                wrist_enabled = not wrist_enabled
                print(f"[INFO] Wrist control: {'ON' if wrist_enabled else 'OFF'}")
            elif key == ord('g') or key == ord('G'):
                mode = grip.cycle_mode()
                client.set_grip_strength(int(grip.get_strength()))
                print(f"[GRIP] Mode: {mode} — {grip.label} (strength {grip.get_strength():.0f}%)")
            elif key == ord('+') or key == ord('='):
                s = grip.adjust_strength(5)
                client.set_grip_strength(int(s))
                print(f"[GRIP] Strength: {s:.0f}%")
            elif key == ord('-') or key == ord('_'):
                s = grip.adjust_strength(-5)
                client.set_grip_strength(int(s))
                print(f"[GRIP] Strength: {s:.0f}%")

    except KeyboardInterrupt:
        print("\n[EXIT] Interrupted by user")

    finally:
        # Cleanup
        print("[CLEANUP] Releasing resources...")
        tracker.release()
        client.disconnect()
        cap.release()
        cv2.destroyAllWindows()
        print("[CLEANUP] Done. Goodbye!")


if __name__ == "__main__":
    main()