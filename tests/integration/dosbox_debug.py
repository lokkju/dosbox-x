"""
Simple GDB and QMP client implementations for DOSBox-X integration tests.

This module provides lightweight client implementations that don't rely on
external dependencies, avoiding issues with third-party libraries.
"""

import json
import socket
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Optional, Union


class GDBError(Exception):
    """GDB protocol error."""
    pass


class QMPError(Exception):
    """QMP protocol error."""
    pass


@dataclass
class Registers:
    """CPU registers from GDB."""
    eax: int = 0
    ecx: int = 0
    edx: int = 0
    ebx: int = 0
    esp: int = 0
    ebp: int = 0
    esi: int = 0
    edi: int = 0
    eip: int = 0
    eflags: int = 0
    cs: int = 0
    ss: int = 0
    ds: int = 0
    es: int = 0
    fs: int = 0
    gs: int = 0

    def __getitem__(self, key):
        """Allow dict-like access for compatibility."""
        return getattr(self, key)

    def get(self, key, default=None):
        """Allow dict-like get() for compatibility."""
        return getattr(self, key, default)

    def keys(self):
        """Return register names."""
        return ["eax", "ecx", "edx", "ebx", "esp", "ebp", "esi", "edi",
                "eip", "eflags", "cs", "ss", "ds", "es", "fs", "gs"]


