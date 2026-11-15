"""Create a repeatable local library for viewer development without credentials."""

from __future__ import annotations

import argparse
from pathlib import Path
from subprocess import SubprocessError

from library_sample.generator import prepare_sample
from library_sample.models import SampleConfig


def main() -> None:
    """Validate arguments and report the generated library's actual dimensions."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out', type=Path, default=Path('.sample/library'))
    parser.add_argument('--seed', type=int, default=7)
    parser.add_argument('--posts', type=int, default=1430)
    options = parser.parse_args()
    try:
        result = prepare_sample(
            options.out, SampleConfig(seed=options.seed, posts=options.posts)
        )
    except (OSError, ValueError, RuntimeError, SubprocessError) as error:
        parser.exit(1, f'Cannot generate sample: {error}\n')
    print(
        f'Sample: {result.root}\n{result.authors} authors, {result.posts} posts, '
        f'{result.saved_posts} saved bodies, {result.media} media; assets: {result.backend.value}.'
    )


if __name__ == '__main__':
    main()
