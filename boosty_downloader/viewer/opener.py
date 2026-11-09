"""Hand validated local files to the system's default application or file manager."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from enum import Enum
from functools import partial
from pathlib import Path, PureWindowsPath
from threading import Lock, Thread
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from boosty_downloader.viewer.api_models import OpenerSystem

_LAUNCH_GRACE_SECONDS: Final = 2.0
_HANDOFF_TIMEOUT_SECONDS: Final = 10.0
_ERROR_LENGTH: Final = 500
_RECORD_LOCK: Final = Lock()
RECORD_ENV: Final = 'BOOSTY_VIEWER_OPEN_LOG'


class OpenAction(str, Enum):
    """Actions recorded by the non-executing development opener."""

    open = 'open'
    reveal = 'reveal'


class OpenError(Exception):
    """The system could not open a file or show it in its folder."""


@dataclass(frozen=True, slots=True)
class Opener:
    """Available local actions; Android has no folder or reveal capability."""

    open: Callable[[Path], None] | None
    reveal: Callable[[Path], None] | None
    folders: bool
    system: OpenerSystem | None = None


NO_OPENER: Final = Opener(open=None, reveal=None, folders=False)


def detect_opener(environ: Mapping[str, str] | None = None) -> Opener:
    """Select local desktop actions or a recording-only development hook."""
    env = os.environ if environ is None else environ
    if log := env.get(RECORD_ENV):
        record = partial(_record, Path(log))
        return Opener(
            open=partial(record, OpenAction.open),
            reveal=partial(record, OpenAction.reveal),
            folders=True,
            system=_system(env),
        )
    if any(key in env for key in ('SSH_CONNECTION', 'SSH_CLIENT', 'SSH_TTY')):
        return NO_OPENER
    return _system_opener(env)


def _system(env: Mapping[str, str]) -> OpenerSystem:
    match sys.platform:
        case 'darwin':
            return 'macos'
        case 'win32':
            return 'windows'
        case _:
            return 'android' if 'ANDROID_ROOT' in env else 'linux'


def _system_opener(env: Mapping[str, str]) -> Opener:
    match _system(env):
        case 'macos':
            return Opener(_mac_open, _mac_reveal, folders=True, system='macos')
        case 'windows':
            return _windows_opener(env)
        case 'android':
            if shutil.which('termux-open'):
                return Opener(_termux_open, None, folders=False, system='android')
        case 'linux':
            if (env.get('DISPLAY') or env.get('WAYLAND_DISPLAY')) and shutil.which(
                'xdg-open'
            ):
                return Opener(_linux_open, _linux_reveal, folders=True, system='linux')
    return NO_OPENER


def _mac_open(path: Path) -> None:
    _run(['open', str(path)])


def _mac_reveal(path: Path) -> None:
    _run(['open', '-R', str(path)])


def _windows_opener(env: Mapping[str, str]) -> Opener:
    root = env.get('SystemRoot') or env.get('SYSTEMROOT') or r'C:\Windows'
    directory = PureWindowsPath(root)
    if not directory.is_absolute():
        return NO_OPENER
    reveal = partial(_windows_reveal, directory / 'explorer.exe')
    return Opener(_windows_open, reveal, folders=True, system='windows')


def _windows_open(path: Path) -> None:
    try:
        os.startfile(path)  # type: ignore[attr-defined]  # noqa: S606 - validated local file
    except OSError as error:
        raise OpenError(error.strerror or str(error)) from error


def _windows_reveal(explorer: PureWindowsPath, path: Path) -> None:
    # Explorer accepts one command line and may return 1 after a successful reveal.
    try:
        process = subprocess.Popen(  # noqa: S603 - fixed executable, quoted absolute paths
            f'"{explorer}" /select,"{path}"',
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError as error:
        raise OpenError(str(error)) from error
    _reap_later(process)


def _linux_open(path: Path) -> None:
    _launch(['xdg-open', str(path)])


def _linux_reveal(path: Path) -> None:
    arguments = [
        'dbus-send',
        '--session',
        '--print-reply',
        '--type=method_call',
        '--dest=org.freedesktop.FileManager1',
        '/org/freedesktop/FileManager1',
        'org.freedesktop.FileManager1.ShowItems',
        f'array:string:{path.as_uri()}',
        'string:',
    ]
    try:
        _run(arguments)
    except OpenError:
        _launch(['xdg-open', str(path.parent)])


def _termux_open(path: Path) -> None:
    _launch(['termux-open', str(path)])


def _run(arguments: list[str]) -> None:
    result = _handoff(arguments)
    if result.returncode:
        lines = result.stderr.strip().splitlines()
        message = lines[0][:_ERROR_LENGTH] if lines else f'{arguments[0]} failed.'
        raise OpenError(message)


def _handoff(arguments: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(  # noqa: S603 - fixed program, path is one argument
            arguments,
            capture_output=True,
            text=True,
            errors='replace',
            timeout=_HANDOFF_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        message = 'The system did not answer in time.'
        raise OpenError(message) from error
    except OSError as error:
        raise OpenError(str(error)) from error


def _launch(arguments: list[str]) -> None:
    process = _start_detached(arguments)
    try:
        code = process.wait(timeout=_LAUNCH_GRACE_SECONDS)
    except subprocess.TimeoutExpired:
        _reap_later(process)
        return
    if code:
        message = f'{arguments[0]} could not open it (exit code {code}).'
        raise OpenError(message)


def _start_detached(arguments: list[str]) -> subprocess.Popen[bytes]:
    try:
        return subprocess.Popen(  # noqa: S603 - fixed program, path is one argument
            arguments,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except OSError as error:
        raise OpenError(str(error)) from error


def _reap_later(process: subprocess.Popen[bytes]) -> None:
    Thread(target=process.wait, daemon=True).start()


def _record(log: Path, action: OpenAction, path: Path) -> None:
    line = json.dumps({'action': action.value, 'path': str(path)}, ensure_ascii=False)
    try:
        with _RECORD_LOCK, log.open('a', encoding='utf-8') as output:
            output.write(line + '\n')
    except OSError as error:
        message = 'The recording opener could not write its log.'
        raise OpenError(message) from error
