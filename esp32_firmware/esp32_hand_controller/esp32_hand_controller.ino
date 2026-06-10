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
 *    5V 20A Adapter on PCA9685 V+
 *
 *  References:
 *    Libraries:
 *      - Adafruit PWM Servo Driver Library (PCA9685 I2C control):
 *          https://github.com/adafruit/Adafruit-PWM-Servo-Driver-Library
 *          https://learn.adafruit.com/16-channel-pwm-servo-driver/library-reference
 *      - Arduino Wire Library (I2C master):
 *          https://www.arduino.cc/reference/en/language/functions/communication/wire/
 *      - ESP32 Arduino Core:
 *          https://docs.espressif.com/projects/arduino-esp32/en/latest/
 *
 *    WiFi / Networking:
 *      - ESP32 WiFi Library (Station mode, TCP server):
 *          https://docs.espressif.com/projects/arduino-esp32/en/latest/api/wifi.html
 *      - WiFiServer & WiFiClient API:
 *          https://www.arduino.cc/reference/en/libraries/wifi/
 *      - TCP_NODELAY / Nagle's algorithm (setNoDelay for low-latency):
 *          https://en.wikipedia.org/wiki/Nagle%27s_algorithm
 *
 *    Servo Control Theory:
 *      - PWM-to-angle mapping (PCA9685 12-bit ticks → µs → degrees):
 *          See PCA9685 datasheet Section 7.3.5
 *          https://www.nxp.com/docs/en/data-sheet/PCA9685.pdf
 *      - Smooth servo interpolation (rate-limited position stepping):
 *          https://www.arduino.cc/reference/en/language/functions/math/constrain/
 *      - Compliance zone / soft-landing approach (preventing grip crush):
 *          Inspired by robotic gripper force-control literature
 *          https://en.wikipedia.org/wiki/Impedance_control
 *
 *    Stall/Current Detection (optional):
 *      - ESP32 ADC (analogRead, 12-bit resolution):
 *          https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/peripherals/adc_oneshot.html
 *      - Motor stall detection via current sensing:
 *          https://learn.adafruit.com/adafruit-ina219-current-sensor-breakout
 *
 *    Serial Communication:
 *      - Arduino Serial (UART at 115200 baud):
 *          https://www.arduino.cc/reference/en/language/functions/communication/serial/
 *      - strtok() for command parsing (C standard library):
 *          https://en.cppreference.com/w/c/string/byte/strtok
 *
 *    InMoov Project:
 *      - InMoov open-source robot (hand & forearm design):
 *          https://inmoov.fr/hand-and-forarm/
 * ============================================================
 */

#include "config.h"
#include <Adafruit_PWMServoDriver.h>
#include <Wire.h>

#if ENABLE_WIFI
#include <WiFi.h>
#endif

// ---- PCA9685 Driver ----
Adafruit_PWMServoDriver pwm = Adafruit_PWMServoDriver(PCA9685_ADDR);

// ---- Servo State ----
int currentAngle[NUM_SERVOS] = {90, 90, 90, 90, 90, 90};
int targetAngle[NUM_SERVOS] = {90, 90, 90, 90, 90, 90};
const int servoChannels[NUM_SERVOS] = {CH_THUMB, CH_INDEX, CH_MIDDLE,
                                       CH_RING,  CH_PINKY, CH_WRIST};

// ---- Timing ----
unsigned long lastUpdateTime = 0;
unsigned long lastLedToggle = 0;
bool ledState = false;

// ---- Safety Configurations synced from Python ----
bool safetyInverted[NUM_SERVOS] = {false, false, false, false, false, false};
int safetyMin[NUM_SERVOS] = {ANGLE_MIN, ANGLE_MIN, ANGLE_MIN, ANGLE_MIN, ANGLE_MIN, ANGLE_MIN};
int safetyMax[NUM_SERVOS] = {ANGLE_MAX, ANGLE_MAX, ANGLE_MAX, ANGLE_MAX, ANGLE_MAX, ANGLE_MAX};