class GDBClient:
    """Simple GDB Remote Serial Protocol client."""

    def __init__(self, host: str = "localhost", port: int = 2159, timeout: float = 5.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._socket: Optional[socket.socket] = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def connect(self):
        """Connect to the GDB server."""
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.settimeout(self.timeout)
        self._socket.connect((self.host, self.port))

    def close(self):
        """Close the connection."""
        if self._socket:
            try:
                # Send detach before closing
                self._send_packet("D")
            except:
                pass
            self._socket.close()
            self._socket = None

    def _checksum(self, data: str) -> int:
        """Calculate GDB packet checksum."""
        return sum(ord(c) for c in data) % 256

    def _send_packet(self, data: str) -> str:
        """Send a GDB packet and receive response."""
        if not self._socket:
            raise GDBError("Not connected")

        # Build packet: $data#checksum
        checksum = self._checksum(data)
        packet = f"${data}#{checksum:02x}"
        self._socket.send(packet.encode())

        # Read response
        response = b""
        while True:
            chunk = self._socket.recv(4096)
            if not chunk:
                break
            response += chunk
            # Look for end of packet
            if b"#" in response:
                # Check if we have the full checksum
                idx = response.rfind(b"#")
                if len(response) >= idx + 3:
                    break

        response_str = response.decode()

        # Strip ACK if present
        if response_str.startswith("+"):
            response_str = response_str[1:]

        # Parse packet
        if response_str.startswith("$") and "#" in response_str:
            # Extract data between $ and #
            start = response_str.index("$") + 1
            end = response_str.rindex("#")
            return response_str[start:end]

        return response_str

    def halt(self) -> str:
        """Send halt/break signal (Ctrl+C)."""
        if not self._socket:
            raise GDBError("Not connected")
        # Send break character
        self._socket.send(b"\x03")
        time.sleep(0.1)
        # Read stop reply
        response = self._socket.recv(4096).decode()
        if response.startswith("+"):
            response = response[1:]
        if "$" in response and "#" in response:
            start = response.index("$") + 1
            end = response.rindex("#")
            return response[start:end]
        return response

    def enable_no_ack_mode(self) -> bool:
        """Request no-ack mode (QStartNoAckMode)."""
        response = self._send_packet("QStartNoAckMode")
        return response == "OK"

    def query_halt_reason(self) -> str:
        """Query why the target halted."""
        return self._send_packet("?")

    def read_registers(self) -> Registers:
        """Read all CPU registers."""
        response = self._send_packet("g")

        if response.startswith("E"):
            raise GDBError(f"Error reading registers: {response}")

        # Parse 32-bit registers (8 hex chars each)
        # Order: EAX, ECX, EDX, EBX, ESP, EBP, ESI, EDI, EIP, EFLAGS, CS, SS, DS, ES, FS, GS
        def get_reg(offset: int, size: int = 8) -> int:
            hex_str = response[offset:offset + size]
            if len(hex_str) < size:
                return 0
            # GDB sends little-endian, need to swap bytes
            bytes_list = [hex_str[i:i+2] for i in range(0, len(hex_str), 2)]
            bytes_list.reverse()
            return int("".join(bytes_list), 16)

        return Registers(
            eax=get_reg(0),
            ecx=get_reg(8),
            edx=get_reg(16),
            ebx=get_reg(24),
            esp=get_reg(32),
            ebp=get_reg(40),
            esi=get_reg(48),
            edi=get_reg(56),
            eip=get_reg(64),
            eflags=get_reg(72),
            cs=get_reg(80),
            ss=get_reg(88),
            ds=get_reg(96),
            es=get_reg(104),
            fs=get_reg(112),
            gs=get_reg(120),
        )

    def read_register(self, reg_num: int) -> int:
        """Read a single register by index.

        Args:
            reg_num: Register index (0=EAX, 1=ECX, ..., 8=EIP, 9=EFLAGS, 10-15=segments)
        """
        response = self._send_packet(f"p{reg_num:x}")

        if response.startswith("E"):
            raise GDBError(f"Error reading register {reg_num}: {response}")

        # GDB sends little-endian hex, need to swap bytes
        if len(response) >= 2:
            bytes_list = [response[i:i+2] for i in range(0, len(response), 2)]
            bytes_list.reverse()
            return int("".join(bytes_list), 16)
        return 0

    def read_memory(self, addr: Union[int, str], size: int) -> bytes:
        """Read memory from target.

        Args:
            addr: Linear address (int) or seg:off string (e.g., "b800:0000")
            size: Number of bytes to read
        """
        if isinstance(addr, str) and ":" in addr:
            # Convert seg:off to linear
            seg, off = addr.split(":")
            addr = (int(seg, 16) << 4) + int(off, 16)

        response = self._send_packet(f"m{addr:x},{size:x}")

        if response.startswith("E"):
            raise GDBError(f"Error reading memory: {response}")

        # Convert hex string to bytes
        return bytes.fromhex(response)

    def write_memory(self, addr: Union[int, str], data: bytes) -> bool:
        """Write memory to target.

        Args:
            addr: Linear address (int) or seg:off string
            data: Bytes to write
        """
        if isinstance(addr, str) and ":" in addr:
            seg, off = addr.split(":")
            addr = (int(seg, 16) << 4) + int(off, 16)

        hex_data = data.hex()
        response = self._send_packet(f"M{addr:x},{len(data):x}:{hex_data}")

        return response == "OK"

    def set_breakpoint(self, addr: Union[int, str]) -> bool:
        """Set a software breakpoint.

        Args:
            addr: Linear address (int) or seg:off string
        """
        if isinstance(addr, str) and ":" in addr:
            seg, off = addr.split(":")
            addr = (int(seg, 16) << 4) + int(off, 16)

        # Z0 = software breakpoint, kind=1 for x86
        response = self._send_packet(f"Z0,{addr:x},1")
        return response == "OK"

    def remove_breakpoint(self, addr: Union[int, str]) -> bool:
        """Remove a software breakpoint."""
        if isinstance(addr, str) and ":" in addr:
            seg, off = addr.split(":")
            addr = (int(seg, 16) << 4) + int(off, 16)

        response = self._send_packet(f"z0,{addr:x},1")
        return response == "OK"

    def step(self) -> str:
        """Single step execution."""
        return self._send_packet("s")

    def continue_(self) -> str:
        """Continue execution."""
        return self._send_packet("c")

    def detach(self) -> str:
        """Detach from target."""
        return self._send_packet("D")


class QMPClient:
    """Simple QMP (QEMU Monitor Protocol) client."""

    def __init__(self, host: str = "localhost", port: int = 4444, timeout: float = 5.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._socket: Optional[socket.socket] = None
        self._connected = False

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def connect(self):
        """Connect to the QMP server and negotiate capabilities."""
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._socket.settimeout(self.timeout)
        self._socket.connect((self.host, self.port))

        # Read greeting
        greeting = self._recv_json()
        if "QMP" not in greeting:
            raise QMPError(f"Invalid QMP greeting: {greeting}")

        # Send capabilities negotiation
        self._send_command("qmp_capabilities")
        self._connected = True

    def close(self):
        """Close the connection."""
        if self._socket:
            self._socket.close()
            self._socket = None
        self._connected = False

    def _recv_json(self) -> dict:
        """Receive a JSON response."""
        if not self._socket:
            raise QMPError("Not connected")

        data = b""
        while True:
            chunk = self._socket.recv(4096)
            if not chunk:
                break
            data += chunk
            # Try to parse JSON
            try:
                return json.loads(data.decode())
            except json.JSONDecodeError:
                continue

        raise QMPError(f"Failed to receive valid JSON: {data}")

    def _send_command(self, command: str, arguments: dict = None) -> dict:
        """Send a QMP command and return the response."""
        if not self._socket:
            raise QMPError("Not connected")

        msg = {"execute": command}
        if arguments:
            msg["arguments"] = arguments

        self._socket.send((json.dumps(msg) + "\n").encode())
        return self._recv_json()

    def send_key(self, keys: list, hold_time: int = 100) -> dict:
        """Send key press via send-key command.

        Args:
            keys: List of key names (qcodes)
            hold_time: Hold time in milliseconds
        """
        key_objects = [{"type": "qcode", "data": k} for k in keys]
        return self._send_command("send-key", {
            "keys": key_objects,
            "hold-time": hold_time
        })

    def input_send_event(self, events: list) -> dict:
        """Send input events via input-send-event command."""
        return self._send_command("input-send-event", {"events": events})

    def query_commands(self) -> list:
        """Query available commands."""
        result = self._send_command("query-commands")
        return result.get("return", [])

    def key_down(self, key: str) -> dict:
        """Press a key down (without releasing)."""
        return self.input_send_event([{
            "type": "key",
            "data": {"down": True, "key": {"type": "qcode", "data": key}}
        }])

    def key_up(self, key: str) -> dict:
        """Release a key."""
        return self.input_send_event([{
            "type": "key",
            "data": {"down": False, "key": {"type": "qcode", "data": key}}
        }])

    def key_press(self, key: str, hold_time: float = 0.1) -> dict:
        """Press and release a key with hold time.

        Args:
            key: Key qcode name
            hold_time: Time in seconds to hold key
        """
        self.key_down(key)
        time.sleep(hold_time)
        return self.key_up(key)

    def type_text(self, text: str, delay: float = 0.05):
        """Type text character by character.

        This implementation sends each character separately with a delay,
        which is more reliable than batching.
        """
        # Mapping for special characters
        special_keys = {
            " ": "spc",
            "\n": "ret",
            "\t": "tab",
            ".": "dot",
            ",": "comma",
            ";": "semicolon",
            "'": "apostrophe",
            "`": "grave_accent",
            "-": "minus",
            "=": "equal",
            "[": "bracket_left",
            "]": "bracket_right",
            "\\": "backslash",
            "/": "slash",
        }

        shift_keys = {
            "!": "1", "@": "2", "#": "3", "$": "4", "%": "5",
            "^": "6", "&": "7", "*": "8", "(": "9", ")": "0",
            "_": "minus", "+": "equal", "{": "bracket_left",
            "}": "bracket_right", "|": "backslash", ":": "semicolon",
            '"': "apostrophe", "<": "comma", ">": "dot", "?": "slash",
            "~": "grave_accent",
        }

        for char in text:
            keys = []

            if char in special_keys:
                keys = [special_keys[char]]
            elif char in shift_keys:
                keys = ["shift", shift_keys[char]]
            elif char.isupper():
                keys = ["shift", char.lower()]
            elif char.isalnum():
                keys = [char.lower()]
            else:
                # Skip unknown characters
                continue

            self.send_key(keys)
            time.sleep(delay)

    def debug_break_on_exec(self, enabled: bool) -> dict:
        """Enable/disable debug-break-on-exec."""
        return self._send_command("debug-break-on-exec", {"enabled": enabled})

    def query_status(self) -> dict:
        """Query emulator status."""
        return self._send_command("query-status")

    def stop(self) -> dict:
        """Stop/pause the emulator."""
        return self._send_command("stop")

    def cont(self) -> dict:
        """Continue/resume the emulator."""
        return self._send_command("cont")


@contextmanager
def gdb_connection(host: str = "localhost", port: int = 2159, timeout: float = 5.0):
    """Context manager for GDB connection with automatic cleanup."""
    client = GDBClient(host=host, port=port, timeout=timeout)
    try:
        client.connect()
        yield client
    finally:
        client.close()


@contextmanager
def qmp_connection(host: str = "localhost", port: int = 4444, timeout: float = 5.0):
    """Context manager for QMP connection with automatic cleanup."""
    client = QMPClient(host=host, port=port, timeout=timeout)
    try:
        client.connect()
        yield client
    finally:
        client.close()


# =============================================================================
# Video Tools
# =============================================================================

@dataclass
class VGAAttribute:
    """Decoded VGA text mode attribute byte."""
    foreground: int
    background: int
    bright: bool
    blink: bool

    @property
    def fg_color(self) -> str:
        """Get foreground color name."""
        colors = ["black", "blue", "green", "cyan", "red", "magenta", "brown", "white"]
        base = self.foreground & 0x07
        return colors[base]

    @property
    def bg_color(self) -> str:
        """Get background color name."""
        colors = ["black", "blue", "green", "cyan", "red", "magenta", "brown", "white"]
        return colors[self.background & 0x07]


def decode_vga_attribute(attr: int) -> VGAAttribute:
    """Decode a VGA text mode attribute byte.

    Attribute byte format:
    - Bits 0-2: Foreground color (0-7)
    - Bit 3: Bright/intensity
    - Bits 4-6: Background color (0-7)
    - Bit 7: Blink (or bright background if blink disabled)
    """
    return VGAAttribute(
        foreground=attr & 0x07,
        background=(attr >> 4) & 0x07,
        bright=bool(attr & 0x08),
        blink=bool(attr & 0x80),
    )


def format_attribute_info(attr: int) -> str:
    """Format VGA attribute as human-readable string."""
    info = decode_vga_attribute(attr)
    parts = [f"fg={info.fg_color}"]
    if info.bright:
        parts.append("bright")
    parts.append(f"bg={info.bg_color}")
    if info.blink:
        parts.append("blink")
    return " ".join(parts)


class DOSVideoTools:
    """Video memory access tools using GDB client."""

    # VGA text mode video memory
    VIDEO_MEM_ADDR = 0xB8000
    VIDEO_MEM_SIZE = 4000  # 80x25x2 bytes

    # BIOS data area addresses
    BIOS_TIMER_TICKS = 0x46C  # 32-bit timer tick count
    BIOS_VIDEO_MODE = 0x449  # Current video mode

    def __init__(self, host: str = "localhost", port: int = 2159, timeout: float = 5.0):
        self.host = host
        self.port = port
        self.timeout = timeout
        self._gdb: Optional[GDBClient] = None

    def __enter__(self):
        self._gdb = GDBClient(host=self.host, port=self.port, timeout=self.timeout)
        self._gdb.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._gdb:
            self._gdb.close()
            self._gdb = None
        return False

    def screen_raw(self) -> bytes:
        """Read raw video memory (character + attribute pairs)."""
        if not self._gdb:
            raise GDBError("Not connected")
        return self._gdb.read_memory(self.VIDEO_MEM_ADDR, self.VIDEO_MEM_SIZE)

    def screen_dump(self, width: int = 80, height: int = 25) -> list:
        """Read screen as list of text lines (characters only)."""
        raw = self.screen_raw()
        lines = []
        for row in range(height):
            line = ""
            for col in range(width):
                offset = (row * width + col) * 2
                if offset < len(raw):
                    char = raw[offset]
                    # Convert to printable character
                    if 32 <= char < 127:
                        line += chr(char)
                    else:
                        line += " "
            lines.append(line.rstrip())
        return lines

    def screen_dump_with_ticks(self, width: int = 80, height: int = 25) -> tuple:
        """Read screen and timer ticks atomically."""
        lines = self.screen_dump(width, height)
        ticks = self.read_timer_ticks()
        return lines, ticks

    def screen_debug(self, width: int = 80, height: int = 25) -> list:
        """Read screen with full debug info (char, attribute, decoded)."""
        raw = self.screen_raw()
        result = []
        for row in range(height):
            row_data = []
            for col in range(width):
                offset = (row * width + col) * 2
                if offset + 1 < len(raw):
                    char = raw[offset]
                    attr = raw[offset + 1]
                    row_data.append({
                        "char": chr(char) if 32 <= char < 127 else ".",
                        "code": char,
                        "attr": attr,
                        "attr_info": decode_vga_attribute(attr),
                    })
            result.append(row_data)
        return result

    def read_video_mode(self) -> int:
        """Read current video mode from BIOS data area."""
        if not self._gdb:
            raise GDBError("Not connected")
        data = self._gdb.read_memory(self.BIOS_VIDEO_MODE, 1)
        return data[0] if data else 0

    def read_timer_ticks(self) -> int:
        """Read BIOS timer tick count (18.2 Hz)."""
        if not self._gdb:
            raise GDBError("Not connected")
        data = self._gdb.read_memory(self.BIOS_TIMER_TICKS, 4)
        if len(data) >= 4:
            return int.from_bytes(data, byteorder="little")
        return 0
