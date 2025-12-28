# DOSBox-X Remote Debugging

DOSBox-X includes remote debugging capabilities for external tools to connect and interact with the emulator:

- **GDB Server** - Debug DOS programs using GDB or compatible debuggers
- **QMP Server** - Inject keyboard input using QEMU Monitor Protocol

## Building

Remote debugging requires POSIX sockets and is supported on Linux, BSD, and macOS.

```bash
./build-debug --enable-remotedebug
```

Or manually:
```bash
./configure --enable-debug --enable-remotedebug
make
```

## Configuration

Add to the `[dosbox]` section of your configuration file:

```ini
[dosbox]
# GDB remote debugging server
gdbserver=true
gdbserver port=2159

# QMP keyboard input server
qmpserver=true
qmpserver port=4444
```

| Option | Default | Description |
|--------|---------|-------------|
| `gdbserver` | `false` | Enable GDB remote debugging server |
| `gdbserver port` | `2159` | GDB server TCP port |
| `qmpserver` | `false` | Enable QMP keyboard input server |
| `qmpserver port` | `4444` | QMP server TCP port |

Servers can be toggled at runtime via **Debug > GDB Server** and **Debug > QMP Server** menus.

### Logging

Control remote debugging verbosity via the `[log]` section:

```ini
[log]
remote=debug    # debug, normal (default), warn, error, fatal, never
```

---

## GDB Server

