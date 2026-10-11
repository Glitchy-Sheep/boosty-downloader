"""A post record remains complete across file failures and process interruption."""

import os
import subprocess
import sys
from copy import deepcopy
from datetime import datetime, timezone
from enum import Enum
from errno import EBADF
from pathlib import Path
from tempfile import NamedTemporaryFile
from unittest.mock import Mock

import pytest

from boosty_downloader.domain.post_data_chunks import PostDataChunkText
from boosty_downloader.domain.stored_post import (
    PostMetadata,
    PostSync,
    StoredPost,
    TextBlock,
)
from boosty_downloader.infrastructure.library import json_store
from boosty_downloader.infrastructure.library._post_json import (
    decode_post_record,
    encode_post_record,
)
from boosty_downloader.infrastructure.library.errors import (
    InvalidPostRecordError,
    UnsupportedPostSchemaError,
)
from boosty_downloader.infrastructure.library.json_store import (
    read_post_record,
    write_post_record,
)

NOW = datetime(2026, 10, 11, 12, tzinfo=timezone.utc)
CRASH_EXIT_CODE = 73
CRASH_BEFORE_REPLACE = """
import os
import sys
from pathlib import Path
from boosty_downloader.infrastructure.library import json_store

folder = Path(sys.argv[1])
record = json_store.read_post_record(folder)
assert record is not None
record.post.title = 'Interrupted update'

def abort_before_replace(source, destination):
    os._exit(73)

Path.replace = abort_before_replace
json_store.write_post_record(folder, record)
"""


class FailurePoint(Enum):
    write = 'write'
    flush = 'flush'
    fsync = 'fsync'
    replace = 'replace'


@pytest.fixture
def record() -> StoredPost:
    return StoredPost(
        post=PostMetadata(
            id='post-1',
            author='author',
            url='https://boosty.to/author/posts/post-1',
            title='Урок 🚀',
            created_at=NOW,
            updated_at=NOW,
            tags=['обучение'],
        ),
        sync=PostSync(NOW, NOW),
        blocks=[TextBlock([PostDataChunkText.TextFragment('Привет, мир!')])],
    )


def test_new_record_round_trips_in_unicode_folder_without_mutating_input(
    tmp_path: Path, record: StoredPost
):
    folder = tmp_path / 'Автор' / 'Урок 🚀'
    folder.mkdir(parents=True)
    original = deepcopy(record)

    write_post_record(folder, record)

    assert read_post_record(folder) == original
    assert record == original
    data = (folder / 'post.json').read_bytes()
    assert 'Привет, мир!' in data.decode('utf-8')
    assert data.endswith(b'\n')
    assert [path.name for path in folder.iterdir()] == ['post.json']


def test_replacement_flushes_and_syncs_complete_file_then_closes_before_publication(
    tmp_path: Path, record: StoredPost, monkeypatch: pytest.MonkeyPatch
):
    write_post_record(tmp_path, record)
    old_bytes = (tmp_path / 'post.json').read_bytes()
    record.post.title = 'Updated'
    synced_descriptors: list[int] = []
    real_fsync, real_replace = os.fsync, Path.replace
    replaced = False

    def observe_fsync(descriptor: int) -> None:
        (temporary,) = tmp_path.glob('post.json.*.tmp')
        assert decode_post_record(temporary.read_bytes()) == record
        synced_descriptors.append(descriptor)
        real_fsync(descriptor)

    def observe_replace(source: Path, destination: Path) -> None:
        nonlocal replaced
        assert len(synced_descriptors) == 1
        with pytest.raises(OSError) as raised:  # noqa: PT011 - Check errno across platforms.
            os.fstat(synced_descriptors[0])
        assert raised.value.errno == EBADF
        assert Path(source).parent == tmp_path
        assert Path(destination) == tmp_path / 'post.json'
        assert Path(destination).read_bytes() == old_bytes
        assert decode_post_record(Path(source).read_bytes()) == record
        real_replace(source, destination)
        replaced = True

    monkeypatch.setattr(json_store.os, 'fsync', observe_fsync)
    monkeypatch.setattr(Path, 'replace', observe_replace)
    write_post_record(tmp_path, record)

    assert replaced
    assert read_post_record(tmp_path) == record
    assert list(tmp_path.glob('post.json.*.tmp')) == []


def test_reads_are_independent_snapshots_and_leave_all_files_unchanged(
    tmp_path: Path, record: StoredPost
):
    write_post_record(tmp_path, record)
    (tmp_path / 'post.json.abandoned.tmp').write_bytes(b'incomplete')
    record_path = tmp_path / 'post.json'
    original_bytes, original_mtime = (
        record_path.read_bytes(),
        record_path.stat().st_mtime_ns,
    )
    first = read_post_record(tmp_path)
    second = read_post_record(tmp_path)
    assert first is not None
    assert second is not None
    first.post.tags.append('changed')
    first.blocks.clear()

    assert second == record
    assert record_path.read_bytes() == original_bytes
    assert record_path.stat().st_mtime_ns == original_mtime
    assert (tmp_path / 'post.json.abandoned.tmp').read_bytes() == b'incomplete'
    assert len(list(tmp_path.iterdir())) == 2


