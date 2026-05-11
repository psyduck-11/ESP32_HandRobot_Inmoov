/*
 * ============================================================
 *  InMoov Hand Controller — ESP32 Firmware
 *  Controls 6x MG996R servos via PCA9685 I2C PWM driver.
 *  Accepts commands over USB Serial AND WiFi TCP.
 *
 *  Protocol:
 *    F<t>,<i>,<m>,<r>,<p>,<w>\n  — Set all 6 servos (0-180°)
 *    C<ch>,<angle>\n              — Set single channel
 *    G<strength>\n                — Set grip strength (0-100%)
 *    P\n                          — Ping (replies PONG)
 *    S\n                          — Status (replies current angles + grip)
 *
 *  Hardware:
 *    ESP32 DevKit 30P (CH340, Type-C)
 *    PCA9685 16-ch PWM driver on I2C (SDA=21, SCL=22)
 *    6x MG996R servos on channels 0-5
 *    External 5V 10A+ power supply on PCA9685 V+
 * ============================================================
 */

#include <Wire.h>
#include <Adafruit_PWMServoDriver.h>
#include "config.h"

#if ENABLE_WIFI
  #include <WiFi.h>
#endif

// ---- PCA9685 Driver ----
Adafruit_PWMServoDriver pwm = Adafruit_PWMServoDriver(PCA9685_ADDR);

// ---- Servo State ----
int currentAngle[NUM_SERVOS] = {90, 90, 90, 90, 90, 90};
int targetAngle[NUM_SERVOS]  = {90, 90, 90, 90, 90, 90};
const int servoChannels[NUM_SERVOS] = {
  CH_THUMB, CH_INDEX, CH_MIDDLE, CH_RING, CH_PINKY, CH_WRIST
};

// ---- Timing ----
unsigned long lastUpdateTime = 0;
unsigned long lastLedToggle  = 0;
bool ledState = false;

// ---- Grip Protection ----
int gripStrength = 75;               // 0-100% — limits max closing angle
int maxServoAngle[NUM_SERVOS];       // Computed max angle per servo based on grip
bool stallDetected[NUM_SERVOS] = {false};

#if ENABLE_CURRENT_SENSE
  int stallCounter = 0;              // Debounce counter for stall detection
  unsigned long lastCurrentRead = 0;
#endif

// ---- Serial Input Buffer ----
String serialBuffer = "";

// ---- WiFi TCP ----
#if ENABLE_WIFI
  WiFiServer tcpServer(TCP_PORT);
  WiFiClient tcpClient;
  String wifiBuffer = "";
  bool wifiConnected = false;
#endif

// ============================================================
//  UTILITY FUNCTIONS
// ============================================================

/**
 * Convert angle (0-180°) to PCA9685 PWM tick value.
 */
int angleToPWM(int angle) {
  angle = constrain(angle, ANGLE_MIN, ANGLE_MAX);
  return map(angle, 0, 180, SERVO_MIN_TICK, SERVO_MAX_TICK);
}

/**
 * Set a servo to a specific angle immediately (no smoothing).
 */
void setServoImmediate(int channel, int angle) {
  angle = constrain(angle, ANGLE_MIN, ANGLE_MAX);
  int pwmVal = angleToPWM(angle);
  pwm.setPWM(channel, 0, pwmVal);
}

/**
 * Update servo positions with smooth interpolation and compliance.
 * Compliance: when a servo is closing (increasing angle) and within
 * COMPLIANCE_ZONE_DEG of its target, speed is progressively reduced.
 * This creates a "soft approach" that prevents sudden force on objects.
 */
