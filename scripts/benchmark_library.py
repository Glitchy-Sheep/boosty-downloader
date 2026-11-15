"""Generate an owned synthetic library and assert production index budgets."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from library_benchmark.fixture import FixtureConfig, prepare_fixture
from library_benchmark.runner import print_report, report_data, run_benchmark
from sqlalchemy.exc import SQLAlchemyError


def _positive(value: str) -> int:
    number = int(value)
    if number < 1:
        message = 'value must be a positive integer'
        raise argparse.ArgumentTypeError(message)
    return number


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        'root', type=Path, help='New fixture folder, or a matching owned fixture'
    )
    parser.add_argument(
        '--authors',
        type=_positive,
        default=20,
        help='Synthetic authors; acceptance requires 20',
    )
    parser.add_argument(
        '--posts-per-author',
        type=_positive,
        default=1000,
        help='Posts per author; acceptance requires 1000',
    )
    parser.add_argument(
        '--samples',
        type=_positive,
        default=5,
        help='Warm samples for open, SQL and diagnostics',
    )
    parser.add_argument(
        '--rebuild-samples',
        type=_positive,
        default=3,
        help='Warm full-rebuild samples after the first run',
    )
    parser.add_argument(
        '--json',
        type=Path,
        dest='json_path',
        help='Write report outside the fixture directory',
    )
    parser.add_argument(
        '--generate-only',
        action='store_true',
        help='Prepare the fixture without measuring budgets',
    )
    return parser


def _check_report_path(root: Path, output: Path | None) -> None:
    if output is not None and output.resolve().is_relative_to(root.resolve()):
        message = 'The JSON report must be outside the owned fixture directory'
        raise ValueError(message)


def main(argv: list[str] | None = None) -> int:
    """Return failure when any declared warm-median budget is missed."""
    parser = _parser()
    args = parser.parse_args(argv)
    try:
        _check_report_path(args.root, args.json_path)
        config = FixtureConfig(
            authors=args.authors, posts_per_author=args.posts_per_author
        )
        fixture = prepare_fixture(args.root, config)
        if args.generate_only:
            print(
                f'Fixture ready: {fixture.root}; {fixture.posts} posts, {fixture.media} media'
            )
            return 0
        report = run_benchmark(
            fixture, samples=args.samples, rebuild_samples=args.rebuild_samples
        )
        print_report(report)
        if args.json_path is not None:
            args.json_path.write_text(
                json.dumps(report_data(report), indent=2) + '\n', encoding='utf-8'
            )
    except (OSError, ValueError, RuntimeError, SQLAlchemyError) as error:
        parser.exit(2, f'Benchmark failed: {error}\n')
    return 0 if report.passed else 1


if __name__ == '__main__':
    raise SystemExit(main())
