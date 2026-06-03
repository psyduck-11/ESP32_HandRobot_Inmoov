"""
Hand Tracking Module — MediaPipe Tasks API hand landmark detection.
Detects hand landmarks from webcam frames and computes per-finger
curl percentages (0% = open, 100% = fully closed).

Uses the new MediaPipe Tasks API (0.10.14+), which replaces the
deprecated mp.solutions.hands interface.
"""

import os
import math
import time
import numpy as np
import cv2
import mediapipe as mp
from mediapipe.tasks import python as mp_tasks
from mediapipe.tasks.python import vision

import config


# Path to the hand landmarker model file
_MODEL_PATH = os.path.join(os.path.dirname(__file__), "hand_landmarker.task")

# Number of frames without detection before resetting smoothed values
_LOST_HAND_RESET_FRAMES = 15


class HandTracker:
    """
    Uses MediaPipe Hand Landmarker (Tasks API) to detect hand landmarks
    and compute finger curl angles.
    """

    # MediaPipe hand landmark indices
    WRIST = 0
    THUMB_CMC = 1
    THUMB_MCP = 2
    THUMB_IP  = 3
    THUMB_TIP = 4
    INDEX_MCP = 5
    INDEX_PIP = 6
    INDEX_DIP = 7
    INDEX_TIP = 8
    MIDDLE_MCP = 9
    MIDDLE_PIP = 10
    MIDDLE_DIP = 11
    MIDDLE_TIP = 12
    RING_MCP = 13
    RING_PIP = 14
    RING_DIP = 15
    RING_TIP = 16
    PINKY_MCP = 17
    PINKY_PIP = 18
    PINKY_DIP = 19
    PINKY_TIP = 20

    # Finger definitions: (name, [base, PIP-equiv, DIP-equiv, TIP])
    FINGER_LANDMARKS = {
        "thumb":  [THUMB_CMC, THUMB_MCP, THUMB_IP, THUMB_TIP],
        "index":  [INDEX_MCP, INDEX_PIP, INDEX_DIP, INDEX_TIP],
        "middle": [MIDDLE_MCP, MIDDLE_PIP, MIDDLE_DIP, MIDDLE_TIP],
        "ring":   [RING_MCP, RING_PIP, RING_DIP, RING_TIP],
        "pinky":  [PINKY_MCP, PINKY_PIP, PINKY_DIP, PINKY_TIP],
    }

    # Hand landmark connections for drawing (same as MediaPipe standard)
    HAND_CONNECTIONS = [
        (0, 1), (1, 2), (2, 3), (3, 4),       # Thumb
        (0, 5), (5, 6), (6, 7), (7, 8),       # Index
        (0, 9), (9, 10), (10, 11), (11, 12),  # Middle
        (0, 13), (13, 14), (14, 15), (15, 16), # Ring
        (0, 17), (17, 18), (18, 19), (19, 20), # Pinky
        (5, 9), (9, 13), (13, 17),             # Palm
    ]

    def __init__(self):
        if not os.path.exists(_MODEL_PATH):
            raise FileNotFoundError(
                f"Hand landmarker model not found at: {_MODEL_PATH}\n"
                "Download it with:\n"
                '  Invoke-WebRequest -Uri "https://storage.googleapis.com/mediapipe-models/'
                'hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task" '
                '-OutFile "hand_landmarker.task"'
            )

        # Configure Hand Landmarker
        base_options = mp_tasks.BaseOptions(model_asset_path=_MODEL_PATH)
        options = vision.HandLandmarkerOptions(
            base_options=base_options,
            running_mode=vision.RunningMode.VIDEO,
            num_hands=config.MEDIAPIPE_MAX_HANDS,
            min_hand_detection_confidence=config.MEDIAPIPE_DETECTION_CONFIDENCE,
            min_hand_presence_confidence=config.MEDIAPIPE_TRACKING_CONFIDENCE,
            min_tracking_confidence=config.MEDIAPIPE_TRACKING_CONFIDENCE,
        )
        self._landmarker = vision.HandLandmarker.create_from_options(options)

        # Use real wall-clock time for MediaPipe VIDEO mode timestamps
        self._start_time = time.perf_counter()
        self._last_timestamp_ms = 0

        # EMA-smoothed curl values
        self._smoothed = {
            "thumb": 0.0, "index": 0.0, "middle": 0.0,
            "ring": 0.0, "pinky": 0.0, "wrist": 90.0,
        }

        # Raw (unsmoothed) curl values for display
        self.raw_curls = dict(self._smoothed)

        # Last detection result (for drawing)
        self._last_landmarks = None
        self._hand_detected = False
        self._frames_since_lost = 0

    @property
    def hand_detected(self) -> bool:
        return self._hand_detected

    def process_frame(self, frame_rgb: np.ndarray) -> dict:
        """
        Process an RGB frame and return smoothed curl percentages.

        Args:
            frame_rgb: RGB image (H, W, 3) as numpy array.

        Returns:
            Dict with keys: thumb, index, middle, ring, pinky, wrist
            Values: 0.0 (open) to 100.0 (closed) for fingers,
                    0–180 degrees for wrist rotation.
        """
        # Convert to MediaPipe Image
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)

        # Use real elapsed time for monotonically increasing timestamps
        elapsed_ms = int((time.perf_counter() - self._start_time) * 1000)
        # Ensure strictly increasing (MediaPipe requires monotonic)
        if elapsed_ms <= self._last_timestamp_ms:
            elapsed_ms = self._last_timestamp_ms + 1
        self._last_timestamp_ms = elapsed_ms

        # Run detection
        result = self._landmarker.detect_for_video(mp_image, elapsed_ms)

        if not result.hand_landmarks:
            self._hand_detected = False
            self._last_landmarks = None
            self._frames_since_lost += 1

            # After losing the hand for N frames, reset smoothed values
            # so re-detection doesn't start from stale data
            if self._frames_since_lost >= _LOST_HAND_RESET_FRAMES:
                self._smoothed = {
                    "thumb": 0.0, "index": 0.0, "middle": 0.0,
                    "ring": 0.0, "pinky": 0.0, "wrist": 90.0,
                }
            return dict(self._smoothed)

        self._hand_detected = True
        self._frames_since_lost = 0
        # Use the first detected hand
        landmarks = result.hand_landmarks[0]
        self._last_landmarks = landmarks

        # Compute raw curl for each finger
        raw = {}
        for finger_name, lm_indices in self.FINGER_LANDMARKS.items():
            curl = self._compute_finger_curl(landmarks, lm_indices, finger_name)
            raw[finger_name] = curl

        # Compute wrist rotation angle
        raw["wrist"] = self._compute_wrist_rotation(landmarks)

        self.raw_curls = dict(raw)

        # Apply EMA smoothing
        alpha = config.EMA_ALPHA
        for key in self._smoothed:
            self._smoothed[key] = alpha * raw[key] + (1 - alpha) * self._smoothed[key]

        return dict(self._smoothed)

    def _compute_finger_curl(self, landmarks, indices, finger_name: str) -> float:
        """
        Compute how curled a finger is (0 = extended, 100 = fully curled).
        Uses tuples + scalar math to avoid numpy allocation overhead.
        """
        # Get 3D coordinates as tuples (no numpy array allocation)
        pts = []
        for idx in indices:
            lm = landmarks[idx]
            pts.append((lm.x, lm.y, lm.z))

        if finger_name == "thumb":
            return self._compute_thumb_curl(landmarks, pts)

        # For regular fingers: compute angles at PIP and DIP joints
        base, pip_joint, dip_joint, tip = pts

        angle_pip = self._angle_between(base, pip_joint, dip_joint)
        angle_dip = self._angle_between(pip_joint, dip_joint, tip)

        # Combined curl: weighted sum of joint angles
        avg_angle = 0.65 * angle_pip + 0.35 * angle_dip

        # Map angle to curl percentage
        # 170° = straight (0% curl), 40° = fully bent (100% curl)
        if avg_angle >= 170.0:
            curl = 0.0
        elif avg_angle <= 40.0:
            curl = 100.0
        else:
            curl = (170.0 - avg_angle) / (170.0 - 40.0) * 100.0

        return max(0.0, min(100.0, curl))

    def _compute_thumb_curl(self, landmarks, pts) -> float:
        """
        Compute thumb curl using distance + angle hybrid method.
        Uses scalar math to avoid numpy allocation overhead.
        """
        cmc, mcp, ip, tip = pts

        index_mcp = landmarks[self.INDEX_MCP]
        imx, imy, imz = index_mcp.x, index_mcp.y, index_mcp.z

        wrist_lm = landmarks[self.WRIST]
        wx, wy, wz = wrist_lm.x, wrist_lm.y, wrist_lm.z

        # Distance from thumb tip to index finger base (scalar)
        dx = tip[0] - imx
        dy = tip[1] - imy
        dz = tip[2] - imz
        dist = math.sqrt(dx*dx + dy*dy + dz*dz)

        # Normalize by hand size (wrist to middle MCP)
        middle_mcp = landmarks[self.MIDDLE_MCP]
        mmx, mmy, mmz = middle_mcp.x, middle_mcp.y, middle_mcp.z
        hx = mmx - wx
        hy = mmy - wy
        hz = mmz - wz
        hand_size = math.sqrt(hx*hx + hy*hy + hz*hz)

        if hand_size < 1e-6:
            return 0.0

        normalized_dist = dist / hand_size

        # Angle at MCP joint
        angle_mcp = self._angle_between(cmc, mcp, ip)

        # Combine distance and angle methods (scalar interp)
        # curl_dist: [0.15, 0.7] -> [100, 0]
        if normalized_dist <= 0.15:
            curl_dist = 100.0
        elif normalized_dist >= 0.7:
            curl_dist = 0.0
        else:
            curl_dist = (0.7 - normalized_dist) / (0.7 - 0.15) * 100.0

        # curl_angle: [90, 160] -> [100, 0] (Amplified from 60)
        if angle_mcp <= 90.0:
            curl_angle = 100.0
        elif angle_mcp >= 160.0:
            curl_angle = 0.0
        else:
            curl_angle = (160.0 - angle_mcp) / (160.0 - 90.0) * 100.0

        curl = 0.5 * curl_dist + 0.5 * curl_angle
        return max(0.0, min(100.0, curl))

    def _compute_wrist_rotation(self, landmarks) -> float:
        """
        Compute wrist rotation (pronation/supination) from the palm's
        roll angle.  Returns a value in degrees (0–180) for the servo.

        Method: measure the angle of the cross-palm vector (index MCP →
        pinky MCP) projected onto the plane perpendicular to the hand's
        longitudinal axis.  This isolates forearm roll from arm tilt or
        wrist flexion/extension.
        """
        wrist = landmarks[self.WRIST]
        middle_mcp = landmarks[self.MIDDLE_MCP]
        index_mcp = landmarks[self.INDEX_MCP]
        pinky_mcp = landmarks[self.PINKY_MCP]

        # Longitudinal axis of the hand (wrist → middle MCP)
        ax = middle_mcp.x - wrist.x
        ay = middle_mcp.y - wrist.y
        az = middle_mcp.z - wrist.z
        a_mag = math.sqrt(ax * ax + ay * ay + az * az)
        if a_mag < 1e-8:
            return 90.0  # neutral fallback

        # Normalise longitudinal axis
        ax /= a_mag
        ay /= a_mag
        az /= a_mag

        # Cross-palm vector (index MCP → pinky MCP)
        cx = pinky_mcp.x - index_mcp.x
        cy = pinky_mcp.y - index_mcp.y
        cz = pinky_mcp.z - index_mcp.z

        # Project cross-palm onto the plane perpendicular to the
        # longitudinal axis:  c_perp = c - (c · a) * a
        dot_ca = cx * ax + cy * ay + cz * az
        px = cx - dot_ca * ax
        py = cy - dot_ca * ay
        pz = cz - dot_ca * az

        # We need two reference axes in the perpendicular plane.
        # Choose "camera-right" (1,0,0) and "camera-up" (0,-1,0) as the
        # world frame, then Gram-Schmidt them against the hand axis.
        #
        # Ref-right: r = (1,0,0) - ((1,0,0)·a)*a  → horizontal in image
        rx = 1.0 - ax * ax
        ry = 0.0 - ax * ay
        rz = 0.0 - ax * az
        r_mag = math.sqrt(rx * rx + ry * ry + rz * rz)

        # If the hand axis is nearly parallel to camera-right, fall back
        # to camera-up as the reference instead.
        if r_mag < 1e-6:
            rx = 0.0 - ay * ax
            ry = -1.0 - ay * ay
            rz = 0.0 - ay * az
            r_mag = math.sqrt(rx * rx + ry * ry + rz * rz)
            if r_mag < 1e-6:
                return 90.0
        rx /= r_mag
        ry /= r_mag
        rz /= r_mag

        # Second perpendicular axis: u = a × r  (camera-"up"-ish)
        ux = ay * rz - az * ry
        uy = az * rx - ax * rz
        uz = ax * ry - ay * rx

        # Angle of the projected cross-palm vector in the r-u plane
        comp_r = px * rx + py * ry + pz * rz
        comp_u = px * ux + py * uy + pz * uz

        roll_rad = math.atan2(comp_u, comp_r)
        roll_deg = math.degrees(roll_rad)  # –180 … +180

        # Map roll to servo range.
        # roll ≈ 0°    → palm facing camera (front face)  → servo 180
        # roll ≈ ±180° → back of hand facing camera       → servo 0
        # Use cosine to smoothly map: cos(0)=1 → 180, cos(±180)=-1 → 0
        servo_angle = (math.cos(roll_rad) + 1.0) * 90.0  # 0…180

        return max(0.0, min(180.0, servo_angle))

    @staticmethod
    def _angle_between(a, b, c) -> float:
        """
        Calculate the angle at point B formed by points A-B-C.
        Uses scalar math to avoid numpy array allocation overhead.
        a, b, c are tuples/lists of (x, y, z).
        Returns angle in degrees.
        """
        bax = a[0] - b[0]
        bay = a[1] - b[1]
        baz = a[2] - b[2]
        bcx = c[0] - b[0]
        bcy = c[1] - b[1]
        bcz = c[2] - b[2]

        dot = bax * bcx + bay * bcy + baz * bcz
        mag_ba = math.sqrt(bax*bax + bay*bay + baz*baz)
        mag_bc = math.sqrt(bcx*bcx + bcy*bcy + bcz*bcz)

        if mag_ba < 1e-8 or mag_bc < 1e-8:
            return 180.0

        cos_angle = dot / (mag_ba * mag_bc)
        # Clamp to [-1, 1] to handle floating point errors
        if cos_angle > 1.0:
            cos_angle = 1.0
        elif cos_angle < -1.0:
            cos_angle = -1.0

        return math.degrees(math.acos(cos_angle))

    def draw_landmarks(self, frame_bgr: np.ndarray) -> np.ndarray:
        """
        Draw hand landmarks and connections on the BGR frame.
        Uses manual drawing since mp.solutions.drawing_utils is no longer available.
        """
        if self._last_landmarks is None:
            return frame_bgr

        h, w = frame_bgr.shape[:2]
        landmarks = self._last_landmarks

        # Convert normalized coordinates to pixel coordinates
        pixel_coords = []
        for lm in landmarks:
            px = int(lm.x * w)
            py = int(lm.y * h)
            pixel_coords.append((px, py))

        # Draw connections
        for start_idx, end_idx in self.HAND_CONNECTIONS:
            pt1 = pixel_coords[start_idx]
            pt2 = pixel_coords[end_idx]
            cv2.line(frame_bgr, pt1, pt2, (0, 255, 128), 2, cv2.LINE_AA)

        # Draw landmark points
        for i, (px, py) in enumerate(pixel_coords):
            # Color: wrist=red, fingertips=blue, others=green
            if i == 0:
                color = (0, 0, 255)    # Wrist — red
                radius = 6
            elif i in (4, 8, 12, 16, 20):
                color = (255, 100, 0)  # Fingertips — blue
                radius = 5
            else:
                color = (0, 220, 0)    # Joints — green
                radius = 4

            cv2.circle(frame_bgr, (px, py), radius, color, -1, cv2.LINE_AA)
            cv2.circle(frame_bgr, (px, py), radius, (255, 255, 255), 1, cv2.LINE_AA)

        return frame_bgr

    def release(self):
        """Release MediaPipe resources."""
        self._landmarker.close()