void updateServos() {
  for (int i = 0; i < NUM_SERVOS; i++) {
    // Apply grip strength limit: cap target angle
    int effectiveTarget = targetAngle[i];
    if (effectiveTarget > maxServoAngle[i]) {
      effectiveTarget = maxServoAngle[i];
    }

    // Skip if stall was detected on this servo
    if (stallDetected[i]) {
      continue;
    }

    if (currentAngle[i] != effectiveTarget) {
      int diff = effectiveTarget - currentAngle[i];
      bool isClosing = (diff > 0);  // Closing = increasing angle

      int speedLimit = SERVO_SPEED_LIMIT;

      // Apply compliance when closing (not when opening)
      if (isClosing && COMPLIANCE_ZONE_DEG > 0 && speedLimit > 0) {
        int distToTarget = abs(effectiveTarget - currentAngle[i]);
        if (distToTarget <= COMPLIANCE_ZONE_DEG) {
          // Linearly reduce speed as we approach the target
          // At edge of zone: full speed. At target: COMPLIANCE_MIN_SPEED
          float factor = (float)distToTarget / (float)COMPLIANCE_ZONE_DEG;
          speedLimit = max(COMPLIANCE_MIN_SPEED,
                          (int)(COMPLIANCE_MIN_SPEED + factor * (SERVO_SPEED_LIMIT - COMPLIANCE_MIN_SPEED)));
        }
      }

      // Apply speed limit
      if (speedLimit > 0 && abs(diff) > speedLimit) {
        diff = (diff > 0) ? speedLimit : -speedLimit;
      }

      currentAngle[i] += diff;
      currentAngle[i] = constrain(currentAngle[i], ANGLE_MIN, ANGLE_MAX);
      setServoImmediate(servoChannels[i], currentAngle[i]);
    }
  }
}

// ============================================================
//  GRIP PROTECTION
// ============================================================

/**
 * Recalculate max allowed angle for each servo based on gripStrength.
 * gripStrength=100 means full range, 50 means only half range.
 */
void updateGripLimits() {
  for (int i = 0; i < NUM_SERVOS; i++) {
    // Map grip strength to max angle
    // At 100%: ANGLE_MAX (full range). At 0%: ANGLE_MIN (can't close at all).
    maxServoAngle[i] = map(gripStrength, 0, 100, ANGLE_MIN, ANGLE_MAX);
    // Clear stall flag when grip changes
    stallDetected[i] = false;
  }
}

#if ENABLE_CURRENT_SENSE
/**
 * Read current from ADC and detect stall condition.
 * When current exceeds threshold for STALL_DEBOUNCE_COUNT readings,
 * back off all closing servos.
 */
void checkCurrentStall() {
  unsigned long now = millis();
  if (now - lastCurrentRead < 10) return;  // Read every 10ms
  lastCurrentRead = now;

  int adcVal = analogRead(CURRENT_SENSE_PIN);

  if (adcVal > CURRENT_STALL_ADC) {
    stallCounter++;
    if (stallCounter >= STALL_DEBOUNCE_COUNT) {
      // Stall detected! Back off all servos that are closing
      Serial.println("[GRIP] Stall detected! Current ADC: " + String(adcVal) + " — backing off");
      for (int i = 0; i < NUM_SERVOS; i++) {
        if (currentAngle[i] > ANGLE_MIN + STALL_BACKOFF_DEG) {
          targetAngle[i] = currentAngle[i] - STALL_BACKOFF_DEG;
          stallDetected[i] = true;
        }
      }
      stallCounter = 0;
    }
  } else {
    stallCounter = max(0, stallCounter - 1);  // Decay counter
  }
}
#endif

// ============================================================
//  COMMAND PARSING
// ============================================================

/**
 * Process a complete command string.
 * Returns a response string (may be empty).
 */
