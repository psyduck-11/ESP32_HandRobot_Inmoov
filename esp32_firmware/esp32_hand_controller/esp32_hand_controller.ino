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
 *   5V 20A Adapter   →  PCA9685 V+ (servo power)
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

<<<<<<< HEAD
// ======================== GLOBALS ==================================

Adafruit_PWMServoDriver pca = Adafruit_PWMServoDriver(PCA9685_ADDR);
=======
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
>>>>>>> a4bbd299d7136c62fb48ec74b9faf694e9d41bad

// ======================== HELPER FUNCTIONS =========================

/**
<<<<<<< HEAD
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
=======
 * Set a servo to a specific angle immediately (no smoothing).
 * Optimized to compute PWM inline using pure integer arithmetic.
 */
inline void setServoImmediate(int channel, int angle) {
  int pwmVal = (angle * (SERVO_MAX_TICK - SERVO_MIN_TICK)) / 180 + SERVO_MIN_TICK;
  pwm.setPWM(channel, 0, pwmVal);
>>>>>>> a4bbd299d7136c62fb48ec74b9faf694e9d41bad
}

/**
 * Check whether a channel is in the allowed SERVO_CHANNELS list.
 */
bool isValidChannel(uint8_t ch) {
  for (int i = 0; i < NUM_SERVOS; i++) {
<<<<<<< HEAD
    if (SERVO_CHANNELS[i] == ch) return true;
=======
    // Apply grip strength limit: cap target angle
    int effectiveTarget = targetAngle[i];
    if (effectiveTarget > maxServoAngle[i]) {
      effectiveTarget = maxServoAngle[i];
    }

    // Fast-path skip: don't evaluate if already at target or stalled
    if (stallDetected[i] || currentAngle[i] == effectiveTarget) {
      continue;
    }

    int diff = effectiveTarget - currentAngle[i];

#if SERVO_SPEED_LIMIT > 0
    int speedLimit = SERVO_SPEED_LIMIT;

    // Apply compliance when closing (diff > 0)
    if (diff > 0 && COMPLIANCE_ZONE_DEG > 0) {
      if (diff <= COMPLIANCE_ZONE_DEG) {
        // Linearly reduce speed as we approach the target
        int scaledSpeed = COMPLIANCE_MIN_SPEED + 
          (diff * (SERVO_SPEED_LIMIT - COMPLIANCE_MIN_SPEED)) / COMPLIANCE_ZONE_DEG;
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
    if (currentAngle[i] < ANGLE_MIN) currentAngle[i] = ANGLE_MIN;
    else if (currentAngle[i] > ANGLE_MAX) currentAngle[i] = ANGLE_MAX;
    
    setServoImmediate(servoChannels[i], currentAngle[i]);
>>>>>>> a4bbd299d7136c62fb48ec74b9faf694e9d41bad
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

<<<<<<< HEAD
// ======================== SETUP ====================================
=======
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
        if (currentAngle[i] > ANGLE_MIN) {
          int backoffTarget = currentAngle[i] - STALL_BACKOFF_DEG;
          targetAngle[i] = backoffTarget > ANGLE_MIN ? backoffTarget : ANGLE_MIN;
          stallDetected[i] = true;
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
        targetAngle[i] = constrain(vals[i], ANGLE_MIN, ANGLE_MAX);
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
>>>>>>> a4bbd299d7136c62fb48ec74b9faf694e9d41bad

void setup() {
  Serial.begin(115200);
  while (!Serial) { delay(10); }
  Serial.println();
  Serial.println("========================================");
  Serial.println("  ESP32 + PCA9685  Servo Reset Utility  ");
  Serial.println("========================================");

  // Initialise I2C with custom pins (ESP32)
  Wire.begin(SDA_PIN, SCL_PIN);

<<<<<<< HEAD
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
=======
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
  gripStrength = 75; // Default: NORMAL mode
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
>>>>>>> a4bbd299d7136c62fb48ec74b9faf694e9d41bad

  // Reset servo CH5 to demanded angle on boot
  Serial.println();
<<<<<<< HEAD
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
=======
  Serial.println("[READY] Listening for commands...");
  Serial.println(
      "  Protocol: F<t>,<i>,<m>,<r>,<p>,<w>  C<ch>,<angle>  G<str>  P  S");
  Serial.print("  Grip: strength=");
  Serial.print(gripStrength);
  Serial.print("% compliance=");
  Serial.print(COMPLIANCE_ZONE_DEG);
  Serial.println("deg");
  Serial.println("========================================");
>>>>>>> a4bbd299d7136c62fb48ec74b9faf694e9d41bad
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
