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

### Key Names (QKeyCode)

Standard QEMU key names: `a`-`z`, `0`-`9`, `f1`-`f12`, `ret`, `esc`, `tab`, `spc`, `shift`, `ctrl`, `alt`, `caps_lock`, `left`, `right`, `up`, `down`, `insert`, `delete`, `home`, `end`, `pgup`, `pgdn`, `kp_0`-`kp_9`, etc.

See [QEMU QKeyCode](https://www.qemu.org/docs/master/interop/qemu-qmp-ref.html) for full list.

---

## Files

- `src/debug/gdbserver.cpp`, `include/gdbserver.h` - GDB server
- `src/debug/qmp.cpp`, `include/qmp.h` - QMP server
- `src/debug/debug.cpp` - Integration

---

## TODO

- [ ] Windows support (currently POSIX sockets only)
- [ ] Hardware breakpoints/watchpoints for GDB server
- [ ] Mouse input support for QMP server
- [ ] Integration tests
