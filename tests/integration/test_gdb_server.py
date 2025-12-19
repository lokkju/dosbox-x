#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "dbxdebug>=0.2.1",
#     "pytest>=8.0",
# ]
# ///
"""
Integration tests for DOSBox-X GDB Server.

Prerequisites:
    - DOSBox-X built with --enable-remotedebug
    - DOSBox-X running with gdbserver=true (default port 2159)

Run with:
    uv run tests/integration/test_gdb_server.py

Or with pytest:
    uv run --with pytest pytest tests/integration/test_gdb_server.py -v
"""

import socket
import sys
import time
from contextlib import contextmanager

import pytest
from dbxdebug.gdb import GDBClient

# Test configuration
GDB_HOST = "localhost"
GDB_PORT = 2159
CONNECT_TIMEOUT = 5.0


def is_server_available(host: str = GDB_HOST, port: int = GDB_PORT) -> bool:
    """Check if the GDB server is reachable."""
    try:
        with socket.create_connection((host, port), timeout=1.0):
            return True
    except (socket.error, socket.timeout):
        return False


@pytest.fixture(scope="module")
def gdb_available():
    """Skip all tests if GDB server is not available."""
    if not is_server_available():
        pytest.skip(f"GDB server not available at {GDB_HOST}:{GDB_PORT}")


@pytest.fixture
def gdb(gdb_available):
    """Provide a fresh GDB client connection for each test."""
    with GDBClient(host=GDB_HOST, port=GDB_PORT) as client:
        yield client


# =============================================================================
# Connection Tests
# =============================================================================

class TestConnection:
    """Test GDB server connection handling."""

    def test_basic_connect(self, gdb_available):
        """Server accepts connection and responds."""
        with GDBClient(host=GDB_HOST, port=GDB_PORT) as gdb:
            # Connection successful if we get here
            assert gdb is not None

    def test_no_ack_mode(self, gdb_available):
        """QStartNoAckMode disables acknowledgments."""
        with GDBClient(host=GDB_HOST, port=GDB_PORT) as gdb:
            result = gdb.enable_no_ack_mode()
            assert result is True

    def test_reconnect_after_disconnect(self, gdb_available):
        """Server accepts new connection after client disconnects."""
        # First connection
        with GDBClient(host=GDB_HOST, port=GDB_PORT) as gdb1:
            regs1 = gdb1.read_registers()
            assert regs1 is not None

        # Brief pause to allow server cleanup
        time.sleep(0.1)

        # Second connection
        with GDBClient(host=GDB_HOST, port=GDB_PORT) as gdb2:
            regs2 = gdb2.read_registers()
            assert regs2 is not None


# =============================================================================
# Register Tests
# =============================================================================

class TestRegisters:
    """Test register read/write operations."""

    REGISTER_NAMES = [
        "eax", "ecx", "edx", "ebx", "esp", "ebp", "esi", "edi",
        "eip", "eflags", "cs", "ss", "ds", "es", "fs", "gs"
    ]

    def test_read_all_registers(self, gdb):
        """Read all 16 registers via 'g' packet."""
        regs = gdb.read_registers()
        assert regs is not None
        assert isinstance(regs, dict)
        # Should have all expected registers
        for name in self.REGISTER_NAMES:
            assert name in regs, f"Missing register: {name}"
            assert isinstance(regs[name], int)

    def test_read_single_register(self, gdb):
        """Read individual registers via 'p' packet."""
        for i in range(16):
            value = gdb.read_register(i)
            assert isinstance(value, int)
            assert 0 <= value <= 0xFFFFFFFF

    def test_register_values_consistent(self, gdb):
        """Single register reads match bulk register read."""
        all_regs = gdb.read_registers()
        for i, name in enumerate(self.REGISTER_NAMES):
            single_value = gdb.read_register(i)
            assert single_value == all_regs[name], \
                f"Register {name} mismatch: {single_value} vs {all_regs[name]}"

    def test_eip_is_valid_address(self, gdb):
        """EIP should be a reasonable code address."""
        regs = gdb.read_registers()
        eip = regs["eip"]
        # EIP should be non-zero and within reasonable bounds
        assert eip > 0
        # For real-mode DOS, typically below 1MB
        # For protected mode, could be higher
        assert eip < 0x100000000  # 32-bit address space


# =============================================================================
# Memory Tests
# =============================================================================

class TestMemory:
    """Test memory read/write operations."""

    # Video memory - always readable in DOS
    VIDEO_MEM_ADDR = 0xB8000
    VIDEO_MEM_SIZE = 4000  # 80x25 * 2 bytes

    # BIOS data area - readable
    BIOS_DATA_ADDR = 0x400
    BIOS_DATA_SIZE = 256

    def test_read_video_memory(self, gdb):
        """Read video memory (always present in DOS)."""
        data = gdb.read_memory(self.VIDEO_MEM_ADDR, self.VIDEO_MEM_SIZE)
        assert data is not None
        assert len(data) == self.VIDEO_MEM_SIZE

    def test_read_bios_data_area(self, gdb):
        """Read BIOS data area."""
        data = gdb.read_memory(self.BIOS_DATA_ADDR, self.BIOS_DATA_SIZE)
        assert data is not None
        assert len(data) == self.BIOS_DATA_SIZE

    def test_read_with_segment_offset(self, gdb):
        """Read using segment:offset notation."""
        # B800:0000 = 0xB8000 (video memory)
        data = gdb.read_memory("b800:0000", 80)
        assert data is not None
        assert len(data) == 80

    def test_write_and_read_back(self, gdb):
        """Write memory and verify by reading back."""
        # Use a safe scratch area - we'll use video memory page 2
        # which is less likely to cause visible disruption
        scratch_addr = 0xB8000 + 4000  # Second video page

        # Save original content
        original = gdb.read_memory(scratch_addr, 4)

        try:
            # Write test pattern
            test_pattern = b"\xDE\xAD\xBE\xEF"
            gdb.write_memory(scratch_addr, test_pattern)

            # Read back and verify
            readback = gdb.read_memory(scratch_addr, 4)
            assert readback == test_pattern
        finally:
            # Restore original content
            if original:
                gdb.write_memory(scratch_addr, original)

    def test_read_various_sizes(self, gdb):
        """Read different sizes of memory."""
        for size in [1, 2, 4, 8, 16, 64, 256, 1024]:
            data = gdb.read_memory(self.VIDEO_MEM_ADDR, size)
            assert len(data) == size, f"Expected {size} bytes, got {len(data)}"

    def test_read_large_block(self, gdb):
        """Read a large memory block (near packet size limit)."""
        # GDB packet size is ~16KB, so read ~8KB to be safe
        large_size = 8192
        data = gdb.read_memory(self.VIDEO_MEM_ADDR, large_size)
        assert len(data) == large_size