// ---- Grip Protection ----
int gripStrength = 100;        // 0-100% — limits max closing angle
int gripLimitAngle[NUM_SERVOS] = {ANGLE_MAX, ANGLE_MAX, ANGLE_MAX, ANGLE_MAX, ANGLE_MAX, ANGLE_MAX}; // Computed target limit angle per servo based on grip
bool stallDetected[NUM_SERVOS] = {false};

#if ENABLE_CURRENT_SENSE
int stallCounter = 0; // Debounce counter for stall detection
unsigned long lastCurrentRead = 0;
#endif

// ---- Serial Input Buffer ----
char serialBuffer[128];
int serialBufferIdx = 0;

// ---- WiFi TCP ----
#if ENABLE_WIFI
WiFiServer tcpServer(TCP_PORT);
WiFiClient tcpClient;
char wifiBuffer[128];
int wifiBufferIdx = 0;
bool wifiConnected = false;
#endif

// ============================================================
//  UTILITY FUNCTIONS
// ============================================================

/**
 * Set a servo to a specific angle immediately (no smoothing).
 * Optimized to compute PWM inline using pure integer arithmetic.
 */
inline void setServoImmediate(int channel, int angle) {
  int pwmVal = (angle * (SERVO_MAX_TICK - SERVO_MIN_TICK)) / 180 + SERVO_MIN_TICK;
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
    if (safetyInverted[i]) {
      // Inverted: closing means angle decreases. Cap target at gripLimitAngle (lower bound).
      if (effectiveTarget < gripLimitAngle[i]) {
        effectiveTarget = gripLimitAngle[i];
      }
    } else {
      // Normal: closing means angle increases. Cap target at gripLimitAngle (upper bound).
      if (effectiveTarget > gripLimitAngle[i]) {
        effectiveTarget = gripLimitAngle[i];
      }
    }

    // Fast-path skip: don't evaluate if already at target or stalled
    if (stallDetected[i] || currentAngle[i] == effectiveTarget) {
      continue;
    }

    // Anti-shaking deadband: ignore small target changes that would
    // only produce servo buzzing without meaningful movement.
#if SERVO_DEADBAND_DEG > 0
    if (abs(effectiveTarget - currentAngle[i]) < SERVO_DEADBAND_DEG) {
      continue;
    }
#endif

    int diff = effectiveTarget - currentAngle[i];

#if SERVO_SPEED_LIMIT > 0
    int speedLimit = SERVO_SPEED_LIMIT;

    // Apply compliance when closing
    bool isClosing = (safetyInverted[i] && diff < 0) || (!safetyInverted[i] && diff > 0);
    if (isClosing && COMPLIANCE_ZONE_DEG > 0) {
      int absDiff = abs(diff);
      if (absDiff <= COMPLIANCE_ZONE_DEG) {
        // Linearly reduce speed as we approach the target
        int scaledSpeed = COMPLIANCE_MIN_SPEED + 
          (absDiff * (SERVO_SPEED_LIMIT - COMPLIANCE_MIN_SPEED)) / COMPLIANCE_ZONE_DEG;
        speedLimit = scaledSpeed > COMPLIANCE_MIN_SPEED ? scaledSpeed : COMPLIANCE_MIN_SPEED;
      }
    }

    // Apply speed limit
    if (abs(diff) > speedLimit) {
      diff = (diff > 0) ? speedLimit : -speedLimit;
    }
#endif

    currentAngle[i] += diff;
    
    // Failsafe bound check
    int low = safetyMin[i] < safetyMax[i] ? safetyMin[i] : safetyMax[i];
    int high = safetyMin[i] > safetyMax[i] ? safetyMin[i] : safetyMax[i];
    if (currentAngle[i] < low) currentAngle[i] = low;
    else if (currentAngle[i] > high) currentAngle[i] = high;
    
    setServoImmediate(servoChannels[i], currentAngle[i]);
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
    // Map grip strength to angle limits based on safety config
    if (safetyInverted[i]) {
      // Inverted: open is safetyMax[i] (larger angle), closed is safetyMin[i] (smaller angle)
      gripLimitAngle[i] = map(gripStrength, 0, 100, safetyMax[i], safetyMin[i]);
    } else {
      // Normal: open is safetyMin[i] (smaller angle), closed is safetyMax[i] (larger angle)
      gripLimitAngle[i] = map(gripStrength, 0, 100, safetyMin[i], safetyMax[i]);
    }
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
  if (now - lastCurrentRead < 10)
    return; // Read every 10ms
  lastCurrentRead = now;

  int adcVal = analogRead(CURRENT_SENSE_PIN);

  if (adcVal > CURRENT_STALL_ADC) {
    stallCounter++;
    if (stallCounter >= STALL_DEBOUNCE_COUNT) {
      // Stall detected! Back off all servos to release grip
      Serial.print("[GRIP] Stall detected! Current ADC: ");
      Serial.print(adcVal);
      Serial.println(" — backing off");
      for (int i = 0; i < NUM_SERVOS; i++) {
        if (safetyInverted[i]) {
          if (currentAngle[i] < safetyMax[i]) {
            int backoffTarget = currentAngle[i] + STALL_BACKOFF_DEG;
            targetAngle[i] = backoffTarget < safetyMax[i] ? backoffTarget : safetyMax[i];
            stallDetected[i] = true;
          }
        } else {
          if (currentAngle[i] > safetyMin[i]) {
            int backoffTarget = currentAngle[i] - STALL_BACKOFF_DEG;
            targetAngle[i] = backoffTarget > safetyMin[i] ? backoffTarget : safetyMin[i];
            stallDetected[i] = true;
          }
        }
      }
      stallCounter = 0;
    }
  } else {
    if (stallCounter > 0) stallCounter--; // Fast decay without macro overhead
  }
}
#endif