@pytest.mark.parametrize('folder_name', ['', 'missing/nested'])
def test_missing_record_returns_none_without_creating_anything(
    tmp_path: Path, folder_name: str
):
    assert read_post_record(tmp_path / folder_name) is None
    assert list(tmp_path.iterdir()) == []


def test_orphan_temporary_does_not_count_as_a_record(
    tmp_path: Path, record: StoredPost
):
    orphan = tmp_path / 'post.json.orphan.tmp'
    orphan.write_bytes(encode_post_record(record))

    assert read_post_record(tmp_path) is None
    assert [path.name for path in tmp_path.iterdir()] == [orphan.name]


@pytest.mark.parametrize(
    ('data', 'error_type'),
    [
        pytest.param(b'\xff', InvalidPostRecordError, id='invalid-utf8'),
        pytest.param(b'{', InvalidPostRecordError, id='invalid-json'),
        pytest.param(
            b'{"schema_version": 1}', InvalidPostRecordError, id='invalid-record'
        ),
        pytest.param(
            b'{"schema_version": 2}', UnsupportedPostSchemaError, id='future-schema'
        ),
    ],
)
def test_format_errors_name_file_preserve_error_kind_and_do_not_rewrite(
    tmp_path: Path, data: bytes, error_type: type[InvalidPostRecordError]
):
    path = tmp_path / 'post.json'
    path.write_bytes(data)

    with pytest.raises(error_type) as raised:
        read_post_record(tmp_path)

    assert type(raised.value) is error_type
    assert str(path) in str(raised.value)
    assert isinstance(raised.value.__cause__, error_type)
    assert path.read_bytes() == data
    assert [entry.name for entry in tmp_path.iterdir()] == ['post.json']


def test_read_permission_error_propagates_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    error = PermissionError('record is unreadable')
    monkeypatch.setattr(Path, 'read_bytes', Mock(side_effect=error))

    with pytest.raises(PermissionError) as raised:
        read_post_record(tmp_path)

    assert raised.value is error


def test_directory_in_place_of_record_remains_a_filesystem_error(tmp_path: Path):
    (tmp_path / 'post.json').mkdir()

    with pytest.raises((IsADirectoryError, PermissionError)):
        read_post_record(tmp_path)

    assert (tmp_path / 'post.json').is_dir()


def test_invalid_record_is_rejected_before_creating_a_temporary(
    tmp_path: Path, record: StoredPost, monkeypatch: pytest.MonkeyPatch
):
    write_post_record(tmp_path, record)
    old_bytes = (tmp_path / 'post.json').read_bytes()
    record.post.id = ''
    create_temporary = Mock(side_effect=AssertionError('filesystem was touched'))
    monkeypatch.setattr(json_store, 'NamedTemporaryFile', create_temporary)

    with pytest.raises(InvalidPostRecordError):
        write_post_record(tmp_path, record)

    create_temporary.assert_not_called()
    assert (tmp_path / 'post.json').read_bytes() == old_bytes
    assert [path.name for path in tmp_path.iterdir()] == ['post.json']


def test_write_requires_existing_parent(tmp_path: Path, record: StoredPost):
    with pytest.raises(FileNotFoundError):
        write_post_record(tmp_path / 'missing' / 'nested', record)

    assert list(tmp_path.iterdir()) == []


def test_temporary_creation_error_preserves_existing_record(
    tmp_path: Path, record: StoredPost, monkeypatch: pytest.MonkeyPatch
):
    write_post_record(tmp_path, record)
    old_bytes = (tmp_path / 'post.json').read_bytes()
    error = PermissionError('folder is not writable')
    monkeypatch.setattr(json_store, 'NamedTemporaryFile', Mock(side_effect=error))

    with pytest.raises(PermissionError) as raised:
        write_post_record(tmp_path, record)

    assert raised.value is error
    assert (tmp_path / 'post.json').read_bytes() == old_bytes
    assert [path.name for path in tmp_path.iterdir()] == ['post.json']


@pytest.mark.parametrize('failure_point', FailurePoint)
def test_prepublication_failure_keeps_old_record_and_cleans_only_own_temporary(
    tmp_path: Path,
    record: StoredPost,
    monkeypatch: pytest.MonkeyPatch,
    failure_point: FailurePoint,
):
    write_post_record(tmp_path, record)
    old_bytes = (tmp_path / 'post.json').read_bytes()
    orphan = tmp_path / 'post.json.other-writer.tmp'
    orphan.write_bytes(b'other writer')
    record.post.title = 'Unpublished'
    error = OSError('injected disk failure')
    with NamedTemporaryFile(
        dir=tmp_path, prefix='post.json.', suffix='.tmp', delete=False
    ) as temporary:
        monkeypatch.setattr(
            json_store, 'NamedTemporaryFile', Mock(return_value=temporary)
        )
        match failure_point:
            case FailurePoint.write:

                def fail_partial_write(data: bytes) -> int:
                    temporary.file.write(data[:10])
                    raise error

                monkeypatch.setattr(temporary, 'write', fail_partial_write)
            case FailurePoint.flush:
                monkeypatch.setattr(temporary, 'flush', Mock(side_effect=error))
            case FailurePoint.fsync:
                monkeypatch.setattr(json_store.os, 'fsync', Mock(side_effect=error))
            case FailurePoint.replace:
                monkeypatch.setattr(Path, 'replace', Mock(side_effect=error))

        with pytest.raises(OSError, match='injected disk failure') as raised:
            write_post_record(tmp_path, record)

        assert raised.value is error
        assert temporary.closed
    assert (tmp_path / 'post.json').read_bytes() == old_bytes
    assert orphan.read_bytes() == b'other writer'
    assert set(tmp_path.iterdir()) == {tmp_path / 'post.json', orphan}


