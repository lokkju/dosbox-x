#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "dbxdebug>=0.2.1",
#     "pytest>=8.0",
# ]
# ///
"""
Integration tests for DOSBox-X QMP Server.

Prerequisites:
    - DOSBox-X built with --enable-remotedebug
    - DOSBox-X running with qmpserver=true (default port 4444)

Run with:
    uv run tests/integration/test_qmp_server.py

Or with pytest:
    uv run --with pytest pytest tests/integration/test_qmp_server.py -v
"""

import socket
import sys
import time

import pytest
from dbxdebug.qmp import QMPClient, QMPError

# Test configuration
QMP_HOST = "localhost"
QMP_PORT = 4444
CONNECT_TIMEOUT = 5.0


def is_server_available(host: str = QMP_HOST, port: int = QMP_PORT) -> bool:
    """Check if the QMP server is reachable."""
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except (socket.error, socket.timeout):
        return False


@pytest.fixture(scope="module")
def qmp_available():
    """Skip all tests if QMP server is not available."""
    if not is_server_available():
        pytest.skip(f"QMP server not available at {QMP_HOST}:{QMP_PORT}")


@pytest.fixture
def qmp(qmp_available):
    """Provide a fresh QMP client connection for each test."""
    with QMPClient(host=QMP_HOST, port=QMP_PORT) as client:
        yield client


# =============================================================================
# Connection Tests
# =============================================================================

class TestConnection:
    """Test QMP server connection handling."""

    def test_basic_connect(self, qmp_available):
        """Server accepts connection and sends greeting."""
        with QMPClient(host=QMP_HOST, port=QMP_PORT) as qmp:
            # Connection successful if we get here (greeting received)
            assert qmp is not None

    def test_reconnect_after_disconnect(self, qmp_available):
        """Server accepts new connection after client disconnects."""
        # First connection
        with QMPClient(host=QMP_HOST, port=QMP_PORT) as qmp1:
            cmds1 = qmp1.query_commands()
            assert cmds1 is not None

        # Brief pause to allow server cleanup
        time.sleep(0.1)

        # Second connection
        with QMPClient(host=QMP_HOST, port=QMP_PORT) as qmp2:
            cmds2 = qmp2.query_commands()
            assert cmds2 is not None

    def test_query_commands(self, qmp):
        """Query available commands."""
        commands = qmp.query_commands()
        assert commands is not None
        assert isinstance(commands, (list, dict))


# =============================================================================
# send-key Tests
# =============================================================================

class TestSendKey:
    """Test send-key command for key combinations."""

    def test_single_key(self, qmp):
        """Send a single key press."""
        # Press 'a' - should not raise
        qmp.send_key(["a"])

    def test_multiple_keys(self, qmp):
        """Send multiple keys simultaneously."""
        # Ctrl+C combination
        qmp.send_key(["ctrl", "c"])

    def test_modifier_combinations(self, qmp):
        """Test various modifier key combinations."""
        # Note: Avoid Ctrl+Alt+Del and Alt+F4 as they can disrupt the emulator
        combos = [
            ["shift", "a"],       # Shift+A
            ["ctrl", "c"],        # Ctrl+C (safe in DOS)
            ["ctrl", "shift", "a"],   # Ctrl+Shift+A
        ]
        for combo in combos:
            qmp.send_key(combo)
            time.sleep(0.05)  # Small delay between combos

    def test_function_keys(self, qmp):
        """Test function key presses."""
        for i in range(1, 13):  # F1-F12
            qmp.send_key([f"f{i}"])
            time.sleep(0.02)

    def test_navigation_keys(self, qmp):
        """Test navigation key presses."""
        nav_keys = ["left", "right", "up", "down",
                    "home", "end", "pgup", "pgdn",
                    "insert", "delete"]
        for key in nav_keys:
            qmp.send_key([key])
            time.sleep(0.02)

    def test_special_keys(self, qmp):
        """Test special key presses."""
        special_keys = ["esc", "tab", "ret", "spc",
                        "caps_lock", "num_lock", "scroll_lock"]
        for key in special_keys:
            qmp.send_key([key])
            time.sleep(0.02)


# =============================================================================
# input-send-event Tests
# =============================================================================

