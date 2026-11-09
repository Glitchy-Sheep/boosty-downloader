"""Local installation uses the complete package build and stops on build failure."""

from __future__ import annotations

import subprocess
from typing import TYPE_CHECKING

import build_install
import pytest

if TYPE_CHECKING:
    from pathlib import Path


def test_builds_runtime_assets_before_installing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    dist = tmp_path / 'dist'
    calls: list[list[str]] = []

    def run(args: list[str], *, check: bool) -> subprocess.CompletedProcess[str]:
        assert check
        calls.append(args)
        if args == ['task', 'build']:
            dist.mkdir()
            (dist / 'package.whl').write_bytes(b'wheel')
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(build_install, 'DIST_DIR', dist)
    monkeypatch.setattr(build_install, '_get_version', lambda: '1.0')
    monkeypatch.setattr(build_install.subprocess, 'run', run)
    monkeypatch.setattr(build_install.shutil, 'which', lambda _name: '/test/pipx')

    build_install.main()

    assert calls == [
        ['task', 'build'],
        ['/test/pipx', 'install', '--force', str(dist / 'package.whl')],
    ]


def test_does_not_install_after_build_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    calls: list[list[str]] = []

    def run(args: list[str], *, check: bool) -> subprocess.CompletedProcess[str]:
        assert check
        calls.append(args)
        raise subprocess.CalledProcessError(1, args)

    monkeypatch.setattr(build_install, 'DIST_DIR', tmp_path / 'dist')
    monkeypatch.setattr(build_install, '_get_version', lambda: '1.0')
    monkeypatch.setattr(build_install.subprocess, 'run', run)

    with pytest.raises(subprocess.CalledProcessError):
        build_install.main()

    assert calls == [['task', 'build']]
