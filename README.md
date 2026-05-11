# InMoov Hand Gesture Control System

Real-time robot hand control using laptop webcam hand tracking with ESP32 + PCA9685 + MG996R servos.

```
  🎥 Webcam → 🐍 Python (MediaPipe) → 📡 ESP32 (Serial/WiFi) → 🔌 PCA9685 → 🦾 6x MG996R
```

---

## 📋 Bill of Materials

| Item | Qty | Notes |
|------|-----|-------|
| ESP32 DevKit 30P (CH340, Type-C) | 1 | WiFi + Bluetooth MCU |
| PCA9685 16-Channel PWM Driver | 1 | I2C servo controller |
| MG996R Servo Motor | 6 | 5 fingers + 1 wrist |
| External 5V Power Supply (≥10A) | 1 | **DO NOT power servos from ESP32** |
| USB Type-C Cable | 1 | ESP32 ↔ Laptop |
| Jumper Wires (M-F) | ~10 | For I2C + power connections |
| InMoov Hand (3D printed) | 1 | With fishing line tendons |
| Laptop with Webcam | 1 | Running Python client |

---

## 🔌 Wiring Diagram

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
  └─────────────────┘      │       │  CH0 ─── Thumb  Servo (Orange=Signal)
                           │       │  CH1 ─── Index  Servo
                           │       │  CH2 ─── Middle Servo
     External 5V PSU       │       │  CH3 ─── Ring   Servo
  ┌─────────────────┐      │       │  CH4 ─── Pinky  Servo
  │  +5V           ├──────┼───────┤ V+  (Servo Power)  │
  │  GND           ├──────┘       │                     │
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

### ⚠️ Critical Power Notes

1. **NEVER** power servos from the ESP32 USB or 3.3V pins
2. Use an external **5V power supply rated at 10A+** (each MG996R can draw 2.5A stall)
3. Connect PSU ground to PCA9685 GND **AND** ESP32 GND (common ground)
4. Add a **1000µF capacitor** across V+ and GND on PCA9685 to prevent brownouts

---

## 🖥️ Software Setup

### Step 1: Install Python Dependencies

```bash
cd python_client
pip install -r requirements.txt
```

Required packages:
- `opencv-python` — Webcam capture and display
- `mediapipe` — Hand landmark detection
- `numpy` — Math operations
- `pyserial` — USB serial communication

### Step 2: Flash ESP32 Firmware

1. Open Arduino IDE (or PlatformIO)
2. Install required libraries via Library Manager:
   - **Adafruit PWM Servo Driver Library** (search "Adafruit PWM Servo")
   - **Wire** (built-in)
   - **WiFi** (built-in for ESP32)
3. Select board: **Tools → Board → ESP32 Dev Module**
4. Select port: **Tools → Port → COMx** (your ESP32 COM port)
5. Open `esp32_firmware/esp32_hand_controller/esp32_hand_controller.ino`
6. Edit `config.h`:
   - Set your WiFi SSID and password (for wireless mode)
   - Set `ENABLE_WIFI` to `false` if testing Serial only first
7. Click **Upload** (→ button)
8. Open **Serial Monitor** (115200 baud) to verify startup messages

### Step 3: Configure Python Client

Edit `python_client/config.py`:

```python
# For wired (USB) testing:
COMM_MODE = "serial"
SERIAL_PORT = "COM3"    # ← Change to your ESP32's COM port

# For wireless (WiFi) — after Serial works:
# COMM_MODE = "wifi"
# ESP32_IP = "192.168.1.100"  # ← Printed on ESP32 Serial Monitor
```

**Finding your COM port (Windows):**
1. Open Device Manager
2. Expand "Ports (COM & LPT)"
3. Look for "USB-SERIAL CH340 (COMx)"

---

## 🎮 Running the System

### Quick Start (Wired/Serial Mode)

```bash
cd python_client
python main.py
```

### Controls
   
| Key | Action |
|-----|--------|
| `Q` | Quit |
| `P` | Pause/Resume sending to ESP32 |
| `R` | Reconnect to ESP32 |
| `M` | Toggle mirror mode (flip camera) |
| `Space` | Toggle wrist control on/off |

### What You Should See

- Camera feed with hand landmarks drawn in color
- Finger curl bar gauges at bottom-left (green=open, red=closed)
- Servo angle numbers above each bar
- Connection status indicator (green dot = connected)
- FPS counter top-right

---

## 🔧 Calibration Guide

Calibration is **essential** because each servo + finger mechanism has different mechanical limits.

### Step 1: Run the Calibration Tool

```bash
cd python_client
python calibration_tool.py
```

### Step 2: Understand the Interface