class TestInputSendEvent:
    """Test input-send-event command for explicit key control."""

    def test_key_down(self, qmp):
        """Send key down event."""
        qmp.key_down("a")
        time.sleep(0.05)
        qmp.key_up("a")

    def test_key_up(self, qmp):
        """Send key up event."""
        qmp.key_down("b")
        time.sleep(0.05)
        qmp.key_up("b")

    def test_key_press(self, qmp):
        """Key press with configurable hold time."""
        qmp.key_press("c", hold_time=0.1)  # 100ms

    def test_held_modifier(self, qmp):
        """Hold modifier while pressing other keys."""
        # Hold shift, press multiple letters, release shift
        qmp.key_down("shift")
        time.sleep(0.02)
        for letter in ["h", "e", "l", "l", "o"]:
            qmp.key_press(letter, hold_time=0.05)  # 50ms
            time.sleep(0.02)
        qmp.key_up("shift")


# =============================================================================
# type_text Tests
# =============================================================================

class TestTypeText:
    """Test text typing functionality."""

    def test_type_lowercase(self, qmp):
        """Type lowercase text."""
        qmp.type_text("hello")

    def test_type_uppercase(self, qmp):
        """Type uppercase text (requires shift handling)."""
        qmp.type_text("HELLO")

    def test_type_mixed_case(self, qmp):
        """Type mixed case text."""
        qmp.type_text("Hello World")

    def test_type_numbers(self, qmp):
        """Type numeric text."""
        qmp.type_text("12345")

    def test_type_special_chars(self, qmp):
        """Type text with special characters."""
        # Characters that might need shift on US keyboard
        qmp.type_text("Hello!")

    def test_type_with_delay(self, qmp):
        """Type text with custom inter-key delay."""
        # If the client supports delay parameter
        qmp.type_text("abc")


# =============================================================================
# Error Handling Tests
# =============================================================================

class TestErrorHandling:
    """Test error handling behavior."""

    def test_invalid_key_name(self, qmp):
        """Invalid key name should raise error."""
        with pytest.raises((QMPError, ValueError, KeyError)):
            qmp.send_key(["not_a_real_key_name_xyz"])

    def test_empty_key_list(self, qmp):
        """Empty key list handling."""
        # This might succeed with no-op or raise error
        try:
            qmp.send_key([])
        except (QMPError, ValueError):
            pass  # Acceptable to reject empty key list


# =============================================================================
# Timing Tests
# =============================================================================

class TestTiming:
    """Test timing-related behavior."""

    def test_rapid_key_presses(self, qmp):
        """Rapid successive key presses."""
        for _ in range(20):
            qmp.send_key(["a"])
        # Should complete without errors

    def test_hold_time_parameter(self, qmp):
        """Verify hold-time parameter is accepted."""
        # We can't easily verify the actual timing, but we can
        # verify the parameter is accepted
        qmp.key_press("x", hold_time=0.2)  # 200ms


# =============================================================================
# Key Code Coverage Tests
# =============================================================================

class TestKeyCodeCoverage:
    """Test coverage of various QEMU key codes."""

    def test_letter_keys(self, qmp):
        """Test all letter keys a-z."""
        for c in "abcdefghijklmnopqrstuvwxyz":
            qmp.send_key([c])
            time.sleep(0.01)

    def test_number_keys(self, qmp):
        """Test number keys 0-9."""
        for c in "0123456789":
            qmp.send_key([c])
            time.sleep(0.01)

    def test_keypad_keys(self, qmp):
        """Test numeric keypad keys."""
        keypad_keys = ["kp_0", "kp_1", "kp_2", "kp_3", "kp_4",
                       "kp_5", "kp_6", "kp_7", "kp_8", "kp_9",
                       "kp_add", "kp_subtract", "kp_multiply", "kp_divide"]
        for key in keypad_keys:
            qmp.send_key([key])
            time.sleep(0.01)

    def test_punctuation_keys(self, qmp):
        """Test punctuation keys."""
        punct_keys = ["minus", "equal", "backslash", "backspace",
                      "comma", "dot", "slash", "semicolon",
                      "apostrophe", "grave_accent",
                      "bracket_left", "bracket_right"]
        for key in punct_keys:
            try:
                qmp.send_key([key])
                time.sleep(0.01)
            except (QMPError, ValueError, KeyError):
                # Some keys might not be mapped
                pass


# =============================================================================
# Main entry point
# =============================================================================

if __name__ == "__main__":
    # Check server availability first
    if not is_server_available():
        print(f"ERROR: QMP server not available at {QMP_HOST}:{QMP_PORT}")
        print("Please start DOSBox-X with qmpserver=true")
        sys.exit(1)

    # Run pytest
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