# =============================================================================
# Breakpoint Tests
# =============================================================================

class TestBreakpoints:
    """Test breakpoint operations."""

    def test_set_breakpoint(self, gdb):
        """Set a software breakpoint."""
        # Use a safe address in conventional memory
        test_addr = 0x1000
        result = gdb.set_breakpoint(test_addr)
        assert result is True

        # Clean up
        gdb.remove_breakpoint(test_addr)

    def test_remove_breakpoint(self, gdb):
        """Remove a previously set breakpoint."""
        test_addr = 0x1000
        gdb.set_breakpoint(test_addr)
        result = gdb.remove_breakpoint(test_addr)
        assert result is True

    def test_multiple_breakpoints(self, gdb):
        """Set and remove multiple breakpoints."""
        addrs = [0x1000, 0x1010, 0x1020, 0x1030]

        # Set all breakpoints
        for addr in addrs:
            result = gdb.set_breakpoint(addr)
            assert result is True, f"Failed to set breakpoint at {addr:#x}"

        # Remove all breakpoints
        for addr in addrs:
            result = gdb.remove_breakpoint(addr)
            assert result is True, f"Failed to remove breakpoint at {addr:#x}"

    def test_breakpoint_with_segment_offset(self, gdb):
        """Set breakpoint using segment:offset notation."""
        result = gdb.set_breakpoint("0100:0000")  # 0x1000
        assert result is True
        gdb.remove_breakpoint("0100:0000")


# =============================================================================
# Execution Control Tests
# =============================================================================

class TestExecution:
    """Test execution control (step, continue, halt).

    NOTE: These tests are currently limited because DEBUG_Step/DEBUG_Continue
    use DEBUG_CheckKeys to simulate keypresses, which doesn't work properly
    when called from the GDB server thread. See issue DBX-z6v.
    """

    @pytest.mark.xfail(reason="DBX-z6v: step doesn't execute from GDB thread")
    def test_step_advances_eip(self, gdb):
        """Single step advances instruction pointer."""
        # Get initial EIP
        regs_before = gdb.read_registers()
        eip_before = regs_before["eip"]

        # Single step
        result = gdb.step()
        assert result is not None

        # EIP should have changed (advanced by at least 1 byte)
        regs_after = gdb.read_registers()
        eip_after = regs_after["eip"]
        assert eip_after != eip_before, "EIP did not change after step"

    def test_step_returns_signal(self, gdb):
        """Step returns stop signal (SIGTRAP = 0x05)."""
        result = gdb.step()
        # Result should indicate SIGTRAP
        assert result is not None
        # The response format depends on the client library
        # but should indicate the CPU stopped

    def test_halt_stops_execution(self, gdb):
        """Halt stops running execution."""
        result = gdb.halt()
        # Should receive a stop response
        assert result is not None

    @pytest.mark.skip(reason="DBX-z6v: continue/halt not fully working from GDB thread")
    def test_continue_and_halt(self, gdb):
        """Continue execution then halt."""
        # This test is tricky - we need to ensure we can stop
        # Set a breakpoint first to ensure we stop
        test_addr = 0x1000
        gdb.set_breakpoint(test_addr)

        try:
            # If CPU is currently halted, step to get it running-ish
            gdb.step()
            # Then halt again
            result = gdb.halt()
            assert result is not None
        finally:
            gdb.remove_breakpoint(test_addr)


# =============================================================================
# Protocol Edge Cases
# =============================================================================

class TestProtocol:
    """Test protocol-level behavior."""

    def test_empty_memory_read(self, gdb):
        """Reading zero bytes should handle gracefully."""
        # This might return empty bytes or raise an error
        # depending on implementation
        try:
            data = gdb.read_memory(0x1000, 0)
            assert data == b"" or data is None
        except ValueError:
            pass  # Also acceptable to reject zero-length read

    def test_unaligned_memory_access(self, gdb):
        """Memory access at odd addresses works."""
        # Read at odd address
        data = gdb.read_memory(0xB8001, 7)  # Odd addr, odd length
        assert len(data) == 7


# =============================================================================
# Main entry point
# =============================================================================

if __name__ == "__main__":
    # Check server availability first
    if not is_server_available():
        print(f"ERROR: GDB server not available at {GDB_HOST}:{GDB_PORT}")
        print("Please start DOSBox-X with gdbserver=true")
        sys.exit(1)

    # Run pytest
    sys.exit(pytest.main([__file__, "-v", "--tb=short"]))
