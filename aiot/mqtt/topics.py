"""Shared MQTT topic names and default message policies."""

from __future__ import annotations

from dataclasses import dataclass


TOPIC_MOTION_DETECTED = "motion/detected"
TOPIC_SYSTEM_STATUS = "system/status"
TOPIC_CONTROL_STREAM = "control/stream"
TOPIC_RECOGNITION_RESULT = "recognition/result"
TOPIC_ERROR_RTSP = "error/rtsp"
TOPIC_ERROR_PIPELINE = "error/pipeline"

AUDIT_TOPICS = (
    TOPIC_RECOGNITION_RESULT,
    TOPIC_MOTION_DETECTED,
    "error/#",
)


@dataclass(frozen=True)
class TopicPolicy:
    qos: int
    retain: bool
    persist: bool


TOPIC_POLICIES = {
    TOPIC_MOTION_DETECTED: TopicPolicy(qos=1, retain=False, persist=True),
    TOPIC_SYSTEM_STATUS: TopicPolicy(qos=0, retain=True, persist=False),
    TOPIC_CONTROL_STREAM: TopicPolicy(qos=1, retain=False, persist=False),
    TOPIC_RECOGNITION_RESULT: TopicPolicy(qos=1, retain=False, persist=True),
    TOPIC_ERROR_RTSP: TopicPolicy(qos=1, retain=False, persist=True),
    TOPIC_ERROR_PIPELINE: TopicPolicy(qos=1, retain=False, persist=True),
}