String processCommand(String cmd) {
  cmd.trim();

  if (cmd.length() == 0) {
    return "";
  }

  char type = cmd.charAt(0);

  switch (type) {
    case 'F':
    case 'f': {
      // F<thumb>,<index>,<middle>,<ring>,<pinky>,<wrist>
      String data = cmd.substring(1);
      int vals[NUM_SERVOS];
      int idx = 0;

      while (data.length() > 0 && idx < NUM_SERVOS) {
        int commaPos = data.indexOf(',');
        if (commaPos == -1) {
          vals[idx] = data.toInt();
          data = "";
        } else {
          vals[idx] = data.substring(0, commaPos).toInt();
          data = data.substring(commaPos + 1);
        }
        idx++;
      }

      if (idx >= NUM_SERVOS) {
        for (int i = 0; i < NUM_SERVOS; i++) {
          targetAngle[i] = constrain(vals[i], ANGLE_MIN, ANGLE_MAX);
        }
        return "OK\n";
      } else {
        return "E:INVALID_ARGS\n";
      }
    }

    case 'C':
    case 'c': {
      // C<channel>,<angle>
      String data = cmd.substring(1);
      int commaPos = data.indexOf(',');
      if (commaPos > 0) {
        int ch = data.substring(0, commaPos).toInt();
        int angle = data.substring(commaPos + 1).toInt();
        angle = constrain(angle, ANGLE_MIN, ANGLE_MAX);

        if (ch >= 0 && ch < 16) {
          setServoImmediate(ch, angle);
          // Also update state if it's one of our tracked channels
          for (int i = 0; i < NUM_SERVOS; i++) {
            if (servoChannels[i] == ch) {
              currentAngle[i] = angle;
              targetAngle[i] = angle;
              break;
            }
          }
          return "OK\n";
        }
      }
      return "E:INVALID_CHANNEL\n";
    }

    case 'P':
    case 'p':
      return "PONG\n";

    case 'G':
    case 'g': {
      // G<strength> — set grip strength (0-100)
      int str = cmd.substring(1).toInt();
      gripStrength = constrain(str, 0, 100);
      updateGripLimits();
      Serial.println("[GRIP] Strength set to " + String(gripStrength) + "%");
      return "OK:G" + String(gripStrength) + "\n";
    }

    case 'S':
    case 's': {
      // Return current angles and grip strength
      String resp = "A";
      for (int i = 0; i < NUM_SERVOS; i++) {
        resp += String(currentAngle[i]);
        if (i < NUM_SERVOS - 1) resp += ",";
      }
      resp += ",G" + String(gripStrength);
      resp += "\n";
      return resp;
    }

    default:
      return "E:UNKNOWN_CMD\n";
  }
}

/**
 * Read and process data from Serial.
 */
void handleSerial() {
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n' || c == '\r') {
      if (serialBuffer.length() > 0) {
        String response = processCommand(serialBuffer);
        if (response.length() > 0) {
          Serial.print(response);
        }
        serialBuffer = "";
      }
    } else {
      serialBuffer += c;
      // Safety: prevent buffer overflow
      if (serialBuffer.length() > 100) {
        serialBuffer = "";
      }
    }
  }
}

#if ENABLE_WIFI
/**
 * Read and process data from WiFi TCP client.
 */
void handleWiFi() {
  // Check for new client
  if (!tcpClient || !tcpClient.connected()) {
    tcpClient = tcpServer.available();
    if (tcpClient) {
      Serial.println("[WIFI] Client connected: " + tcpClient.remoteIP().toString());
      wifiConnected = true;
      wifiBuffer = "";
    } else if (wifiConnected) {
      Serial.println("[WIFI] Client disconnected");
      wifiConnected = false;
    }
  }

  // Read data from connected client
  if (tcpClient && tcpClient.connected()) {
    while (tcpClient.available()) {
      char c = (char)tcpClient.read();
      if (c == '\n' || c == '\r') {
        if (wifiBuffer.length() > 0) {
          String response = processCommand(wifiBuffer);
          if (response.length() > 0) {
            tcpClient.print(response);
          }
          wifiBuffer = "";
        }
      } else {
        wifiBuffer += c;
        if (wifiBuffer.length() > 100) {
          wifiBuffer = "";
        }
      }
    }
  }
}
#endif

/**
 * Blink the status LED.
 * Fast blink = no WiFi, Slow blink = WiFi connected, Solid = client connected.
 */
