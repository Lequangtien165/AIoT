"""Run the AIoT web dashboard (FastAPI + WebRTC video)."""

from pathlib import Path
import argparse
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from aiot.mqtt.client import password_from_env


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Serve the AIoT admin dashboard.")
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1).")
    parser.add_argument("--port", type=int, default=8080, help="Dashboard HTTP port (default: 8080).")
    parser.add_argument(
        "--video-url",
        default="http://127.0.0.1:8889",
        help="MediaMTX WebRTC base URL for WHEP (default: http://127.0.0.1:8889).",
    )
    parser.add_argument("--video-path", default="camera", help="MediaMTX path to play (default: camera).")
    parser.add_argument("--mqtt-host", default="127.0.0.1", help="MQTT broker host (default: 127.0.0.1).")
    parser.add_argument("--mqtt-port", type=int, default=1883, help="MQTT broker port (default: 1883).")
    parser.add_argument("--mqtt-client-id", default="aiot-dashboard", help="MQTT client ID (default: aiot-dashboard).")
    parser.add_argument("--mqtt-username", help="MQTT username. Password is read from --mqtt-password-env.")
    parser.add_argument("--mqtt-password-env", help="Environment variable containing the MQTT password.")
    parser.add_argument("--mqtt-ca-cert", help="CA certificate path for TLS MQTT connections.")
    parser.add_argument(
        "--audit-db",
        default=str(Path("database") / "audit_log.sqlite3"),
        help="SQLite audit database to read (default: database/audit_log.sqlite3).",
    )
    parser.add_argument(
        "--wanted-config",
        help="Path to the wanted-person JSON config (default: config/wanted.json).",
    )
    parser.add_argument(
        "--snapshot-dir",
        help="Recognition snapshot directory served at /snapshots/* (optional).",
    )
    return parser


def parse_args() -> argparse.Namespace:
    args = build_parser().parse_args()
    if not 0 < args.port < 65536:
        parser.error("--port must be between 1 and 65535.")
    if args.mqtt_username:
        try:
            password_from_env(args.mqtt_username, args.mqtt_password_env)
        except ValueError as error:
            parser.error(str(error))
    return args


def main() -> int:
    args = parse_args()
    try:
        import uvicorn
    except ImportError:
        print(
            "Dashboard requires extra dependencies: "
            "python -m pip install -r requirements-dashboard.txt",
            file=sys.stderr,
        )
        return 1

    from aiot.dashboard.server import DashboardConfig, create_app

    config = DashboardConfig(
        mqtt_host=args.mqtt_host,
        mqtt_port=args.mqtt_port,
        mqtt_client_id=args.mqtt_client_id,
        mqtt_username=args.mqtt_username,
        mqtt_password=(
            password_from_env(args.mqtt_username, args.mqtt_password_env)
            if args.mqtt_username
            else None
        ),
        mqtt_ca_cert=args.mqtt_ca_cert,
        audit_db=args.audit_db,
        wanted_config=args.wanted_config,
        snapshot_dir=args.snapshot_dir,
        video_url=args.video_url,
        video_path=args.video_path,
    )
    app = create_app(config)
    print(f"[DASHBOARD] serving http://{args.host}:{args.port} (video: {config.video_url}/{config.video_path})")
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
