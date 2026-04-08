#!/usr/bin/with-contenv bashio

bashio::log.info "Starting IDS X64 MQTT Bridge..."

SERIAL_PORT=$(bashio::config 'serial_port')
MQTT_BROKER=$(bashio::config 'mqtt_broker')
MQTT_PORT=$(bashio::config 'mqtt_port')
MQTT_USERNAME=$(bashio::config 'mqtt_username')
MQTT_PASSWORD=$(bashio::config 'mqtt_password')
TOPIC_PREFIX=$(bashio::config 'mqtt_topic_prefix')
NUM_PARTITIONS=$(bashio::config 'num_partitions')
NUM_ZONES=$(bashio::config 'num_zones')
POLL_INTERVAL=$(bashio::config 'poll_interval')

bashio::log.info "Serial port : ${SERIAL_PORT}"
bashio::log.info "MQTT broker : ${MQTT_BROKER}:${MQTT_PORT}"
bashio::log.info "Partitions  : ${NUM_PARTITIONS}  Zones: ${NUM_ZONES}"

cat > /tmp/bridge_config.yaml << EOF
serial:
  port: ${SERIAL_PORT}
  baud_rate: 9600

mqtt:
  broker: ${MQTT_BROKER}
  port: ${MQTT_PORT}
  username: "${MQTT_USERNAME}"
  password: "${MQTT_PASSWORD}"
  topic_prefix: ${TOPIC_PREFIX}
  discovery_prefix: homeassistant

panel:
  num_partitions: ${NUM_PARTITIONS}
  num_zones: ${NUM_ZONES}
  poll_interval_seconds: ${POLL_INTERVAL}
EOF

exec python3 /app/ids_x64_mqtt.py /tmp/bridge_config.yaml
