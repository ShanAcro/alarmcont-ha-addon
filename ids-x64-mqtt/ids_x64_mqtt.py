#!/usr/bin/env python3
"""
IDS X64 Alarm Panel — MQTT Bridge for Raspberry Pi USB-RS485

Reads the IDS X64 keypad bus via a USB-to-RS485 adapter and publishes
partition/zone/trouble/event state to MQTT with Home Assistant Discovery.
Subscribes to command topics for arm/disarm control.

IDS X64 RS485 keypad bus protocol implementation.
"""

import json
import logging
import signal
import struct
import sys
import threading
import time
from pathlib import Path

import paho.mqtt.client as mqtt
import serial
import yaml

# ── Logging ──────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("ids_x64")

# ── Protocol constants ───────────────────────────────────────────
STX = 0x58  # 'X'
ETX = 0x5A  # 'Z'
MAX_PACKET = 256

PART_DISARMED = 0
PART_STAY_ARMED = 1
PART_AWAY_ARMED = 2
PART_ALARM = 3

PARTITION_STRINGS = {
    PART_DISARMED: "Disarmed",
    PART_STAY_ARMED: "Stay Armed",
    PART_AWAY_ARMED: "Away Armed",
    PART_ALARM: "ALARM",
}

# ── Event name table ─────────────────────────────────────────────
EVENT_NAMES = [
    "All Doors",
    "Door 1", "Door 2", "Door 3", "Door 4",
    "Door 5", "Door 6", "Door 7", "Door 8",
    "CLOSE - USER",
    "STAY CLOSE - USER",
    "OPEN - USER",
    "CANCEL - USER",
    "ACCESS - USER",
    "ZONE VIOLATE",
    "ZONE ALARM RESTORE",
    "ZONE BYPASS",
    "ZONE FORCE",
    "ZONE TAMPER",
    "ZONE TAMPER RESTORE",
    "ZONE SHUTDOWN",
    "ZONE SHUTDOWN RESTORE",
    "AC FAIL",
    "COMS FAIL",
    "LINE TAMPER",
    "SIREN FAIL",
    "BATTERY LOW",
    "AUX12V FUSE",
    "INSTALLER RESET",
    "BOX TAMPER",
    "BUS DEVICE TAMPER",
    "BUS COMMS FAIL",
    "LOW BATTERY",
    "BUS DEVICE BATTERY FAIL",
    "AC RESTORE",
    "COMS RESTORE",
    "LINE TAMPER RESTORE",
    "SIREN RESTORE",
    "BATTERY RESTORE",
    "AUX12V RESTORE",
    "INSTALLER RESET RESTORE",
    "BOX TAMPER RESTORE",
    "BUS DEVICE TAMPER RESTORE",
    "BUS COMMS FAIL RESTORE",
    "BUS DEVICE BATTERY RESTORE",
    "DEDICATED PANIC",
    "AUTO TEST",
    "DOWNLOAD",
    "DURESS - USER",
    "PANIC",
    "KP FIRE",
    "KP MEDICAL",
    "KP LOCKOUT",
    "CANCEL AUTO ARM - USER",
    "USER CODE CHANGE",
    "INSTALLER MODE",
    "DEFAULT USER",
    "POWER UP",
    "DEFAULT PANEL",
    "AUX OP CHANGE",
    "AC CLOCK",
    "EXTERNAL CLOCK",
    "INSTALLER CHANGE",
    "VERIFIED ALARM",
    "STAY OPEN - USER",
    "KEY CODE", "ENTRY CARD CODE",
    "EXIT CARD CODE", "KEY HOLD",
    "KEY PRESS", "RX EDIT DATA",
    "DTMF DOOR", "REMOTE CODE",
    "192 DAYS PASSED",
    "USER BYPASSED ZONES",
    "DMTF LOGIN - USER",
    "DOWNLOAD LOGIN FAIL",
    "RF DETECTOR LOW BATTERY",
    "RF DETECTOR SUPERVISION LOSS",
    "RF RECEIVER JAM",
    "RF DETECTOR LOW RSSI",
    "RF DETECTOR LOW BATTERY RESTORE",
    "RF DETECTOR SUPERVISION LOSS RESTORE",
    "RF RECEIVER JAM RESTORE",
    "RF DETECTOR LOW RSSI RESTORE",
    "USER MENU ACCESS",
    "STAY ZONE",
    "TIME STAMP",
    "MPS AC FAIL",
    "MPS LOW BATT",
    "MPS FUSE FAIL",
    "MPS AC RESTORE",
    "MPS BATT RESTORE",
    "MPS FUSE RESTORE",
    "EXIT DELAY",
    "DTMF LOGIN LOCKOUT",
    "USER UNBYPASSED ZONES",
    "ENTRY DELAY",
    "CROSS ZONE TRIGGERED",
    "FORCED DOOR",
    "RECEIVED ARMING TAG",
    "RECEIVED ARMING REMOTE",
    "REMOTE PANIC",
    "TAMPER ALARM",
    "FIRE ALARM",
    "NO EVENT",
    "ARMED BY ZONE",
    "ARMED BY 1 KEY",
    "ARMED BY 5 KEY",
    "ARMED BY 6 KEY",
    "AUTO ARM",
    "ARMED BY DOWNLOAD SW",
    "DISARMED BY FIRE KEY",
    "DISARMED BY FIRE ZONE",
    "PERMITTED", "PERMITTED (DOOR OFFLINE)",
    "DENIED (DOOR OFFLINE)",
    "DENIED (PARTITION ARMED)",
    "DENIED (NOT ALLOWED)",
    "UNKNOWN CARD",
    "EXIT PUSH BUTTON",
    "TAMPER",
    "DOOR LEFT OPEN",
    "DOOR KEEP OPEN",
    "DOOR NORMAL OPERATION",
    "WATCHDOG RESET",
    "BROWNOUT RESET",
    "SOFTWARE RESET",
    "STACK OVERFLOW RESET",
    "STACK UNDERFLOW RESET",
    "FIRE DOOR OPEN",
    "EVENT LOG ERROR",
]

