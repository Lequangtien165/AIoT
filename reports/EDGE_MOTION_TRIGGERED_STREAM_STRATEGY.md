# Edge-Triggered Face Session Strategy (DONE)

## Chosen Parameters

| Parameter | Value |
|---|---:|
| Cloud `face_presence` interval | Every **15 seconds** while at least one face is detected |
| Edge face keepalive timeout | **120 seconds** after the last valid `face_presence` |
| Face discovery timeout | **30 seconds** after the stream is ready without an initial face presence |

There is no maximum session duration. A session continues while the cloud keeps detecting faces and renews the lease. This is an intentionally accepted behavior.

## Architectural Principles

- When idle, the edge owns the camera for a lightweight motion detector.
- When streaming, FFmpeg owns the camera to publish RTSP; the edge motion detector stops completely.
- The cloud receives RTSP, detects faces, serves the web view, and sends face-presence leases to the edge.
- The edge keeps a stream alive based on cloud face detection, not recognized identity.
- Unknown faces renew the stream lease just like known faces.

This prevents two processes from contending for the camera.

## Edge State Flow

```text
MONITORING
  -> significant motion
STARTING_STREAM
  -> RTSP publisher ready
AWAITING_FACE
  -> cloud reports initial face_presence within 30 seconds
STREAMING
  -> no face_presence for 120 seconds
STOPPING_STREAM
  -> FFmpeg stops and releases the camera
MONITORING
```

### MONITORING

- The edge motion detector owns the camera.
- It runs at a low resolution and frame rate.
- It uses a significant-motion threshold, debounce, and optional ROI filtering.
- The FFmpeg publisher is not running.
- MediaMTX may remain persistent because it is lightweight.

When motion crosses the trigger threshold:

1. Stop the motion detector and release its camera handle completely.
2. Generate a `stream_session_id`.
3. Publish state `starting`.
4. Start the FFmpeg publisher.

### STARTING_STREAM

- FFmpeg owns the camera and publishes to MediaMTX.
- The edge waits until the RTSP publisher/path is ready.

If startup fails:

1. Publish `error/rtsp`.
2. Publish state `error`.
3. Clean up FFmpeg.
4. Return to `MONITORING`.

When RTSP is ready:

- Publish state `streaming` with `device_id` and `stream_session_id`.
- The cloud can now connect to RTSP.
- Enter `AWAITING_FACE` with a 30-second discovery deadline.

### AWAITING_FACE

- FFmpeg owns the camera.
- The edge motion detector does not run.
- The cloud receives `streaming`, connects or reconnects to RTSP, and runs face detection.

If the edge receives a valid `face_presence` for its current `device_id` and `stream_session_id`:

- Enter `STREAMING`.
- Set the deadline to `now + 120 seconds`.

If no valid face presence arrives within 30 seconds:

- Stop the stream.
- Return to `MONITORING`.

### STREAMING

- The cloud publishes `face_presence` every 15 seconds only while its detector sees at least one face.
- Every valid message resets the deadline:

```text
deadline = edge_monotonic_now + 120 seconds
```

- Continuous face-presence messages keep the session active.
- If no presence message arrives for 120 seconds, enter `STOPPING_STREAM`.

### STOPPING_STREAM

1. Publish state `stopping`.
2. Stop FFmpeg and wait for it to exit.
3. Publish state `monitoring`.
4. Reopen the camera in the motion detector.
5. Return to `MONITORING`.

## MQTT Protocol

### Edge Status

Use device-scoped topics:

```text
system/status/<device_id>
error/rtsp/<device_id>
```

Supported state values:

```text
monitoring
starting
streaming
stopping
error
```

A `streaming` status message must include:

```json
{
  "schema_version": 1,
  "device_id": "pi4-edge-01",
  "stream_session_id": "generated-session-id",
  "state": "streaming",
  "component": "rtsp-publisher"
}
```

The cloud only connects to RTSP after it receives state `streaming`.

### Cloud Face-Presence Keepalive

Use a topic separate from ordinary stream commands:

```text
stream/activity/<device_id>
```

Payload:

```json
{
  "schema_version": 1,
  "device_id": "pi4-edge-01",
  "stream_session_id": "generated-session-id",
  "action": "face_presence",
  "face_count": 1
}
```

Edge validation rules:

- Accept only the current `device_id`.
- Accept only the current `stream_session_id`.
- Require a valid schema and action.
- Do not retain these messages.
- Renew the lease only when `face_count >= 1`.
- Calculate expiry with the edge's local monotonic clock, not a cloud timestamp.

## Cloud Behavior

When the cloud receives `system/status/<device_id>` with state `streaming`:

1. Connect or reconnect to RTSP.
2. Run detection and recognition.
3. Render the annotated frame.
4. Relay it to the web service.
5. When the detector sees at least one face, publish `face_presence` every 15 seconds.
6. When no face is detected, do not renew the lease; the edge expires it after 120 seconds.

The cloud does not need to send an explicit stop command for this lifecycle.

## Web Relay

The recognition pipeline renders each frame once:

```text
RTSP -> detection/recognition -> annotated frame
                              -> MQTT recognition/result
                              -> optional local cv2 preview
                              -> latest JPEG buffer -> web MJPEG
```

In web or headless mode:

- Do not call `cv2.imshow`.
- Do not open a local preview window.
- Use a latest annotated JPEG buffer for the web service MJPEG response.
- Feed web UI status, motion, recognition, and error updates through MQTT to WebSocket or SSE.
