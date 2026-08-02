"""Shared MQTT topic names and default message policies."""

from __future__ import annotations

from dataclasses import dataclass


TOPIC_MOTION_DETECTED = "motion/detected"
TOPIC_SYSTEM_STATUS = "system/status"
TOPIC_CONTROL_STREAM = "control/stream"
TOPIC_RECOGNITION_RESULT = "recognition/result"
TOPIC_ERROR_RTSP = "error/rtsp"
TOPIC_ERROR_PIPELINE = "error/pipeline"
TOPIC_STREAM_ACTIVITY = "stream/activity"

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
    TOPIC_STREAM_ACTIVITY: TopicPolicy(qos=1, retain=False, persist=False),
}


def topic_for_device(base_topic: str, device_id: str) -> str:
    clean_device_id = device_id.strip().strip("/")
    if not clean_device_id:
        raise ValueError("device_id is required for per-device MQTT topics.")
    return f"{base_topic}/{clean_device_id}"


def system_status_topic(device_id: str) -> str:
    return topic_for_device(TOPIC_SYSTEM_STATUS, device_id)


def control_stream_topic(device_id: str) -> str:
    return topic_for_device(TOPIC_CONTROL_STREAM, device_id)


def error_rtsp_topic(device_id: str) -> str:
    return topic_for_device(TOPIC_ERROR_RTSP, device_id)


def error_pipeline_topic(device_id: str) -> str:
    return topic_for_device(TOPIC_ERROR_PIPELINE, device_id)


def stream_activity_topic(device_id: str) -> str:
    return topic_for_device(TOPIC_STREAM_ACTIVITY, device_id)


def topic_policy(topic: str) -> TopicPolicy:
    policy = TOPIC_POLICIES.get(topic)
    if policy is not None:
        return policy
    if topic.startswith(f"{TOPIC_SYSTEM_STATUS}/"):
        return TOPIC_POLICIES[TOPIC_SYSTEM_STATUS]
    if topic.startswith(f"{TOPIC_CONTROL_STREAM}/"):
        return TOPIC_POLICIES[TOPIC_CONTROL_STREAM]
    if topic.startswith(f"{TOPIC_ERROR_RTSP}/"):
        return TOPIC_POLICIES[TOPIC_ERROR_RTSP]
    if topic.startswith(f"{TOPIC_ERROR_PIPELINE}/"):
        return TOPIC_POLICIES[TOPIC_ERROR_PIPELINE]
    if topic.startswith(f"{TOPIC_STREAM_ACTIVITY}/"):
        return TOPIC_POLICIES[TOPIC_STREAM_ACTIVITY]
    return TopicPolicy(qos=1, retain=False, persist=topic.startswith("error/"))

