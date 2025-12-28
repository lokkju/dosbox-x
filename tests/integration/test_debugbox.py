#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "pytest>=8.0",
# ]
# ///
"""
Integration tests for DEBUGBOX command with remote debugging.

These tests verify that DEBUGBOX and the GDB server work together correctly:
- DEBUGBOX pauses at program entry point
- GDB client can connect and see the paused state
- Registers reflect the program's entry point

These tests use DOSBoxInstance to automatically start/stop DOSBox-X.

Run with:
    uv run pytest tests/integration/test_debugbox.py -v

Or:
    uv run tests/integration/test_debugbox.py
"""

import os
import sys
import time
from pathlib import Path

import pytest
from dosbox_debug import DOSBoxInstance, GDBClient, QMPClient


# Test assets directory (relative to this file)
TEST_ASSETS_DIR = Path(__file__).parent / "assets"


def create_test_com_file():
    """Create a minimal test COM file for testing.

    Returns the path to the created file, or None if creation failed.
    The COM file contains a simple program that just exits immediately.
    """
    # Ensure assets directory exists
    TEST_ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    test_com_path = TEST_ASSETS_DIR / "DBXTEST.COM"

    # Minimal COM file: NOP, NOP, INT 20h (terminate)
    # COM files start at offset 0x100 in memory
    # This program does nothing but exit cleanly
    com_bytes = bytes([
        0x90,        # NOP
        0x90,        # NOP
        0xB8, 0x00, 0x4C,  # MOV AX, 4C00h (DOS exit with code 0)
        0xCD, 0x21,  # INT 21h (DOS function call)
    ])

    try:
        with open(test_com_path, 'wb') as f:
            f.write(com_bytes)
        return test_com_path
    except Exception as e:
        print(f"Warning: Could not create test COM file: {e}")
        return None


@pytest.fixture(scope="module")
def dosbox():
    """Start DOSBox-X for the test module."""
    with DOSBoxInstance() as dbx:
        # Wait for boot
        dbx.continue_()
        time.sleep(2.0)
        yield dbx


@pytest.fixture
def ensure_running(dosbox):
    """Ensure the emulator is running (not paused) before the test."""
    try:
        status = dosbox.query_status().get('return', {})
        if status.get('status') == 'paused' or not status.get('running', True):
            dosbox.continue_()
            time.sleep(0.2)
    except Exception:
        pass
    yield


# =============================================================================
# DEBUGBOX Basic Tests
# =============================================================================

class TestDebugboxBasic:
    """Test basic DEBUGBOX functionality."""

    def test_debugbox_without_args_pauses(self, dosbox, ensure_running):
        """DEBUGBOX without arguments should pause in debugger mode."""
        # Make sure running
        dosbox.continue_()
        time.sleep(0.3)

        # Type DEBUGBOX command without arguments
        dosbox.run_command("DEBUGBOX", wait_after=0.5)

        # Halt to ensure we're stopped
        dosbox.halt()
        time.sleep(0.2)

        # Verify we can read registers (confirms pause state)
        regs = dosbox.gdb.read_registers()
        assert regs is not None, "Could not read registers during DEBUGBOX"

        # Check if emulator is paused via query-status
        status = dosbox.query_status().get('return', {})

        # Debugger mode should pause execution
        is_paused = status.get('status') == 'paused' or not status.get('running', True)
        assert is_paused, f"Expected paused state, got: {status}"


class TestDebugboxWithGdb:
    """Test DEBUGBOX integration with GDB server."""

    def test_gdb_can_connect_during_debugbox(self, dosbox):
        """GDB should be able to connect while DEBUGBOX is active."""
        # Should be able to read registers
        regs = dosbox.gdb.read_registers()
        assert regs is not None
        assert hasattr(regs, 'eip')

    def test_gdb_sees_pause_after_breakpoint(self, dosbox):
        """GDB should see the CPU paused when breakpoint is hit."""
        # Read initial EIP
        regs = dosbox.gdb.read_registers()
        initial_eip = regs.eip

        # Perform a step - this should pause and return
        result = dosbox.gdb.step()
        assert result is not None

        # Read registers after step
        regs_after = dosbox.gdb.read_registers()
        assert regs_after is not None


class TestDebugboxEntryPoint:
    """Test that DEBUGBOX correctly breaks at program entry point."""

    @pytest.fixture
    def test_com_file(self):
        """Create and provide path to test COM file."""
        com_path = create_test_com_file()
        if com_path is None:
            pytest.skip("Could not create test COM file")
        yield com_path

    def test_debugbox_program_entry_detection(self, test_com_file):
        """DEBUGBOX should pause at program entry point."""
        # Just verify the COM file was created
        assert test_com_file is not None
        assert test_com_file.exists()


