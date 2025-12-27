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

There are two approaches for setting breakpoints at a program's entry point:

### Option 1: Using DEBUGBOX (External Tool)

[DEBUGBOX](https://pypi.org/project/dbxdebug/) is a Python library that orchestrates the QMP and GDB servers:

```python
from dbxdebug import DOSBoxDebugger

debugger = DOSBoxDebugger()
debugger.run_program("C:\\MYGAME.EXE")  # Types command, sets break-on-exec, waits for GDB
```

### Option 2: Using QMP debug-break-on-exec

For manual or custom automation:

1. Connect GDB to DOSBox-X:
   ```bash
   gdb
   (gdb) target remote localhost:2159
   ```

2. Enable break-on-exec via QMP:
   ```bash
   echo '{"execute": "qmp_capabilities"}' | nc localhost 4444
   echo '{"execute": "debug-break-on-exec", "arguments": {"enabled": true}}' | nc localhost 4444
   ```

3. Type the program name at the DOS prompt using QMP send-key:
   ```bash
   # Type "GAME.EXE" followed by Enter
   echo '{"execute": "send-key", "arguments": {"keys": [{"type": "qcode", "data": "shift"}, {"type": "qcode", "data": "g"}]}}' | nc localhost 4444
   echo '{"execute": "send-key", "arguments": {"keys": [{"type": "qcode", "data": "a"}]}}' | nc localhost 4444
   # ... type remaining characters ...
   echo '{"execute": "send-key", "arguments": {"keys": [{"type": "qcode", "data": "ret"}]}}' | nc localhost 4444
   ```

4. When the program starts, GDB receives the breakpoint notification.

---

## Files

- `src/debug/gdbserver.cpp`, `include/gdbserver.h` - GDB server
- `src/debug/qmp.cpp`, `include/qmp.h` - QMP server
- `src/debug/debug.cpp` - Integration
- `tests/integration/` - Integration tests

---

## Integration Tests

Integration tests use Python with the [dbxdebug](https://pypi.org/project/dbxdebug/) client library. Tests are self-contained scripts using [PEP 723](https://peps.python.org/pep-0723/) inline metadata for dependency management.

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