# Trouble event codes and their restore counterparts
TROUBLE_EVENTS = {
    0x16: ("ac_fail", True),
    0x22: ("ac_fail", False),
    0x1A: ("battery_low", True),
    0x20: ("battery_low", True),
    0x26: ("battery_low", False),
    0x19: ("siren_fault", True),
    0x25: ("siren_fault", False),
    0x1D: ("box_tamper", True),
    0x29: ("box_tamper", False),
}


# ── CRC — Modified Fletcher-16 (accumulators init 0xFF) ──────────
def ids_crc(data: bytes) -> tuple[int, int]:
    """Compute the IDS X64 modified Fletcher-16 checksum."""
    a1 = 0xFF
    a2 = 0xFF
    i = 0
    remaining = len(data)
    while remaining > 0:
        chunk = min(remaining, 21)
        remaining -= chunk
        for _ in range(chunk):
            a1 = (a1 + data[i]) & 0xFFFF
            a2 = (a2 + a1) & 0xFFFF
            i += 1
        a1 = (a1 >> 8) + (a1 & 0xFF)
        a2 = (a2 >> 8) + (a2 & 0xFF)
    a2f = (a2 >> 8) + (a2 & 0xFF)
    hi = ((a1 >> 8) + (a1 & 0xFF)) & 0xFF
    lo = a2f & 0xFF
    return hi, lo


def ids_verify(pkt: bytes) -> bool:
    """Validate CRC on a complete packet (STX..ETX)."""
    if len(pkt) < 4:
        return False
    hi, lo = ids_crc(pkt[1:-3])  # bytes between STX and CRC
    return hi == pkt[-3] and lo == pkt[-2]


def ids_build_packet(inner: bytes) -> bytes:
    """Build a complete packet: STX + inner + CRC + ETX."""
    hi, lo = ids_crc(inner)
    return bytes([STX]) + inner + bytes([hi, lo, ETX])


# ── Command builders ─────────────────────────────────────────────
# Inner bytes: [0x02][0x01][0x00][0x04][0x41][0x02][CMD][PART]
#   CMD:  0x61 = Arm Away, 0x53 = Stay Arm, 0x41 = Disarm
#   PART: bitmask — 0x01=P1, 0x02=P2, 0x04=P3, 0x08=P4, 0xFF=All

