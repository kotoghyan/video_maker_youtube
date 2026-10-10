import argparse
import json
import sys
from subprocess import SubprocessError
from .config import load_config
from .doctor import doctor
from .inventory import dry_run
from .safety import SafeError
from .technical import inspect_media
from .prepare import prepare_a01


def main(argv=None):
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Vinyl Codex: локальные проверки без публикации.")
    parser.add_argument("--config", default="config.json")
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("doctor")
    inspect.add_argument("--check-write", action="store_true")
    dry = commands.add_parser("dry-run")
    dry.add_argument("--museum-id", required=True)
    dry.add_argument("--record")
    dry.add_argument("--metadata-profile", choices=("official", "approved-246"), default="official")
    technical = commands.add_parser("technical")
    technical.add_argument("--museum-id", required=True)
    technical.add_argument("--record", required=True)
    technical.add_argument("--ffprobe", required=True)
    prepare = commands.add_parser("prepare-a01")
    prepare.add_argument("--record", required=True)
    prepare.add_argument("--ffmpeg", required=True)
    prepare.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        if args.command == "doctor":
            report = doctor(config, args.check_write)
        elif args.command == "technical":
            report = inspect_media(config, args.museum_id, args.record, args.ffprobe)
        elif args.command == "prepare-a01":
            report = prepare_a01(config, args.record, args.ffmpeg, args.resume)
        else:
            report = dry_run(config, args.museum_id, args.record, args.metadata_profile)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except (SafeError, OSError, ValueError, TypeError, SubprocessError) as error:
        message = str(error) if isinstance(error, SafeError) else "Локальная проверка не выполнена: проверьте доступность файлов и конфигурацию."
        print(json.dumps({"status": "error", "message": message, "uploads": 0},
                         ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
