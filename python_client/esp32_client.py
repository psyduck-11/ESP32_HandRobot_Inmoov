"""
ESP32 Communication Module — Serial and WiFi TCP client.
Sends servo commands to ESP32 using a compact text protocol.

Protocol:
    F<thumb>,<index>,<middle>,<ring>,<pinky>,<wrist>\n   — Set all servos
    C<channel>,<angle>\n                                   — Set single servo (calibration)
    P\n                                                    — Ping (expects "PONG\n")
    S\n                                                    — Query status

References:
  Serial Communication:
    - PySerial Library Documentation:
        https://pyserial.readthedocs.io/en/latest/
    - PySerial API Reference (Serial class):
        https://pyserial.readthedocs.io/en/latest/pyserial_api.html
    - ESP32 UART/USB-Serial (CH340 driver):
        https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-reference/peripherals/uart.html

  TCP/WiFi Communication:
    - Python socket module — TCP client programming:
        https://docs.python.org/3/library/socket.html
    - TCP_NODELAY / Nagle's algorithm (low-latency real-time control):
        https://en.wikipedia.org/wiki/Nagle%27s_algorithm
    - ESP32 WiFi TCP Server (Arduino WiFi library):
        https://docs.espressif.com/projects/arduino-esp32/en/latest/api/wifi.html

  Design Patterns:
    - Python ABC (Abstract Base Classes) — BaseClient pattern:
        https://docs.python.org/3/library/abc.html
    - Rate limiting / token bucket (send rate control):
        https://en.wikipedia.org/wiki/Token_bucket
"""

import time
import threading
import socket
from abc import ABC, abstractmethod

import config


class BaseClient(ABC):
    """Abstract base for ESP32 communication."""

    def __init__(self):
        self._connected = False
        self._lock = threading.Lock()
        self._last_send_time = 0
        self._send_interval = 1.0 / config.SEND_RATE_HZ
        self._last_angles = {}

    @property
    def connected(self) -> bool:
        return self._connected

    @abstractmethod
    def connect(self) -> bool:
        """Attempt to connect. Returns True on success."""
        pass

    @abstractmethod
    def disconnect(self):
        """Close the connection."""
        pass

    @abstractmethod
    def _send_raw(self, data: str):
        """Send raw string data to ESP32."""
        pass

    @abstractmethod
    def _read_line(self, timeout: float = 0.5) -> str:
        """Read a line from ESP32. Returns empty string on timeout."""
        pass

    def send_all_servos(self, angles: dict, force: bool = False):
        """
        Send all servo angles to ESP32.

        Args:
            angles: Dict with keys (thumb, index, middle, ring, pinky, wrist)
                    and int values 0–180.
            force:  If True, bypass rate limiting and deadband checks.
        """
        if not self._connected:
            return

        if not force:
            # Rate limiting
            now = time.time()
            if now - self._last_send_time < self._send_interval:
                return

            # Deadband check: skip if nothing changed significantly
            # Only compare keys that exist in both dicts to avoid false triggers
            if self._last_angles:
                common_keys = set(angles) & set(self._last_angles)
                if common_keys:
                    max_change = max(
                        abs(angles[k] - self._last_angles[k])
                        for k in common_keys
                    )
                    if max_change < config.DEADBAND_DEGREES:
                        return

        # Build command string
        t = int(angles.get("thumb", 90))
        i = int(angles.get("index", 90))
        m = int(angles.get("middle", 90))
        r = int(angles.get("ring", 90))
        p = int(angles.get("pinky", 90))
        w = int(angles.get("wrist", 90))

        cmd = f"F{t},{i},{m},{r},{p},{w}\n"

        now = time.time()
        with self._lock:
            try:
                self._send_raw(cmd)
                self._last_send_time = now
                self._last_angles = dict(angles)
            except Exception as e:
                print(f"[COMM] Send error: {e}")
                self._connected = False

    def send_single_servo(self, channel: int, angle: int):
        """
        Send a single servo command (for calibration).

        Args:
            channel: PCA9685 channel (0–15)
            angle: Servo angle (0–180)
        """
        if not self._connected:
            return

        cmd = f"C{channel},{angle}\n"
        with self._lock:
            try:
                self._send_raw(cmd)
            except Exception as e:
                print(f"[COMM] Send error: {e}")
                self._connected = False

    def ping(self) -> bool:
        """Send ping, return True if PONG received."""
        if not self._connected:
            return False

        with self._lock:
            try:
                self._send_raw("P\n")
                response = self._read_line(timeout=1.0)
                return response.strip() == "PONG"
            except Exception:
                self._connected = False
                return False

    def sync_config(self):
        """Send configuration to ESP32: Inversion, Min, Max."""
        if not self._connected:
            return

        fingers = ["thumb", "index", "middle", "ring", "pinky", "wrist"]
        
        # Send Inversions (I command)
        invs = [1 if config.SERVO_INVERTED[f] else 0 for f in fingers]
        cmd_i = f"I{invs[0]},{invs[1]},{invs[2]},{invs[3]},{invs[4]},{invs[5]}\n"
        
        # Send Min angles (M command)
        mins = [config.SERVO_MIN[f] for f in fingers]
        cmd_m = f"M{mins[0]},{mins[1]},{mins[2]},{mins[3]},{mins[4]},{mins[5]}\n"
        
        # Send Max angles (X command)
        maxs = [config.SERVO_MAX[f] for f in fingers]
        cmd_x = f"X{maxs[0]},{maxs[1]},{maxs[2]},{maxs[3]},{maxs[4]},{maxs[5]}\n"
        
        with self._lock:
            try:
                self._send_raw(cmd_i)
                self._read_line(timeout=0.2)
                self._send_raw(cmd_m)
                self._read_line(timeout=0.2)
                self._send_raw(cmd_x)
                self._read_line(timeout=0.2)
            except Exception as e:
                print(f"[COMM] Sync error: {e}")
                self._connected = False

    def set_grip_strength(self, strength: int):
        """Send grip strength limit to ESP32."""
        if not self._connected:
            return
            
        cmd = f"G{strength}\n"
        with self._lock:
            try:
                self._send_raw(cmd)
                self._read_line(timeout=0.2)
            except Exception as e:
                print(f"[COMM] Send error: {e}")
                self._connected = False


