# DOSBox-X GDB Server

DOSBox-X includes an experimental GDB remote debugging stub that allows external debuggers to connect and debug DOS programs running in the emulator.

## Building

The GDB server is an optional feature that must be enabled at compile time. It requires POSIX sockets and is currently supported on Linux, BSD, and macOS.

```bash
./build-debug --enable-gdbserver
```

Or manually:
```bash
./configure --enable-debug --enable-gdbserver
make
```

## Configuration

Add to the `[dosbox]` section of your configuration file:

```ini
[dosbox]
gdbserver=true
gdbserver port=2159
```

| Option | Default | Description |
|--------|---------|-------------|
| `gdbserver` | `false` | Enable/disable the GDB server |
| `gdbserver port` | `2159` | TCP port to listen on (requires restart to change) |

The server can also be toggled at runtime via **Debug > GDB Server** menu.

## Usage

```bash
gdb
(gdb) target remote localhost:2159
```

The server implements the [GDB Remote Serial Protocol](https://sourceware.org/gdb/current/onlinedocs/gdb.html/Remote-Protocol.html). Standard commands for reading/writing registers, memory access, stepping, breakpoints, and continue are supported.

### Register Mapping

Registers 0-7 map to EAX, ECX, EDX, EBX, ESP, EBP, ESI, EDI. Register 8 is EIP (linear address), 9 is EFLAGS, and 10-15 are segment registers (CS, SS, DS, ES, FS, GS).

### Memory Addressing

Addresses are linear physical addresses. For real-mode segmented addresses, compute `(segment << 4) + offset`.

## Custom Extensions

The server advertises a `keyboard+` feature for keystroke injection:

| Command | Description |
|---------|-------------|
| `k` | Read next pending keystroke (returns `00` if none) |
| `K<codes>` | Inject keystrokes (semicolon-separated key codes from `KBD_KEYS` enum) |

Example - inject 'A' key: `K1e`

Full format with explicit press/release: `K<keycode>,<state>` where state is `1` (press) or `0` (release).

## Limitations

- Linux/BSD/macOS only (POSIX sockets required)
- Software breakpoints only; hardware breakpoints/watchpoints not implemented
- Port changes require restart

## Files

- `src/debug/gdbserver.cpp`, `include/gdbserver.h` - GDB server implementation
- `src/debug/debug.cpp` - Integration with DOSBox-X debugger
