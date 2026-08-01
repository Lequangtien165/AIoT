# Implementation Plan

## Outstanding Work

### 1. Raspberry Pi 4 Edge Integration

- Pi Camera RTSP streaming over the LAN has not been implemented.
- The runtime has not been supported or tested on Raspberry Pi Linux ARM64.
- The end-to-end flow has not been validated: Pi 4 -> RTSP -> cloud laptop -> recognition.

### 2. MQTT Control Plane

- MQTT broker/client integration has been implemented as an optional runtime path using `paho-mqtt`.
- The planned topics now exist in source: `motion/detected`, `system/status`, `error/*`, `control/stream`, and `recognition/result`.
- `stream_server.py` can publish RTSP status/heartbeat messages and subscribe to `control/stream` for a stop command.
- `recognize_stream.py` can publish `recognition/result`, recognition lifecycle status, and `error/pipeline`.
- PIR sensor support and motion-triggered streaming have not been implemented.
- Broker-level runtime validation with Mosquitto has not been performed yet.

### 3. Consumers and Audit Logging

- A logging service has been implemented at `scripts/run_mqtt_logger.py`.
- Recognition audit trails, pipeline errors, and motion events are persisted to SQLite at `database/audit_log.sqlite3` by default.
- Message payload builders, topic constants, QoS, retained-message policy, and audit topic subscriptions are defined under `aiot/mqtt/`.
- Unit tests cover schema builders, topic coverage, CLI MQTT flags, and SQLite audit persistence.
- End-to-end validation with a live MQTT broker and real Pi-originated messages has not been performed yet.

### 4. Live-Surveillance Web Application

- No Flask/FastAPI web server exists.
- There is no browser UI displaying live video with annotated bounding boxes and names.
- No MJPEG, WebSocket, HLS, or WebRTC output transports annotated video to web clients.
- The web UI does not receive or update from `recognition/result` events.

### 5. Real-World Validation and Tuning

- A complete enrollment dataset for real users has not been created.
- The recognition threshold has not been calibrated beyond the default `0.45`.
- FPS, recognition latency, GPU/CPU/RAM usage, multiple-face behavior, and sustained runtime have not been benchmarked.
- Long-running RTSP disconnection/reconnection, snapshot/video storage usage, and VRAM stability have not been tested.
