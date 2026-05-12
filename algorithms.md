# InMoov Hand Control — Algorithm Deep Dive

Every algorithm in the system, explained with math and visuals.

---

## 1. Finger Curl Detection (Index, Middle, Ring, Pinky)

**File:** [hand_tracker.py:162–186](file:///c:/ESP32_HandRobot_Inmoov/python_client/hand_tracker.py#L162-L186)

**Goal:** Measure how bent a finger is → output 0% (straight) to 100% (fist).

**Method:** Compute the angle at each joint using the **dot product formula**.

```
     MCP ←── angle_pip ──→ DIP ←── angle_dip ──→ TIP
      ↑                     ↑                      ↑
  base joint          middle joint             fingertip
```

### The angle formula

Given 3 points **A → B → C**, the angle at **B**:

```
  BA = A - B
  BC = C - B
  cos(θ) = (BA · BC) / (|BA| × |BC|)
  θ = arccos(cos(θ))
```

```python
# hand_tracker.py line 241-258
def _angle_between(a, b, c):
    ba = a - b
    bc = c - b
    cos_angle = dot(ba, bc) / (|ba| × |bc|)
    return degrees(arccos(cos_angle))
```

### Combining two joints

```python
avg_angle = 0.65 × angle_PIP + 0.35 × angle_DIP
```

PIP (knuckle) contributes **65%** because it has the largest range of motion. DIP (fingertip joint) contributes **35%**.

### Mapping angle → curl %

```python
curl = interp(avg_angle, [40°, 170°], [100%, 0%])
```

```
Angle:  170° (straight)  ──────────────  40° (fully bent)
Curl:     0% (open)      ──────────────  100% (closed)
```

---

## 2. Thumb Curl Detection (Hybrid Method)

**File:** [hand_tracker.py:188–221](file:///c:/ESP32_HandRobot_Inmoov/python_client/hand_tracker.py#L188-L221)

The thumb moves differently (opposition, not just flexion), so it uses **two methods averaged 50/50**:

### Method A — Distance-based

```
normalized_dist = |thumb_tip − index_MCP| / |middle_MCP − wrist|
                   ↑ how far thumb is        ↑ hand size (for scale)
                     from index base

curl_dist = interp(normalized_dist, [0.15, 0.7], [100%, 0%])
```

- Thumb tip **near** index base → curled (100%)
- Thumb tip **far** from index base → open (0%)
- Dividing by hand size makes it work at any camera distance

### Method B — Angle-based

```
curl_angle = interp(angle_at_MCP, [60°, 160°], [100%, 0%])
```

### Combined

```python
curl = 0.5 × curl_dist + 0.5 × curl_angle
```

---

## 3. Wrist Rotation

**File:** [hand_tracker.py:223–238](file:///c:/ESP32_HandRobot_Inmoov/python_client/hand_tracker.py#L223-L238)

```python
dx = middle_MCP.x - wrist.x
dy = middle_MCP.y - wrist.y
angle_rad = atan2(dx, -dy)        # Angle of hand from vertical
servo = interp(degrees(angle_rad), [-90°, 90°], [0°, 180°])
```

```
  Hand tilted left (-90°) → servo 0°
  Hand vertical (0°)      → servo 90°
  Hand tilted right (90°) → servo 180°
```

---

## 4. EMA Smoothing

**File:** [hand_tracker.py:156–158](file:///c:/ESP32_HandRobot_Inmoov/python_client/hand_tracker.py#L156-L158)

Raw MediaPipe values jitter frame-to-frame. **Exponential Moving Average** smooths them:

```python
smoothed = α × raw + (1 - α) × previous_smoothed     # α = 0.35
```

```
α = 1.0  →  No smoothing (instant but jittery)
α = 0.35 →  Balanced (responsive + smooth)  ← default
α = 0.1  →  Heavy smoothing (laggy but very smooth)
```

Visually, if raw value jumps from 20 to 80 instantly:

```
Frame:    1     2     3     4     5     6     7
Raw:     80    80    80    80    80    80    80
Smooth:  41    54    63    70    74    77    79
         ↑ only jumps to 41 on first frame, then gradually catches up
```

---

## 5. Grip Protection — Compliance Zone (Cosine Easing)

**File:** [main.py:83–124](file:///c:/ESP32_HandRobot_Inmoov/python_client/main.py#L83-L124)

**Goal:** Prevent crushing objects by capping how far fingers can close, with a smooth deceleration zone.

### The three zones

```
Curl %:  0%  ─────────────  55%  ─────────  75%  ─── 100%
         │   FREE ZONE      │  COMPLIANCE   │  BLOCKED
         │   (1:1 mapping)  │  (eased)      │  (capped)
                             ↑               ↑
                     (max_curl - compliance)  max_curl (= grip strength)
```

Example: NORMAL mode → strength=75%, compliance_zone=20%

### The cosine easing math

Inside the compliance zone (curl between 55% and 75%):

```python
zone_progress = (curl - 55) / 20          # 0.0 at entry → 1.0 at limit
easing = 0.5 × (1 - cos(π × progress))   # Cosine ease-in curve
effective_curl = 55 + 20 × easing
```

```
Input curl:      55%   60%   65%   70%   75%   80%   90%  100%
Effective curl:  55%   56%   60%   68%   75%   75%   75%   75%
                  ↑ barely moves at start    ↑ capped here
```

The cosine curve creates a **soft brake** — starts gentle, increases braking near the limit.

### Final servo angle mapping

```python
# After grip protection:
if not inverted:
    angle = interp(effective_curl, [0, 100], [SERVO_MIN, SERVO_MAX])
else:
    angle = interp(effective_curl, [0, 100], [SERVO_MAX, SERVO_MIN])
```

---

## 6. ESP32 Communication Filters

**File:** [esp32_client.py:54–96](file:///c:/ESP32_HandRobot_Inmoov/python_client/esp32_client.py#L54-L96)

### Rate limiter

```python
if (now - last_send_time) < 1/30:   # 33ms minimum interval
    return  # Skip this frame, too soon
```

At 60 FPS camera but 30 Hz send rate → only every other frame actually sends.

### Deadband filter

```python
max_change = max(|new_angle[finger] - old_angle[finger]|  for each finger)
if max_change < 2°:
    return  # Skip — nothing moved enough to matter
```

Prevents sending identical or nearly-identical commands.

---

## 7. ESP32 Firmware — Smooth Servo Interpolation

**File:** [esp32_hand_controller.ino:93–134](file:///c:/ESP32_HandRobot_Inmoov/esp32_firmware/esp32_hand_controller/esp32_hand_controller.ino#L93-L134)

Runs every **20ms**. Instead of jumping to the target angle, the servo moves **at most 8° per step**:

```cpp
diff = target - current;
if (|diff| > 8)
    diff = sign(diff) × 8;    // Cap at 8°/step
current += diff;
```

```
Target jumps from 10° to 170° (160° gap):
Step:     0    1    2    3   ...  19    20
Current: 10°  18°  26°  34° ... 162°  170° ✓
                                      ↑ arrives in 20 steps = 400ms
```

### Firmware compliance zone

When the servo is **closing** (angle increasing) and within 20° of its target:

```cpp
// Linear speed reduction in compliance zone
factor = distance_to_target / 20;
speed = max(1, 1 + factor × (8 - 1));
```

```
Distance to target:  20°   15°   10°    5°    1°
Speed (°/step):       8     6     4     2     1
                      ↑ full speed          ↑ crawling (gentle contact)
```

---

## 8. Hold/Lock Algorithm

**File:** [main.py:345–366](file:///c:/ESP32_HandRobot_Inmoov/python_client/main.py#L345-L366), [main.py:411–421](file:///c:/ESP32_HandRobot_Inmoov/python_client/main.py#L411-L421)

```mermaid
flowchart TD
    A["Every frame"] --> B{"hold_mode?"}
    B -->|"YES (locked)"| C["Use frozen snapshot:\ncurls = held_curls\nangles = held_servo_angles"]
    B -->|"NO (live)"| D{"Hand detected?"}
    D -->|YES| E["Compute servo angles\nfrom live curl data"]
    D -->|NO| F["Reset all to OPEN\n(SERVO_MIN angles)"]
    C --> G["Send to ESP32"]
    E --> G
    F --> G

    H["User presses H"] --> I{"Currently locked?"}
    I -->|NO → LOCK| J["held_curls = current curls\nheld_servo_angles = current angles\nhold_mode = True"]
    I -->|YES → UNLOCK| K["held_curls = None\nheld_servo_angles = None\nhold_mode = False"]
```

**Key insight:** The hold check (line 346) runs **before** the hand-detection check. When locked, the entire live-tracking/reset path is bypassed. That's why it's independent from reset.

---

## 9. PCA9685 PWM Tick Conversion

**File:** [esp32_hand_controller.ino:73–76](file:///c:/ESP32_HandRobot_Inmoov/esp32_firmware/esp32_hand_controller/esp32_hand_controller.ino#L73-L76)

```
angle (0-180°)  →  PWM ticks (102-512)  →  pulse width (500-2500µs)

                    PCA9685 at 50Hz:
                    Period = 20ms = 4096 ticks
                    1 tick ≈ 4.88µs

   0° → 102 ticks → 498µs   (MG996R minimum)
  90° → 307 ticks → 1499µs  (MG996R center)
 180° → 512 ticks → 2499µs  (MG996R maximum)
```

```cpp
pwm_tick = map(angle, 0, 180, 102, 512);
pwm.setPWM(channel, 0, pwm_tick);
```

---

## Summary — Full Pipeline per Frame

```
Camera frame (BGR, 1280×720)
    │
    ├─ flip if mirror mode
    ├─ convert BGR → RGB
    │
    ▼
MediaPipe Hand Landmarker
    │
    ├─ detects 21 landmarks (x, y, z normalized)
    │
    ▼
Curl Computation (per finger)
    │
    ├─ Fingers: joint angles → weighted avg → map to 0-100%
    ├─ Thumb: distance + angle hybrid → 0-100%
    ├─ Wrist: atan2 → 0-180°
    │
    ▼
EMA Smoothing (α = 0.35)
    │
    ├─ smoothed = 0.35 × raw + 0.65 × previous
    │
    ▼
Hold Check ─── if LOCKED → use frozen snapshot, skip below
    │
    ▼
Grip Protection
    │
    ├─ Cap curl at grip strength %
    ├─ Cosine easing in compliance zone
    │
    ▼
Servo Angle Mapping
    │
    ├─ interp(curl, [0,100], [SERVO_MIN, SERVO_MAX])
    ├─ handle inversion
    │
    ▼
Rate Limit (30 Hz) + Deadband (2°)
    │
    ▼
Serial/WiFi → "F90,10,45,30,10,90\n"
    │
    ▼
ESP32 Command Parser
    │
    ├─ sets targetAngle[] for each servo
    │
    ▼
Servo Update Loop (every 20ms)
    │
    ├─ move max 8°/step toward target
    ├─ compliance: slow down when closing + near target
    │
    ▼
PCA9685 → PWM pulse → MG996R servo moves
```
