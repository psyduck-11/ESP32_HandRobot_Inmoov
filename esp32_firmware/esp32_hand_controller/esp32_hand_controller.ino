/*
 * reset_servo.ino
 * ────────────────────────────────────────────────────────────────────
 * Arduino IDE sketch for ESP32 DevKit + PCA9685 16-channel PWM driver.
 * Resets 6 servos (channels 0-5) to a demanded angle.
 *
 * Required library:
 *   Adafruit PWM Servo Driver Library
 *   → Install via: Sketch > Include Library > Manage Libraries…
 *     Search "Adafruit PWM Servo Driver" and install.
 *
 * Wiring (ESP32 ↔ PCA9685):
 *   ESP32 GPIO21 (SDA)  →  PCA9685 SDA
 *   ESP32 GPIO22 (SCL)  →  PCA9685 SCL
 *   ESP32 3.3V          →  PCA9685 VCC
 *   ESP32 GND           →  PCA9685 GND
 *   External 5-6V PSU   →  PCA9685 V+ (servo power)
 *
 * Board:
 *   Select "ESP32 Dev Module" in Arduino IDE.
 * ────────────────────────────────────────────────────────────────────
 */

#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>

// ======================== USER CONFIGURATION ========================

#define DEMANDED_DEGREE   0        // Target angle for all servos (0-180)

#define PCA9685_ADDR      0x40      // Default I2C address
#define SDA_PIN           21        // ESP32 default SDA
#define SCL_PIN           22        // ESP32 default SCL

#define NUM_SERVOS        6         // Number of servos to control
const uint8_t SERVO_CHANNELS[NUM_SERVOS] = {0, 1, 2, 3, 4, 5};

// Standard servo pulse widths (microseconds) — adjust for your servos
#define SERVO_MIN_US      500       // Pulse width at 0°
#define SERVO_MAX_US      2500      // Pulse width at 180°
#define SERVO_FREQ_HZ     50        // 50 Hz = 20 ms period (standard)

#define STAGGER_DELAY_MS  150       // Delay between each servo to reduce inrush

// ======================== GLOBALS ==================================

Adafruit_PWMServoDriver pca = Adafruit_PWMServoDriver(PCA9685_ADDR);

// ======================== HELPER FUNCTIONS =========================

/**
 * Convert an angle (0-180°) to a 12-bit PCA9685 tick count.
 */
uint16_t angleToPWM(float angle) {
  angle = constrain(angle, 0.0f, 180.0f);

  // Map angle to pulse width in microseconds
  float pulseUs = SERVO_MIN_US + (SERVO_MAX_US - SERVO_MIN_US) * (angle / 180.0f);

  // Convert microseconds to 12-bit ticks
  // Period at 50 Hz = 20 000 µs → 4096 ticks
  float periodUs = 1000000.0f / (float)SERVO_FREQ_HZ;
  uint16_t ticks = (uint16_t)(pulseUs / periodUs * 4096.0f + 0.5f);

  return constrain(ticks, (uint16_t)0, (uint16_t)4095);
}

/**
 * Return pulse width in µs for a given angle (for display purposes).
 */
float angleToPulseUs(float angle) {
  angle = constrain(angle, 0.0f, 180.0f);
  return SERVO_MIN_US + (SERVO_MAX_US - SERVO_MIN_US) * (angle / 180.0f);
}

/**
 * Check whether a channel is in the allowed SERVO_CHANNELS list.
 */
bool isValidChannel(uint8_t ch) {
  for (int i = 0; i < NUM_SERVOS; i++) {
    if (SERVO_CHANNELS[i] == ch) return true;
  }
  return false;
}

/**
 * Move a single servo to the specified angle.
 */
void resetSingleServo(uint8_t ch, float angle) {
  uint16_t pwmTicks = angleToPWM(angle);
  float pulseUs     = angleToPulseUs(angle);

  pca.setPWM(ch, 0, pwmTicks);

  Serial.print("    CH");
  Serial.print(ch);
  Serial.print(" -> ");
  Serial.print(angle, 1);
  Serial.print("°  (");
  Serial.print(pulseUs, 0);
  Serial.println(" µs)");
}

/**
 * Reset all servos to the specified angle.
 */