class SerialClient(BaseClient):
    """USB Serial connection to ESP32."""

    def __init__(self):
        super().__init__()
        self._serial = None

    def connect(self) -> bool:
        try:
            import serial
            import serial.tools.list_ports
            self._serial = serial.Serial(
                port=config.SERIAL_PORT,
                baudrate=config.SERIAL_BAUD,
                timeout=1.0,
                write_timeout=1.0,
            )
            time.sleep(2)  # Wait for ESP32 to reset after serial connection
            # Flush any startup messages
            self._serial.reset_input_buffer()
            self._connected = True
            print(f"[SERIAL] Connected to {config.SERIAL_PORT} @ {config.SERIAL_BAUD} baud")
            return True
        except Exception as e:
            print(f"[SERIAL] Connection failed: {e}")
            try:
                import serial.tools.list_ports
                ports = list(serial.tools.list_ports.comports())
                if ports:
                    print(f"[SERIAL] Available ports:")
                    for p in ports:
                        print(f"         {p.device} — {p.description}")
                else:
                    print(f"[SERIAL] No COM ports found — is the ESP32 plugged in?")
            except Exception:
                pass
            self._connected = False
            return False

    def disconnect(self):
        if self._serial and self._serial.is_open:
            self._serial.close()
        self._connected = False
        print("[SERIAL] Disconnected")

    def _send_raw(self, data: str):
        if self._serial and self._serial.is_open:
            self._serial.write(data.encode('utf-8'))

    def _read_line(self, timeout: float = 0.5) -> str:
        if self._serial and self._serial.is_open:
            self._serial.timeout = timeout
            line = self._serial.readline()
            return line.decode('utf-8', errors='ignore')
        return ""


class WiFiClient(BaseClient):
    """WiFi TCP socket connection to ESP32."""

    def __init__(self):
        super().__init__()
        self._socket = None
        self._recv_buffer = ""

    def connect(self) -> bool:
        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.settimeout(5.0)
            self._socket.connect((config.ESP32_IP, config.ESP32_PORT))
            self._socket.settimeout(0.5)
            self._connected = True
            print(f"[WIFI] Connected to {config.ESP32_IP}:{config.ESP32_PORT}")
            return True
        except Exception as e:
            print(f"[WIFI] Connection failed: {e}")
            self._connected = False
            return False

    def disconnect(self):
        if self._socket:
            try:
                self._socket.close()
            except Exception:
                pass
        self._connected = False
        print("[WIFI] Disconnected")

    def _send_raw(self, data: str):
        if self._socket:
            self._socket.sendall(data.encode('utf-8'))

    def _read_line(self, timeout: float = 0.5) -> str:
        if not self._socket:
            return ""

        self._socket.settimeout(timeout)
        try:
            while '\n' not in self._recv_buffer:
                chunk = self._socket.recv(256).decode('utf-8', errors='ignore')
                if not chunk:
                    self._connected = False
                    return ""
                self._recv_buffer += chunk
                # Prevent unbounded buffering on malformed data
                if len(self._recv_buffer) > 1024:
                    self._recv_buffer = ""
                    return ""

            line, self._recv_buffer = self._recv_buffer.split('\n', 1)
            return line + '\n'
        except socket.timeout:
            return ""
        except Exception:
            self._connected = False
            return ""


def create_client() -> BaseClient:
    """
    Factory function — creates the appropriate client based on config.COMM_MODE.
    """
    if config.COMM_MODE.lower() == "wifi":
        return WiFiClient()
    else:
        return SerialClient()
