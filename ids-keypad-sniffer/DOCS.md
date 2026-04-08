# IDS Keypad Bus Sniffer

Passively captures all RS485 traffic on the IDS X64 D+/D- keypad bus.
Writes timestamped frame log files to persistent storage for protocol analysis.

## Configuration

| Option | Description | Default |
|--------|-------------|---------|
| `serial_port` | Serial device for the USB-RS485 adapter | `/dev/ttyUSB0` |
| `baud_rate` | Bus baud rate — try 9600 first, then 4800 | `9600` |
| `frame_gap_ms` | Silence gap in ms used to detect frame boundaries | `5` |

## Wiring

Connect the USB-RS485 adapter to the IDS X64 keypad bus terminals:

```
Adapter A  →  Panel D+
Adapter B  →  Panel D-
```

If the log shows no data, swap A and B.

## Running a Capture Session

1. Install and start the add-on
2. Open **Log** tab — you will see one line per detected frame, e.g.:
   ```
   21:03:21.307 | F000001 |   7B | 57 bf 1c e1 3e 38 4d | W....8M
   ```
3. Let it run for at least **5 minutes** at idle (panel disarmed, no activity)
4. Then perform each action below, waiting 30 seconds between each:
   - Violate a zone (open a door/window)
   - Restore the zone
   - Arm the panel (Away) from the keypad
   - Disarm the panel from the keypad
   - Arm (Stay) from the keypad
   - Disarm again
   - Press the panic button briefly then cancel

After each action, note the **time** so you can find the corresponding frames in the log.

## Retrieving Log Files

Log files are saved to `/data/captures/` inside the add-on container.
Access them via:

- **Samba share**: `\\<ha-host>\addon_configs\<slug>\captures\`
- **SSH** (Advanced SSH add-on required): `/addon_configs/ids_keypad_sniffer/captures/`
- **File Editor add-on**: navigate to `/addon_configs/ids_keypad_sniffer/captures/`

Each session creates a new file named `capture_YYYYMMDD_HHMMSS.txt`.

## Log File Format

```
# IDS X64 Keypad Bus Capture
# Port     : /dev/ttyUSB0 @ 9600 baud
# Frame gap: 5 ms
#
# Columns: TIMESTAMP | FRAME | LEN | HEX (spaced) | ASCII
#
21:03:21.307 | F000001 |   7B | 57 bf 1c e1 3e 38 4d 00 | W....8M.
21:03:21.358 | F000002 |  13B | 04 1c 5d 30 98 fc 9c 36 | ..]0...6
```

- **TIMESTAMP** — wall-clock time of the last byte in the frame
- **FRAME** — sequential frame number
- **LEN** — byte count
- **HEX** — all bytes in hex, space-separated
- **ASCII** — printable bytes shown as characters, others as `.`

## Analysis Tips

### Finding the framing byte

Look for a byte value that:
- Appears at or near the **start** of most frames
- Has roughly consistent spacing (e.g. every N frames)
- Has a different value at the **end** of frames (ETX)

In the current captures the most frequent starting bytes are `0x57` and `0x59`.

### Identifying packet types

1. Sort/group frames by their first byte — each distinct value is likely a different packet type
2. Look for frames that change when you arm/disarm (compare idle vs armed captures)
3. Look for frames that change when a zone is violated

### Baud rate check

If frames look like noise (no repeating structure, lengths vary wildly), try changing
`baud_rate` to `4800`. Restart the add-on and capture again.

### Polarity check

If after swapping A/B the data pattern completely changes (different byte values), try
both and compare — the "correct" polarity will show more consistent repeating structure.