void updateLED() {
  unsigned long now = millis();
  unsigned long interval;

  #if ENABLE_WIFI
    if (wifiConnected) {
      digitalWrite(LED_PIN, HIGH);  // Solid on
      return;
    } else if (WiFi.status() == WL_CONNECTED) {
      interval = 1000;  // Slow blink — WiFi OK, no client
    } else {
      interval = 200;   // Fast blink — no WiFi
    }
  #else
    interval = 1000;  // Slow blink — Serial only mode
  #endif

  if (now - lastLedToggle >= interval) {
    ledState = !ledState;
    digitalWrite(LED_PIN, ledState);
    lastLedToggle = now;
  }
}

// ============================================================
//  SETUP & LOOP
// ============================================================

void setup() {
  // --- Serial ---
  Serial.begin(SERIAL_BAUD);
  delay(500);
  Serial.println();
  Serial.println("========================================");
  Serial.println("  InMoov Hand Controller v1.0");
  Serial.println("  ESP32 + PCA9685 + 6x MG996R");
  Serial.println("========================================");

  // --- LED ---
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);

  // --- I2C & PCA9685 ---
  Wire.begin(I2C_SDA, I2C_SCL);
  pwm.begin();
  pwm.setPWMFreq(PWM_FREQ);
  delay(10);
  Serial.println("[OK] PCA9685 initialized (addr 0x" + String(PCA9685_ADDR, HEX) + ")");

  // Initialize all servos to 90° (neutral)
  for (int i = 0; i < NUM_SERVOS; i++) {
    setServoImmediate(servoChannels[i], 90);
    Serial.println("[OK] Servo CH" + String(servoChannels[i]) + " → 90°");
  }

  // Initialize grip protection
  gripStrength = 75;  // Default: NORMAL mode
  updateGripLimits();
  Serial.println("[OK] Grip protection active (strength: " + String(gripStrength) + "%)");

  #if ENABLE_CURRENT_SENSE
    pinMode(CURRENT_SENSE_PIN, INPUT);
    analogSetAttenuation(ADC_11db);  // Full 0-3.3V range
    Serial.println("[OK] Current sensing enabled on GPIO " + String(CURRENT_SENSE_PIN));
  #else
    Serial.println("[INFO] Current sensing disabled (software compliance only)");
  #endif

  // --- WiFi ---
  #if ENABLE_WIFI
    Serial.print("[WIFI] Connecting to ");
    Serial.println(WIFI_SSID);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

    int attempts = 0;
    while (WiFi.status() != WL_CONNECTED && attempts < 40) {
      delay(500);
      Serial.print(".");
      attempts++;
    }

    if (WiFi.status() == WL_CONNECTED) {
      Serial.println();
      Serial.print("[WIFI] Connected! IP: ");
      Serial.println(WiFi.localIP());
      tcpServer.begin();
      Serial.println("[WIFI] TCP server started on port " + String(TCP_PORT));
      Serial.println("[WIFI] Set ESP32_IP in Python config.py to: " + WiFi.localIP().toString());
    } else {
      Serial.println();
      Serial.println("[WIFI] Connection failed — continuing with Serial only");
    }
  #else
    Serial.println("[INFO] WiFi disabled — Serial only mode");
  #endif

  Serial.println();
  Serial.println("[READY] Listening for commands...");
  Serial.println("  Protocol: F<t>,<i>,<m>,<r>,<p>,<w>  C<ch>,<angle>  G<str>  P  S");
  Serial.println("  Grip: strength=" + String(gripStrength) + "% compliance=" + String(COMPLIANCE_ZONE_DEG) + "deg");
  Serial.println("========================================");
}

void loop() {
  // Handle incoming commands
  handleSerial();

  #if ENABLE_WIFI
    handleWiFi();
  #endif

  // Update servo positions (smooth movement with compliance)
  unsigned long now = millis();
  if (now - lastUpdateTime >= UPDATE_INTERVAL_MS) {
    updateServos();
    lastUpdateTime = now;
  }

  // Check for current stall (if hardware is present)
  #if ENABLE_CURRENT_SENSE
    checkCurrentStall();
  #endif

  // Update status LED
  updateLED();
}