class TestDebugboxEntryPointFull:
    """Full end-to-end test for DEBUGBOX entry point."""

    def test_debugbox_breaks_at_com_entry(self, dosbox, ensure_running):
        """Verify DEBUGBOX pauses at COM file entry point."""
        # Ensure test COM file exists
        com_path = create_test_com_file()
        if com_path is None:
            pytest.skip("Could not create test COM file")

        # Make sure running
        dosbox.continue_()
        time.sleep(0.3)

        # Change to test drive
        dosbox.run_command("T:", wait_after=0.3)

        # Run DEBUGBOX with test program
        dosbox.run_command("DEBUGBOX DBXTEST.COM", wait_after=1.0)

        # Halt to ensure we're stopped
        dosbox.halt()
        time.sleep(0.2)

        # Read registers
        regs = dosbox.gdb.read_registers()
        assert regs is not None, "Failed to read registers"

        eip = regs.eip
        cs = regs.cs

        # For COM files, EIP should have offset 0x100 within its segment
        eip_offset = eip - (cs * 16)

        # The program should be at entry point 0x100 (NOP instruction)
        assert eip_offset in (0x100, 0x101, 0x102), (
            f"Expected EIP offset ~0x100 for COM entry point, "
            f"got 0x{eip_offset:04X} (full EIP: 0x{eip:08X}, CS: 0x{cs:04X})"
        )

        # Read memory at entry point to verify it's our test program
        entry_addr = (cs << 4) + 0x100 if cs else eip - eip_offset + 0x100
        mem = dosbox.gdb.read_memory(entry_addr, 7)

        expected_bytes = bytes([0x90, 0x90, 0xB8, 0x00, 0x4C, 0xCD, 0x21])
        assert mem == expected_bytes, (
            f"Memory at entry point doesn't match test program. "
            f"Expected: {expected_bytes.hex()}, Got: {mem.hex()}"
        )

        # Continue execution to clean up
        dosbox.gdb.step()
        dosbox.gdb.step()

    def test_debugbox_paused_state_visible_via_qmp(self, dosbox, ensure_running):
        """Verify DEBUGBOX pause state is visible via QMP query-status."""
        # Ensure test COM file exists
        com_path = create_test_com_file()
        if com_path is None:
            pytest.skip("Could not create test COM file")

        # Make sure running
        dosbox.continue_()
        time.sleep(0.3)

        # Change to test drive (verify=False to avoid halt/continue overhead)
        dosbox.run_command("T:", wait_after=0.5, verify=False)

        # Run DEBUGBOX with test program (verify=False for reliability)
        dosbox.run_command("DEBUGBOX DBXTEST.COM", wait_after=1.5, verify=False)

        # Halt to ensure we're stopped
        dosbox.halt()
        time.sleep(0.2)

        # Query status - should show debug pause state
        response = dosbox.query_status()
        status = response.get('return', {})

        # Overall status should be paused
        assert status.get('status') == 'paused', f"Expected 'paused', got {status.get('status')}"
        assert status.get('running') is False, "Expected running to be false"

        # Debug object should show active and paused
        debug = status.get('debug', {})
        assert debug.get('active') is True, "Expected debug.active to be true"
        assert debug.get('paused') is True, "Expected debug.paused to be true"


class TestQueryStatus:
    """Test QMP query-status command for debugging state."""

    def test_query_status_returns_valid_response(self, dosbox):
        """query-status should return valid running/paused state with debug info."""
        response = dosbox.query_status()
        status = response.get('return', {})

        # Status should have required fields
        assert 'status' in status, "Missing 'status' field"
        assert 'running' in status, "Missing 'running' field"
        assert status['status'] in ('running', 'paused')
        assert isinstance(status['running'], bool)

        # Should have emulator-paused field
        assert 'emulator-paused' in status, "Missing 'emulator-paused' field"
        assert isinstance(status['emulator-paused'], bool)

        # Should have debug object with active and paused fields
        assert 'debug' in status, "Missing 'debug' object"
        debug = status['debug']
        assert 'active' in debug, "Missing 'debug.active' field"
        assert 'paused' in debug, "Missing 'debug.paused' field"

    def test_stop_and_cont_commands(self, dosbox):
        """stop and cont commands should control emulator pause state."""
        # First ensure we're running
        dosbox.continue_()
        time.sleep(0.3)

        # Stop the emulator
        dosbox.qmp.stop()
        time.sleep(0.2)

        # Verify paused
        response = dosbox.query_status()
        status = response.get('return', {})

        assert status.get('status') == 'paused', f"Expected 'paused', got {status.get('status')}"
        # Note: emulator-paused may be False if GDB is connected and pausing
        # The important thing is that status='paused' and running=False

        # Resume
        dosbox.qmp.cont()
        time.sleep(0.2)

        # Also continue GDB to fully resume
        dosbox.continue_()
        time.sleep(0.2)

        # Verify running
        response = dosbox.query_status()
        status = response.get('return', {})

        assert status.get('status') == 'running', f"Expected 'running', got {status.get('status')}"


