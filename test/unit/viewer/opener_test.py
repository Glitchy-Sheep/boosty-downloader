"""Native opener handoffs and recording hooks never invoke a shell."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from threading import Event
from typing import TYPE_CHECKING
from unittest.mock import Mock

import pytest

from boosty_downloader.viewer.opener import (
    NO_OPENER,
    RECORD_ENV,
    OpenError,
    detect_opener,
)

if TYPE_CHECKING:
    from pathlib import Path

    from boosty_downloader.viewer.opener import Opener


@dataclass
class _Process:
    code: int | None = 0
    waits: list[float | None] = field(default_factory=list[float | None])
    reaped: Event = field(default_factory=Event)

    def wait(self, timeout: float | None = None) -> int:
        self.waits.append(timeout)
        if self.code is None and timeout is not None:
            command = 'test opener'
            raise subprocess.TimeoutExpired(command, timeout)
        self.reaped.set()
        return self.code or 0


@dataclass(frozen=True, slots=True)
class _Linux:
    opener: Opener
    handoff: Mock
    launch: Mock
    process: _Process


def _which_all(name: str) -> str:
    return f'/usr/bin/{name}'


def _which_none(_name: str) -> None:
    return None


def _linux(
    monkeypatch: pytest.MonkeyPatch,
    *,
    handoff_code: int = 0,
    launch_code: int | None = 0,
) -> _Linux:
    handoff = Mock(return_value=subprocess.CompletedProcess([], handoff_code, '', ''))
    process = _Process(launch_code)
    launch = Mock(return_value=process)
    monkeypatch.setattr(sys, 'platform', 'linux')
    monkeypatch.setattr(shutil, 'which', _which_all)
    monkeypatch.setattr(subprocess, 'run', handoff)
    monkeypatch.setattr(subprocess, 'Popen', launch)
    opener = detect_opener({'WAYLAND_DISPLAY': 'wayland-0'})
    return _Linux(opener, handoff, launch, process)


def test_recording_precedes_ssh_detection_and_never_launches(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run, launch = Mock(), Mock()
    monkeypatch.setattr(subprocess, 'run', run)
    monkeypatch.setattr(subprocess, 'Popen', launch)
    log = tmp_path / 'actions.jsonl'
    opener = detect_opener({RECORD_ENV: str(log), 'SSH_CONNECTION': 'present'})
    assert opener.open is not None
    assert opener.reveal is not None
    assert opener.folders
    opener.open(tmp_path / 'текст, файл.pdf')
    opener.reveal(tmp_path / 'archive.zip')
    assert [
        json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()
    ] == [
        {'action': 'open', 'path': str(tmp_path / 'текст, файл.pdf')},
        {'action': 'reveal', 'path': str(tmp_path / 'archive.zip')},
    ]
    run.assert_not_called()
    launch.assert_not_called()


def test_recording_preserves_all_80_concurrent_actions(tmp_path: Path) -> None:
    log = tmp_path / 'actions.jsonl'
    opener = detect_opener({RECORD_ENV: str(log)})
    assert opener.open is not None
    paths = [tmp_path / f'{index}, длинное имя.pdf' for index in range(80)]
    with ThreadPoolExecutor(max_workers=16) as workers:
        list(workers.map(opener.open, paths))
    actions = [
        json.loads(line) for line in log.read_text(encoding='utf-8').splitlines()
    ]
    assert len(actions) == len(paths)
    assert {action['path'] for action in actions} == {str(path) for path in paths}
    assert {action['action'] for action in actions} == {'open'}


def test_recording_failure_is_an_opener_error(tmp_path: Path) -> None:
    opener = detect_opener({RECORD_ENV: str(tmp_path / 'absent/actions.jsonl')})
    assert opener.open is not None
    with pytest.raises(OpenError, match='recording opener could not write'):
        opener.open(tmp_path / 'file.pdf')


@pytest.mark.parametrize('key', ['SSH_CONNECTION', 'SSH_CLIENT', 'SSH_TTY'])
@pytest.mark.parametrize('value', ['', 'present'])
def test_ssh_environment_disables_real_actions(key: str, value: str) -> None:
    assert detect_opener({key: value}) is NO_OPENER


def test_macos_uses_separate_arguments_and_ten_second_handoff(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run = Mock(return_value=subprocess.CompletedProcess([], 0, '', ''))
    monkeypatch.setattr(sys, 'platform', 'darwin')
    monkeypatch.setattr(subprocess, 'run', run)
    opener = detect_opener({})
    assert opener.system == 'macos'
    assert opener.folders
    assert opener.open is not None
    assert opener.reveal is not None
    path = tmp_path / 'имя, пробелы; $(touch unexpected).pdf'
    opener.open(path)
    opener.reveal(path)
    assert [call.args[0] for call in run.call_args_list] == [
        ['open', str(path)],
        ['open', '-R', str(path)],
    ]
    for call in run.call_args_list:
        assert call.kwargs['timeout'] == 10
        assert not call.kwargs.get('shell', False)


@pytest.mark.parametrize(
    ('failure', 'reason'),
    [
        (
            subprocess.CompletedProcess([], 1, '', 'No default app\nDetails'),
            'No default app',
        ),
        (subprocess.CompletedProcess([], 1, '', ''), 'open failed'),
        (subprocess.TimeoutExpired('open', 10), 'did not answer in time'),
        (OSError('handoff failed'), 'handoff failed'),
    ],
)
def test_immediate_handoff_reports_system_failures(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure: subprocess.CompletedProcess[str] | Exception,
    reason: str,
) -> None:
    run = Mock()
    if isinstance(failure, Exception):
        run.side_effect = failure
    else:
        run.return_value = failure
    monkeypatch.setattr(sys, 'platform', 'darwin')
    monkeypatch.setattr(subprocess, 'run', run)
    opener = detect_opener({})
    assert opener.open is not None
    with pytest.raises(OpenError, match=reason):
        opener.open(tmp_path / 'file.unknown')


def test_immediate_error_reason_is_bounded(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run = Mock(return_value=subprocess.CompletedProcess([], 1, '', 'x' * 10000))
    monkeypatch.setattr(sys, 'platform', 'darwin')
    monkeypatch.setattr(subprocess, 'run', run)
    opener = detect_opener({})
    assert opener.open is not None
    with pytest.raises(OpenError) as error:
        opener.open(tmp_path / 'file.unknown')
    assert len(str(error.value)) == 500


@pytest.mark.parametrize('display', [{}, {'DISPLAY': ''}, {'WAYLAND_DISPLAY': ''}])
def test_linux_without_graphical_session_has_no_actions(
    monkeypatch: pytest.MonkeyPatch, display: dict[str, str]
) -> None:
    monkeypatch.setattr(sys, 'platform', 'linux')
    monkeypatch.setattr(shutil, 'which', _which_all)
    assert detect_opener(display) is NO_OPENER


@pytest.mark.parametrize('display', ['DISPLAY', 'WAYLAND_DISPLAY'])
def test_linux_without_xdg_open_has_no_actions(
    monkeypatch: pytest.MonkeyPatch, display: str
) -> None:
    monkeypatch.setattr(sys, 'platform', 'linux')
    monkeypatch.setattr(shutil, 'which', _which_none)
    assert detect_opener({display: 'desktop'}) is NO_OPENER


def test_linux_reveal_escapes_comma_and_unicode_in_file_manager_uri(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fixture = _linux(monkeypatch)
    assert fixture.opener.reveal is not None
    path = tmp_path / 'имя, файл.zip'
    fixture.opener.reveal(path)
    arguments = fixture.handoff.call_args.args[0]
    assert arguments[0] == 'dbus-send'
    assert 'org.freedesktop.FileManager1.ShowItems' in arguments
    assert f'array:string:{path.as_uri()}' in arguments
    assert '%2C' in path.as_uri()
    fixture.launch.assert_not_called()


@pytest.mark.parametrize(
    'failure', [OSError('no bus'), subprocess.TimeoutExpired('dbus', 10)]
)
def test_linux_reveal_falls_back_when_file_manager_is_unavailable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failure: Exception
) -> None:
    fixture = _linux(monkeypatch)
    fixture.handoff.side_effect = failure
    assert fixture.opener.reveal is not None
    fixture.opener.reveal(tmp_path / 'file.zip')
    assert fixture.launch.call_args.args[0] == ['xdg-open', str(tmp_path)]


def test_linux_reveal_falls_back_after_file_manager_refuses(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fixture = _linux(monkeypatch, handoff_code=1)
    assert fixture.opener.reveal is not None
    fixture.opener.reveal(tmp_path / 'file.zip')
    assert fixture.launch.call_args.args[0] == ['xdg-open', str(tmp_path)]


def test_linux_long_lived_opener_detaches_and_collects_exit(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fixture = _linux(monkeypatch, launch_code=None)
    assert fixture.opener.open is not None
    fixture.opener.open(tmp_path / 'file.pdf')
    assert fixture.launch.call_args.args[0] == ['xdg-open', str(tmp_path / 'file.pdf')]
    assert fixture.launch.call_args.kwargs['start_new_session']
    assert fixture.process.reaped.wait(2)
    assert fixture.process.waits == [2.0, None]


@pytest.mark.parametrize('code', [1, 3])
def test_linux_reports_early_launch_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, code: int
) -> None:
    fixture = _linux(monkeypatch, launch_code=code)
    assert fixture.opener.open is not None
    with pytest.raises(OpenError, match=f'exit code {code}'):
        fixture.opener.open(tmp_path / 'file.pdf')


def test_linux_launch_oserror_becomes_an_opener_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fixture = _linux(monkeypatch)
    fixture.launch.side_effect = OSError('Cannot start helper')
    assert fixture.opener.open is not None
    with pytest.raises(OpenError, match='Cannot start helper'):
        fixture.opener.open(tmp_path / 'file.pdf')


def test_windows_uses_shell_api_and_absolute_explorer_without_waiting_for_status(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    opened = Mock()
    process = _Process(1)
    launch = Mock(return_value=process)
    monkeypatch.setattr(sys, 'platform', 'win32')
    monkeypatch.setattr(os, 'startfile', opened, raising=False)
    monkeypatch.setattr(subprocess, 'Popen', launch)
    opener = detect_opener({'SystemRoot': r'D:\Windows'})
    assert opener.open is not None
    assert opener.reveal is not None
    assert opener.system == 'windows'
    assert opener.folders
    path = tmp_path / 'имя, файл.pdf'
    opener.open(path)
    opener.reveal(path)
    opened.assert_called_once_with(path)
    assert launch.call_args.args[0] == f'"D:\\Windows\\explorer.exe" /select,"{path}"'
    assert not launch.call_args.kwargs.get('shell', False)
    assert process.reaped.wait(2)
    assert process.waits == [None]


@pytest.mark.parametrize('action', ['open', 'reveal'])
def test_windows_reports_launch_oserror(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, action: str
) -> None:
    monkeypatch.setattr(sys, 'platform', 'win32')
    monkeypatch.setattr(
        os, 'startfile', Mock(side_effect=OSError('Denied')), raising=False
    )
    monkeypatch.setattr(subprocess, 'Popen', Mock(side_effect=OSError('Denied')))
    opener = detect_opener({})
    command = opener.open if action == 'open' else opener.reveal
    assert command is not None
    with pytest.raises(OpenError, match='Denied'):
        command(tmp_path / 'file.pdf')


def test_relative_windows_system_root_does_not_search_for_an_executable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, 'platform', 'win32')
    assert detect_opener({'SystemRoot': 'relative'}) is NO_OPENER


def test_termux_only_opens_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fixture = _linux(monkeypatch)
    opener = detect_opener({'ANDROID_ROOT': '/system'})
    assert opener.open is not None
    assert opener.reveal is None
    assert not opener.folders
    assert opener.system == 'android'
    opener.open(tmp_path / 'file.pdf')
    assert fixture.launch.call_args.args[0] == [
        'termux-open',
        str(tmp_path / 'file.pdf'),
    ]


def test_android_without_termux_opener_has_no_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, 'platform', 'linux')
    monkeypatch.setattr(shutil, 'which', _which_none)
    assert detect_opener({'ANDROID_ROOT': '/system'}) is NO_OPENER
