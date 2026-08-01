# Implementation Plan

## Outstanding Work

### 1. Raspberry Pi 4 Edge Integration

- Pi Camera RTSP streaming over the LAN has not been implemented.
- The runtime has not been supported or tested on Raspberry Pi Linux ARM64.
- The end-to-end flow has not been validated: Pi 4 -> RTSP -> cloud laptop -> recognition.

### 2. MQTT Control Plane

- MQTT broker/client integration has not been implemented.
- The planned topics do not yet exist: `motion/detected`, `system/status`, `error/*`, `control/*`, and `recognition/result`.
- There is no heartbeat, camera/RTSP status reporting, or cloud-to-edge stream-control command.
- PIR sensor support and motion-triggered streaming have not been implemented.

### 3. Consumers and Audit Logging

- No logging service subscribes to MQTT topics.
- Recognition audit trails, pipeline errors, and motion events are not persisted to SQLite/Postgres.
- Message schemas/contracts, QoS, and retained-message policies have not been defined per topic.

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
