#!/usr/bin/env python3
"""
IDS X64 Keypad Bus Sniffer

Passively captures all RS485 traffic on the D+/D- keypad bus.
Writes timestamped frame logs to /data/captures/ for protocol analysis.
"""

import signal
import sys
import time
import logging
from datetime import datetime
from pathlib import Path

import serial
import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] sniffer: %(message)s",
)
log = logging.getLogger("sniffer")


class KeypadBusSniffer:
    def __init__(self, config_path: str):
        with open(config_path) as f:
            self.cfg = yaml.safe_load(f)

        self.port = self.cfg["serial"]["port"]
        self.baud = self.cfg["serial"].get("baud_rate", 9600)
        self.log_dir = Path(self.cfg.get("log_dir", "/data/captures"))
        self.frame_gap_ms = self.cfg.get("frame_gap_ms", 5)

        self.running = False
        self.ser = None
        self.log_file = None
        self.frame_count = 0
        self.byte_count = 0

    def _open_log(self):
        self.log_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_path = self.log_dir / f"capture_{ts}.txt"
        self.log_file = open(log_path, "w", buffering=1)
        log.info("Writing capture to %s", log_path)

        self.log_file.write("# IDS X64 Keypad Bus Capture\n")
        self.log_file.write(f"# Port     : {self.port} @ {self.baud} baud\n")
        self.log_file.write(f"# Frame gap: {self.frame_gap_ms} ms\n")
        self.log_file.write(f"# Started  : {datetime.now().isoformat()}\n")
        self.log_file.write("#\n")
        self.log_file.write("# Columns: TIMESTAMP | FRAME | LEN | HEX (spaced) | ASCII\n")
        self.log_file.write("#\n")

    def _log_frame(self, frame: bytes):
        self.frame_count += 1
        ts = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        hex_spaced = " ".join(f"{b:02x}" for b in frame)
        ascii_repr = "".join(chr(b) if 32 <= b < 127 else "." for b in frame)
        line = f"{ts} | F{self.frame_count:06d} | {len(frame):3d}B | {hex_spaced} | {ascii_repr}"

        log.info(line)
        if self.log_file:
            self.log_file.write(line + "\n")

    def run(self):
        self._open_log()
        self.running = True

        self.ser = serial.Serial(
            port=self.port,
            baudrate=self.baud,
            bytesize=serial.EIGHTBITS,
            parity=serial.PARITY_NONE,
            stopbits=serial.STOPBITS_ONE,
            timeout=self.frame_gap_ms / 1000.0,  # read timeout = frame gap
        )
        log.info("Opened %s at %d baud — listening passively...", self.port, self.baud)
        log.info("Frame boundary detection: gap > %d ms", self.frame_gap_ms)

        current_frame = bytearray()

        while self.running:
            try:
                data = self.ser.read(256)
                self.byte_count += len(data)

                if data:
                    current_frame.extend(data)
                else:
                    # Timeout expired — treat as frame boundary
                    if current_frame:
                        self._log_frame(bytes(current_frame))
                        current_frame = bytearray()

            except serial.SerialException:
                if self.running:
                    log.exception("Serial error")
                time.sleep(0.5)
            except Exception:
                if self.running:
                    log.exception("Unexpected error")
                time.sleep(0.1)

        # Flush any remaining bytes
        if current_frame:
            self._log_frame(bytes(current_frame))

        if self.log_file:
            self.log_file.write("#\n")
            self.log_file.write(f"# Ended  : {datetime.now().isoformat()}\n")
            self.log_file.write(f"# Frames : {self.frame_count}\n")
            self.log_file.write(f"# Bytes  : {self.byte_count}\n")
            self.log_file.close()

        if self.ser and self.ser.is_open:
            self.ser.close()

        log.info("Stopped. %d frames, %d bytes captured.", self.frame_count, self.byte_count)


def main():
    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    sniffer = KeypadBusSniffer(config_path)

    def handle_signal(signum, frame):
        sniffer.running = False

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    sniffer.run()


if __name__ == "__main__":
    main()
