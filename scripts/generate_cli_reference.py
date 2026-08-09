"""Generate the auto region of docs/CLI_REFERENCE.md from the argparse definitions.

Every user-facing CLI exposes a `build_parser()`; this script imports each one
(no camera, broker, model, or heavy recognition dependencies are touched) and
renders deterministic Markdown tables between the AUTO markers in
`docs/CLI_REFERENCE.md`. `tests/test_cli_reference.py` fails when the committed
reference is stale, so run this after adding or changing any flag:

    python scripts/generate_cli_reference.py
"""

from __future__ import annotations

import argparse
import importlib
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DOC_PATH = PROJECT_ROOT / "docs" / "CLI_REFERENCE.md"
AUTO_START = "<!-- CLI-REF:AUTO-START -->"
AUTO_END = "<!-- CLI-REF:AUTO-END -->"


@dataclass(frozen=True)
class Entry:
    module: str
    command: str
    purpose: str
    platform: str
    source: str = ""


ENTRIES: list[Entry] = [
    Entry(
        module="app",
        command="python app.py",
        purpose="Reconnecting MediaPipe face-detection preview of an RTSP stream.",
        platform="Windows AMD64 and macOS Apple Silicon (needs the BlazeFace model)",
    ),
    Entry(
        module="stream_server",
        command="python stream_server.py",
        purpose="Publish a webcam to a MediaMTX RTSP stream; owns MediaMTX and optionally FFmpeg.",
        platform="Windows, macOS, Linux ARM64 (profile auto-detected; rpi-csi must be explicit)",
    ),
    Entry(
        module="recognize_stream",
        command="python recognize_stream.py",
        purpose="Realtime InsightFace + FAISS recognition of an RTSP stream; publishes recognition/result over MQTT.",
        platform="Windows AMD64 only",
    ),
    Entry(
        module="recognize_image",
        command="python recognize_image.py IMAGE",
        purpose="One-shot image recognition against the FAISS enrollment index.",
        platform="Windows AMD64 only",
    ),
    Entry(
        module="scripts.run_edge_agent",
        command="python scripts/run_edge_agent.py",
        purpose="Persistent MQTT supervisor that owns a stream_server.py publisher child.",
        platform="Windows, macOS, Linux ARM64",
    ),
    Entry(
        module="scripts.run_dashboard",
        command="python scripts/run_dashboard.py",
        purpose="Web guard console: WebRTC video, recognition overlay, event timeline, edge control.",
        platform="Windows, macOS (requires requirements-dashboard.txt)",
    ),
    Entry(
        module="aiot.mqtt.audit_logger",
        command="python scripts/run_mqtt_logger.py",
        purpose="Persist recognition/motion/error/ack events to database/audit_log.sqlite3.",
        platform="Windows, macOS, Linux",
        source="aiot/mqtt/audit_logger.py",
    ),
    Entry(
        module="scripts.setup_tools",
        command="python scripts/setup_tools.py",
        purpose="Download, verify, and install the pinned FFmpeg and MediaMTX builds.",
        platform="Windows, macOS Apple Silicon, Linux ARM64",
    ),
]


def build_parser_for(entry: Entry) -> argparse.ArgumentParser:
    module = importlib.import_module(entry.module)
    return module.build_parser()


def _escape(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _type_name(action: argparse.Action) -> str:
    if isinstance(action, (argparse._StoreTrueAction, argparse._StoreFalseAction)):
        return "flag"
    if action.choices:
        return "choice"
    if action.type is not None:
        return getattr(action.type, "__name__", str(action.type))
    return "str"


def _default_repr(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "`true`" if value else "`false`"
    if isinstance(value, str):
        return f"`{value}`"
    return f"`{value!r}`"


def render_flag_table(parser: argparse.ArgumentParser) -> str:
    lines = ["| Flag | Type | Default | Required | Description |", "|---|---|---|---|---|"]
    for action in parser._actions:
        if isinstance(action, (argparse._HelpAction, argparse._VersionAction)):
            continue
        if action.option_strings:
            name = "`" + "`, `".join(action.option_strings) + "`"
        else:
            nargs = "" if action.nargs in (None, "?") else " …"
            name = f"`{action.dest}{nargs}` (positional)"
        description = _escape(action.help or "")
        if action.choices:
            choices = ", ".join(f"`{choice}`" for choice in action.choices)
            description = f"{description} Choices: {choices}."
        lines.append(
            f"| {name} | {_type_name(action)} | {_default_repr(action.default)} "
            f"| {'yes' if action.required else 'no'} | {description} |"
        )
    return "\n".join(lines)


def render_module(entry: Entry, parser: argparse.ArgumentParser) -> str:
    parts = [
        f"### `{entry.command}`",
        "",
        entry.purpose,
        "",
        f"Platform: {entry.platform}.",
        "",
        render_flag_table(parser),
        "",
    ]
    if entry.source:
        parts.extend([f"Flags defined in `{entry.source}`.", ""])
    return "\n".join(parts)


def render_overview(entries: list[Entry], parsers: list[argparse.ArgumentParser]) -> str:
    lines = [
        "## Commands At A Glance",
        "",
        "| Command | Purpose | Platform | Flags | Required |",
        "|---|---|---|---|---|",
    ]
    for entry, parser in zip(entries, parsers):
        actions = [
            action
            for action in parser._actions
            if not isinstance(action, (argparse._HelpAction, argparse._VersionAction))
        ]
        flag_count = sum(1 for action in actions if action.option_strings)
        positional_count = len(actions) - flag_count
        required = sum(1 for action in actions if action.required)
        counts = f"{flag_count} {'flag' if flag_count == 1 else 'flags'}"
        if positional_count:
            counts += f" + {positional_count} positional"
        lines.append(
            f"| `{entry.command}` | {_escape(entry.purpose)} | {_escape(entry.platform)} "
            f"| {counts} | {required} |"
        )
    return "\n".join(lines)


def render_auto_section() -> str:
    parsers = [build_parser_for(entry) for entry in ENTRIES]
    parts = [AUTO_START, "", render_overview(ENTRIES, parsers), ""]
    for entry, parser in zip(ENTRIES, parsers):
        parts.append(render_module(entry, parser))
        parts.append("")
    parts.append(AUTO_END)
    return "\n".join(parts)


def regenerate() -> int:
    if not DOC_PATH.is_file():
        print(
            f"Missing {DOC_PATH.relative_to(PROJECT_ROOT)}; "
            "create it with the AUTO markers first.",
            file=sys.stderr,
        )
        return 1
    content = DOC_PATH.read_text(encoding="utf-8")
    if AUTO_START not in content or AUTO_END not in content:
        print(f"Missing AUTO markers in {DOC_PATH.relative_to(PROJECT_ROOT)}.", file=sys.stderr)
        return 1
    # rindex: curated text must never repeat the markers verbatim after the region.
    start = content.rindex(AUTO_START)
    end = content.rindex(AUTO_END) + len(AUTO_END)
    new_content = content[:start] + render_auto_section() + content[end:]
    if new_content == content:
        print("CLI reference is up to date.")
        return 0
    DOC_PATH.write_text(new_content, encoding="utf-8", newline="\n")
    print(f"Updated {DOC_PATH.relative_to(PROJECT_ROOT)}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(regenerate())
