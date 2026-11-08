"""Start or reuse the local management console without changing Codex files."""
from __future__ import annotations

import errno
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
import webbrowser


ROOT = Path(__file__).resolve().parent
SERVER_PATH = ROOT / 'server.py'
DATA_DIR = ROOT / '.local'
CONSOLE_URL = 'http://127.0.0.1:8765/'
HEALTH_URL = CONSOLE_URL + 'api/health'
SERVICE_NAME = 'codex-skill-workspace'
STARTUP_TIMEOUT = 8.0
_START_LOCK = threading.Lock()


class LauncherError(RuntimeError):
    """The console cannot safely be started or opened."""


def _port_is_free() -> bool:
    """Confirm offline status without sharing or taking over an occupied port."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            # On Windows, a normal bind may share an existing SO_REUSEADDR
            # listener. Exclusive binding is required for a trustworthy check.
            if os.name == 'nt':
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            probe.bind(('127.0.0.1', 8765))
        return True
    except OSError:
        return False


def _probe_console(timeout: float = 0.4) -> bool:
    """Return False only when nothing is listening; reject other services."""
    try:
        with urlopen(HEALTH_URL, timeout=timeout) as response:
            payload = json.loads(response.read(4096))
    except HTTPError as exc:
        raise LauncherError('8765 端口已有其他服务，或健康接口不可用；未停止任何进程。') from exc
    except URLError as exc:
        reason = exc.reason
        if isinstance(reason, ConnectionRefusedError) or getattr(reason, 'errno', None) in (errno.ECONNREFUSED, 10061):
            return False
        if isinstance(reason, TimeoutError) and _port_is_free():
            return False
        raise LauncherError('无法验证 8765 端口上的服务；未启动新进程。') from exc
    except TimeoutError as exc:
        if _port_is_free():
            return False
        raise LauncherError('8765 端口上的服务响应超时；未停止任何进程。') from exc
    except (OSError, ValueError, UnicodeError) as exc:
        raise LauncherError('8765 端口响应不符合管理台健康检查；未停止任何进程。') from exc
    if not isinstance(payload, dict) or payload.get('service') != SERVICE_NAME:
        raise LauncherError('8765 端口已有其他服务；未停止任何进程。')
    return True


def _spawn_console() -> subprocess.Popen:
    if not SERVER_PATH.is_file():
        raise LauncherError(f'找不到管理台服务脚本：{SERVER_PATH}')
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    options = dict(cwd=str(ROOT), stdin=subprocess.DEVNULL, close_fds=True)
    if os.name == 'nt':
        options['creationflags'] = subprocess.CREATE_NO_WINDOW
    else:
        options['start_new_session'] = True
    with (DATA_DIR / 'launcher.log').open('ab') as log:
        return subprocess.Popen([sys.executable, str(SERVER_PATH)], stdout=log, stderr=log, **options)


def ensure_console() -> str:
    """Reuse a healthy console, otherwise start it hidden and wait up to 8s."""
    with _START_LOCK:
        deadline = time.monotonic() + STARTUP_TIMEOUT
        if _probe_console():
            return CONSOLE_URL
        try:
            process = _spawn_console()
        except OSError as exc:
            raise LauncherError(f'无法启动管理台：{exc}') from exc
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise LauncherError('管理台未在 8 秒内就绪，请查看 .local/launcher.log。')
            try:
                if _probe_console(timeout=min(0.4, remaining)):
                    return CONSOLE_URL
            except LauncherError as exc:
                # Windows may time out a connect attempt just as our child binds.
                # Retry only this transient case after starting our own process.
                cause = exc.__cause__
                if isinstance(cause, URLError):
                    cause = cause.reason
                if not isinstance(cause, TimeoutError):
                    raise
            if process.poll() is not None:
                raise LauncherError('管理台启动后退出，请查看 .local/launcher.log。')
            time.sleep(min(0.1, max(0, deadline - time.monotonic())))


def open_console() -> str:
    """Ensure the service exists, then open the console in the default browser."""
    url = ensure_console()
    if not webbrowser.open(url, new=2):
        raise LauncherError(f'管理台已就绪，但浏览器未能打开。请访问 {url}')
    return url


if __name__ == '__main__':
    try:
        print(open_console())
    except LauncherError as error:
        print(str(error), file=sys.stderr)
        raise SystemExit(1)
