"""
ESP32 Communication Module — Serial and WiFi TCP client.
Sends servo commands to ESP32 using a compact text protocol.

Protocol:
    F<thumb>,<index>,<middle>,<ring>,<pinky>,<wrist>\n   — Set all servos
    C<channel>,<angle>\n                                   — Set single servo (calibration)
    P\n                                                    — Ping (expects "PONG\n")
    S\n                                                    — Query status
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

    def send_all_servos(self, angles: dict):
        """
        Send all servo angles to ESP32.

        Args:
            angles: Dict with keys (thumb, index, middle, ring, pinky, wrist)
                    and int values 0–180.
        """
        if not self._connected:
            return

        # Rate limiting
        now = time.time()
        if now - self._last_send_time < self._send_interval:
            return

        # Deadband check: skip if nothing changed significantly
        if self._last_angles:
            max_change = max(
                abs(angles.get(k, 0) - self._last_angles.get(k, 0))
                for k in angles
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


class SerialClient(BaseClient):
    """USB Serial connection to ESP32."""

    def __init__(self):
        super().__init__()
        self._serial = None

    def connect(self) -> bool:
        try:
            import serial
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