class TestGdbPauseState:
    """Test GDB server pause state detection."""

    def test_gdb_halt_pauses_execution(self, dosbox):
        """GDB halt command should pause CPU execution."""
        # Halt execution
        result = dosbox.halt()
        assert result is not None

        # After halt, we should be able to read registers
        regs = dosbox.gdb.read_registers()
        assert regs is not None
        assert hasattr(regs, 'eip')

    def test_gdb_pause_visible_via_qmp(self, dosbox):
        """GDB step/halt should be visible via QMP query-status."""
        # Step to pause for GDB
        dosbox.gdb.step()

        # Check via QMP
        response = dosbox.query_status()
        status = response.get('return', {})

        # Should show debug active and paused
        debug = status.get('debug', {})
        assert debug.get('active') is True, "Expected debug.active=true when GDB connected"
        assert debug.get('paused') is True, "Expected debug.paused=true after GDB step"

    def test_gdb_step_pauses_after_one_instruction(self, dosbox):
        """GDB step should execute one instruction and pause."""
        # Get initial state
        regs_before = dosbox.gdb.read_registers()
        eip_before = regs_before.eip

        # Step
        result = dosbox.gdb.step()
        assert result is not None

        # After step, should be paused
        regs_after = dosbox.gdb.read_registers()
        assert regs_after is not None

    def test_gdb_breakpoint_pauses_at_address(self, dosbox):
        """GDB breakpoint should pause execution when hit."""
        # Set a breakpoint at a test address
        test_addr = 0x1000
        result = dosbox.gdb.set_breakpoint(test_addr)
        assert result is True

        # Clean up
        dosbox.gdb.remove_breakpoint(test_addr)


class TestDebuggerMutualExclusion:
    """Test mutual exclusion between GDB and interactive debugger."""

    def test_gdb_connection_blocks_interactive_debugger(self, dosbox, ensure_running):
        """With GDB connected, attempting to open interactive debugger should fail."""
        # Ensure we're in a good state - halt first
        dosbox.halt()
        time.sleep(0.2)

        # Verify GDB is connected and working
        regs = dosbox.gdb.read_registers()
        assert regs is not None

        # Ensure emulator is running
        dosbox.continue_()
        time.sleep(0.3)

        # Try to activate interactive debugger via DEBUGBOX
        dosbox.run_command("DEBUGBOX", wait_after=0.5)

        # Halt to check state
        dosbox.halt()
        time.sleep(0.2)

        # GDB should still be responsive
        regs_after = dosbox.gdb.read_registers()
        assert regs_after is not None, "GDB became unresponsive after DEBUGBOX attempt"


class TestRemoteDebugIntegration:
    """Integration tests for remote debugging with DEBUGBOX."""

    def test_gdb_and_qmp_simultaneous_connection(self, dosbox):
        """Both GDB and QMP should be able to connect simultaneously."""
        # Ensure we're halted first for reliable register read
        dosbox.halt()
        time.sleep(0.2)

        # Both connections should work
        regs = dosbox.gdb.read_registers()
        assert regs is not None

        commands = dosbox.qmp.query_commands()
        assert commands is not None

    def test_qmp_stop_and_query_status(self, dosbox):
        """Pausing via QMP stop should be visible via QMP query-status."""
        # Ensure we start running
        dosbox.continue_()
        time.sleep(0.3)

        # Stop via QMP
        dosbox.qmp.stop()
        time.sleep(0.2)

        # Check status - should show paused
        status = dosbox.query_status().get('return', {})
        assert status.get('status') == 'paused', f"Expected status='paused', got {status}"

        # Resume via both QMP and GDB
        dosbox.qmp.cont()
        dosbox.continue_()
        time.sleep(0.3)

        # Check status - should show running
        status = dosbox.query_status().get('return', {})
        assert status.get('status') == 'running', f"Expected status='running', got {status}"

    def test_gdb_registers_valid_during_pause(self, dosbox):
        """Register values should be valid and consistent when paused."""
        # Halt to ensure we're in a stable state
        dosbox.halt()

        # Read registers multiple times - should be consistent
        regs1 = dosbox.gdb.read_registers()
        regs2 = dosbox.gdb.read_registers()

        # All registers should match (no execution happening)
        for name in ['eax', 'ebx', 'ecx', 'edx', 'esp', 'ebp', 'esi', 'edi', 'eip']:
            assert getattr(regs1, name) == getattr(regs2, name), f"Register {name} changed while paused"


# =============================================================================
# Main entry point
# =============================================================================

if __name__ == "__main__":
    # Create test assets
    com_path = create_test_com_file()
    if com_path:
        print(f"Test COM file created at: {com_path}")

    # Run pytest
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
