from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path
from typing import Any
import sys

import uvicorn

if __package__ in {None, ""}:
    ROOT = Path(__file__).resolve().parents[1]
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from cloud_inference_server.app import create_app
    from cloud_inference_server.config import DEFAULT_CONFIG_PATH, ensure_config_exists, load_config, update_config
    from cloud_inference_server.storage import CloudStorage
else:
    from .app import create_app
    from .config import DEFAULT_CONFIG_PATH, ensure_config_exists, load_config, update_config
    from .storage import CloudStorage


def _parse_value(raw: str) -> Any:
    text = str(raw or "")
    lowered = text.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    try:
        return json.loads(text)
    except Exception:
        return text


def _build_storage(config_path: Path | None = None) -> tuple[Path, CloudStorage]:
    path = ensure_config_exists(config_path)
    config = load_config(path)
    storage = CloudStorage(config.database_file)
    storage.initialize()
    return path, storage


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="FaustBot Cloud inference CLI")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_PATH), help="配置文件路径")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init-config", help="初始化默认配置文件")
    subparsers.add_parser("show-config", help="打印当前配置")

    set_parser = subparsers.add_parser("set", help="更新配置字段")
    set_parser.add_argument("key")
    set_parser.add_argument("value")

    create_key = subparsers.add_parser("create-key", help="创建 Service Key")
    create_key.add_argument("--name", default="")
    create_key.add_argument("--note", default="")

    root_key = subparsers.add_parser("set-root-key", help="设置管理用 ROOT key")
    root_key.add_argument("value", help="ROOT key 值")

    subparsers.add_parser("list-keys", help="列出 Service Key")

    enable_key = subparsers.add_parser("enable-key", help="启用 Service Key")
    enable_key.add_argument("service_key")

    disable_key = subparsers.add_parser("disable-key", help="禁用 Service Key")
    disable_key.add_argument("service_key")

    reset_usage = subparsers.add_parser("reset-usage", help="清空指定 Key 的计费流水")
    reset_usage.add_argument("service_key")

    usage_cmd = subparsers.add_parser("usage", help="查看指定 Service Key 的用量快照")
    usage_cmd.add_argument("service_key")

    runserver = subparsers.add_parser("runserver", help="启动 HTTP 服务")
    runserver.add_argument("--host", default="")
    runserver.add_argument("--port", type=int, default=0)

    args = parser.parse_args(argv)
    config_path = Path(args.config)

    if args.command == "init-config":
        path = ensure_config_exists(config_path)
        print(path)
        return 0

    if args.command == "show-config":
        config = load_config(config_path)
        print(json.dumps(asdict(config), ensure_ascii=False, indent=2))
        return 0

    if args.command == "set":
        config = update_config({args.key: _parse_value(args.value)}, config_path)
        print(json.dumps(asdict(config), ensure_ascii=False, indent=2))
        return 0

    if args.command == "set-root-key":
        config = update_config({"root_key": str(args.value or "").strip()}, config_path)
        print(json.dumps(asdict(config), ensure_ascii=False, indent=2))
        return 0

    _, storage = _build_storage(config_path)

    if args.command == "create-key":
        record = storage.create_service_key(name=args.name, note=args.note)
        print(json.dumps(asdict(record), ensure_ascii=False, indent=2))
        return 0

    if args.command == "list-keys":
        print(json.dumps([asdict(item) for item in storage.list_service_keys()], ensure_ascii=False, indent=2))
        return 0

    if args.command == "enable-key":
        print(json.dumps({"updated": storage.set_service_key_enabled(args.service_key, True)}, ensure_ascii=False, indent=2))
        return 0

    if args.command == "disable-key":
        print(json.dumps({"updated": storage.set_service_key_enabled(args.service_key, False)}, ensure_ascii=False, indent=2))
        return 0

    if args.command == "reset-usage":
        print(json.dumps({"deleted_rows": storage.reset_usage(args.service_key)}, ensure_ascii=False, indent=2))
        return 0

    if args.command == "usage":
        cfg = load_config(config_path)
        snapshot = storage.get_usage_snapshot(
            args.service_key,
            hourly_limit_units=cfg.hourly_limit_points * 100,
            daily_limit_units=cfg.daily_limit_points * 100,
        )
        print(json.dumps(snapshot.to_dict(), ensure_ascii=False, indent=2))
        return 0

    if args.command == "runserver":
        config = load_config(config_path)
        app = create_app(config=config)
        host = args.host or config.host
        port = args.port or config.port
        uvicorn.run(app, host=host, port=port)
        return 0

    parser.error("未知命令")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())