// ============================================================
//  COMMAND PARSING
// ============================================================

/**
 * Process a complete command string and print response to output.
 * Uses zero dynamic memory allocation.
 */
void processCommand(char* cmd, Print& output) {
  // Trim trailing newline/cr/spaces
  int len = strlen(cmd);
  while (len > 0 && (cmd[len - 1] == '\n' || cmd[len - 1] == '\r' || cmd[len - 1] == ' ')) {
    cmd[len - 1] = '\0';
    len--;
  }
  
  // Trim leading space
  while (*cmd == ' ') {
    cmd++;
  }

  if (strlen(cmd) == 0) {
    return;
  }

  char type = cmd[0];
  char* data = cmd + 1;

  switch (type) {
  case 'F':
  case 'f': {
    // F<thumb>,<index>,<middle>,<ring>,<pinky>,<wrist>
    int vals[NUM_SERVOS];
    int idx = 0;
    char* token = strtok(data, ",");
    while (token != NULL && idx < NUM_SERVOS) {
      vals[idx++] = atoi(token);
      token = strtok(NULL, ",");
    }

    if (idx == NUM_SERVOS) {
      for (int i = 0; i < NUM_SERVOS; i++) {
        int low = safetyMin[i] < safetyMax[i] ? safetyMin[i] : safetyMax[i];
        int high = safetyMin[i] > safetyMax[i] ? safetyMin[i] : safetyMax[i];
        targetAngle[i] = constrain(vals[i], low, high);
      }
      output.print("OK\n");
    } else {
      output.print("E:INVALID_ARGS\n");
    }
    break;
  }

  case 'C':
  case 'c': {
    // C<channel>,<angle>
    char* comma = strchr(data, ',');
    if (comma != NULL) {
      *comma = '\0';
      int ch = atoi(data);
      int angle = atoi(comma + 1);
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
        output.print("OK\n");
        return;
      }
    }
    output.print("E:INVALID_CHANNEL\n");
    break;
  }

  case 'P':
  case 'p':
    output.print("PONG\n");
    break;

  case 'G':
  case 'g': {
    // G<strength> — set grip strength (0-100)
    int str = atoi(data);
    gripStrength = constrain(str, 0, 100);
    updateGripLimits();
    Serial.print("[GRIP] Strength set to ");
    Serial.print(gripStrength);
    Serial.println("%");
    
    char resp[16];
    snprintf(resp, sizeof(resp), "OK:G%d\n", gripStrength);
    output.print(resp);
    break;
  }

  case 'I':
  case 'i': {
    // I<inv_thumb>,<inv_index>,<inv_middle>,<inv_ring>,<inv_pinky>,<inv_wrist>
    int vals[NUM_SERVOS];
    int idx = 0;
    char* token = strtok(data, ",");
    while (token != NULL && idx < NUM_SERVOS) {
      vals[idx++] = atoi(token);
      token = strtok(NULL, ",");
    }

    if (idx == NUM_SERVOS) {
      for (int i = 0; i < NUM_SERVOS; i++) {
        safetyInverted[i] = (vals[i] != 0);
      }
      updateGripLimits();
      output.print("OK\n");
    } else {
      output.print("E:INVALID_ARGS\n");
    }
    break;
  }

  case 'M':
  case 'm': {
    // M<min_thumb>,<min_index>,...
    int vals[NUM_SERVOS];
    int idx = 0;
    char* token = strtok(data, ",");
    while (token != NULL && idx < NUM_SERVOS) {
      vals[idx++] = atoi(token);
      token = strtok(NULL, ",");
    }

    if (idx == NUM_SERVOS) {
      for (int i = 0; i < NUM_SERVOS; i++) {
        safetyMin[i] = vals[i];
      }
      updateGripLimits();
      output.print("OK\n");
    } else {
      output.print("E:INVALID_ARGS\n");
    }
    break;
  }

  case 'X':
  case 'x': {
    // X<max_thumb>,<max_index>,...
    int vals[NUM_SERVOS];
    int idx = 0;
    char* token = strtok(data, ",");
    while (token != NULL && idx < NUM_SERVOS) {
      vals[idx++] = atoi(token);
      token = strtok(NULL, ",");
    }

    if (idx == NUM_SERVOS) {
      for (int i = 0; i < NUM_SERVOS; i++) {
        safetyMax[i] = vals[i];
      }
      updateGripLimits();
      output.print("OK\n");
    } else {
      output.print("E:INVALID_ARGS\n");
    }
    break;
  }

  case 'S':
  case 's': {
    // Return current angles and grip strength
    char resp[64];
    snprintf(resp, sizeof(resp), "A%d,%d,%d,%d,%d,%d,G%d\n", 
             currentAngle[0], currentAngle[1], currentAngle[2],
             currentAngle[3], currentAngle[4], currentAngle[5],
             gripStrength);
    output.print(resp);
    break;
  }

  default:
    output.print("E:UNKNOWN_CMD\n");
    break;
  }
}