Implements the [GDB Remote Serial Protocol](https://sourceware.org/gdb/current/onlinedocs/gdb.html/Remote-Protocol.html) for debugging DOS programs.

### Connecting

```bash
gdb
(gdb) target remote localhost:2159
```

### Register Mapping

| Index | Register |
|-------|----------|
| 0-7 | EAX, ECX, EDX, EBX, ESP, EBP, ESI, EDI |
| 8 | EIP (linear address) |
| 9 | EFLAGS |
| 10-15 | CS, SS, DS, ES, FS, GS |

### Memory Addressing

Addresses are linear physical. For real-mode: `(segment << 4) + offset`.

### Limitations

- Software breakpoints only (hardware breakpoints/watchpoints not implemented)

---

## QMP Server

Implements a subset of [QEMU Monitor Protocol](https://www.qemu.org/docs/master/interop/qemu-qmp-ref.html) for keyboard input injection. Compatible with QEMU tooling.

### Connecting

Connect via TCP and send JSON commands. The server sends a greeting on connect:

```json
{"QMP": {"version": {...}, "capabilities": ["oob"]}}
```

Acknowledge capabilities to enter command mode:

```json
{"execute": "qmp_capabilities"}
```

### Commands

#### send-key

Press keys simultaneously, auto-release after hold-time:

```json
{"execute": "send-key", "arguments": {
  "keys": [
    {"type": "qcode", "data": "ctrl"},
    {"type": "qcode", "data": "alt"},
    {"type": "qcode", "data": "delete"}
  ],
  "hold-time": 100
}}
```

- `keys`: Array of key objects with `type: "qcode"` and `data: "<keyname>"`
- `hold-time`: Milliseconds before releasing (default: 100)

#### input-send-event

Explicit key press/release control:

```json
{"execute": "input-send-event", "arguments": {
  "events": [{
    "type": "key",
    "data": {"down": true, "key": {"type": "qcode", "data": "a"}}
  }]
}}
```

#### Mouse Events (input-send-event)

Mouse movement and button clicks:

```json
{"execute": "input-send-event", "arguments": {
  "events": [
    {"type": "rel", "data": {"axis": "x", "value": 50}},
    {"type": "rel", "data": {"axis": "y", "value": -30}},
    {"type": "btn", "data": {"button": "left", "down": true}},
    {"type": "btn", "data": {"button": "left", "down": false}}
  ]
}}
```

- `type: "rel"` - Relative mouse movement (`axis`: `x`/`y`, `value`: pixels)
- `type: "btn"` - Mouse button (`button`: `left`/`right`/`middle`, `down`: true/false)

#### debug-break-on-exec

Enable breakpoint on program entry for GDB debugging:

```json
{"execute": "debug-break-on-exec", "arguments": {"enabled": true}}
```

When enabled, DOSBox-X will automatically set a breakpoint when DOS loads an EXE/COM program. If a GDB client is connected, it receives the S05 (SIGTRAP) notification at the program entry point.

Response: `{"return": {"enabled": true}}`

### Key Names (QKeyCode)

Standard QEMU key names: `a`-`z`, `0`-`9`, `f1`-`f12`, `ret`, `esc`, `tab`, `spc`, `shift`, `ctrl`, `alt`, `caps_lock`, `left`, `right`, `up`, `down`, `insert`, `delete`, `home`, `end`, `pgup`, `pgdn`, `kp_0`-`kp_9`, etc.

See [QEMU QKeyCode](https://www.qemu.org/docs/master/interop/qemu-qmp-ref.html) for full list.

---

## Debugging Program Entry Points

There are two approaches for setting breakpoints at a program's entry point.

### Entry Point Addresses

When a breakpoint is hit at program entry:
- **EXE files**: CS:IP points to segment:0000 (entry at start of code segment)
- **COM files**: CS:IP points to segment:0100 (code starts after 256-byte PSP)

The segment address varies based on available memory. Use `offset = EIP - (CS * 16)` to calculate the offset within the segment.

### Option 1: DEBUGBOX Shell Command

The built-in `DEBUGBOX` command sets a breakpoint at program entry:

```
C:\> DEBUGBOX MYGAME.EXE
```

**Important**: A GDB client must be connected BEFORE running DEBUGBOX to receive the breakpoint notification (S05/SIGTRAP).

#### Example with GDB

Terminal 1 - Connect GDB first:
```bash
gdb
(gdb) target remote localhost:2159
```

Terminal 2 - Type DEBUGBOX command via QMP:
```bash
# Initialize QMP
echo '{"execute": "qmp_capabilities"}' | nc localhost 4444

# Type the command (each key separately)
for key in d e b u g b o x spc m y g a m e dot e x e ret; do
  echo "{\"execute\": \"send-key\", \"arguments\": {\"keys\": [{\"type\": \"qcode\", \"data\": \"$key\"}]}}" | nc localhost 4444
  sleep 0.05
done
```

Terminal 1 - GDB receives breakpoint:
```
(gdb) info registers
eax    0x0      0
...
eip    0x8240   0x8240    # Linear address
cs     0x824    0x824     # Code segment
...
# Offset = 0x8240 - (0x824 * 16) = 0x0000 (EXE entry point)
```

### Option 2: QMP debug-break-on-exec

For automation without using the DEBUGBOX command:

**Important**: Connect GDB BEFORE enabling debug-break-on-exec to receive S05.

#### Complete Example

```bash
#!/bin/bash
# debug_program.sh - Debug a DOS program at entry point

PROGRAM="MYGAME.EXE"
QMP_PORT=4444
GDB_PORT=2159

# Step 1: Connect GDB in background (must be first!)
(echo "target remote localhost:$GDB_PORT" | gdb -batch -x -) &
GDB_PID=$!
sleep 0.5

# Step 2: Initialize QMP and enable break-on-exec
{
  echo '{"execute": "qmp_capabilities"}'
  sleep 0.1
  echo '{"execute": "debug-break-on-exec", "arguments": {"enabled": true}}'
  sleep 0.1
} | nc localhost $QMP_PORT

# Step 3: Type the program name
for char in $(echo "$PROGRAM" | grep -o .); do
  key=$(echo "$char" | tr '[:upper:]' '[:lower:]')
  case "$char" in
    .) key="dot" ;;
    " ") key="spc" ;;
  esac
  echo "{\"execute\": \"send-key\", \"arguments\": {\"keys\": [{\"type\": \"qcode\", \"data\": \"$key\"}]}}" | nc localhost $QMP_PORT
  sleep 0.05
done

# Step 4: Press Enter to execute
echo '{"execute": "send-key", "arguments": {"keys": [{"type": "qcode", "data": "ret"}]}}' | nc localhost $QMP_PORT

# GDB will receive S05 when program entry breakpoint is hit
wait $GDB_PID
```

#### Python Example

```python
#!/usr/bin/env python3
"""Debug a DOS program at its entry point."""
import socket
import json
import time

def qmp_command(sock, cmd, args=None):
    """Send QMP command and return response."""
    msg = {"execute": cmd}
    if args:
        msg["arguments"] = args
    sock.send((json.dumps(msg) + "\n").encode())
    return json.loads(sock.recv(4096).decode())

def type_text(sock, text):
    """Type text via QMP send-key."""
    keymap = {'.': 'dot', ' ': 'spc', '\n': 'ret'}
    for char in text:
        key = keymap.get(char, char.lower())
        qmp_command(sock, "send-key", {
            "keys": [{"type": "qcode", "data": key}]
        })
        time.sleep(0.05)

# Connect GDB first (critical!)
gdb = socket.socket()
gdb.connect(("localhost", 2159))
gdb.recv(1024)  # Receive any greeting

# Connect QMP
qmp = socket.socket()
qmp.connect(("localhost", 4444))
qmp.recv(1024)  # Greeting
qmp_command(qmp, "qmp_capabilities")

# Enable break-on-exec
qmp_command(qmp, "debug-break-on-exec", {"enabled": True})

# Type program name and press Enter
type_text(qmp, "MYGAME.EXE\n")

# Wait for S05 from GDB
gdb.settimeout(5.0)
response = gdb.recv(1024)
print(f"GDB received: {response}")  # Should contain $S05#b8

# Now you can read registers, set breakpoints, etc.
gdb.send(b"$g#67")  # Read all registers
print(gdb.recv(4096))
```

---

## Files

- `src/debug/gdbserver.cpp`, `include/gdbserver.h` - GDB server
- `src/debug/qmp.cpp`, `include/qmp.h` - QMP server
- `src/debug/debug.cpp` - Integration
- `tests/integration/` - Integration tests

---

## Integration Tests

Integration tests are self-contained Python scripts using [PEP 723](https://peps.python.org/pep-0723/) inline metadata for dependency management. The tests include a local `dosbox_debug.py` module with GDB and QMP client implementations.

### Requirements

- Python 3.11+
- [uv](https://github.com/astral-sh/uv) (recommended) or pip

### Running Tests

```bash
# Run all tests
uv run tests/integration/run_all.py

# Run individual test suites
uv run tests/integration/test_gdb_server.py
uv run tests/integration/test_qmp_server.py
uv run tests/integration/test_video_tools.py

# With pytest options
uv run tests/integration/run_all.py -v           # Verbose
uv run tests/integration/run_all.py -k memory    # Filter by name
uv run tests/integration/run_all.py -x           # Stop on first failure
```

### Test Coverage

| Suite | Coverage |
|-------|----------|
| `test_gdb_server.py` | Connection, registers, memory, breakpoints, execution control |
| `test_qmp_server.py` | Connection, send-key, input-send-event, type_text, key codes |
| `test_debugbox.py` | GDB pause states, step/continue, breakpoints, debug-break-on-exec |
| `test_video_tools.py` | Screen capture, raw video memory, timer, VGA attributes |

See `tests/integration/README.md` for detailed documentation.

---

## TODO

- [ ] Windows support (currently POSIX sockets only)
- [ ] Hardware breakpoints/watchpoints for GDB server
