"""
Configuration for InMoov Hand Gesture Control System.
Adjust these values to match your hardware setup.

References:
  Hardware:
    - ESP32 DevKit 30P Datasheet & Pinout:
        https://www.espressif.com/sites/default/files/documentation/esp32_datasheet_en.pdf
    - PCA9685 16-Ch PWM Driver Datasheet (NXP):
        https://www.nxp.com/docs/en/data-sheet/PCA9685.pdf
    - MG996R Servo Datasheet (Tower Pro):
        https://www.electronicoscaldas.com/datasheet/MG996R_Tower-Pro.pdf
    - Adafruit PCA9685 Breakout Guide:
        https://learn.adafruit.com/16-channel-pwm-servo-driver/overview
    - InMoov Open-Source Robot Platform:
        https://inmoov.fr/

  Software / Libraries:
    - MediaPipe Hand Landmarker (Tasks API):
        https://ai.google.dev/edge/mediapipe/solutions/vision/hand_landmarker
    - MediaPipe Hand Landmark Model Card:
        https://storage.googleapis.com/mediapipe-assets/Model%20Card%20Hand%20Tracking%20(Lite_Full).pdf
    - OpenCV-Python Documentation:
        https://docs.opencv.org/4.x/
    - PySerial Documentation:
        https://pyserial.readthedocs.io/en/latest/

  Algorithms:
    - Exponential Moving Average (EMA) Filter:
        https://en.wikipedia.org/wiki/Exponential_smoothing
    - Servo PWM Deadband / Anti-Jitter Techniques:
        https://www.servocity.com/how-do-servos-work/
"""

# =============================================================================
#  COMMUNICATION SETTINGS
# =============================================================================

# Communication mode: "serial" or "wifi"
COMM_MODE = "wifi"

# --- Serial Settings (for wired USB connection) ---
SERIAL_PORT = "COM6"        # Change to your ESP32's COM port (check Device Manager)
SERIAL_BAUD = 115200

# --- WiFi Settings (for wireless TCP connection) ---
ESP32_IP = "192.168.1.61"  # Change to your ESP32's IP (printed on Serial Monitor)
ESP32_PORT = 8080

# =============================================================================
#  CAMERA SETTINGS
# =============================================================================

CAMERA_INDEX = 0             # Webcam index (0 = default, 1 = external, etc.)
CAMERA_WIDTH = 1280          # Capture width
CAMERA_HEIGHT = 720          # Capture height

# =============================================================================
#  HAND TRACKING SETTINGS
# =============================================================================

MEDIAPIPE_MAX_HANDS = 1           # Track only 1 hand
MEDIAPIPE_DETECTION_CONFIDENCE = 0.7
MEDIAPIPE_TRACKING_CONFIDENCE = 0.6

# Which hand controls the robot (True = track left hand, False = track right)
# Note: MediaPipe labels are mirrored, so "Left" in camera = your right hand
MIRROR_MODE = False

# =============================================================================
#  SMOOTHING & PERFORMANCE
# =============================================================================

# Exponential Moving Average alpha (0.0 = very smooth/slow, 1.0 = no smoothing)
EMA_ALPHA = 0.35

# Target send rate to ESP32 (Hz). Higher = more responsive but more CPU/bandwidth
SEND_RATE_HZ = 30

# Minimum angle change (degrees) to trigger a send — reduces unnecessary traffic
DEADBAND_DEGREES = 2

# --- Anti-Shaking (Servo Stabilisation) ---
# Per-servo output deadband: a new servo angle is only accepted if it differs
# from the last sent angle by more than this many degrees. Prevents 1-2° jitter
# from reaching the servos. Set to 0 to disable.
SERVO_DEADBAND_DEGREES = 3

# Velocity-adaptive smoothing: when finger movement is below this curl-%
# threshold between frames, the EMA alpha is reduced (= heavier smoothing)
# to kill micro-jitter. Above this threshold, full EMA_ALPHA is used so
# intentional movements stay responsive.
ADAPTIVE_SMOOTH_THRESHOLD = 4.0   # curl-% change per frame
ADAPTIVE_SMOOTH_ALPHA_SLOW = 0.12 # heavy smoothing for near-stationary fingers

# Snap-to-rest: when a finger's smoothed curl is below this threshold,
# snap it to exactly 0% to avoid tiny oscillations around the open position.
SNAP_TO_REST_THRESHOLD = 2.5  # curl-%

# =============================================================================
#  GRIP PROTECTION SETTINGS
#  Prevents the hand from crushing objects by limiting grip force.
#  Grip strength caps how far fingers can close (% of full range).
#  Compliance zone progressively slows fingers as they approach the limit.
# =============================================================================

# Grip mode presets — select the active mode with 'G' key during runtime
# Each mode defines: (grip_strength %, compliance_zone_degrees, description)
GRIP_MODES = {
    "DELICATE": {"strength": 35,  "compliance_zone": 40, "label": "Delicate (egg, glass)"},
    "LIGHT":    {"strength": 55,  "compliance_zone": 30, "label": "Light (plastic cup)"},
    "NORMAL":   {"strength": 75,  "compliance_zone": 20, "label": "Normal (general use)"},
    "FIRM":     {"strength": 100, "compliance_zone": 10, "label": "Firm (no limit)"},
}

# Default grip mode on startup
DEFAULT_GRIP_MODE = "FIRM"

# Stall detection: if ESP32 reports current above this threshold (mA),
# the finger backs off automatically. Set 0 to disable.
# (Requires current sense hardware — see README)
CURRENT_STALL_THRESHOLD_MA = 0

# How many degrees to back off when stall is detected
STALL_BACKOFF_DEGREES = 15

# =============================================================================
#  SERVO CALIBRATION
#  These map the detected finger curl (0% = open, 100% = closed)
#  to servo angle (degrees). Adjust per-finger after running calibration_tool.py
# =============================================================================

SERVO_CHANNELS = {
    "thumb":  0,
    "index":  1,
    "middle": 2,
    "ring":   3,
    "pinky":  4,
    "wrist":  5,
}

# Servo angle when finger is fully OPEN (extended)
SERVO_MIN = {
    "thumb":  0,
    "index":  0,
    "middle": 0,
    "ring":   0,
    "pinky":  0,
    "wrist":  90}


# Servo angle when finger is fully CLOSED (curled)
SERVO_MAX = {
    "thumb":  180,
    "index":  180,
    "middle": 170,
    "ring":   180,
    "pinky":  170,
    "wrist":  180
}

# Set True if a servo rotates in the opposite direction from expected
SERVO_INVERTED = {
    "thumb":  False,
    "index":  False,
    "middle": False,
    "ring":   False,
    "pinky":  False,
    "wrist":  False,
}

# Per-finger grip strength override (0-100, or None to use global mode).
# Use this to make specific fingers softer, e.g. thumb often needs less force.
FINGER_GRIP_OVERRIDE = {
    "thumb":  100,    # 100 = Max strength override
    "index":  None,
    "middle": None,
    "ring":   None,
    "pinky":  None,
}

# =============================================================================
#  DISPLAY SETTINGS
# =============================================================================

SHOW_LANDMARKS = True         # Draw hand landmarks on camera feed
SHOW_ANGLE_BARS = True        # Show per-finger angle bar gauges
SHOW_FPS = True               # Show FPS counter
WINDOW_NAME = "InMoov Hand Gesture Control"
