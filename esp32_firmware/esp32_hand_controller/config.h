/*
 * InMoov Hand Controller — ESP32 Configuration
 * Adjust these values for your hardware setup.
 *
 * References:
 *   Hardware Datasheets:
 *     - ESP32 Technical Reference Manual:
 *         https://www.espressif.com/sites/default/files/documentation/esp32_technical_reference_manual_en.pdf
 *     - ESP32 Datasheet (pinout, electrical characteristics):
 *         https://www.espressif.com/sites/default/files/documentation/esp32_datasheet_en.pdf
 *     - PCA9685 16-Ch 12-bit PWM Driver Datasheet (NXP):
 *         https://www.nxp.com/docs/en/data-sheet/PCA9685.pdf
 *     - MG996R Metal Gear Servo Datasheet (Tower Pro):
 *         https://www.electronicoscaldas.com/datasheet/MG996R_Tower-Pro.pdf
 *     - Adafruit PCA9685 Breakout Guide (wiring, I2C address):
 *         https://learn.adafruit.com/16-channel-pwm-servo-driver/overview
 *
 *   PWM / Servo Timing:
 *     - PCA9685 PWM frequency and resolution (50 Hz, 12-bit = 4096 ticks):
 *         See PCA9685 datasheet Section 7.3.5, "PRE_SCALE register"
 *     - MG996R pulse width range (500–2500 µs):
 *         See MG996R datasheet "Control System" section
 *     - Servo PWM fundamentals:
 *         https://www.servocity.com/how-do-servos-work/
 *
 *   I2C Protocol:
 *     - ESP32 I2C Master (Wire library, SDA=GPIO21, SCL=GPIO22):
 *         https://docs.espressif.com/projects/arduino-esp32/en/latest/api/i2c.html
 *     - I2C Fast Mode (400 kHz):
 *         https://www.nxp.com/docs/en/user-guide/UM10204.pdf
 *
 *   WiFi:
 *     - ESP32 Arduino WiFi library:
 *         https://docs.espressif.com/projects/arduino-esp32/en/latest/api/wifi.html
 *     - ESP32 WiFi modes (Station mode for this project):
 *         https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/network/esp_wifi.html
 *
 *   Current Sensing (optional):
 *     - ESP32 ADC (12-bit, GPIO34 input-only, attenuation):
 *         https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/peripherals/adc_oneshot.html
 *     - INA219 Current Sensor Breakout (Adafruit):
 *         https://learn.adafruit.com/adafruit-ina219-current-sensor-breakout
 */

#ifndef CONFIG_H
#define CONFIG_H

// =============================================================================
//  WiFi Settings (for wireless mode)
// =============================================================================
#define WIFI_SSID     "Hai Anh"        // Change to your WiFi network name
#define WIFI_PASSWORD "11112007"      // Change to your WiFi password
#define TCP_PORT      8080                      // TCP server port

// Set to true to enable WiFi TCP server (in addition to Serial)
#define ENABLE_WIFI   true

// =============================================================================
//  I2C & PCA9685 Settings
// =============================================================================
#define PCA9685_ADDR  0x40     // Default I2C address
#define I2C_SDA       21       // ESP32 default SDA pin
#define I2C_SCL       22       // ESP32 default SCL pin
#define I2C_CLOCK     400000   // I2C clock speed (Hz) — 400kHz Fast Mode for PCA9685
#define PWM_FREQ      50       // Servo PWM frequency (Hz) — standard is 50Hz

// =============================================================================
//  MG996R Servo Pulse Width (PCA9685 tick values at 50Hz, 12-bit)
//  At 50Hz: period = 20ms, 4096 ticks per period
//  1 tick ≈ 4.88µs
//  MG996R typical range: 500µs–2500µs → ~102–512 ticks
//  Adjust these if servos don't reach full range or go past limits
// =============================================================================
#define SERVO_MIN_TICK   102   // Pulse for 0° (≈500µs)
#define SERVO_MAX_TICK   512   // Pulse for 180° (≈2500µs)

// =============================================================================
//  Servo Channel Assignments (PCA9685 channels 0–15)
// =============================================================================
#define CH_THUMB   0
#define CH_INDEX   1
#define CH_MIDDLE  2
#define CH_RING    3
#define CH_PINKY   4
#define CH_WRIST   5
#define NUM_SERVOS 6

// =============================================================================
//  Servo Safety Limits (degrees) — prevents mechanical damage
// =============================================================================
#define ANGLE_MIN  0
#define ANGLE_MAX  180

// =============================================================================
//  Smooth Movement Settings
// =============================================================================
// Maximum degrees a servo can move per update cycle
// Lower = smoother but slower response. Set 0 to disable smoothing.
#define SERVO_SPEED_LIMIT  8

// Update interval in milliseconds
#define UPDATE_INTERVAL_MS 20

// Anti-shaking: ignore target changes smaller than this many degrees.
// Prevents micro-PWM updates from causing servo buzzing/oscillation.
// Set 0 to disable. Recommended: 2 for MG996R.
#define SERVO_DEADBAND_DEG  2

// =============================================================================
//  Grip Protection / Compliance Settings
// =============================================================================
// Compliance zone: servos progressively slow down when within this many
// degrees of their target angle while closing. Prevents sudden force spikes.
#define COMPLIANCE_ZONE_DEG   20

// Minimum speed (degrees/update) when in compliance zone (1 = very gentle)
#define COMPLIANCE_MIN_SPEED  1

// =============================================================================
//  Current Sensing (Optional — requires hardware)
//  Connect a shunt resistor (0.1Ω) + INA219 or simple voltage divider
//  on the servo power line to an ESP32 ADC pin.
//  When current exceeds threshold, servo backs off automatically.
// =============================================================================
// Set to true to enable current-based stall detection
#define ENABLE_CURRENT_SENSE  false

// ESP32 ADC pin for current sensing (GPIO 34 = ADC1_CH6, input-only pin)
#define CURRENT_SENSE_PIN     34

// Current threshold in raw ADC units (12-bit: 0-4095).
// Calibrate this: measure ADC value when servo is stalling vs free-running.
// Default ~2000 assumes a 0.1Ω shunt with voltage divider giving ~1.6V at stall.
#define CURRENT_STALL_ADC     2000

// How many degrees to back off when stall detected
#define STALL_BACKOFF_DEG     15

// How many consecutive high-current readings before triggering backoff
#define STALL_DEBOUNCE_COUNT  5

// =============================================================================
//  Serial Settings
// =============================================================================
#define SERIAL_BAUD  115200

// =============================================================================
//  Status LED (built-in LED on most ESP32 boards)
// =============================================================================
#define LED_PIN  2   // Built-in LED on ESP32 DevKit

#endif // CONFIG_H
