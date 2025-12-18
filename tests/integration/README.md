# Integration Tests for Remote Debugging

This directory contains integration tests for DOSBox-X's remote debugging capabilities (GDB server and QMP server).

## Requirements

- **Python 3.11+**
- **[uv](https://github.com/astral-sh/uv)** - Fast Python package manager
- DOSBox-X built with `--enable-remotedebug`

Dependencies are managed via [PEP 723](https://peps.python.org/pep-0723/) inline script metadata - no separate requirements.txt needed.

## Quick Start

1. Build DOSBox-X with remote debugging:
   ```bash
   ./build-debug --enable-remotedebug
   ```

2. Start DOSBox-X with servers enabled (add to config or use menu):
   ```ini
   [dosbox]
   gdbserver=true
   qmpserver=true
   ```

3. Run all tests:
   ```bash
   uv run tests/integration/run_all.py
   ```

## Running Individual Test Suites

```bash
# GDB server tests
uv run tests/integration/test_gdb_server.py

# QMP server tests
uv run tests/integration/test_qmp_server.py

# Video tools tests
uv run tests/integration/test_video_tools.py
```

## Pytest Options

Pass pytest arguments after the script:

```bash
# Verbose output
uv run tests/integration/run_all.py -v

# Stop on first failure
uv run tests/integration/run_all.py -x

# Run only tests matching pattern
uv run tests/integration/run_all.py -k "memory"
uv run tests/integration/run_all.py -k "TestRegisters"

# Full tracebacks
uv run tests/integration/run_all.py --tb=long

# Show test durations
uv run tests/integration/run_all.py --durations=10
```

## Test Files

| File | Description |
|------|-------------|
| `test_gdb_server.py` | GDB Remote Serial Protocol tests: connection, registers, memory, breakpoints, execution control |
| `test_qmp_server.py` | QEMU Monitor Protocol tests: connection, send-key, input-send-event, type_text |
| `test_video_tools.py` | Screen capture tests: screen dump, raw video memory, timer, VGA attributes |
| `run_all.py` | Test runner that checks server availability and runs all tests |

## Configuration

Default ports (matching DOSBox-X defaults):
- GDB server: `localhost:2159`
- QMP server: `localhost:4444`

To use different ports, modify the constants at the top of each test file.

## Test Categories

### GDB Server Tests
- **Connection**: connect/disconnect, no-ACK mode, reconnection
- **Registers**: read all, read single, write, consistency
- **Memory**: read/write, segment:offset addressing, various sizes
- **Breakpoints**: set, remove, multiple breakpoints
- **Execution**: step, continue, halt

### QMP Server Tests
- **Connection**: greeting, capability handshake, reconnection
- **send-key**: single keys, modifiers, combinations
- **input-send-event**: key down/up, held modifiers
- **type_text**: lowercase, uppercase, mixed, special chars
- **Key codes**: letters, numbers, function keys, navigation, keypad

### Video Tools Tests
- **Screen dump**: text capture, line length, multiple captures
- **Raw screen**: byte access, char/attribute pairs
- **Video mode**: mode detection
- **Timer**: BIOS tick counter, timer advancement
- **VGA attributes**: color decoding, blink bit

## Troubleshooting

**Tests skip with "server not available"**
- Ensure DOSBox-X is running
- Check that `gdbserver=true` and/or `qmpserver=true` in config
- Verify ports are correct (2159 for GDB, 4444 for QMP)
- Check firewall settings if testing remotely

**Import errors**
- Run with `uv run` to auto-install dependencies
- Or manually: `uv pip install dbxdebug pytest`

**Tests hang**
- DOSBox-X might be in a state waiting for input
- Try pressing a key in DOSBox-X or restarting it
