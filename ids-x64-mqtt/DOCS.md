# IDS X64 MQTT Bridge

Connects to an IDS X64 alarm panel via a USB-to-RS485 adapter and publishes
partition, zone, and trouble state to MQTT with Home Assistant Discovery.
All entities (partition status, zone sensors, arm/disarm buttons) appear
automatically in Home Assistant.

## Requirements

- USB-to-RS485 adapter plugged into the Raspberry Pi (appears as `/dev/ttyUSB0`)
- IDS X64 keypad bus D+/D- wired to the adapter's A/B terminals
- Mosquitto broker add-on installed and running

## Configuration

| Option | Description | Default |
|--------|-------------|---------|
| `serial_port` | Serial device path for the USB-RS485 adapter | `/dev/ttyUSB0` |
| `mqtt_broker` | MQTT broker hostname | `core-mosquitto` |
| `mqtt_port` | MQTT broker port | `1883` |
| `mqtt_username` | MQTT username | _(empty)_ |
| `mqtt_password` | MQTT password | _(empty)_ |
| `mqtt_topic_prefix` | Root topic for all published messages | `ids_x64` |
| `num_partitions` | Number of partitions on your panel (max 4) | `4` |
| `num_zones` | Number of zones on your panel (max 16) | `16` |
| `poll_interval` | How often to poll the panel in seconds | `10` |

### Finding your serial port

If the adapter is not at `/dev/ttyUSB0`, check the add-on log after starting —
it will show an error with the attempted port. Common alternatives: `/dev/ttyUSB1`,
`/dev/ttyACM0`.

### MQTT credentials

Use the username and password configured in the **Mosquitto broker** add-on, not
your Home Assistant login. If you haven't set credentials on Mosquitto, leave
both fields empty.

## Entities Created

Once running, the following entities appear automatically in Home Assistant:

| Type | Entities |
|------|---------|
| Sensor | Partition 1-4 Status, Last Event |
| Binary Sensor | Zone 1-16, Zone 1-16 Tamper, AC Fail, Battery Low, Siren Fault, Box Tamper |
| Button | Arm Away / Stay Arm / Disarm per partition, Arm/Disarm All, Cancel Alarm |

## MQTT Topics

### Published

| Topic | Payload |
|-------|---------|
| `ids_x64/partition/{1-4}/status` | `Disarmed` / `Stay Armed` / `Away Armed` / `ALARM` |
| `ids_x64/zone/{1-16}/state` | `ON` / `OFF` |
| `ids_x64/zone/{1-16}/tamper` | `ON` / `OFF` |
| `ids_x64/trouble/ac_fail` | `ON` / `OFF` |
| `ids_x64/trouble/battery_low` | `ON` / `OFF` |
| `ids_x64/trouble/siren_fault` | `ON` / `OFF` |
| `ids_x64/trouble/box_tamper` | `ON` / `OFF` |
| `ids_x64/event` | Event name (e.g. `ZONE VIOLATE`) |

### Commands (subscribed)

| Topic | Action |
|-------|--------|
| `ids_x64/command/cancel_alarm` | Cancel active alarm / clear latched panic |
| `ids_x64/command/partition/{1-4}/arm_away` | Arm away partition |
| `ids_x64/command/partition/{1-4}/stay_arm` | Stay arm partition |
| `ids_x64/command/partition/{1-4}/disarm` | Disarm partition |
| `ids_x64/command/partition/all/arm_away` | Arm away all partitions |
| `ids_x64/command/partition/all/disarm` | Disarm all partitions |
