/*
 * InMoov Hand Controller — ESP32 Configuration
 * Adjust these values for your hardware setup.
 */

#ifndef CONFIG_H
#define CONFIG_H

// =============================================================================
//  WiFi Settings (for wireless mode)
// =============================================================================
#define WIFI_SSID     "YOUR_WIFI_SSID"        // Change to your WiFi network name
#define WIFI_PASSWORD "YOUR_WIFI_PASSWORD"      // Change to your WiFi password
#define TCP_PORT      8080                      // TCP server port

// Set to true to enable WiFi TCP server (in addition to Serial)
#define ENABLE_WIFI   false

// =============================================================================
//  I2C & PCA9685 Settings
// =============================================================================
#define PCA9685_ADDR  0x40     // Default I2C address
#define I2C_SDA       21       // ESP32 default SDA pin
#define I2C_SCL       22       // ESP32 default SCL pin
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
