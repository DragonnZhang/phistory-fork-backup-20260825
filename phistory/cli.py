from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from phistory import __version__
from phistory.registry import AGENT_ORDER, AGENTS, parse_agent_ids
from phistory.render import render_index
from phistory.workflow import capture_latest, iter_backfill, rerender_archive


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="phistory", description="Capture versioned prompt snapshots from agent CLIs.")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--root", default="captures", help="capture root directory")
    parser.add_argument("--cache-dir", default=".phistory-cache", help="install/cache directory")

    sub = parser.add_subparsers(dest="command", required=True)

    capture = sub.add_parser("capture", help="capture current versions")
    capture.add_argument("--latest", action="store_true", help="capture latest package version for each agent")
    capture.add_argument("--agents", default=None, help=f"comma-separated agent ids (default: {','.join(AGENT_ORDER)})")
    capture.add_argument(
        "--variants", default=None, help="comma-separated variant ids (default: every configured variant)"
    )
    capture.add_argument("--force", action="store_true", help="recapture existing versions")
    capture.add_argument("--keep-tap", action="store_true", help="keep raw claude-tap output directories")
    capture.add_argument("--summary-title", default="Capture results", help="GitHub Actions summary title")

    fill = sub.add_parser("backfill", help="capture historical package versions")
    fill.add_argument("agent", choices=sorted(AGENTS), help="agent id")
    fill.add_argument("--from", dest="start", required=True, help="first package version to capture")
    fill.add_argument("--to", dest="end", default="latest", help="last package version to capture")
    fill.add_argument("--limit", type=int, default=None, help="capture at most N versions from the range")
    fill.add_argument("--newest-first", action="store_true", help="capture the selected range from newest to oldest")
    fill.add_argument("--include-prerelease", action="store_true", help="include prerelease package versions")
    fill.add_argument("--captured-only", action="store_true", help="only versions already present in the archive")
    fill.add_argument(
        "--variants", default=None, help="comma-separated variant ids (default: every configured variant)"
    )
    fill.add_argument("--force", action="store_true", help="recapture existing versions")
    fill.add_argument("--keep-tap", action="store_true", help="keep raw claude-tap output directories")
    fill.add_argument("--summary-title", default="Backfill results", help="GitHub Actions summary title")

    rerender = sub.add_parser("rerender", help="rebuild archived prompt markdown from stored traces")
    rerender.add_argument("--agents", default=None, help="comma-separated agent ids (default: every archived agent)")

    index = sub.add_parser("render-index", help="render capture index")
    index.add_argument("-o", "--output", default="README.md", help="index markdown path")

    site = sub.add_parser("build-site", help="build the complete static site without translation API calls")
    site.add_argument("-o", "--output", type=Path, help="publish directory (default: <cache-dir>/site)")

    translate = sub.add_parser("translate", help="translate archived prose using shared Chinese dictionaries")
    translate.add_argument("--agents", help="comma-separated agent ids (default: all archived agents)")
    translate.add_argument(
        "--latest-captured", type=int, metavar="N", help="process the latest N captured versions per agent"
    )
    translate.add_argument("--locale", choices=["zh-CN"], default="zh-CN")
    translate.add_argument("--all-captured", action="store_true", help="process every archived version (the default)")
    translate.add_argument(
        "--dry-run", action="store_true", help="report missing segments without calling an API or writing files"
    )
    translate.add_argument(
        "--usage-log", type=Path, help="request usage JSONL (default: .phistory-cache/translation-usage.jsonl)"
    )
    translate.add_argument(
        "--prune", action="store_true", help="drop dictionary entries the archive no longer references"
    )
    translate.add_argument("--config", type=Path, help="private translation TOML config path")
    translate.add_argument("--model", help="override the configured translation model")
    translate.add_argument("--concurrency", type=int, help="maximum concurrent translation requests")
    translate.add_argument(
        "--max-batches", type=int, help="limit API batches per agent; unfinished segments remain resumable"
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root)
    cache_dir = Path(args.cache_dir)

    if args.command == "capture":
        if not args.latest:
            raise SystemExit("capture currently requires --latest")
        results = capture_latest(
            parse_agent_ids(args.agents),
            root=root,
            cache_dir=cache_dir,
            variant_ids=_parse_csv(args.variants),
            force=args.force,
            keep_tap=args.keep_tap,
        )
        return _print_results(results, args.summary_title)

    if args.command == "backfill":
        failed = False
        for result in iter_backfill(
            args.agent,
            start=args.start,
            end=args.end,
            root=root,
            cache_dir=cache_dir,
            variant_ids=_parse_csv(args.variants),
            force=args.force,
            keep_tap=args.keep_tap,
            limit=args.limit,
            newest_first=args.newest_first,
            include_prerelease=args.include_prerelease,
            captured_only=args.captured_only,
        ):
            failed = _print_result(result) or failed
            _write_github_summary([result], args.summary_title)
        return 1 if failed else 0

    if args.command == "rerender":
        results = rerender_archive(root, _parse_csv(args.agents))
        counts: dict[str, int] = {}
        for item in results:
            counts[item.status] = counts.get(item.status, 0) + 1
            if item.status == "failed":
                print(f"{item.agent_id} {item.version} [{item.variant_id}]: failed: {item.error}")
        print(f"rerender: {', '.join(f'{k}={v}' for k, v in sorted(counts.items()))}")
        return 1 if counts.get("failed") else 0

    if args.command == "render-index":
        render_index(root, Path(args.output))
        print(f"wrote {args.output}")
        return 0

    if args.command == "build-site":
        from phistory.build import build_site

        output = args.output or cache_dir / "site"
        try:
            build_site(root, output)
        except (ValueError, OSError) as exc:
            print(f"site build failed: {exc}", file=sys.stderr)
            return 1
        print(f"built {output}")
        return 0

    if args.command == "translate":
        from phistory.translation.config import load_config
        from phistory.translation.workflow import translate_archive

        if args.latest_captured is not None and (args.latest_captured < 1 or args.all_captured):
            parser_error = "use a positive --latest-captured N or --all-captured, not both"
            raise SystemExit(parser_error)
        if args.max_batches is not None and args.max_batches < 1:
            raise SystemExit("--max-batches must be greater than zero")
        try:
            config = None if args.dry_run else load_config(args.config, model=args.model, concurrency=args.concurrency)
            results = translate_archive(
                root,
                agent_ids=parse_agent_ids(args.agents) if args.agents else None,
                latest_captured=args.latest_captured,
                dry_run=args.dry_run,
                prune=args.prune,
                config=config,
                max_batches=args.max_batches,
                usage_log=args.usage_log,
                progress=lambda message: print(message, flush=True),
            )
        except (ValueError, OSError, RuntimeError) as exc:
            print(f"translation failed: {exc}", file=sys.stderr)
            return 1
        remaining = sum(item.total - item.reused - item.translated for item in results)
        message = f"Translation: {sum(item.translated for item in results)} new, {sum(item.reused for item in results)} reused, {remaining} remaining."
        if pruned := sum(item.pruned for item in results):
            message += f" Pruned {pruned} unreferenced entries."
        message += (
            f" Requests: {sum(item.requests for item in results)}; "
            f"input tokens: {sum(item.input_tokens for item in results)}; "
            f"output tokens: {sum(item.output_tokens for item in results)}."
        )
        print(message, flush=True)
        if summary := os.environ.get("GITHUB_STEP_SUMMARY"):
            with Path(summary).open("a", encoding="utf-8") as output:
                output.write("\n## Chinese translations\n\n" + message + "\n")
        return 1 if remaining and not args.dry_run else 0

    return 2