/**
 * Read and process data from Serial.
 */
void handleSerial() {
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\n' || c == '\r') {
      if (serialBufferIdx > 0) {
        serialBuffer[serialBufferIdx] = '\0'; // Null terminate
        processCommand(serialBuffer, Serial);
        serialBufferIdx = 0;
      }
    } else {
      if (serialBufferIdx < (int)(sizeof(serialBuffer) - 1)) {
        serialBuffer[serialBufferIdx++] = c;
      } else {
        // Buffer overflow: clear buffer
        serialBufferIdx = 0;
      }
    }
  }
}

#if ENABLE_WIFI
/**
 * Read and process data from WiFi TCP client.
 */
void handleWiFi() {
  // Check for new client connection
  if (tcpServer.hasClient()) {
    if (!tcpClient || !tcpClient.connected()) {
      if (tcpClient) tcpClient.stop(); // close previous if any
      tcpClient = tcpServer.available();
      tcpClient.setNoDelay(true); // Disable Nagle's algorithm for lowest possible latency
      Serial.print("[WIFI] Client connected: ");
      Serial.println(tcpClient.remoteIP());
      wifiConnected = true;
      wifiBufferIdx = 0;
    } else {
      // Reject new client if one is already actively connected
      WiFiClient rejectClient = tcpServer.available();
      rejectClient.stop();
    }
  }

  // Handle client disconnection
  if (wifiConnected && tcpClient && !tcpClient.connected()) {
    Serial.println("[WIFI] Client disconnected");
    tcpClient.stop();
    wifiConnected = false;
  }

  // Read data from connected client
  if (tcpClient && (tcpClient.connected() || tcpClient.available())) {
    while (tcpClient.available()) {
      char c = (char)tcpClient.read();
      if (c == '\n' || c == '\r') {
        if (wifiBufferIdx > 0) {
          wifiBuffer[wifiBufferIdx] = '\0';
          processCommand(wifiBuffer, tcpClient);
          wifiBufferIdx = 0;
        }
      } else {
        if (wifiBufferIdx < (int)(sizeof(wifiBuffer) - 1)) {
          wifiBuffer[wifiBufferIdx++] = c;
        } else {
          wifiBufferIdx = 0; // Overflow handling
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
    digitalWrite(LED_PIN, HIGH); // Solid on
    return;
  } else if (WiFi.status() == WL_CONNECTED) {
    interval = 1000; // Slow blink — WiFi OK, no client
  } else {
    interval = 200; // Fast blink — no WiFi
  }
#else
  interval = 1000; // Slow blink — Serial only mode
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
  Wire.setClock(400000); // Optimize I2C speed to 400kHz for faster PWM updates
  pwm.begin();
  pwm.setPWMFreq(PWM_FREQ);
  delay(10);
  Serial.print("[OK] PCA9685 initialized (addr 0x");
  Serial.print(PCA9685_ADDR, HEX);
  Serial.println(")");

  // Initialize all servos to 90° (neutral)
  for (int i = 0; i < NUM_SERVOS; i++) {
    setServoImmediate(servoChannels[i], 90);
    Serial.print("[OK] Servo CH");
    Serial.print(servoChannels[i]);
    Serial.println(" -> 90");
  }

  // Initialize grip protection
  gripStrength = 100; // Default: FIRM mode (full range)
  updateGripLimits();
  Serial.print("[OK] Grip protection active (strength: ");
  Serial.print(gripStrength);
  Serial.println("%)");

#if ENABLE_CURRENT_SENSE
  pinMode(CURRENT_SENSE_PIN, INPUT);
  analogSetAttenuation(ADC_11db); // Full 0-3.3V range
  Serial.print("[OK] Current sensing enabled on GPIO ");
  Serial.println(CURRENT_SENSE_PIN);
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
    Serial.print("[WIFI] TCP server started on port ");
    Serial.println(TCP_PORT);
    Serial.print("[WIFI] Set ESP32_IP in Python config.py to: ");
    Serial.println(WiFi.localIP());
  } else {
    Serial.println();
    Serial.println("[WIFI] Connection failed — continuing with Serial only");
  }
#else
  Serial.println("[INFO] WiFi disabled — Serial only mode");
#endif

  Serial.println();
  Serial.println("[READY] Listening for commands...");
  Serial.println(
      "  Protocol: F<t>,<i>,<m>,<r>,<p>,<w>  C<ch>,<angle>  G<str>  P  S");
  Serial.print("  Grip: strength=");
  Serial.print(gripStrength);
  Serial.print("% compliance=");
  Serial.print(COMPLIANCE_ZONE_DEG);
  Serial.println("deg");
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