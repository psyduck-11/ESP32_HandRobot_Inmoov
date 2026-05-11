"""
Hand Tracking Module — MediaPipe Tasks API hand landmark detection.
Detects hand landmarks from webcam frames and computes per-finger
curl percentages (0% = open, 100% = fully closed).

Uses the new MediaPipe Tasks API (0.10.14+), which replaces the
deprecated mp.solutions.hands interface.
"""

import os
import math
import numpy as np
import cv2
import mediapipe as mp
from mediapipe.tasks import python as mp_tasks
from mediapipe.tasks.python import vision

import config


# Path to the hand landmarker model file
_MODEL_PATH = os.path.join(os.path.dirname(__file__), "hand_landmarker.task")


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
        self._frame_timestamp_ms = 0

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

        # Increment timestamp (Tasks API requires monotonically increasing timestamps)
        self._frame_timestamp_ms += 33  # ~30 FPS

        # Run detection
        result = self._landmarker.detect_for_video(mp_image, self._frame_timestamp_ms)

        if not result.hand_landmarks:
            self._hand_detected = False
            self._last_landmarks = None
            return self._smoothed

        self._hand_detected = True
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
        """
        # Get 3D coordinates from NormalizedLandmark objects
        pts = []
        for idx in indices:
            lm = landmarks[idx]
            pts.append(np.array([lm.x, lm.y, lm.z]))

        if finger_name == "thumb":
            return self._compute_thumb_curl(landmarks, pts)

        # For regular fingers: compute angles at PIP and DIP joints
        base, pip_joint, dip_joint, tip = pts

        angle_pip = self._angle_between(base, pip_joint, dip_joint)
        angle_dip = self._angle_between(pip_joint, dip_joint, tip)

        # Combined curl: weighted sum of joint angles
        avg_angle = 0.65 * angle_pip + 0.35 * angle_dip

        # Map angle to curl percentage
        curl = np.interp(avg_angle, [40, 170], [100, 0])
        return float(np.clip(curl, 0, 100))

    def _compute_thumb_curl(self, landmarks, pts) -> float:
        """
        Compute thumb curl using distance-based method.
        """
        cmc, mcp, ip, tip = pts

        index_mcp = landmarks[self.INDEX_MCP]
        index_mcp_pt = np.array([index_mcp.x, index_mcp.y, index_mcp.z])

        wrist_lm = landmarks[self.WRIST]
        wrist_pt = np.array([wrist_lm.x, wrist_lm.y, wrist_lm.z])

        # Distance from thumb tip to index finger base
        dist = np.linalg.norm(tip - index_mcp_pt)

        # Normalize by hand size (wrist to middle MCP)
        middle_mcp = landmarks[self.MIDDLE_MCP]
        middle_mcp_pt = np.array([middle_mcp.x, middle_mcp.y, middle_mcp.z])
        hand_size = np.linalg.norm(middle_mcp_pt - wrist_pt)

        if hand_size < 1e-6:
            return 0.0

        normalized_dist = dist / hand_size

        # Angle at MCP joint
        angle_mcp = self._angle_between(cmc, mcp, ip)

        # Combine distance and angle methods
        curl_dist = np.interp(normalized_dist, [0.15, 0.7], [100, 0])
        curl_angle = np.interp(angle_mcp, [60, 160], [100, 0])

        curl = 0.5 * curl_dist + 0.5 * curl_angle
        return float(np.clip(curl, 0, 100))

    def _compute_wrist_rotation(self, landmarks) -> float:
        """
        Compute wrist rotation angle from the hand orientation.
        Returns angle in degrees (0–180), mapped to servo range.
        """
        wrist = landmarks[self.WRIST]
        middle_mcp = landmarks[self.MIDDLE_MCP]

        dx = middle_mcp.x - wrist.x
        dy = middle_mcp.y - wrist.y

        angle_rad = math.atan2(dx, -dy)
        angle_deg = math.degrees(angle_rad)

        servo_angle = np.interp(angle_deg, [-90, 90], [0, 180])
        return float(np.clip(servo_angle, 0, 180))

    @staticmethod
    def _angle_between(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
        """
        Calculate the angle at point B formed by points A-B-C.
        Returns angle in degrees.
        """
        ba = a - b
        bc = c - b

        dot = np.dot(ba, bc)
        mag_ba = np.linalg.norm(ba)
        mag_bc = np.linalg.norm(bc)

        if mag_ba < 1e-8 or mag_bc < 1e-8:
            return 180.0

        cos_angle = np.clip(dot / (mag_ba * mag_bc), -1.0, 1.0)
        angle = math.degrees(math.acos(cos_angle))
        return angle

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
