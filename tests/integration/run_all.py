#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "dbxdebug>=0.2.1",
#     "pytest>=8.0",
# ]
# ///
"""
Run all DOSBox-X remote debugging integration tests.

Prerequisites:
    - DOSBox-X built with --enable-remotedebug
    - DOSBox-X running with:
        gdbserver=true
        gdbserver port=2159
        qmpserver=true
        qmpserver port=4444

Run with:
    uv run tests/integration/run_all.py [pytest args...]

Examples:
    uv run tests/integration/run_all.py              # Run all tests
    uv run tests/integration/run_all.py -v           # Verbose output
    uv run tests/integration/run_all.py -k gdb       # Only GDB tests
    uv run tests/integration/run_all.py -x           # Stop on first failure
    uv run tests/integration/run_all.py --tb=long    # Full tracebacks
"""

import socket
import sys
from pathlib import Path

import pytest

# Server configuration
GDB_HOST = "localhost"
GDB_PORT = 2159
QMP_HOST = "localhost"
QMP_PORT = 4444


def check_server(name: str, host: str, port: int) -> bool:
    """Check if a server is reachable."""
    try:
        with socket.create_connection((host, port), timeout=2.0):
            print(f"  [OK] {name} server at {host}:{port}")
            return True
    except (socket.error, socket.timeout):
        print(f"  [--] {name} server at {host}:{port} (not available)")
        return False


def main():
    print("DOSBox-X Remote Debugging Integration Tests")
    print("=" * 50)
    print()
    print("Checking server availability...")

    gdb_ok = check_server("GDB", GDB_HOST, GDB_PORT)
    qmp_ok = check_server("QMP", QMP_HOST, QMP_PORT)

    print()

    if not gdb_ok and not qmp_ok:
        print("ERROR: No servers available!")
        print()
        print("Please start DOSBox-X with remote debugging enabled:")
        print()
        print("  [dosbox]")
        print("  gdbserver=true")
        print("  gdbserver port=2159")
        print("  qmpserver=true")
        print("  qmpserver port=4444")
        print()
        return 1

    if not gdb_ok:
        print("WARNING: GDB server not available - GDB tests will be skipped")
    if not qmp_ok:
        print("WARNING: QMP server not available - QMP tests will be skipped")

    print()
    print("Running tests...")
    print("-" * 50)

    # Get the directory containing this script
    test_dir = Path(__file__).parent

    # Build pytest arguments
    pytest_args = [
        str(test_dir),
        "-v",
        "--tb=short",
    ]

    # Add any additional arguments passed to this script
    pytest_args.extend(sys.argv[1:])

    # Run pytest
    return pytest.main(pytest_args)


if __name__ == "__main__":
    sys.exit(main())
