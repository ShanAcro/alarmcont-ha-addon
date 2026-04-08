#!/usr/bin/with-contenv bashio

SERIAL_PORT=$(bashio::config 'serial_port')
BAUD_RATE=$(bashio::config 'baud_rate')
FRAME_GAP=$(bashio::config 'frame_gap_ms')

bashio::log.info "Starting IDS Keypad Bus Sniffer..."
bashio::log.info "Serial port : ${SERIAL_PORT}"
bashio::log.info "Baud rate   : ${BAUD_RATE}"
bashio::log.info "Frame gap   : ${FRAME_GAP}ms"

cat > /tmp/sniffer_config.yaml <<EOF
serial:
  port: "${SERIAL_PORT}"
  baud_rate: ${BAUD_RATE}
log_dir: /share/ids_sniffer
frame_gap_ms: ${FRAME_GAP}
EOF

exec python3 /app/sniffer.py /tmp/sniffer_config.yaml