void resetAllServos(float angle) {
  float pulseUs = angleToPulseUs(angle);

  Serial.println();
  Serial.print(">>> Resetting ALL ");
  Serial.print(NUM_SERVOS);
  Serial.print(" servos to ");
  Serial.print(angle, 1);
  Serial.print("°  (pulse ");
  Serial.print(pulseUs, 0);
  Serial.println(" µs)");
  Serial.println();

  for (int i = 0; i < NUM_SERVOS; i++) {
    resetSingleServo(SERVO_CHANNELS[i], angle);
    delay(STAGGER_DELAY_MS);
  }

  Serial.println();
  Serial.println("[DONE] All servos set.");
  Serial.println();
}

// ======================== SETUP ====================================

void setup() {
  Serial.begin(115200);
  while (!Serial) { delay(10); }
  Serial.println();
  Serial.println("========================================");
  Serial.println("  ESP32 + PCA9685  Servo Reset Utility  ");
  Serial.println("========================================");

  // Initialise I2C with custom pins (ESP32)
  Wire.begin(SDA_PIN, SCL_PIN);

  // Scan for PCA9685
  Wire.beginTransmission(PCA9685_ADDR);
  uint8_t error = Wire.endTransmission();
  if (error != 0) {
    Serial.print("[ERROR] PCA9685 not found at 0x");
    Serial.print(PCA9685_ADDR, HEX);
    Serial.println("!");
    Serial.println("        Check wiring and power.");
    Serial.println("        Halting.");
    while (true) { delay(1000); }   // Halt
  }
  Serial.print("[OK] PCA9685 found at 0x");
  Serial.println(PCA9685_ADDR, HEX);

  // Initialise PCA9685
  pca.begin();
  pca.setPWMFreq(SERVO_FREQ_HZ);
  delay(10);
  Serial.print("[OK] PWM frequency set to ");
  Serial.print(SERVO_FREQ_HZ);
  Serial.println(" Hz");

  // Reset servo CH5 to demanded angle on boot
  Serial.println();
  Serial.print(">>> Resetting servo CH5 to ");
  Serial.print(DEMANDED_DEGREE);
  Serial.println("°");
  resetSingleServo(5, DEMANDED_DEGREE);
  Serial.println("[DONE]");
  Serial.println();

  // Prompt for interactive control
  Serial.println("──────────────────────────────────────────────");
  Serial.println("Serial commands:");
  Serial.println("  <ch> <angle>   Move one servo   (e.g. 2 90)");
  Serial.println("  all <angle>    Move all servos   (e.g. all 45)");
  Serial.println("──────────────────────────────────────────────");
}

// ======================== LOOP =====================================

void loop() {
  // Interactive: read commands from Serial Monitor
  if (Serial.available() > 0) {
    String input = Serial.readStringUntil('\n');
    input.trim();
    if (input.length() == 0) return;

    // ── "all <angle>" — move every servo ──
    if (input.startsWith("all ") || input.startsWith("ALL ")) {
      float angle = input.substring(4).toFloat();
      if (angle < 0 || angle > 180) {
        Serial.println("[WARN] Angle must be 0-180");
      } else {
        resetAllServos(angle);
      }
      return;
    }

    // ── "<ch> <angle>" — move a single servo ──
    int spaceIdx = input.indexOf(' ');
    if (spaceIdx > 0) {
      int ch        = input.substring(0, spaceIdx).toInt();
      float angle   = input.substring(spaceIdx + 1).toFloat();

      if (!isValidChannel((uint8_t)ch)) {
        Serial.print("[WARN] CH");
        Serial.print(ch);
        Serial.print(" is not in SERVO_CHANNELS. Valid: ");
        for (int i = 0; i < NUM_SERVOS; i++) {
          Serial.print(SERVO_CHANNELS[i]);
          if (i < NUM_SERVOS - 1) Serial.print(", ");
        }
        Serial.println();
      } else if (angle < 0 || angle > 180) {
        Serial.println("[WARN] Angle must be 0-180");
      } else {
        Serial.println();
        Serial.print(">>> Moving servo CH");
        Serial.print(ch);
        Serial.print(" to ");
        Serial.print(angle, 1);
        Serial.println("°");
        resetSingleServo((uint8_t)ch, angle);
        Serial.println("[DONE]");
        Serial.println();
      }
      return;
    }

    // ── Unknown format ──
    Serial.println("[WARN] Use:  <ch> <angle>  or  all <angle>");
  }
}
