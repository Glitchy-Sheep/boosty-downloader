"""Nothing captured from the live API lives in the test tree.

Test data is synthetic by rule: ids follow the pattern of
support/synthetic_post.py and data files point at fake hosts. A real post id
or a real Boosty link copied into a fixture fails here, not in a review.
"""

from __future__ import annotations

import re
from pathlib import Path

TEST_ROOT = Path(__file__).parents[2]
TEXT_SUFFIXES = {'.py', '.json', '.html', '.txt', '.md'}
DATA_SUFFIXES = {'.json', '.html', '.txt'}

UUID = re.compile(r'\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b')
# One leading digit, then zeros: a shape no real uuid has.
SYNTHETIC_UUID = re.compile(r'^[0-9a-f]0{7}-0000-4000-8000-[0-9a-f]{12}$')
BOOSTY_LINK = re.compile(r'[a-z.]*boosty\.to(?:/[A-Za-z0-9_./?=&-]*)?')
# Test data may link to made-up creators only.
FAKE_CREATOR_LINK = re.compile(
    r'^boosty\.to/(?:example|example_author|other_author)/?$'
)


def _files(suffixes: set[str]) -> list[Path]:
    return sorted(
        path
        for path in TEST_ROOT.rglob('*')
        if path.suffix in suffixes and '__pycache__' not in path.parts
    )


def test_every_uuid_in_the_test_tree_is_synthetic():
    """A copied real id is the trace a sanitized capture leaves behind."""
    real_ids = [
        f'{path.relative_to(TEST_ROOT)}: {found}'
        for path in _files(TEXT_SUFFIXES)
        for found in UUID.findall(path.read_text(encoding='utf-8'))
        if not SYNTHETIC_UUID.match(found)
    ]
    assert not real_ids, 'Ids outside the synthetic pattern:\n' + '\n'.join(real_ids)


def test_data_files_link_to_fake_hosts_only():
    """A data file with a real Boosty link was captured, not written."""
    real_links = [
        f'{path.relative_to(TEST_ROOT)}: {found}'
        for path in _files(DATA_SUFFIXES)
        for found in BOOSTY_LINK.findall(path.read_text(encoding='utf-8'))
        if not FAKE_CREATOR_LINK.match(found)
    ]
    assert not real_links, 'Boosty links in data files:\n' + '\n'.join(real_links)
