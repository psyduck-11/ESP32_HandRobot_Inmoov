# InMoov Hand Robot — Comprehensive User Manual

> **Version:** 2.0 · **Last Updated:** May 2026
>
> Real-time robot hand control using laptop webcam hand tracking with ESP32 + PCA9685 + MG996R servos.

```
  🎥 Webcam → 🐍 Python (MediaPipe) → 📡 ESP32 (Serial/WiFi) → 🔌 PCA9685 → 🦾 6× MG996R
```

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Hardware Requirements](#2-hardware-requirements)
3. [Wiring Guide](#3-wiring-guide)
4. [Software Installation](#4-software-installation)
5. [Configuration Reference](#5-configuration-reference)
6. [Running the System](#6-running-the-system)
7. [Calibration Guide](#7-calibration-guide)
8. [Algorithm Deep Dive](#8-algorithm-deep-dive)
   - [8.1 MediaPipe Hand Landmarks](#81-mediapipe-hand-landmarks)
   - [8.2 Finger Curl Detection (4 Fingers)](#82-finger-curl-detection-4-fingers)
   - [8.3 Thumb Curl Detection (Hybrid)](#83-thumb-curl-detection-hybrid)
   - [8.4 Wrist Rotation Detection](#84-wrist-rotation-detection)
   - [8.5 EMA Smoothing](#85-ema-smoothing)
   - [8.6 Grip Protection & Compliance Zone](#86-grip-protection--compliance-zone)
   - [8.7 Servo Angle Mapping](#87-servo-angle-mapping)
   - [8.8 Communication Filters](#88-communication-filters-rate-limit--deadband)
   - [8.9 ESP32 Smooth Servo Interpolation](#89-esp32-smooth-servo-interpolation)
   - [8.10 PCA9685 PWM Conversion](#810-pca9685-pwm-conversion)
9. [Full Data Pipeline](#9-full-data-pipeline)
10. [Hold/Lock System](#10-holdlock-system)
11. [Communication Protocol](#11-communication-protocol)
12. [WiFi Mode Setup](#12-wifi-mode-setup)
13. [Troubleshooting](#13-troubleshooting)
14. [Project Structure](#14-project-structure)

---

## 1. System Overview

This project turns your hand into a real-time controller for an InMoov robot hand. A webcam captures your hand, Google MediaPipe detects 21 hand landmarks in 3D, custom algorithms compute how curled each finger is, and those values are sent as servo angles to an ESP32 microcontroller driving 6 servos via a PCA9685 PWM board.

### Key Features

- **6 servos:** 5 fingers (thumb, index, middle, ring, pinky) + 1 wrist rotation
- **Dual communication:** USB Serial (wired) or WiFi TCP (wireless)
- **Grip protection:** 4 preset modes (Delicate → Firm) with cosine-eased compliance zones
- **Hold/Lock mode:** Freeze the robot's posture and remove your hand
- **Interactive calibration tool:** Slider-based per-servo calibration
- **Smooth motion:** EMA smoothing on the Python side + speed-limited interpolation on the ESP32

---

## 2. Hardware Requirements

| Item | Qty | Notes |
|------|-----|-------|
| ESP32 DevKit 30P (CH340, Type-C) | 1 | WiFi + Bluetooth MCU |
| PCA9685 16-Channel PWM Driver | 1 | I2C servo controller |
| MG996R Servo Motor | 6 | 5 fingers + 1 wrist |
| 5V 20A DC Power Supply Adapter | 1 | **DO NOT power servos from ESP32** |
| USB Type-C Cable | 1 | ESP32 ↔ Laptop |
| Jumper Wires (M-F) | ~10 | For I2C + power connections |
| InMoov Hand (3D printed) | 1 | With fishing line tendons |
| Laptop with Webcam | 1 | Running Python client |

### ⚠️ Critical Power Notes

1. **NEVER** power servos from the ESP32 USB or 3.3V pins — each MG996R can draw 2.5A at stall
2. Use the **5V 20A adapter** connected directly to PCA9685 V+ (MG996R servos are rated for 4.8–7.2V)
3. Connect PSU ground to PCA9685 GND **AND** ESP32 GND (common ground is essential)
4. Add a **1000µF electrolytic capacitor** across V+ and GND on PCA9685 to prevent brownouts

---

## 3. Wiring Guide

### ESP32 ↔ PCA9685

```
   ESP32 DevKit 30P                  PCA9685 Board
  ┌─────────────────┐              ┌─────────────────────┐
  │                 │              │                     │
  │  GPIO 21 (SDA) ├──────────────┤ SDA                 │
  │  GPIO 22 (SCL) ├──────────────┤ SCL                 │
  │  3.3V          ├──────────────┤ VCC (Logic Power)   │
  │  GND           ├──────┬───────┤ GND                 │
  │                 │      │       │                     │
  └─────────────────┘      │       │  CH0 ─── Thumb  Servo
                           │       │  CH1 ─── Index  Servo
     5V 20A Adapter        │       │  CH2 ─── Middle Servo
  ┌─────────────────┐      │       │  CH3 ─── Ring   Servo
  │  +5V           ├──────┼───────┤ V+  (Servo Power)  │
  │  GND           ├──────┘       │  CH4 ─── Pinky  Servo
  └─────────────────┘              │  CH5 ─── Wrist  Servo
                                   └─────────────────────┘
```

### Servo Connections (each MG996R)

```
  MG996R Wire Colors:
    Brown  = GND     → PCA9685 GND rail (outer pin)
    Red    = VCC     → PCA9685 V+ rail  (middle pin)
    Orange = Signal  → PCA9685 PWM pin  (inner pin)
```

### Channel Assignment Summary

| Channel | Servo | Function |
|---------|-------|----------|
| CH0 | Thumb | Thumb curl open/close |
| CH1 | Index | Index finger curl |
| CH2 | Middle | Middle finger curl |
| CH3 | Ring | Ring finger curl |
| CH4 | Pinky | Pinky finger curl |
| CH5 | Wrist | Wrist rotation (pronation/supination) |

---

## 4. Software Installation

### Step 1: Python Dependencies

```bash
cd python_client
pip install -r requirements.txt
```

**Packages:**
| Package | Purpose |
|---------|---------|
| `opencv-python` ≥4.8 | Webcam capture, display, and UI drawing |
| `mediapipe` ≥0.10 | Hand landmark detection (21 points in 3D) |
| `numpy` ≥1.24 | Math operations, interpolation |
| `pyserial` ≥3.5 | USB serial communication with ESP32 |

> ⚠️ Install `pyserial`, NOT `serial` — they are different packages!

### Step 2: Download MediaPipe Model

The hand tracking requires a model file `hand_landmarker.task` in the `python_client/` folder. Download it:

```powershell
cd python_client
Invoke-WebRequest -Uri "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task" -OutFile "hand_landmarker.task"
```

### Step 3: Flash ESP32 Firmware

1. Open **Arduino IDE** (or PlatformIO)
2. Install required libraries via **Library Manager**:
   - **Adafruit PWM Servo Driver Library** (search "Adafruit PWM Servo")
   - **Wire** (built-in)
   - **WiFi** (built-in for ESP32)
3. Select board: **Tools → Board → ESP32 Dev Module**
4. Select port: **Tools → Port → COMx** (your ESP32 COM port)
5. Open `esp32_firmware/esp32_hand_controller/esp32_hand_controller.ino`
6. Edit `config.h` if needed (WiFi credentials, pin assignments)
7. Click **Upload** (→ button)
8. Open **Serial Monitor** (115200 baud) to verify startup messages

---

## 5. Configuration Reference

All Python-side settings are in `python_client/config.py`. ESP32 settings are in `esp32_firmware/esp32_hand_controller/config.h`.

### Python — `config.py`

#### Communication

| Setting | Default | Description |
|---------|---------|-------------|
| `COMM_MODE` | `"serial"` | `"serial"` for USB, `"wifi"` for TCP |
| `SERIAL_PORT` | `"COM6"` | COM port of your ESP32 (check Device Manager) |
| `SERIAL_BAUD` | `115200` | Must match firmware `SERIAL_BAUD` |
| `ESP32_IP` | `"192.168.1.100"` | ESP32's IP (shown in Serial Monitor when WiFi enabled) |
| `ESP32_PORT` | `8080` | TCP port (must match `TCP_PORT` in `config.h`) |

#### Camera

| Setting | Default | Description |
|---------|---------|-------------|
| `CAMERA_INDEX` | `0` | Webcam index (0=default, 1=external) |
| `CAMERA_WIDTH` | `1280` | Capture resolution width |
| `CAMERA_HEIGHT` | `720` | Capture resolution height |

#### Hand Tracking

| Setting | Default | Description |
|---------|---------|-------------|
| `MEDIAPIPE_MODEL_COMPLEXITY` | `1` | 0=lite (fast), 1=full (accurate) |
| `MEDIAPIPE_MAX_HANDS` | `1` | Number of hands to track |
| `MEDIAPIPE_DETECTION_CONFIDENCE` | `0.7` | Min confidence to detect a hand |
| `MEDIAPIPE_TRACKING_CONFIDENCE` | `0.6` | Min confidence to keep tracking |
| `MIRROR_MODE` | `False` | Flip camera horizontally |

#### Smoothing & Performance

| Setting | Default | Description |
|---------|---------|-------------|
| `EMA_ALPHA` | `0.35` | Smoothing factor (1.0=none, 0.1=heavy) |
| `SEND_RATE_HZ` | `30` | Max commands per second to ESP32 |
| `DEADBAND_DEGREES` | `2` | Min angle change to trigger a send |

#### Grip Protection

| Mode | Strength | Compliance Zone | Use Case |
|------|----------|----------------|----------|
| DELICATE | 35% | 40° | Eggs, glass objects |
| LIGHT | 55% | 30° | Plastic cups |
| NORMAL | 75% | 20° | General use |
| FIRM | 100% | 10° | Maximum grip (no limit) |

#### Servo Calibration

| Setting | Description |
|---------|-------------|
| `SERVO_CHANNELS` | PCA9685 channel per finger (`thumb:0` through `wrist:5`) |
| `SERVO_MIN` | Angle when finger is fully OPEN |
| `SERVO_MAX` | Angle when finger is fully CLOSED |
| `SERVO_INVERTED` | `True` if servo rotates backwards |
| `FINGER_GRIP_OVERRIDE` | Per-finger grip strength override (or `None`) |

#### Display

| Setting | Default | Description |
|---------|---------|-------------|
| `SHOW_LANDMARKS` | `True` | Draw hand landmarks on camera feed |
| `SHOW_ANGLE_BARS` | `True` | Show per-finger angle bar gauges |
| `SHOW_FPS` | `True` | Show FPS counter |
| `WINDOW_NAME` | `"InMoov Hand Gesture Control"` | OpenCV window title |

#### Stall Detection

| Setting | Default | Description |
|---------|---------|-------------|
| `CURRENT_STALL_THRESHOLD_MA` | `0` | ADC threshold for stall detection (0 = disabled) |
| `STALL_BACKOFF_DEGREES` | `15` | Degrees to back off on stall |
| `DEFAULT_GRIP_MODE` | `"NORMAL"` | Grip mode on startup |

### ESP32 — `config.h`

| Setting | Default | Description |
|---------|---------|-------------|
| `PCA9685_ADDR` | `0x40` | I2C address of PCA9685 |
| `I2C_SDA` / `I2C_SCL` | `21` / `22` | ESP32 I2C pins |
| `PWM_FREQ` | `50` | Servo PWM frequency (Hz) |
| `SERVO_MIN_TICK` | `102` | PCA9685 tick for 0° (~500µs) |
| `SERVO_MAX_TICK` | `512` | PCA9685 tick for 180° (~2500µs) |
| `SERVO_SPEED_LIMIT` | `8` | Max degrees per update step |
| `UPDATE_INTERVAL_MS` | `20` | Servo update loop interval |
| `COMPLIANCE_ZONE_DEG` | `20` | Firmware-side compliance zone |
| `COMPLIANCE_MIN_SPEED` | `1` | Min speed (°/update) in compliance zone |
| `ENABLE_CURRENT_SENSE` | `false` | Enable hardware stall detection |
| `CURRENT_SENSE_PIN` | `34` | ESP32 ADC pin for current sensing |
| `CURRENT_STALL_ADC` | `2000` | ADC threshold for stall (12-bit) |
| `STALL_BACKOFF_DEG` | `15` | Degrees to back off on stall |
| `STALL_DEBOUNCE_COUNT` | `5` | Consecutive readings before stall trigger |
| `SERIAL_BAUD` | `115200` | Serial baud rate |
| `LED_PIN` | `2` | Built-in status LED pin |

---

## 6. Running the System

### Quick Start

```bash
cd python_client
python main.py
```

### Keyboard Controls

| Key | Action |
|-----|--------|
| `Q` | Quit |
| `P` | Pause/Resume sending to ESP32 |
| `R` | Reconnect to ESP32 |
| `M` | Toggle mirror mode (flip camera) |
| `H` | Toggle hold mode (freeze posture) |
| `Space` | Toggle wrist control on/off |
| `G` | Cycle grip mode (DELICATE → LIGHT → NORMAL → FIRM) |
| `+` / `-` | Fine-adjust grip strength ±5% |

### Mouse Controls

All top-bar badges and cards are clickable:

| UI Element | Click Action |
|------------|--------------|
| **QUIT** badge | Exit the application |
| **ACTIVE/PAUSED** badge | Toggle pause state |
| **CONNECTED/DISCONNECTED** badge | Reconnect to ESP32 |
| **HOLD** badge | Toggle hold/lock mode |
| **GRIP** card | Cycle to next grip mode |
| **WRIST** button (in telemetry) | Toggle wrist control on/off |
| **PAUSED** center alert | Resume sending |

### What You Should See

- **Camera feed** with hand landmarks drawn (green joints, blue fingertips, red wrist)
- **Top badges (row 1):** QUIT, ACTIVE/PAUSED, INMOOV title, CONNECTED/DISCONNECTED status, FPS counter
- **Hold badge (row 2):** Shows "POSTURE LOCKED" (yellow) or "LIVE CONTROLLER" (muted)
- **Grip card (top-right):** Shows grip mode label, strength bar, and percentage
- **Telemetry card (bottom-left):** 5–6 vertical bars (T, I, M, R, P, W) showing curl %, with WRIST toggle button
- **Hand pose thumbnail (bottom-right):** Miniature skeleton of the detected hand pose (or locked pose)
- **Center alerts:** "NO HAND DETECTED" (orange) or "SYSTEM TRANSMISSION: PAUSED" (red) when applicable
- **Bottom taskbar:** Key shortcut reference strip

### Preview Mode

If the ESP32 is not connected, the system runs in **preview mode** — hand tracking and the UI work normally, but no servo commands are sent. Useful for testing the tracking without hardware.

---

## 7. Calibration Guide

Each servo + finger mechanism has different mechanical limits. Calibration maps the correct angle range.

### Running the Calibration Tool

```bash
cd python_client
python calibration_tool.py
```

### Interface

- **6 trackbar sliders** — one per servo
- **Visual angle bars** with green (MIN) and blue (MAX) limit markers
- **Selected servo** highlighted with a blue box

### Step-by-Step Calibration

For each servo (1 through 6):

1. **Select** — Press `1`–`6` to select (1=Thumb, 2=Index, ... 6=Wrist)
2. **Find OPEN position** — Drag slider until the finger is fully extended. Don't push past where the servo strains. Press `O` to save as MIN.
3. **Find CLOSED position** — Drag slider the other way until fully curled. Press `C` to save as MAX.
4. **Check direction** — If the finger moves opposite to expected (closes when it should open), press `I` to invert.
5. **Test** — Press `T` to sweep from MIN → MAX → MIN.
6. **Test all** — Press `A` to run a wave pattern across all fingers.
7. **Save** — Press `S` to save to `calibration_data.json` and print values for `config.py`.

### Applying Calibration

Copy the printed values into `config.py`:

```python
SERVO_MIN = {"thumb": 15, "index": 10, "middle": 12, "ring": 10, "pinky": 8, "wrist": 20}
SERVO_MAX = {"thumb": 165, "index": 170, "middle": 168, "ring": 170, "pinky": 172, "wrist": 160}
SERVO_INVERTED = {"thumb": False, "index": False, "middle": True, ...}
```

### Reset Servos Utility

To quickly reset all 6 servos to 90° (neutral):

```bash
python reset_servos.py
```

---

## 8. Algorithm Deep Dive

This section explains every algorithm in the processing pipeline, with the underlying math.

### 8.1 MediaPipe Hand Landmarks

MediaPipe detects **21 landmarks** on the hand, each with normalized (x, y, z) coordinates:

```
                    ┌─ 4  (Thumb Tip)
                  3 ┘
                2 ┘
              1 ┘
    8 ─ 7 ─ 6 ─ 5 ┐
   12 ─11 ─10 ─ 9 ┤
   16 ─15 ─14 ─13 ┤  ← 0 (Wrist)
   20 ─19 ─18 ─17 ┘
```

| Index | Name | Index | Name |
|-------|------|-------|------|
| 0 | Wrist | 11 | Middle DIP |
| 1 | Thumb CMC | 12 | Middle Tip |
| 2 | Thumb MCP | 13 | Ring MCP |
| 3 | Thumb IP | 14 | Ring PIP |
| 4 | Thumb Tip | 15 | Ring DIP |
| 5 | Index MCP | 16 | Ring Tip |
| 6 | Index PIP | 17 | Pinky MCP |
| 7 | Index DIP | 18 | Pinky PIP |
| 8 | Index Tip | 19 | Pinky DIP |
| 9 | Middle MCP | 20 | Pinky Tip |
| 10 | Middle PIP | | |

Coordinates are normalized: x,y ∈ [0,1] relative to image dimensions, z is depth relative to the wrist.

---

### 8.2 Finger Curl Detection (4 Fingers)

**File:** `hand_tracker.py` — `_compute_finger_curl()`

**Goal:** Measure how bent a finger is → output **0%** (straight/open) to **100%** (fully curled/fist).

#### Joint Angle Calculation

For each finger (index, middle, ring, pinky), we compute the angle at two joints:

```
     MCP ←── angle_pip ──→ DIP ←── angle_dip ──→ TIP
      ↑                     ↑                      ↑
  base joint          middle joint             fingertip
```

Given 3 points **A → B → C**, the angle at **B** using the dot product:

```
  BA⃗ = A - B
  BC⃗ = C - B

  cos(θ) = (BA⃗ · BC⃗) / (|BA⃗| × |BC⃗|)

  θ = arccos( clamp(cos(θ), -1, 1) )
```

Where the dot product **BA⃗ · BC⃗** = BAx·BCx + BAy·BCy + BAz·BCz

And the magnitude |BA⃗| = √(BAx² + BAy² + BAz²)

#### Weighted Joint Combination

The two joint angles are combined with different weights because the PIP (knuckle) joint has a much larger range of motion than the DIP (fingertip) joint:

```
avg_angle = 0.65 × angle_PIP + 0.35 × angle_DIP
```

#### Mapping to Curl Percentage

```
Angle:  170° (straight)  ──────────────  40° (fully bent)
Curl:     0% (open)      ──────────────  100% (closed)
```

```python
if avg_angle >= 170:  curl = 0%
elif avg_angle <= 40: curl = 100%
else:                 curl = (170 - avg_angle) / (170 - 40) × 100
```

The result is clamped to [0, 100].

---

### 8.3 Thumb Curl Detection (Hybrid)

**File:** `hand_tracker.py` — `_compute_thumb_curl()`

The thumb moves differently from other fingers — it performs **opposition** (moving across the palm) rather than simple flexion. A single joint angle doesn't capture this well, so we use **two methods averaged 50/50**:

#### Method A — Distance-Based

Measures how far the thumb tip is from the index finger base, normalized by hand size:

```
                          |thumb_tip − index_MCP|
normalized_dist = ────────────────────────────────────
                          |middle_MCP − wrist|
                            ↑ hand size (for scale-invariance)
```

Mapping:
```
normalized_dist:  0.15 (thumb touching index) ──── 0.7 (thumb fully extended)
curl_dist:        100% (closed)                ──── 0% (open)
```

Dividing by hand size makes the measurement work at any camera distance.

#### Method B — Angle-Based

Computes the angle at the thumb MCP joint (points: CMC → MCP → IP):

```
angle_MCP:    60° (bent)  ──────────  160° (straight)
curl_angle:   100%        ──────────  0%
```

#### Combined Result

```python
curl = 0.5 × curl_dist + 0.5 × curl_angle
```

This hybrid approach catches both the "thumb crossing the palm" motion (distance) and the "thumb bending" motion (angle).

---

### 8.4 Wrist Rotation Detection

**File:** `hand_tracker.py` — `_compute_wrist_rotation()`

**Goal:** Detect forearm rotation (pronation/supination) — like turning a doorknob — and map it to the wrist servo (0°–180°).

#### The Challenge

Simply measuring the wrist angle in 2D would conflate arm tilt with forearm roll. We need to **isolate the roll component** in 3D.

#### Method: 3D Palm Roll Extraction

**Step 1 — Establish the hand's longitudinal axis:**

```
â = normalize(middle_MCP − wrist)   →   points "up" along the hand
```

**Step 2 — Get the cross-palm vector:**

```
c⃗ = pinky_MCP − index_MCP   →   points across the palm
```

**Step 3 — Project cross-palm onto the perpendicular plane:**

Remove the component along the hand axis so we only see the roll:

```
c⃗_perp = c⃗ − (c⃗ · â) × â
```

**Step 4 — Build reference axes in the perpendicular plane:**

Using Gram-Schmidt orthogonalization against the hand axis:

```
r̂ = normalize( (1,0,0) − ((1,0,0)·â) × â )   →   "camera-right" reference
û = â × r̂                                        →   "camera-up" reference
```

If the hand axis is nearly parallel to camera-right, fall back to camera-up (0,−1,0) as the initial reference.

**Step 5 — Compute roll angle:**

```
roll = atan2(c⃗_perp · û, c⃗_perp · r̂)
```

**Step 6 — Map to servo using cosine:**

```python
servo_angle = (cos(roll_rad) + 1.0) × 90.0    # Range: 0 … 180
```

This gives:

| Hand orientation | roll (rad) | cos(roll) | Servo angle |
|-----------------|------------|-----------|-------------|
| Palm facing camera (front) | 0 | 1.0 | **180°** |
| Hand sideways | ±π/2 | 0.0 | **90°** |
| Back of hand facing camera | ±π | −1.0 | **0°** |

The cosine mapping provides a smooth, continuous transition with no discontinuity at the ±180° wrap-around point.

---

### 8.5 EMA Smoothing

**File:** `hand_tracker.py` — `process_frame()` line 178

Raw MediaPipe values jitter frame-to-frame. **Exponential Moving Average** (EMA) smooths them:

```
smoothed[t] = α × raw[t] + (1 − α) × smoothed[t-1]
```

Where **α = 0.35** (configurable via `EMA_ALPHA`).

#### How it behaves

| α value | Effect |
|---------|--------|
| 1.0 | No smoothing — instant but jittery |
| 0.35 | **Default** — balanced responsiveness and smoothness |
| 0.1 | Heavy smoothing — laggy but very smooth |

**Example:** If the raw value jumps from 20 to 80 instantly:

```
Frame:    0     1     2     3     4     5     6     7
Raw:     20    80    80    80    80    80    80    80
Smooth:  20    41    54    63    70    74    77    79
              ↑ α=0.35: jumps to 41, then gradually converges
```

The smoothing is applied independently to all 6 channels (5 fingers + wrist).

#### Lost hand reset

After losing the hand for **15 consecutive frames**, the smoothed values are reset to defaults (fingers=0%, wrist=90°) so re-detection doesn't start from stale data.

---

### 8.6 Grip Protection & Compliance Zone

**File:** `main.py` — `curl_to_servo_angle()` and `GripController`

**Goal:** Prevent crushing objects by capping how far fingers can close, with a smooth deceleration zone.

#### The Three Zones

```
Curl %:  0%  ─────────────  55%  ─────────  75%  ─── 100%
         │   FREE ZONE      │  COMPLIANCE   │  BLOCKED
         │   (1:1 mapping)  │  (eased)      │  (capped)
                             ↑               ↑
                 (max_curl - compliance)   max_curl (= grip strength)
```

Example: NORMAL mode → strength=75%, compliance_zone=20%

#### Cosine Easing Math

Inside the compliance zone (curl between 55% and 75% in the example):

```python
zone_progress = (curl - 55) / 20              # 0.0 at entry → 1.0 at limit
easing = 0.5 × (1 − cos(π × zone_progress))   # Cosine ease-in-out curve
effective_curl = 55 + 20 × easing
```

| Input curl | Zone progress | Easing | Effective curl |
|-----------|---------------|--------|---------------|
| 55% | 0.0 | 0.000 | 55.0% |
| 60% | 0.25 | 0.146 | 57.9% |
| 65% | 0.50 | 0.500 | 65.0% |
| 70% | 0.75 | 0.854 | 72.1% |
| 75% | 1.0 | 1.000 | 75.0% (capped) |
| 90% | — | — | 75.0% (capped) |

The cosine curve creates a **soft brake**: starts gently (barely restricts motion), then progressively increases braking as you approach the limit.

#### Per-Finger Override

Individual fingers can have different grip strengths via `FINGER_GRIP_OVERRIDE` in config — e.g., making the thumb softer for delicate pinch grips.

---

### 8.7 Servo Angle Mapping

**File:** `main.py` — `curl_to_servo_angle()` line 118

After grip protection, the effective curl percentage is mapped to a servo angle:

```python
# Normal direction:
angle = interp(effective_curl, [0%, 100%], [SERVO_MIN, SERVO_MAX])

# Inverted direction:
angle = interp(effective_curl, [0%, 100%], [SERVO_MAX, SERVO_MIN])
```

The wrist servo has its own mapper (`wrist_to_servo_angle()`) that maps the 0°–180° rotation value directly to the servo's calibrated range.

---

### 8.8 Communication Filters (Rate Limit & Deadband)

**File:** `esp32_client.py` — `send_all_servos()`

Two filters reduce unnecessary traffic to the ESP32:

#### Rate Limiter

```python
if (now − last_send_time) < 1/30:   # 33ms minimum interval
    return  # Skip — too soon
```

At 60 FPS camera but 30 Hz send rate → only every other frame sends a command.

#### Deadband Filter

```python
max_change = max(|new_angle[f] − old_angle[f]| for each finger)
if max_change < 2°:
    return  # Skip — nothing moved enough to matter
```

Prevents sending identical or nearly-identical commands. Both filters can be bypassed with `force=True` (used by `reset_servos.py` and initial setup).

---

### 8.9 ESP32 Smooth Servo Interpolation

**File:** `config.h` — `SERVO_SPEED_LIMIT`, `UPDATE_INTERVAL_MS`

The firmware runs a servo update loop every **20ms**. Instead of jumping instantly to the target angle, the servo moves **at most 8° per step**:

```
diff = target − current
if |diff| > 8:
    diff = sign(diff) × 8    # Cap at 8°/step
current += diff
```

**Example:** Target jumps from 10° to 170° (160° gap):

```
Step:     0    1    2    3   ...  19    20
Current: 10°  18°  26°  34° ... 162°  170° ✓
                                      ↑ arrives in 20 steps = 400ms
```

#### Firmware Compliance Zone

When the servo is **closing** and within 20° of its target, the speed is linearly reduced:

```
factor = distance_to_target / 20
speed = max(1, 1 + factor × (8 − 1))
```

| Distance to target | Speed (°/step) |
|--------------------:|---------------:|
| 20° | 8 (full speed) |
| 15° | 6 |
| 10° | 4 |
| 5° | 2 |
| 1° | 1 (crawling) |

This creates gentle contact when gripping objects — the finger slows down as it approaches the target.

---

### 8.10 PCA9685 PWM Conversion

**File:** `esp32_hand_controller.ino` — `angleToPWM()`

The PCA9685 generates PWM signals using a 12-bit counter (0–4095 ticks) at 50 Hz:

```
PCA9685 at 50 Hz:
  Period = 20ms = 20,000µs = 4096 ticks
  1 tick ≈ 4.88µs

MG996R servo range:
  0°   → 500µs  → 102 ticks
  90°  → 1500µs → 307 ticks
  180° → 2500µs → 512 ticks
```

The conversion formula:

```
pulse_µs = 500 + (2500 − 500) × (angle / 180)
ticks = pulse_µs / 20000 × 4096
```

```c
pwm.setPWM(channel, 0, ticks);  // 0 = pulse starts at tick 0
```

---

## 9. Full Data Pipeline

Here's the complete flow for every camera frame:

```
┌─────────────────────────────────────────────────────┐
│  PYTHON CLIENT                                      │
│                                                     │
│  Camera frame (BGR, 1280×720)                       │
│      │                                              │
│      ├─ Flip if mirror mode                         │
│      ├─ Convert BGR → RGB                           │
│      ▼                                              │
│  MediaPipe Hand Landmarker                          │
│      │                                              │
│      ├─ Detects 21 landmarks (x, y, z normalized)   │
│      ▼                                              │
│  Curl Computation (per finger)                      │
│      ├─ Index/Middle/Ring/Pinky: joint angles        │
│      │    → weighted avg → map to 0–100%            │
│      ├─ Thumb: distance + angle hybrid → 0–100%     │
│      ├─ Wrist: 3D palm roll → cos mapping → 0–180°  │
│      ▼                                              │
│  EMA Smoothing (α = 0.35)                           │
│      │  smoothed = 0.35 × raw + 0.65 × previous    │
│      ▼                                              │
│  Hold Check ── if LOCKED → use frozen snapshot ──┐  │
│      │                                           │  │
│      ▼                                           │  │
│  Grip Protection                                 │  │
│      ├─ Cap curl at grip strength %              │  │
│      ├─ Cosine easing in compliance zone         │  │
│      ▼                                           │  │
│  Servo Angle Mapping                             │  │
│      ├─ interp(curl, [0,100], [MIN, MAX])        │  │
│      ├─ Handle inversion                         │  │
│      ▼                                           │  │
│  Rate Limit (30 Hz) + Deadband (2°) ◄────────────┘  │
│      │                                              │
│      ▼                                              │
│  Serial/WiFi → "F90,10,45,30,10,90\n"              │
└─────────────────┬───────────────────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────────────────┐
│  ESP32 FIRMWARE                                     │
│                                                     │
│  Command Parser                                     │
│      ├─ Sets targetAngle[] for each servo           │
│      ▼                                              │
│  Servo Update Loop (every 20ms)                     │
│      ├─ Move max 8°/step toward target              │
│      ├─ Compliance: slow down when closing + near   │
│      │   target                                     │
│      ▼                                              │
│  PCA9685 → PWM pulse → MG996R servo moves           │
└─────────────────────────────────────────────────────┘
```

---

## 10. Hold/Lock System

**File:** `main.py` — toggle with `H` key

The hold system lets you freeze the robot's posture, remove your hand, and have the robot maintain the position.

### How It Works

```
Every frame:
    ├── hold_mode is ON?
    │     ├── YES → Use frozen snapshot (skip all live tracking)
    │     └── NO  → Hand detected?
    │                 ├── YES → Compute servos from live tracking
    │                 └── NO  → Reset all fingers to OPEN
    ▼
    Send to ESP32
```

### Lock/Unlock Flow

```
User presses H:
    ├── Currently LIVE?
    │     ├── Hand detected? → YES → LOCK: snapshot curls & angles
    │     │                   → NO  → "Cannot lock — no hand detected"
    │
    └── Currently LOCKED?
          └── UNLOCK: clear snapshot, return to live tracking
```

**Key insight:** The hold check runs **before** the hand-detection check. When locked, the live-tracking and reset paths are completely bypassed.

---

## 11. Communication Protocol

Text-based protocol over Serial or WiFi TCP. All commands end with `\n`.

### Commands (Python → ESP32)

| Command | Format | Example | Description |
|---------|--------|---------|-------------|
| **Set all servos** | `F<t>,<i>,<m>,<r>,<p>,<w>\n` | `F90,45,30,60,10,120\n` | Set all 6 servos at once |
| **Set single servo** | `C<channel>,<angle>\n` | `C2,90\n` | Set one servo (calibration) |
| **Ping** | `P\n` | `P\n` | Check connection |
| **Query status** | `S\n` | `S\n` | Request status info |
| **Set inversions** | `I<t>,<i>,<m>,<r>,<p>,<w>\n` | `I0,0,1,0,0,0\n` | 0/1 per servo |
| **Set minimums** | `M<t>,<i>,<m>,<r>,<p>,<w>\n` | `M10,10,12,10,8,20\n` | Min angles |
| **Set maximums** | `X<t>,<i>,<m>,<r>,<p>,<w>\n` | `X165,170,168,170,172,160\n` | Max angles |
| **Set grip strength** | `G<strength>\n` | `G75\n` | 0–100% |

### Response (ESP32 → Python)

| Response | Meaning |
|----------|---------|
| `OK\n` | Command accepted (F, C commands) |
| `PONG\n` | Reply to ping |
| `OK:G<n>\n` | Grip strength set to n% |
| `A<t>,<i>,<m>,<r>,<p>,<w>,G<grip>\n` | Status reply (current angles + grip) |
| `E:INVALID_ARGS\n` | Wrong number of arguments |
| `E:INVALID_CHANNEL\n` | Invalid PCA9685 channel |
| `E:UNKNOWN_CMD\n` | Unrecognized command letter |

---

## 12. WiFi Mode Setup

After everything works over USB Serial:

1. **Edit firmware config** (`config.h`):
   ```c
   #define WIFI_SSID     "YourWiFiName"
   #define WIFI_PASSWORD "YourWiFiPassword"
   #define ENABLE_WIFI   true
   ```

2. **Re-upload firmware** to ESP32

3. **Note the IP address** from Serial Monitor:
   ```
   [WIFI] Connected! IP: 192.168.1.105
   ```

4. **Edit Python config** (`config.py`):
   ```python
   COMM_MODE = "wifi"
   ESP32_IP = "192.168.1.105"
   ESP32_PORT = 8080
   ```

5. Run `python main.py` — now wireless!

> **Note:** Both Serial and WiFi are active simultaneously on the ESP32, so you can monitor via Serial Monitor while controlling via WiFi.

> **Important:** ESP32 only supports **2.4 GHz** WiFi networks, not 5 GHz.

---

## 13. Troubleshooting

| Problem | Solution |
|---------|----------|
| "Cannot open camera" | Try `CAMERA_INDEX = 1` in config.py, or close other apps using the camera |
| "Hand landmarker model not found" | Download `hand_landmarker.task` — see [Step 2 of Installation](#step-2-download-mediapipe-model) |
| No hand detected | Ensure good lighting, show full hand to camera, avoid busy backgrounds |
| ESP32 won't connect (Serial) | Check COM port in Device Manager, try different USB cable |
| "ModuleNotFoundError: serial" | Install with `pip install pyserial` (NOT `pip install serial`) |
| Servos don't move | Check external power supply is ON and connected to PCA9685 V+ |
| Servos jitter/buzz | Servo is hitting mechanical limit — recalibrate MIN/MAX to avoid extremes |
| Erratic servo movement | Add 1000µF capacitor to PCA9685 V+/GND, check wiring |
| WiFi won't connect | Verify SSID/password, ensure 2.4 GHz network (ESP32 doesn't support 5 GHz) |
| Laggy response | Reduce `MEDIAPIPE_MODEL_COMPLEXITY` to `0`, increase `EMA_ALPHA` |
| Wrong finger mapping | Check PCA9685 channel wiring matches `config.h` CH_THUMB through CH_WRIST |
| Wrist moves wrong direction | Set `SERVO_INVERTED["wrist"] = True` in config.py, or recalibrate |
| Hold mode won't activate | A hand must be detected first — show your hand, then press H |
| Grip too strong/weak | Press G to cycle modes, or +/− to fine-tune strength |

---

## 14. Project Structure

```
ESP32_HandRobot_Inmoov/
├── README.md                         ← Quick-start guide
├── USER_MANUAL.md                    ← This comprehensive manual
├── algorithms.md                     ← Algorithm reference
│
├── python_client/
│   ├── config.py                     ← All Python-side configuration
│   ├── hand_tracker.py               ← MediaPipe hand tracking & angle calculation
│   ├── esp32_client.py               ← Serial/WiFi communication module
│   ├── main.py                       ← Main application entry point
│   ├── calibration_tool.py           ← Interactive servo calibration
│   ├── reset_servos.py               ← Reset all servos to 90° (neutral)
│   ├── hand_landmarker.task          ← MediaPipe model file (downloaded)
│   ├── calibration_data.json         ← (Generated) Saved calibration values
│   └── requirements.txt              ← Python dependencies
│
└── esp32_firmware/
    └── esp32_hand_controller/
        ├── esp32_hand_controller.ino ← Main ESP32 firmware
        └── config.h                  ← Firmware configuration
```

### File Responsibilities

| File | Role |
|------|------|
| `hand_tracker.py` | All computer vision: landmark detection, curl calculation, wrist rotation, EMA smoothing |
| `main.py` | Application loop: camera → tracker → grip protection → servo mapping → UI → ESP32 |
| `esp32_client.py` | Communication abstraction: Serial & WiFi clients, rate limiting, deadband, protocol formatting |
| `config.py` | Central configuration: ports, camera, tracking params, grip modes, servo calibration |
| `calibration_tool.py` | Standalone calibration UI with sliders, test sweeps, and save/load |
| `reset_servos.py` | Simple utility to reset all servos to neutral (90°) |
| `config.h` | Firmware-side configuration: I2C pins, PWM range, speed limits, compliance |
| `esp32_hand_controller.ino` | Firmware: command parsing, smooth interpolation, PCA9685 control |

---

*Built for the InMoov open-source robot platform. For educational and hobby use.*