def test_cleanup_failure_does_not_hide_the_publication_error(
    tmp_path: Path, record: StoredPost, monkeypatch: pytest.MonkeyPatch
):
    write_post_record(tmp_path, record)
    old_bytes = (tmp_path / 'post.json').read_bytes()
    error = OSError('publication failed')
    with monkeypatch.context() as patches:
        patches.setattr(Path, 'replace', Mock(side_effect=error))
        patches.setattr(
            Path, 'unlink', Mock(side_effect=PermissionError('cleanup denied'))
        )
        with pytest.raises(OSError, match='publication failed') as raised:
            write_post_record(tmp_path, record)
        assert raised.value is error

    assert (tmp_path / 'post.json').read_bytes() == old_bytes
    assert len(list(tmp_path.glob('post.json.*.tmp'))) == 1
    assert read_post_record(tmp_path) == record


def test_interrupted_publication_cleans_owned_temporary(
    tmp_path: Path, record: StoredPost, monkeypatch: pytest.MonkeyPatch
):
    write_post_record(tmp_path, record)
    old_bytes = (tmp_path / 'post.json').read_bytes()
    monkeypatch.setattr(Path, 'replace', Mock(side_effect=KeyboardInterrupt))

    with pytest.raises(KeyboardInterrupt):
        write_post_record(tmp_path, record)

    assert (tmp_path / 'post.json').read_bytes() == old_bytes
    assert list(tmp_path.glob('post.json.*.tmp')) == []


def test_overlapping_writes_own_distinct_temporaries_and_last_publication_wins(
    tmp_path: Path, record: StoredPost, monkeypatch: pytest.MonkeyPatch
):
    other = deepcopy(record)
    other.post.title = 'Other writer'
    sources: list[Path] = []
    real_replace = Path.replace

    def publish_with_other_writer(source: Path, destination: Path) -> None:
        sources.append(Path(source))
        if len(sources) == 1:
            write_post_record(tmp_path, other)
            assert read_post_record(tmp_path) == other
            assert Path(source).exists()
        real_replace(source, destination)

    monkeypatch.setattr(Path, 'replace', publish_with_other_writer)
    write_post_record(tmp_path, record)

    assert len(set(sources)) == 2
    assert all(path.parent == tmp_path for path in sources)
    assert all(path.match('post.json.*.tmp') for path in sources)
    assert read_post_record(tmp_path) == record
    assert list(tmp_path.glob('post.json.*.tmp')) == []


def test_save_preserves_media_pages_viewing_marks_and_abandoned_temporaries(
    tmp_path: Path, record: StoredPost
):
    unrelated = {
        'index.html': b'page',
        'viewer.json': b'marks',
        'post.json.old.tmp': b'orphan',
    }
    for name, content in unrelated.items():
        (tmp_path / name).write_bytes(content)
    (tmp_path / 'media').mkdir()
    (tmp_path / 'media' / 'video.mp4').write_bytes(b'video')

    write_post_record(tmp_path, record)
    record.post.title = 'Replacement'
    write_post_record(tmp_path, record)

    for name, content in unrelated.items():
        assert (tmp_path / name).read_bytes() == content
    assert (tmp_path / 'media' / 'video.mp4').read_bytes() == b'video'
    assert read_post_record(tmp_path) == record


def test_process_exit_before_replace_leaves_old_record_authoritative(
    tmp_path: Path, record: StoredPost
):
    write_post_record(tmp_path, record)
    old_bytes = (tmp_path / 'post.json').read_bytes()

    result = subprocess.run(  # noqa: S603 - Fixed child code and pytest-owned directory.
        [sys.executable, '-c', CRASH_BEFORE_REPLACE, str(tmp_path)],
        cwd=Path(__file__).resolve().parents[3],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )

    assert result.returncode == CRASH_EXIT_CODE, result.stderr
    assert (tmp_path / 'post.json').read_bytes() == old_bytes
    assert read_post_record(tmp_path) == record
    (orphan,) = tmp_path.glob('post.json.*.tmp')
    orphan_bytes = orphan.read_bytes()
    assert decode_post_record(orphan_bytes).post.title == 'Interrupted update'
    record.post.title = 'Next successful save'
    write_post_record(tmp_path, record)
    assert read_post_record(tmp_path) == record
    assert orphan.read_bytes() == orphan_bytes