The calibration window shows:
- **6 trackbar sliders** (one per servo)
- **Visual angle bars** with green (MIN) and blue (MAX) markers
- **Selected servo** highlighted in blue

### Step 3: Calibrate Each Finger

For each finger (1–6), do the following:

1. **Press the number key** (`1`=Thumb, `2`=Index, `3`=Middle, `4`=Ring, `5`=Pinky, `6`=Wrist) to select it

2. **Find the OPEN position:**
   - Slowly drag the slider until the finger is fully extended (open)
   - Don't go too far — stop just before the servo strains or buzzes
   - Press `O` to save this as the MIN (open) angle

3. **Find the CLOSED position:**
   - Slowly drag the slider in the opposite direction until the finger is fully curled (closed)
   - Again, stop just before straining
   - Press `C` to save this as the MAX (closed) angle

4. **Check direction:**
   - If the finger moves the wrong way (opens when it should close), press `I` to invert

5. **Test the range:**
   - Press `T` to test — the servo will sweep from MIN → MAX → MIN
   - Verify the full range looks correct

### Step 4: Test All Servos

- Press `A` to run a wave test across all fingers
- All fingers should open, then close one-by-one, then open in reverse

### Step 5: Save Calibration

- Press `S` to save
- Values are saved to `calibration_data.json`
- The console also prints values to copy into `config.py`:

```python
SERVO_MIN = {"thumb": 15, "index": 10, "middle": 12, "ring": 10, "pinky": 8, "wrist": 20}
SERVO_MAX = {"thumb": 165, "index": 170, "middle": 168, "ring": 170, "pinky": 172, "wrist": 160}
SERVO_INVERTED = {"thumb": False, "index": False, ...}
```

### Step 6: Update config.py

Copy the printed values into `python_client/config.py`, replacing the default values.

---

## 🔀 Switching to WiFi Mode

After everything works over USB Serial:

1. Edit `esp32_firmware/esp32_hand_controller/config.h`:
   ```c
   #define WIFI_SSID     "YourWiFiName"
   #define WIFI_PASSWORD "YourWiFiPassword"
   #define ENABLE_WIFI   true
   ```

2. Re-upload firmware to ESP32

3. Open Serial Monitor — note the printed IP address:
   ```
   [WIFI] Connected! IP: 192.168.1.105
   ```

4. Edit `python_client/config.py`:
   ```python
   COMM_MODE = "wifi"
   ESP32_IP = "192.168.1.105"  # From Serial Monitor
   ESP32_PORT = 8080
   ```

5. Run `python main.py` — now wireless!

> **Note:** Both Serial and WiFi are active simultaneously on the ESP32, so you can monitor via Serial Monitor while controlling via WiFi.

---

## 🐛 Troubleshooting

| Problem | Solution |
|---------|----------|
| "Cannot open camera" | Try `CAMERA_INDEX = 1` in config.py, or close other apps using the camera |
| No hand detected | Ensure good lighting, show full hand to camera |
| ESP32 won't connect (Serial) | Check COM port in Device Manager, try different USB cable |
| Servos don't move | Check external power supply is ON and connected to PCA9685 V+ |
| Servos jitter/buzz | Servo is hitting mechanical limit — recalibrate MIN/MAX to avoid extremes |
| Erratic servo movement | Add 1000µF capacitor to PCA9685 V+/GND, check wiring |
| WiFi won't connect | Verify SSID/password, ensure 2.4GHz network (ESP32 doesn't support 5GHz) |
| Laggy response | Reduce `MEDIAPIPE_MODEL_COMPLEXITY` to `0` in config.py |
| Wrong finger mapping | Check PCA9685 channel wiring matches config.h CH_THUMB through CH_WRIST |
| "ModuleNotFoundError: serial" | Install with `pip install pyserial` (not `pip install serial`) |

---

## 📁 Project Structure

```
ESP32_HandRobot_Inmoov/
├── README.md                       ← You are here
├── python_client/
│   ├── config.py                   ← Configuration (COM port, camera, calibration)
│   ├── hand_tracker.py             ← MediaPipe hand tracking & angle calculation
│   ├── esp32_client.py             ← Serial/WiFi communication
│   ├── main.py                     ← Main application entry point
│   ├── calibration_tool.py         ← Interactive servo calibration
│   ├── calibration_data.json       ← (Generated) Saved calibration values
│   └── requirements.txt            ← Python dependencies
└── esp32_firmware/
    └── esp32_hand_controller/
        ├── esp32_hand_controller.ino  ← Main ESP32 firmware
        └── config.h                   ← Firmware configuration
```

---

## 📜 License

This project is for educational and hobby use with the InMoov open-source robot platform.
