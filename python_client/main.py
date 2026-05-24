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
import tkinter as tk
from tkinter import simpledialog

import config
from hand_tracker import HandTracker
from esp32_client import create_client

# Global registry for mouse-clickable UI areas
CLICKABLE_REGIONS = {}


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


class CameraSelectionDialog:
    """A custom Tkinter dialog that presents clickable camera source buttons."""
    def __init__(self, parent, detected_cameras, title="Select Camera Source"):
        self.parent = parent
        self.result = None
        
        self.dialog = tk.Toplevel(parent)
        self.dialog.title(title)
        self.dialog.geometry("380x320")
        self.dialog.resizable(False, False)
        
        # Style details
        self.dialog.configure(bg="#2d2d2d")
        
        # Center the dialog
        self.dialog.update_idletasks()
        width = self.dialog.winfo_width()
        height = self.dialog.winfo_height()
        x = (self.dialog.winfo_screenwidth() // 2) - (width // 2)
        y = (self.dialog.winfo_screenheight() // 2) - (height // 2)
        self.dialog.geometry(f"+{x}+{y}")
        
        # Make topmost and modal
        self.dialog.transient(parent)
        self.dialog.grab_set()
        self.dialog.focus_set()
        
        # Header Label
        lbl = tk.Label(
            self.dialog, 
            text="Select Camera Source", 
            font=("Helvetica", 14, "bold"), 
            bg="#2d2d2d", 
            fg="#00ff80", 
            pady=10
        )
        lbl.pack()
        
        # Description Label
        lbl_desc = tk.Label(
            self.dialog, 
            text="Choose a detected camera or enter a custom stream URL:", 
            font=("Helvetica", 9), 
            bg="#2d2d2d", 
            fg="#cccccc", 
            pady=5
        )
        lbl_desc.pack()
        
        # Grid Frame for buttons
        btn_frame = tk.Frame(self.dialog, bg="#2d2d2d")
        btn_frame.pack(pady=10)
        
        # Camera options based on detection
        for idx, cam_idx in enumerate(detected_cameras):
            if cam_idx == 0:
                btn_text = "Camera 0 (Laptop)"
            else:
                btn_text = f"Camera {cam_idx} (Detected)"
                
            btn = tk.Button(
                btn_frame, 
                text=btn_text, 
                font=("Helvetica", 9, "bold"),
                width=16, 
                height=2,
                bg="#3a3a3a",
                fg="#ffffff",
                activebackground="#00ff80",
                activeforeground="#2d2d2d",
                relief=tk.FLAT,
                command=lambda val=cam_idx: self.select_source(val)
            )
            btn.grid(row=idx//2, column=idx%2, padx=10, pady=5)
            
        # Custom URL Frame
        custom_frame = tk.Frame(self.dialog, bg="#2d2d2d", pady=5)
        custom_frame.pack()
        
        lbl_custom = tk.Label(custom_frame, text="Custom URL:", font=("Helvetica", 9), bg="#2d2d2d", fg="#ffffff")
        lbl_custom.pack(side=tk.LEFT, padx=5)
        
        self.entry = tk.Entry(custom_frame, width=22, font=("Helvetica", 10), bg="#3a3a3a", fg="#ffffff", insertbackground="white", relief=tk.FLAT)
        self.entry.pack(side=tk.LEFT, padx=5)
        self.entry.bind("<Return>", lambda event: self.select_custom())
        
        btn_use = tk.Button(
            custom_frame, 
            text="Use URL", 
            font=("Helvetica", 9, "bold"),
            bg="#0080ff",
            fg="#ffffff",
            activebackground="#00ff80",
            relief=tk.FLAT,
            command=self.select_custom
        )
        btn_use.pack(side=tk.LEFT, padx=5)
        
        # Cancel Button
        btn_cancel = tk.Button(
            self.dialog, 
            text="Cancel", 
            font=("Helvetica", 10),
            width=15, 
            bg="#555555",
            fg="#ffffff",
            activebackground="#ff5555",
            relief=tk.FLAT,
            command=self.close
        )
        btn_cancel.pack(pady=10)
        
        self.dialog.protocol("WM_DELETE_WINDOW", self.close)
        self.dialog.wait_window()
        
    def select_source(self, index):
        self.result = str(index)
        self.dialog.destroy()
        
    def select_custom(self):
        url = self.entry.get().strip()
        if url:
            self.result = url
        self.dialog.destroy()
        
    def close(self):
        self.dialog.destroy()


def prompt_camera_source():
    """Display a GUI dialog asking for a camera index or stream URL, with console fallback."""
    print("\n[CAMERA] Opening Change Camera dialog...")
    print("Please select a camera index using the GUI buttons, or use a custom URL.")
    print("If the GUI fails, you can enter the source in this terminal.")
    
    # Scan for connected camera devices
    print("[CAMERA] Scanning for available camera devices...")
    detected = []
    try:
        for i in range(5):
            if i == 0:
                temp_cap = cv2.VideoCapture(i)
                if not temp_cap.isOpened():
                    temp_cap.release()
                    temp_cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
            else:
                temp_cap = cv2.VideoCapture(i, cv2.CAP_DSHOW)
                    
            if temp_cap.isOpened():
                detected.append(i)
            
            temp_cap.release()
    except Exception as e:
        print(f"[CAMERA] Error scanning cameras: {e}")
        
    if not detected:
        # Fallback to Camera 0 (Laptop) if nothing detected
        detected = [0]
    print(f"[CAMERA] Detected active cameras: {detected}")

    source = None
    try:
        root = tk.Tk()
        root.withdraw()
        # Force the root window to be topmost
        root.attributes("-topmost", True)
        root.focus_force()
        
        # Display our custom selection dialog
        dialog = CameraSelectionDialog(root, detected_cameras=detected)
        source = dialog.result
        root.destroy()
    except Exception as e:
        print(f"[CAMERA] Tkinter GUI dialog failed: {e}")
        source = None

    # Fallback to console input if dialog was cancelled, empty, or failed
    if source is None or source.strip() == "":
        print("\n--- CAMERA SWITCH CONSOLE INPUT ---")
        print("Enter camera index (e.g. 0, 1) or IP stream URL (or press Enter to cancel):")
        try:
            console_val = input("Camera source: ").strip()
            if console_val != "":
                source = console_val
        except (KeyboardInterrupt, EOFError):
            print("\n[CAMERA] Console input cancelled.")
            source = None

    return source


def draw_card(frame, x, y, width, height, bg_color=(20, 20, 20), alpha=0.7, border_color=None, border_thickness=1, corner_accents=False):
    """
    Draws a semi-transparent card background with optional border and corner accents.
    """
    h_max, w_max = frame.shape[:2]
    # Bound check
    x1, y1 = max(0, x), max(0, y)
    x2, y2 = min(w_max, x + width), min(h_max, y + height)
    if x2 <= x1 or y2 <= y1:
        return
    
    # Blending the card background
    roi = frame[y1:y2, x1:x2]
    bg = np.zeros_like(roi)
    bg[:] = bg_color
    blend = cv2.addWeighted(bg, alpha, roi, 1.0 - alpha, 0)
    frame[y1:y2, x1:x2] = blend
    
    # Draw border
    if border_color is not None:
        cv2.rectangle(frame, (x1, y1), (x2, y2), border_color, border_thickness)
        
    # Optional corner accents (nice sci-fi styling)
    if corner_accents and border_color is not None:
        l = min(10, width // 4, height // 4)
        # Top-left
        cv2.line(frame, (x1, y1), (x1 + l, y1), border_color, border_thickness + 1)
        cv2.line(frame, (x1, y1), (x1, y1 + l), border_color, border_thickness + 1)
        # Top-right
        cv2.line(frame, (x2 - 1, y1), (x2 - 1 - l, y1), border_color, border_thickness + 1)
        cv2.line(frame, (x2 - 1, y1), (x2 - 1, y1 + l), border_color, border_thickness + 1)
        # Bottom-left
        cv2.line(frame, (x1, y2 - 1), (x1 + l, y2 - 1), border_color, border_thickness + 1)
        cv2.line(frame, (x1, y2 - 1), (x1, y2 - 1 - l), border_color, border_thickness + 1)
        # Bottom-right
        cv2.line(frame, (x2 - 1, y2 - 1), (x2 - 1 - l, y2 - 1), border_color, border_thickness + 1)
        cv2.line(frame, (x2 - 1, y2 - 1), (x2 - 1, y2 - 1 - l), border_color, border_thickness + 1)


def draw_badge(frame, text, x, y, bg_color=(20, 20, 20), text_color=(255, 255, 255), border_color=None, font_scale=0.5, thickness=1, padding=(10, 6)):
    """
    Draws a badge with a semi-transparent background and text inside.
    Returns width and height of the badge.
    """
    px, py = padding
    # Calculate text size
    (tw, th), baseline = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, thickness)
    
    badge_w = tw + px * 2
    badge_h = th + py * 2
    
    # Draw background card
    draw_card(frame, x, y, badge_w, badge_h, bg_color=bg_color, alpha=0.75, border_color=border_color, border_thickness=1)
    
    # Draw text
    tx = x + px
    ty = y + py + th
    cv2.putText(frame, text, (tx, ty), cv2.FONT_HERSHEY_SIMPLEX, font_scale, text_color, thickness, cv2.LINE_AA)
    
    return badge_w, badge_h


def draw_hand_pose_thumbnail(frame, landmarks, x, y, width, height, color=(0, 255, 128)):
    """
    Draws a normalized 2D hand skeleton inside a bounded card region.
    """
    if not landmarks:
        return
        
    # Extract coordinates
    pts = [(lm.x, lm.y) for lm in landmarks]
    xs = [pt[0] for pt in pts]
    ys = [pt[1] for pt in pts]
    
    # Calculate bounding box of the hand
    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)
    
    dx = max_x - min_x
    dy = max_y - min_y
    if dx < 1e-6 or dy < 1e-6:
        return
        
    # Scale to fit inside the thumbnail card (with 15px padding)
    pad = 15
    avail_w = width - 2 * pad
    avail_h = height - 2 * pad
    
    # Keep aspect ratio
    scale = min(avail_w / dx, avail_h / dy)
    
    # Center the hand in the card
    offset_x = x + pad + (avail_w - dx * scale) / 2
    offset_y = y + pad + (avail_h - dy * scale) / 2
    
    # Map points
    mapped_pts = []
    for px, py in pts:
        mx = int(offset_x + (px - min_x) * scale)
        my = int(offset_y + (py - min_y) * scale)
        mapped_pts.append((mx, my))
        
    # Draw connections
    from hand_tracker import HandTracker
    for start_idx, end_idx in HandTracker.HAND_CONNECTIONS:
        pt1 = mapped_pts[start_idx]
        pt2 = mapped_pts[end_idx]
        cv2.line(frame, pt1, pt2, color, 1, cv2.LINE_AA)
        
    # Draw joints
    for idx, (mx, my) in enumerate(mapped_pts):
        if idx == 0:
            cv2.circle(frame, (mx, my), 3, (0, 0, 255), -1, cv2.LINE_AA)  # Wrist
        elif idx in (4, 8, 12, 16, 20):
            cv2.circle(frame, (mx, my), 2, (255, 100, 0), -1, cv2.LINE_AA)  # Tips
        else:
            cv2.circle(frame, (mx, my), 2, (0, 220, 0), -1, cv2.LINE_AA)   # Joints


def draw_ui_overlay(frame, curls, servo_angles, tracker, client, state, grip=None):
    """Draw the redesigned informational overlay on the camera frame and register clickable regions."""
    h, w = frame.shape[:2]
    global CLICKABLE_REGIONS
    CLICKABLE_REGIONS = {}

    fps = state['fps']
    paused = state['paused']
    wrist_enabled = state['wrist_enabled']
    hold_mode = state['hold_mode']
    held_landmarks = state['held_landmarks']

    # Colors (BGR)
    COLOR_DARK_BG = (20, 20, 20)
    COLOR_BORDER_ACCENT = (140, 140, 140)
    COLOR_ACCENT_BLUE = (255, 160, 0)      # Neon Blue
    COLOR_ACCENT_GREEN = (0, 220, 100)     # Neon Green
    COLOR_ACCENT_RED = (50, 50, 255)       # Coral Red
    COLOR_ACCENT_ORANGE = (0, 130, 255)    # Amber Orange
    COLOR_ACCENT_YELLOW = (0, 220, 220)    # Gold Yellow
    COLOR_TEXT_MUTED = (160, 160, 160)
    COLOR_TEXT_BRIGHT = (255, 255, 255)

    # --- Header Badges ---
    # 1. Quit badge (interactive button)
    quit_w, quit_h = draw_badge(
        frame, "QUIT", 10, 10,
        bg_color=(20, 20, 80), text_color=(255, 255, 255),
        border_color=(100, 100, 255), font_scale=0.45, thickness=2
    )
    CLICKABLE_REGIONS["quit"] = (10, 10, 10 + quit_w, 10 + quit_h)

    # 2. Pause/Active badge (interactive toggle)
    pause_label = "PAUSED" if paused else "ACTIVE"
    pause_color = COLOR_ACCENT_RED if paused else COLOR_ACCENT_GREEN
    pause_w, pause_h = draw_badge(
        frame, pause_label, 10 + quit_w + 10, 10,
        bg_color=COLOR_DARK_BG, text_color=pause_color,
        border_color=pause_color, font_scale=0.45, thickness=1
    )
    CLICKABLE_REGIONS["pause_toggle"] = (10 + quit_w + 10, 10, 10 + quit_w + 10 + pause_w, 10 + pause_h)

    # 3. Camera Badge (interactive button)
    cam_str = str(config.CAMERA_INDEX)
    if len(cam_str) > 15:
        cam_str = cam_str[:12] + "..."
    cam_w, cam_h = draw_badge(
        frame, f"CAM: {cam_str}", 10 + quit_w + 10 + pause_w + 10, 10,
        bg_color=COLOR_DARK_BG, text_color=COLOR_TEXT_BRIGHT,
        border_color=COLOR_BORDER_ACCENT, font_scale=0.45, thickness=1
    )
    CLICKABLE_REGIONS["camera"] = (10 + quit_w + 10 + pause_w + 10, 10, 10 + quit_w + 10 + pause_w + 10 + cam_w, 10 + cam_h)

    # 4. Title Badge
    title_x = 10 + quit_w + 10 + pause_w + 10 + cam_w + 10
    title_w, _ = draw_badge(
        frame, "INMOOV", title_x, 10,
        bg_color=(35, 25, 15), text_color=COLOR_TEXT_BRIGHT,
        border_color=COLOR_ACCENT_BLUE, font_scale=0.45, thickness=1
    )

    # Connection badge & Reconnect (interactive button)
    status_text = "CONNECTED" if client.connected else "DISCONNECTED"
    status_color = COLOR_ACCENT_GREEN if client.connected else COLOR_ACCENT_RED
    
    # Place FPS badge at the very right: w - 85
    fps_w, _ = draw_badge(
        frame, f"FPS: {fps:.0f}", w - 85, 10,
        bg_color=COLOR_DARK_BG, text_color=COLOR_ACCENT_GREEN if fps >= 15 else COLOR_ACCENT_ORANGE,
        border_color=COLOR_BORDER_ACCENT, font_scale=0.45, thickness=1
    )
    
    # Place status badge to the left of the FPS badge
    reconnect_x = w - 85 - 130
    status_badge_w, status_badge_h = draw_badge(
        frame, status_text, reconnect_x, 10,
        bg_color=COLOR_DARK_BG, text_color=status_color,
        border_color=status_color, font_scale=0.45, thickness=1
    )
    CLICKABLE_REGIONS["reconnect"] = (reconnect_x, 10, reconnect_x + status_badge_w, 10 + status_badge_h)

    # --- Hold Mode Badge ---
    # Located under the top badges (y=45)
    if hold_mode:
        hold_w, hold_h = draw_badge(
            frame, "[HOLD] POSTURE LOCKED", 10, 45,
            bg_color=(15, 30, 15), text_color=COLOR_ACCENT_YELLOW,
            border_color=COLOR_ACCENT_YELLOW, font_scale=0.45, thickness=1
        )
        cv2.putText(frame, "Click here or press 'H' to release", (10, 80),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, COLOR_TEXT_MUTED, 1, cv2.LINE_AA)
    else:
        hold_w, hold_h = draw_badge(
            frame, "[HOLD] LIVE CONTROLLER", 10, 45,
            bg_color=COLOR_DARK_BG, text_color=COLOR_TEXT_MUTED,
            border_color=COLOR_BORDER_ACCENT, font_scale=0.45, thickness=1
        )
        cv2.putText(frame, "Click here or press 'H' to lock current posture", (10, 80),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, COLOR_TEXT_MUTED, 1, cv2.LINE_AA)
    CLICKABLE_REGIONS["hold"] = (10, 45, 10 + hold_w, 45 + hold_h)

    # --- Grip Controller Card ---
    # Located under the connection/fps badges on the right side
    if grip:
        strength = grip.get_strength()
        mode_label = grip.label
        
        # Color based on strength: green (soft) -> orange -> red (firm)
        if strength <= 35:
            grip_color = COLOR_ACCENT_GREEN
        elif strength <= 70:
            grip_color = COLOR_ACCENT_ORANGE
        else:
            grip_color = COLOR_ACCENT_RED
            
        grip_x = w - 215
        grip_y = 45
        grip_w = 200
        grip_h = 55
        
        # Draw background card
        draw_card(frame, grip_x, grip_y, grip_w, grip_h, bg_color=COLOR_DARK_BG, alpha=0.75, border_color=grip_color, corner_accents=True)
        
        # Grip label
        cv2.putText(frame, f"GRIP: {mode_label}", (grip_x + 10, grip_y + 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, COLOR_TEXT_BRIGHT, 1, cv2.LINE_AA)
        
        # Strength Bar
        bar_x = grip_x + 10
        bar_y = grip_y + 28
        bar_w = 135
        bar_h = 8
        
        cv2.rectangle(frame, (bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h), (50, 50, 50), -1)
        fill_w = int(bar_w * strength / 100)
        cv2.rectangle(frame, (bar_x, bar_y), (bar_x + fill_w, bar_y + bar_h), grip_color, -1)
        cv2.rectangle(frame, (bar_x, bar_y), (bar_x + bar_w, bar_y + bar_h), COLOR_BORDER_ACCENT, 1)
        
        # Strength percentage text
        cv2.putText(frame, f"{strength:.0f}%", (bar_x + bar_w + 8, bar_y + 8),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, COLOR_TEXT_BRIGHT, 1, cv2.LINE_AA)
        CLICKABLE_REGIONS["grip"] = (grip_x, grip_y, grip_x + grip_w, grip_y + grip_h)

    # --- System Notifications & Alerts ---
    # Center Alert for No Hand Detected
    if not tracker.hand_detected and not hold_mode:
        alert_w = 420
        alert_h = 50
        alert_x = (w - alert_w) // 2
        alert_y = h // 2 - 50
        
        # Background card
        draw_card(frame, alert_x, alert_y, alert_w, alert_h, bg_color=(15, 20, 30), alpha=0.8, border_color=COLOR_ACCENT_ORANGE, corner_accents=True)
        
        # Alert Text
        cv2.putText(frame, "WARNING: NO HAND DETECTED", (alert_x + 15, alert_y + 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, COLOR_ACCENT_ORANGE, 2, cv2.LINE_AA)
        cv2.putText(frame, "Show your hand to the camera to transmit control commands.", (alert_x + 15, alert_y + 38),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, COLOR_TEXT_BRIGHT, 1, cv2.LINE_AA)

    # Center Alert for Paused System (interactive toggle on click)
    if paused:
        alert_w = 420
        alert_h = 50
        alert_x = (w - alert_w) // 2
        alert_y = h // 2 + 15 if (not tracker.hand_detected and not hold_mode) else h // 2 - 25
        
        # Background card
        draw_card(frame, alert_x, alert_y, alert_w, alert_h, bg_color=(30, 15, 15), alpha=0.8, border_color=COLOR_ACCENT_RED, corner_accents=True)
        
        # Alert Text
        cv2.putText(frame, "SYSTEM TRANSMISSION: PAUSED", (alert_x + 15, alert_y + 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, COLOR_ACCENT_RED, 2, cv2.LINE_AA)
        cv2.putText(frame, "ESP32 command pipeline is frozen. Click here to resume.", (alert_x + 15, alert_y + 38),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, COLOR_TEXT_BRIGHT, 1, cv2.LINE_AA)
        CLICKABLE_REGIONS["pause_toggle_alert"] = (alert_x, alert_y, alert_x + alert_w, alert_y + alert_h)

    # --- Finger Angle Bars / Telemetry Card ---
    if config.SHOW_ANGLE_BARS:
        card_x = 15
        card_w = 330 if wrist_enabled else 275
        card_y = h - 185
        card_h = 145
        
        draw_card(frame, card_x, card_y, card_w, card_h, bg_color=COLOR_DARK_BG, alpha=0.75, border_color=COLOR_ACCENT_BLUE, corner_accents=True)
        
        # Telemetry title
        cv2.putText(frame, "TELEMETRY", (card_x + 12, card_y + 18),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, COLOR_ACCENT_BLUE, 1, cv2.LINE_AA)
        
        # Wrist control toggle button next to title
        wrist_btn_text = "WRIST: ON" if wrist_enabled else "WRIST: OFF"
        wrist_btn_color = COLOR_ACCENT_GREEN if wrist_enabled else COLOR_TEXT_MUTED
        wrist_btn_w, wrist_btn_h = draw_badge(
            frame, wrist_btn_text, card_x + 110, card_y + 5,
            bg_color=COLOR_DARK_BG, text_color=wrist_btn_color,
            border_color=wrist_btn_color, font_scale=0.35, thickness=1, padding=(6, 3)
        )
        CLICKABLE_REGIONS["wrist_toggle"] = (card_x + 110, card_y + 5, card_x + 110 + wrist_btn_w, card_y + 5 + wrist_btn_h)
        
        bar_x_start = card_x + 15
        bar_y_start = card_y + 40
        bar_width = 30
        bar_max_height = 75
        bar_spacing = 50
        finger_names = ["thumb", "index", "middle", "ring", "pinky"]

        if wrist_enabled:
            finger_names.append("wrist")

        for idx, name in enumerate(finger_names):
            x = bar_x_start + idx * bar_spacing
            y_base = bar_y_start + bar_max_height

            # Background bar
            cv2.rectangle(frame, (x, bar_y_start), (x + bar_width, y_base), (45, 45, 45), -1)

            # Fill percentage
            if name == "wrist":
                fill_pct = curls.get(name, 90) / 180.0 * 100
            else:
                fill_pct = curls.get(name, 0)

            fill_height = int(bar_max_height * fill_pct / 100)

            # Color gradient
            if fill_pct <= 35:
                bar_color = COLOR_ACCENT_GREEN
            elif fill_pct <= 70:
                bar_color = COLOR_ACCENT_ORANGE
            else:
                bar_color = COLOR_ACCENT_RED

            cv2.rectangle(frame, (x, y_base - fill_height), (x + bar_width, y_base), bar_color, -1)
            cv2.rectangle(frame, (x, bar_y_start), (x + bar_width, y_base), COLOR_BORDER_ACCENT, 1)

            # Finger Label
            label = name[0].upper() if name != "wrist" else "W"
            cv2.putText(frame, label, (x + 8, y_base + 16),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, COLOR_TEXT_BRIGHT, 1, cv2.LINE_AA)

            # Angle value
            angle = servo_angles.get(name, 0)
            cv2.putText(frame, f"{angle}", (x + 2, bar_y_start - 6),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, COLOR_TEXT_MUTED, 1, cv2.LINE_AA)

    # --- Hand Pose Thumbnail Card ---
    pose_card_x = w - 180
    pose_card_y = h - 185
    pose_card_w = 165
    pose_card_h = 145
    
    # Determine which landmarks to show
    if hold_mode:
        active_landmarks = held_landmarks
        pose_title = "POSE LOCKED"
        pose_border = COLOR_ACCENT_YELLOW
        pose_title_color = COLOR_ACCENT_YELLOW
    else:
        active_landmarks = tracker._last_landmarks if tracker.hand_detected else None
        pose_title = "POSE LIVE" if active_landmarks else "NO HAND"
        pose_border = COLOR_ACCENT_BLUE if active_landmarks else COLOR_BORDER_ACCENT
        pose_title_color = COLOR_ACCENT_BLUE if active_landmarks else COLOR_TEXT_MUTED

    draw_card(frame, pose_card_x, pose_card_y, pose_card_w, pose_card_h, bg_color=COLOR_DARK_BG, alpha=0.75, border_color=pose_border, corner_accents=True)
    
    # Title
    cv2.putText(frame, pose_title, (pose_card_x + 12, pose_card_y + 18),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, pose_title_color, 1, cv2.LINE_AA)
    
    # Render pose skeleton
    if active_landmarks:
        draw_hand_pose_thumbnail(
            frame, active_landmarks,
            pose_card_x, pose_card_y + 20,
            pose_card_w, pose_card_h - 20,
            color=COLOR_ACCENT_GREEN
        )
    else:
        cv2.putText(frame, "WAITING...", (pose_card_x + 35, pose_card_y + 80),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, COLOR_TEXT_MUTED, 1, cv2.LINE_AA)

    # --- Bottom Help / Control Strip ---
    taskbar_h = 30
    taskbar_y = h - taskbar_h
    
    # Draw bottom taskbar card
    draw_card(frame, 0, taskbar_y, w, taskbar_h, bg_color=(10, 10, 10), alpha=0.9, border_color=None)
    
    # Draw taskbar text
    controls = "MOUSE:Click badges to control | Keys: Q:Quit | P:Pause | R:Reconn | M:Mirror | H:Hold | C:Cam | Space:Wrist | G:Grip"
    cv2.putText(frame, controls, (15, h - 11),
                cv2.FONT_HERSHEY_SIMPLEX, 0.38, COLOR_TEXT_BRIGHT, 1, cv2.LINE_AA)

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

    # Initialize camera (robust fallback for both built-in and virtual cameras)
    cam_source = config.CAMERA_INDEX
    if isinstance(cam_source, str) and cam_source.isdigit():
        cam_source = int(cam_source)

    if isinstance(cam_source, int):
        if cam_source == 0:
            cap = cv2.VideoCapture(cam_source)
            if not cap.isOpened():
                cap = cv2.VideoCapture(cam_source, cv2.CAP_DSHOW)
        else:
            cap = cv2.VideoCapture(cam_source, cv2.CAP_DSHOW)
            if not cap.isOpened():
                cap = cv2.VideoCapture(cam_source)
    else:
        cap = cv2.VideoCapture(cam_source)
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
    state = {
        'paused': False,
        'wrist_enabled': True,
        'hold_mode': False,
        'mirror': config.MIRROR_MODE,
        'fps': 0.0,
        'held_curls': None,
        'held_servo_angles': None,
        'held_landmarks': None,
        'camera_source_changed': False,
        'reconnect_requested': False,
        'quit_requested': False,
        'curls': {f: 0.0 for f in ["thumb", "index", "middle", "ring", "pinky"]},
        'servo_angles': {f: config.SERVO_MIN[f] for f in ["thumb", "index", "middle", "ring", "pinky"]},
    }
    prev_time = time.perf_counter()
    window_created = False

    def on_mouse_click(event, x, y, flags, param):
        if event != cv2.EVENT_LBUTTONDOWN:
            return
        
        # Check CLICKABLE_REGIONS
        for region_name, (rx1, ry1, rx2, ry2) in CLICKABLE_REGIONS.items():
            if rx1 <= x <= rx2 and ry1 <= y <= ry2:
                print(f"[MOUSE] Clicked region: {region_name}")
                if region_name == "quit":
                    state['quit_requested'] = True
                elif region_name in ("pause_toggle", "pause_toggle_alert"):
                    state['paused'] = not state['paused']
                    print(f"[INFO] {'Paused' if state['paused'] else 'Resumed'} sending")
                elif region_name == "camera":
                    state['camera_source_changed'] = True
                elif region_name == "reconnect":
                    state['reconnect_requested'] = True
                elif region_name == "hold":
                    if not state['hold_mode']:
                        if tracker.hand_detected:
                            state['hold_mode'] = True
                            state['held_curls'] = dict(state['curls'])
                            state['held_servo_angles'] = dict(state['servo_angles'])
                            state['held_landmarks'] = list(tracker._last_landmarks) if tracker._last_landmarks is not None else None
                            print(f"[HOLD] LOCKED — posture frozen (click hold badge again to release)")
                        else:
                            print(f"[HOLD] Cannot lock — no hand detected. Show your hand first.")
                    else:
                        state['hold_mode'] = False
                        state['held_curls'] = None
                        state['held_servo_angles'] = None
                        state['held_landmarks'] = None
                        print(f"[HOLD] RELEASED — back to live tracking")
                elif region_name == "wrist_toggle":
                    state['wrist_enabled'] = not state['wrist_enabled']
                    print(f"[INFO] Wrist control: {'ON' if state['wrist_enabled'] else 'OFF'}")
                elif region_name == "grip":
                    mode = grip.cycle_mode()
                    client.set_grip_strength(int(grip.get_strength()))
                    print(f"[GRIP] Mode: {mode} — {grip.label} (strength {grip.get_strength():.0f}%)")
                break

    try:
        while True:
            # Check async actions requested by mouse clicks
            if state['quit_requested']:
                print("\n[EXIT] Quitting via mouse click...")
                break

            if state['reconnect_requested']:
                state['reconnect_requested'] = False
                print("[INFO] Reconnecting to ESP32 via mouse click...")
                client.disconnect()
                if client.connect():
                    client.sync_config()
                    client.set_grip_strength(int(grip.get_strength()))
                    print("[INFO] Reconnected!")
                else:
                    print("[INFO] Reconnection failed")

            if state['camera_source_changed']:
                state['camera_source_changed'] = False
                print("\n[CAMERA] Opening Change Camera dialog via mouse click...")
                # Temporarily destroy the OpenCV window to prevent it from freezing on screen
                try:
                    cv2.destroyWindow(config.WINDOW_NAME)
                    window_created = False
                except cv2.error:
                    pass

                new_source = prompt_camera_source()
                if new_source is not None and new_source.strip() != "":
                    new_source = new_source.strip()
                    if new_source.isdigit():
                        camera_source = int(new_source)
                    else:
                        camera_source = new_source
                    
                    print(f"[CAMERA] Attempting to switch to source: {camera_source}")
                    if isinstance(camera_source, int):
                        if camera_source == 0:
                            new_cap = cv2.VideoCapture(camera_source)
                            if not new_cap.isOpened():
                                new_cap = cv2.VideoCapture(camera_source, cv2.CAP_DSHOW)
                        else:
                            new_cap = cv2.VideoCapture(camera_source, cv2.CAP_DSHOW)
                            if not new_cap.isOpened():
                                new_cap = cv2.VideoCapture(camera_source)
                    else:
                        new_cap = cv2.VideoCapture(camera_source)
                    if new_cap.isOpened():
                        new_cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.CAMERA_WIDTH)
                        new_cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.CAMERA_HEIGHT)
                        cap.release()
                        cap = new_cap
                        config.CAMERA_INDEX = camera_source
                        print(f"[CAMERA] Successfully switched to camera: {camera_source}")
                    else:
                        print(f"[CAMERA] Error: Failed to open camera source: {camera_source}")

            ret, frame = cap.read()
            if not ret:
                print("[ERROR] Camera read failed!")
                break

            # Mirror the frame if needed
            if state['mirror']:
                frame = cv2.flip(frame, 1)

            # Convert BGR → RGB for MediaPipe
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            # Process hand tracking
            curls = tracker.process_frame(frame_rgb)

            # --- Determine servo output ---
            if state['hold_mode'] and state['held_servo_angles'] is not None:
                # LOCKED: ignore live tracking, use frozen posture
                curls = dict(state['held_curls'])
                servo_angles = dict(state['held_servo_angles'])
            else:
                # LIVE: compute from hand tracking
                servo_angles = {}
                if tracker.hand_detected:
                    for finger in ["thumb", "index", "middle", "ring", "pinky"]:
                        servo_angles[finger] = curl_to_servo_angle(curls[finger], finger, grip)

                    if state['wrist_enabled']:
                        servo_angles["wrist"] = wrist_to_servo_angle(curls["wrist"])
                    else:
                        servo_angles["wrist"] = 90  # Neutral
                else:
                    # No hand detected — reset to open
                    curls = {f: 0.0 for f in ["thumb", "index", "middle", "ring", "pinky"]}
                    curls["wrist"] = 90.0
                    servo_angles = {f: config.SERVO_MIN[f] for f in ["thumb", "index", "middle", "ring", "pinky"]}
                    servo_angles["wrist"] = 90

                # Save live values so that mouse click can capture them
                state['curls'] = curls
                state['servo_angles'] = servo_angles

            # Send to ESP32 (if not paused)
            if not state['paused']:
                client.send_all_servos(servo_angles)

            # Draw landmarks
            if config.SHOW_LANDMARKS:
                frame = tracker.draw_landmarks(frame)

            # Calculate FPS (perf_counter for high-resolution timing on Windows)
            current_time = time.perf_counter()
            dt = current_time - prev_time
            if dt > 0:
                state['fps'] = 0.9 * state['fps'] + 0.1 * (1.0 / dt)  # Smoothed FPS
            prev_time = current_time

            # Draw UI overlay
            frame = draw_ui_overlay(
                frame, curls, servo_angles, tracker, client,
                state, grip=grip,
            )

            # Show frame
            cv2.imshow(config.WINDOW_NAME, frame)
            if not window_created:
                cv2.setMouseCallback(config.WINDOW_NAME, on_mouse_click)
                window_created = True

            # Handle keyboard input
            key = cv2.waitKey(1) & 0xFF

            if key == ord('q') or key == ord('Q'):
                print("\n[EXIT] Quitting...")
                break
            elif key == ord('p') or key == ord('P'):
                state['paused'] = not state['paused']
                print(f"[INFO] {'Paused' if state['paused'] else 'Resumed'} sending")
            elif key == ord('r') or key == ord('R'):
                state['reconnect_requested'] = True
            elif key == ord('m') or key == ord('M'):
                state['mirror'] = not state['mirror']
                print(f"[INFO] Mirror mode: {'ON' if state['mirror'] else 'OFF'}")
            elif key == ord('c') or key == ord('C'):
                state['camera_source_changed'] = True
            elif key == ord('h') or key == ord('H'):
                if not state['hold_mode']:
                    # Attempting to LOCK — only allow if hand is currently detected
                    if tracker.hand_detected:
                        state['hold_mode'] = True
                        state['held_curls'] = dict(curls)
                        state['held_servo_angles'] = dict(servo_angles)
                        state['held_landmarks'] = list(tracker._last_landmarks) if tracker._last_landmarks is not None else None
                        print(f"[HOLD] LOCKED — posture frozen (press H again to release)")
                    else:
                        print(f"[HOLD] Cannot lock — no hand detected. Show your hand first.")
                else:
                    # UNLOCK
                    state['hold_mode'] = False
                    state['held_curls'] = None
                    state['held_servo_angles'] = None
                    state['held_landmarks'] = None
                    print(f"[HOLD] RELEASED — back to live tracking")
            elif key == ord(' '):
                state['wrist_enabled'] = not state['wrist_enabled']
                print(f"[INFO] Wrist control: {'ON' if state['wrist_enabled'] else 'OFF'}")
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