def _print_results(results, summary_title: str = "Capture results") -> int:
    failed = False
    for result in results:
        failed = _print_result(result) or failed
    _write_github_summary(results, summary_title)
    return 1 if failed else 0


def _print_result(result) -> bool:
    print(f"{result.agent_id} {result.version} [{result.variant_id}]: {result.status}", flush=True)
    if result.prompt_path:
        print(f"  prompt: {result.prompt_path}", flush=True)
    if result.trace_path:
        print(f"  trace:  {result.trace_path}", flush=True)
    if result.error:
        print(f"  error:  {result.error}", file=sys.stderr, flush=True)
        _print_github_error(result)
        return True
    return False


def _write_github_summary(results, title: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    counts = {
        status: sum(1 for result in results if result.status == status) for status in ("captured", "skipped", "failed")
    }
    lines = [
        f"## {_md_escape(title)}",
        "",
        f"Captured: **{counts['captured']}** · Skipped: **{counts['skipped']}** · Failed: **{counts['failed']}**",
        "",
        "| Agent | Version | Variant | Status | Prompt | Trace | Error |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for result in results:
        cells = [
            f"`{_md_escape(result.agent_id)}`",
            f"`{_md_escape(result.version)}`",
            f"`{_md_escape(result.variant_id)}`",
            _status_label(result.status),
            _path_link(result.prompt_path),
            _path_link(result.trace_path),
            _md_escape(_error_summary(result.error)),
        ]
        lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    summary_path = Path(path)
    existing = summary_path.read_text(encoding="utf-8") if summary_path.exists() else ""
    summary_path.write_text(existing + "\n".join(lines) + "\n", encoding="utf-8")


def _print_github_error(result) -> None:
    if not os.environ.get("GITHUB_ACTIONS"):
        return
    title = f"{result.agent_id} {result.version} {result.variant_id} capture failed"
    print(
        f"::error title={_annotation_escape(title)}::{_annotation_escape(_error_summary(result.error))}",
        file=sys.stderr,
    )


def _status_label(status: str) -> str:
    return {"captured": "captured", "skipped": "skipped", "failed": "failed"}.get(status, status)


def _path_link(path: Path | None) -> str:
    if path is None:
        return ""
    value = path.as_posix()
    return f"[`{_md_escape(value)}`]({_md_escape(value)})"


def _error_summary(error: str | None) -> str:
    if not error:
        return ""
    line = " ".join(error.strip().splitlines())
    return line[:500] + ("..." if len(line) > 500 else "")


def _md_escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("\n", " ")


def _annotation_escape(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def _parse_csv(value: str | None) -> tuple[str, ...] | None:
    if value is None:
        return None
    items = tuple(item.strip() for item in value.split(",") if item.strip())
    if not items:
        raise SystemExit("--variants requires at least one variant id")
    return items


if __name__ == "__main__":
    raise SystemExit(main())