def cmd_arm_away(partition_mask: int) -> bytes:
    return ids_build_packet(bytes([0x02, 0x01, 0x00, 0x04, 0x41, 0x02, 0x61, partition_mask]))

def cmd_stay_arm(partition_mask: int) -> bytes:
    return ids_build_packet(bytes([0x02, 0x01, 0x00, 0x04, 0x41, 0x02, 0x53, partition_mask]))

def cmd_disarm(partition_mask: int) -> bytes:
    return ids_build_packet(bytes([0x02, 0x01, 0x00, 0x04, 0x41, 0x02, 0x41, partition_mask]))

def cmd_poll_status_a() -> bytes:
    return ids_build_packet(bytes([0x04, 0x01, 0x00, 0x03, 0x53, 0x01, 0x41]))

def cmd_poll_status_s() -> bytes:
    return ids_build_packet(bytes([0x04, 0x01, 0x00, 0x03, 0x53, 0x01, 0x53]))

def cmd_poll_zones() -> bytes:
    return ids_build_packet(bytes([0x04, 0x01, 0x00, 0x03, 0x51, 0x01, 0x56]))


# ── MQTT Bridge ──────────────────────────────────────────────────
class IdsX64MqttBridge:
    def __init__(self, config_path: str = "config.yaml"):
        self.cfg = self._load_config(config_path)
        self.num_partitions = self.cfg["panel"]["num_partitions"]
        self.num_zones = self.cfg["panel"]["num_zones"]
        self.zone_groups = (self.num_zones + 7) // 8
        self.poll_interval = self.cfg["panel"]["poll_interval_seconds"]
        self.topic_prefix = self.cfg["mqtt"]["topic_prefix"]
        self.discovery_prefix = self.cfg["mqtt"]["discovery_prefix"]

        self.ser: serial.Serial | None = None
        self.mqttc: mqtt.Client | None = None
        self.running = False
        self.serial_lock = threading.Lock()

        # RX state machine
        self.rx_buf = bytearray()
        self.in_packet = False
        self.expected_len = -1

    @staticmethod
    def _load_config(path: str) -> dict:
        config_file = Path(path)
        if not config_file.exists():
            # Try relative to script directory
            config_file = Path(__file__).parent / path
        with open(config_file) as f:
            return yaml.safe_load(f)

    # ── Serial ───────────────────────────────────────────────────
    def open_serial(self):
        cfg = self.cfg["serial"]
        self.ser = serial.Serial(
            port=cfg["port"],
            baudrate=cfg["baud_rate"],
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=0.05,
        )
        log.info("Opened serial port %s at %d baud", cfg["port"], cfg["baud_rate"])

    def send_packet(self, packet: bytes):
        with self.serial_lock:
            if self.ser and self.ser.is_open:
                self.ser.write(packet)
                self.ser.flush()
                log.info("TX: %s", packet.hex())

    # ── MQTT ─────────────────────────────────────────────────────
    def connect_mqtt(self):
        cfg = self.cfg["mqtt"]
        self.mqttc = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        if cfg.get("username"):
            self.mqttc.username_pw_set(cfg["username"], cfg.get("password", ""))
        self.mqttc.will_set(
            f"{self.topic_prefix}/status", "offline", retain=True
        )
        self.mqttc.on_connect = self._on_mqtt_connect
        self.mqttc.on_message = self._on_mqtt_message
        self.mqttc.connect(cfg["broker"], cfg["port"])
        self.mqttc.loop_start()

    def _on_mqtt_connect(self, client, userdata, flags, rc, properties=None):
        log.info("Connected to MQTT broker (rc=%s)", rc)
        client.publish(f"{self.topic_prefix}/status", "online", retain=True)
        # Subscribe to command topics
        client.subscribe(f"{self.topic_prefix}/command/#")
        # Publish HA discovery configs
        self._publish_discovery()

    def _on_mqtt_message(self, client, userdata, msg):
        topic = msg.topic
        payload = msg.payload.decode("utf-8", errors="ignore").strip().upper()
        log.info("MQTT command: %s = %s", topic, payload)

        prefix = f"{self.topic_prefix}/command/"
        if not topic.startswith(prefix):
            return

        parts = topic[len(prefix):].split("/")
        # cancel_alarm — clears latched panic/alarm (disarm all partitions)
        if parts == ["cancel_alarm"]:
            log.info("Cancel alarm — sending disarm-all")
            self.send_packet(cmd_disarm(0xFF))
            return

        # Expected: partition/{1-4|all}/{arm_away|stay_arm|disarm}
        if len(parts) == 3 and parts[0] == "partition":
            partition_str = parts[1]
            action = parts[2]

            if partition_str == "all":
                mask = 0xFF
            else:
                try:
                    p = int(partition_str)
                    if 1 <= p <= self.num_partitions:
                        mask = 1 << (p - 1)
                    else:
                        log.warning("Invalid partition number: %s", partition_str)
                        return
                except ValueError:
                    log.warning("Invalid partition: %s", partition_str)
                    return

            if action == "arm_away":
                self.send_packet(cmd_arm_away(mask))
            elif action == "stay_arm":
                self.send_packet(cmd_stay_arm(mask))
            elif action == "disarm":
                self.send_packet(cmd_disarm(mask))
            else:
                log.warning("Unknown action: %s", action)

    def _publish_discovery(self):
        """Publish Home Assistant MQTT Discovery configs."""
        device_info = {
            "identifiers": ["ids_x64_alarm"],
            "name": "IDS X64 Alarm Panel",
            "manufacturer": "IDS",
            "model": "X64",
        }

        # Partition status sensors
        for i in range(1, self.num_partitions + 1):
            uid = f"ids_x64_partition_{i}"
            self.mqttc.publish(
                f"{self.discovery_prefix}/sensor/{uid}/config",
                json.dumps({
                    "name": f"Partition {i} Status",
                    "unique_id": uid,
                    "state_topic": f"{self.topic_prefix}/partition/{i}/status",
                    "icon": "mdi:shield-home",
                    "device": device_info,
                }),
                retain=True,
            )

        # Zone sensors
        for i in range(1, self.num_zones + 1):
            # Zone open/violated
            uid_zone = f"ids_x64_zone_{i}"
            self.mqttc.publish(
                f"{self.discovery_prefix}/binary_sensor/{uid_zone}/config",
                json.dumps({
                    "name": f"Zone {i}",
                    "unique_id": uid_zone,
                    "state_topic": f"{self.topic_prefix}/zone/{i}/state",
                    "payload_on": "ON",
                    "payload_off": "OFF",
                    "device_class": "motion",
                    "device": device_info,
                }),
                retain=True,
            )
            # Zone tamper
            uid_tamper = f"ids_x64_zone_{i}_tamper"
            self.mqttc.publish(
                f"{self.discovery_prefix}/binary_sensor/{uid_tamper}/config",
                json.dumps({
                    "name": f"Zone {i} Tamper",
                    "unique_id": uid_tamper,
                    "state_topic": f"{self.topic_prefix}/zone/{i}/tamper",
                    "payload_on": "ON",
                    "payload_off": "OFF",
                    "device_class": "tamper",
                    "device": device_info,
                }),
                retain=True,
            )

        # Trouble sensors
        for trouble_id, label in [
            ("ac_fail", "AC Power Fail"),
            ("battery_low", "Battery Low"),
            ("siren_fault", "Siren Fault"),
            ("box_tamper", "Box Tamper"),
        ]:
            uid = f"ids_x64_{trouble_id}"
            dev_class = "tamper" if "tamper" in trouble_id else (
                "battery" if "battery" in trouble_id else "problem"
            )
            self.mqttc.publish(
                f"{self.discovery_prefix}/binary_sensor/{uid}/config",
                json.dumps({
                    "name": label,
                    "unique_id": uid,
                    "state_topic": f"{self.topic_prefix}/trouble/{trouble_id}",
                    "payload_on": "ON",
                    "payload_off": "OFF",
                    "device_class": dev_class,
                    "device": device_info,
                }),
                retain=True,
            )

        # Last event sensor
        self.mqttc.publish(
            f"{self.discovery_prefix}/sensor/ids_x64_last_event/config",
            json.dumps({
                "name": "Last Event",
                "unique_id": "ids_x64_last_event",
                "state_topic": f"{self.topic_prefix}/event",
                "icon": "mdi:bell-alert",
                "device": device_info,
            }),
            retain=True,
        )

        # Arm/disarm buttons
        for i in range(1, self.num_partitions + 1):
            for action, label, icon in [
                ("arm_away", "Arm Away", "mdi:shield-lock"),
                ("stay_arm", "Stay Arm", "mdi:shield-half-full"),
                ("disarm", "Disarm", "mdi:shield-off"),
            ]:
                uid = f"ids_x64_{action}_p{i}"
                self.mqttc.publish(
                    f"{self.discovery_prefix}/button/{uid}/config",
                    json.dumps({
                        "name": f"{label} Partition {i}",
                        "unique_id": uid,
                        "command_topic": f"{self.topic_prefix}/command/partition/{i}/{action}",
                        "payload_press": "PRESS",
                        "icon": icon,
                        "device": device_info,
                    }),
                    retain=True,
                )

        # Cancel alarm button
        self.mqttc.publish(
            f"{self.discovery_prefix}/button/ids_x64_cancel_alarm/config",
            json.dumps({
                "name": "Cancel Alarm",
                "unique_id": "ids_x64_cancel_alarm",
                "command_topic": f"{self.topic_prefix}/command/cancel_alarm",
                "payload_press": "PRESS",
                "icon": "mdi:bell-cancel",
                "device": device_info,
            }),
            retain=True,
        )

        # All-partition buttons
        for action, label, icon in [
            ("arm_away", "Arm Away All", "mdi:shield-lock"),
            ("stay_arm", "Stay Arm All", "mdi:shield-half-full"),
            ("disarm", "Disarm All", "mdi:shield-off"),
        ]:
            uid = f"ids_x64_{action}_all"
            self.mqttc.publish(
                f"{self.discovery_prefix}/button/{uid}/config",
                json.dumps({
                    "name": label,
                    "unique_id": uid,
                    "command_topic": f"{self.topic_prefix}/command/partition/all/{action}",
                    "payload_press": "PRESS",
                    "icon": icon,
                    "device": device_info,
                }),
                retain=True,
            )

        log.info("Published HA MQTT Discovery configs")

    def mqtt_publish(self, subtopic: str, value: str, retain: bool = True):
        if self.mqttc:
            self.mqttc.publish(f"{self.topic_prefix}/{subtopic}", value, retain=retain)

    # ── Packet processing ────────────────────────────────────────
    def process_packet(self, pkt: bytes):
        if len(pkt) < 8:
            return
        ptype = pkt[1]
        plen = (pkt[3] << 8) | pkt[4]
        payload = pkt[5 : 5 + plen]

        log.info("RX type=0x%02X len=%d payload=%s", ptype, plen, payload.hex())

        # ── Partition status (type=0x00) ─────────────────────────
        if ptype == 0x00 and plen >= 1:
            for i in range(min(self.num_partitions, plen)):
                status_str = PARTITION_STRINGS.get(payload[i] & 0x03, "Unknown")
                self.mqtt_publish(f"partition/{i + 1}/status", status_str)
                log.info("Partition %d: %s", i + 1, status_str)

        # ── Zone status (type=0x04, sub-cmd 0x51) ───────────────
        if ptype == 0x04 and plen >= 4 and payload[0] == 0x51:
            zdata = payload[2:]  # skip sub-cmd bytes
            available_groups = len(zdata) // 3
            for grp in range(min(available_groups, self.zone_groups)):
                open_bits = zdata[grp * 3 + 0]
                viol_bits = zdata[grp * 3 + 1]
                tamp_bits = zdata[grp * 3 + 2]
                for bit in range(8):
                    zi = grp * 8 + bit + 1  # 1-indexed
                    if zi <= self.num_zones:
                        is_open = bool((open_bits >> bit) & 1)
                        is_tampered = bool((tamp_bits >> bit) & 1)
                        self.mqtt_publish(
                            f"zone/{zi}/state", "ON" if is_open else "OFF"
                        )
                        self.mqtt_publish(
                            f"zone/{zi}/tamper", "ON" if is_tampered else "OFF"
                        )

        # ── Event notifications ──────────────────────────────────
        if ptype == 0x04 and plen >= 3:
            event_code = payload[2]
            if event_code < len(EVENT_NAMES):
                event_name = EVENT_NAMES[event_code]
                self.mqtt_publish("event", event_name)
                log.info("Event: %s (0x%02X)", event_name, event_code)

                # Update trouble sensors
                if event_code in TROUBLE_EVENTS:
                    trouble_id, state = TROUBLE_EVENTS[event_code]
                    self.mqtt_publish(
                        f"trouble/{trouble_id}", "ON" if state else "OFF"
                    )

    # ── RX state machine ─────────────────────────────────────────
    def rx_byte(self, b: int):
        if not self.in_packet:
            if b == STX:
                self.rx_buf = bytearray([b])
                self.expected_len = -1
                self.in_packet = True
            return

        if len(self.rx_buf) >= MAX_PACKET:
            self.in_packet = False
            self.rx_buf.clear()
            return

        self.rx_buf.append(b)

        if len(self.rx_buf) == 5 and self.expected_len == -1:
            self.expected_len = (self.rx_buf[3] << 8) | self.rx_buf[4]

        if b == ETX and (
            self.expected_len == -1
            or len(self.rx_buf) >= self.expected_len + 8
        ):
            pkt = bytes(self.rx_buf)
            if ids_verify(pkt):
                self.process_packet(pkt)
            else:
                log.warning("CRC fail (%d bytes)", len(pkt))
            self.in_packet = False
            self.rx_buf.clear()
            self.expected_len = -1

    # ── Main loops ───────────────────────────────────────────────
    def poll_loop(self):
        """Periodically poll partition status and zone status."""
        while self.running:
            try:
                self.send_packet(cmd_poll_status_a())
                time.sleep(0.5)
                self.send_packet(cmd_poll_status_s())
                time.sleep(1.0)
                self.send_packet(cmd_poll_zones())
            except Exception:
                log.exception("Error in poll loop")
            # Sleep in small increments so we can exit promptly
            for _ in range(self.poll_interval * 10):
                if not self.running:
                    break
                time.sleep(0.1)

    def read_loop(self):
        """Continuously read bytes from the serial port."""
        while self.running:
            try:
                if self.ser and self.ser.is_open:
                    data = self.ser.read(128)
                    if data:
                        log.info("RX raw (%d bytes): %s", len(data), data.hex())
                    for b in data:
                        self.rx_byte(b)
            except serial.SerialException:
                if self.running:
                    log.exception("Serial read error")
                time.sleep(1)
            except Exception:
                if self.running:
                    log.exception("Error in read loop")
                time.sleep(0.1)

    def run(self):
        self.running = True
        self.open_serial()
        self.connect_mqtt()

        read_thread = threading.Thread(target=self.read_loop, daemon=True)
        poll_thread = threading.Thread(target=self.poll_loop, daemon=True)
        read_thread.start()
        poll_thread.start()

        log.info(
            "IDS X64 MQTT bridge running — %d partitions, %d zones, polling every %ds",
            self.num_partitions, self.num_zones, self.poll_interval,
        )

        try:
            while self.running:
                time.sleep(0.5)
        except KeyboardInterrupt:
            pass
        finally:
            self.stop()

    def stop(self):
        log.info("Shutting down...")
        self.running = False
        if self.mqttc:
            self.mqttc.publish(
                f"{self.topic_prefix}/status", "offline", retain=True
            )
            self.mqttc.loop_stop()
            self.mqttc.disconnect()
        if self.ser and self.ser.is_open:
            self.ser.close()


def main():
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    bridge = IdsX64MqttBridge(config_path)

    def handle_signal(signum, frame):
        bridge.stop()

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    bridge.run()


if __name__ == "__main__":
    main()
