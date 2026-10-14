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
from .record_prepare import prepare_record
from .review import build_review
from .youtube_auth import youtube_check, youtube_connect, youtube_status
from .youtube_publish import publish, verify_publication


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
    record_prepare = commands.add_parser("prepare-record")
    record_prepare.add_argument("--recipe", required=True)
    record_prepare.add_argument("--ffmpeg", required=True)
    record_prepare.add_argument("--resume", action="store_true")
    review = commands.add_parser("build-review")
    review.add_argument("--recipe", required=True)
    review.add_argument("--ffmpeg", required=True)
    commands.add_parser("youtube-check")
    commands.add_parser("youtube-status")
    connect = commands.add_parser("youtube-connect")
    connect.add_argument("--timeout", type=int, choices=range(30, 1801), default=600, metavar="SECONDS")
    connect.add_argument("--reconnect", action="store_true")
    upload = commands.add_parser("youtube-upload")
    upload.add_argument("--package", required=True)
    upload.add_argument("--approval", required=True)
    upload.add_argument("--execute", action="store_true", help="Реальная загрузка утверждённого пакета; по умолчанию dry-run")
    verify = commands.add_parser("youtube-upload-verify")
    verify.add_argument("--package", required=True)
    verify.add_argument("--approval", required=True)
    verify.add_argument("--wait", type=int, choices=range(0, 1801), default=600, metavar="SECONDS")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        if args.command == "youtube-upload-verify":
            report = verify_publication(config, args.package, args.approval, args.wait)
        elif args.command == "youtube-upload":
            report = publish(config, args.package, args.approval, dry_run=not args.execute)
        elif args.command == "youtube-check":
            report = youtube_check(config)
        elif args.command == "youtube-connect":
            report = youtube_connect(config, args.timeout, args.reconnect)
        elif args.command == "youtube-status":
            report = youtube_status(config)
        elif args.command == "doctor":
            report = doctor(config, args.check_write)
        elif args.command == "technical":
            report = inspect_media(config, args.museum_id, args.record, args.ffprobe)
        elif args.command == "prepare-a01":
            report = prepare_a01(config, args.record, args.ffmpeg, args.resume)
        elif args.command == "prepare-record":
            report = prepare_record(config, args.recipe, args.ffmpeg, args.resume)
        elif args.command == "build-review":
            report = build_review(config, args.recipe, args.ffmpeg)
        else:
            report = dry_run(config, args.museum_id, args.record, args.metadata_profile)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    except (SafeError, OSError, ValueError, TypeError, SubprocessError) as error:
        message = str(error) if isinstance(error, SafeError) else "Локальная проверка не выполнена: проверьте доступность файлов и конфигурацию."
        count = 0
        if args.command in ("youtube-upload", "youtube-upload-verify"):
            try:
                from pathlib import Path
                from .safety import local_file
                path = local_file(Path(args.package).parent / "youtube-publication-results-v1.json", config.work)
                count = len(json.loads(path.read_text(encoding="utf-8"))["items"])
            except (OSError, ValueError, KeyError, TypeError, UnboundLocalError):
                count = None  # Unknown must not be reported as zero uploads.
        print(json.dumps({"status": "error", "message": message, "uploads": count},
                         ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
