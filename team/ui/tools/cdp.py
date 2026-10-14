"""Drive headless Google Chrome through the Chrome DevTools Protocol.

Standard library only: the WebSocket client is written on raw sockets, so the
UI tests need nothing but Python and an installed Chrome.

    from cdp import Browser

    with Browser() as browser:
        page = browser.new_page()
        page.goto("http://127.0.0.1:8000/")
        page.wait_for("document.body.dataset.boot === 'ready'")
        page.screenshot("out/ready.png")

One `Browser` is one Chrome process with its own temporary profile. One
WebSocket to the browser endpoint carries every page as a flattened session.
A reader thread receives all messages, so events (console, network, load) are
recorded the moment Chrome sends them, also while a command is being awaited.

Set CHROME_PATH to use a specific binary. Set CDP_HEADFUL=1 to watch the
browser in a visible window while debugging a test.
"""

from __future__ import annotations

import atexit
import base64
import collections
import hashlib
import json
import math
import os
import select
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.parse
import weakref

# Tests may reach this file as `cdp` (tools/ on sys.path) or as `tools.cdp`
# (team/ui on sys.path). Both names must be one module object: otherwise
# `except JsError` written against one name misses the class raised by the other.
for _alias in ("cdp", "tools.cdp"):
    sys.modules.setdefault(_alias, sys.modules[__name__])

__all__ = [
    "Browser",
    "CdpConnectionLost",
    "CdpError",
    "CdpTimeout",
    "ChromeNotFound",
    "ElementError",
    "JsError",
    "NavigationError",
    "Page",
    "WaitTimeout",
    "WebSocket",
    "WebSocketClosed",
    "WebSocketTimeout",
    "alive_pids",
    "find_chrome",
    "kill_on_exit",
    "sweep_stale_profiles",
]

VISION_KINDS = (
    "none",
    "achromatopsia",
    "blurredVision",
    "deuteranopia",
    "protanopia",
    "tritanopia",
    "reducedContrast",
)

_STARTUP_TIMEOUT_S = 30.0
_GRACEFUL_EXIT_S = 2.0
_PROFILE_ROOT_NAME = "openegiz-ui-cdp"
_OWNER_FILE = "cdp-owner.pid"
_ORPHAN_WITHOUT_OWNER_AFTER_S = 300.0


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------

class CdpError(Exception):
    """Base class of every error raised by this module."""


class ChromeNotFound(CdpError):
    """No Chrome binary: CHROME_PATH is wrong or Chrome is not installed."""


class CdpTimeout(CdpError):
    """Chrome did not answer a command, or an awaited event did not arrive."""


class CdpConnectionLost(CdpError):
    """The browser exited or the DevTools connection broke."""


class NavigationError(CdpError):
    """`Page.goto` could not load the document (connection refused, bad URL)."""


class JsError(CdpError):
    """JavaScript evaluated by `Page.evaluate` threw or rejected.

    `message` is the first line ("Error: boom"), `stack` the full text Chrome
    reports for the thrown value.
    """

    def __init__(self, message, stack=""):
        super().__init__(message)
        self.message = message
        self.stack = stack or message

    def __str__(self):
        return self.stack


class WaitTimeout(CdpError, AssertionError):
    """`Page.wait_for` ran out of time. An AssertionError, so unittest reports FAIL."""

    def __init__(self, message, last_value=None, last_error=None):
        super().__init__(message)
        self.last_value = last_value
        self.last_error = last_error


class ElementError(CdpError, AssertionError):
    """`Page.click` / `Page.hover` could not act on the element."""


class WebSocketClosed(CdpError):
    def __init__(self, code=1006, reason=""):
        super().__init__(f"WebSocket closed ({code}) {reason}".strip())
        self.code = code
        self.reason = reason


class WebSocketTimeout(CdpError):
    """No complete message within the receive timeout; the stream stays usable."""


# --------------------------------------------------------------------------
# WebSocket client (RFC 6455, client side)
# --------------------------------------------------------------------------

_WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_OP_CONTINUATION, _OP_TEXT, _OP_BINARY = 0x0, 0x1, 0x2
_OP_CLOSE, _OP_PING, _OP_PONG = 0x8, 0x9, 0xA


def _mask(data, key):
    """XOR `data` with the repeating 4-byte `key` (big-integer XOR: fast for megabytes)."""
    size = len(data)
    if not size:
        return b""
    repeated = (key * (size // 4 + 1))[:size]
    return (int.from_bytes(data, "big") ^ int.from_bytes(repeated, "big")).to_bytes(size, "big")


class WebSocket:
    """Blocking WebSocket client: text and binary messages, no extensions.

    `recv` may be used by one thread while other threads call `send`.
    """

    def __init__(self, url, timeout=10.0):
        parts = urllib.parse.urlsplit(url)
        if parts.scheme != "ws":
            raise CdpError(f"only ws:// URLs are supported, got {url!r}")
        host = parts.hostname or "127.0.0.1"
        port = parts.port or 80
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        self._buffer = bytearray()
        self._fragments = None
        self._fragment_opcode = None
        self._send_lock = threading.Lock()
        self._close_sent = False
        self.closed = False
        self._sock = socket.create_connection((host, port), timeout=timeout)
        try:
            self._sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self._handshake(host, port, path, timeout)
        except BaseException:
            self._sock.close()
            raise
        # Blocking from here on; receive timeouts are done with select() so
        # that a timeout on the reading side can never cut a send short.
        self._sock.settimeout(None)

    def _handshake(self, host, port, path, timeout):
        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        self._sock.sendall(request.encode("ascii"))
        deadline = time.monotonic() + timeout
        while b"\r\n\r\n" not in self._buffer:
            self._fill(deadline)
        head, _, rest = bytes(self._buffer).partition(b"\r\n\r\n")
        self._buffer = bytearray(rest)
        lines = head.decode("latin-1").split("\r\n")
        status = lines[0].split(" ", 2)
        if len(status) < 2 or status[1] != "101":
            raise CdpError(f"WebSocket upgrade refused: {lines[0]!r}")
        headers = {}
        for line in lines[1:]:
            name, _, value = line.partition(":")
            headers[name.strip().lower()] = value.strip()
        expected = base64.b64encode(hashlib.sha1((key + _WS_GUID).encode("ascii")).digest()).decode("ascii")
        if headers.get("sec-websocket-accept") != expected:
            raise CdpError("WebSocket upgrade answered with a wrong Sec-WebSocket-Accept")

    def _fill(self, deadline):
        """Read more bytes into the buffer, or raise WebSocketTimeout at the deadline."""
        if deadline is None:
            wait = None
        else:
            wait = deadline - time.monotonic()
            if wait <= 0:
                raise WebSocketTimeout("no complete WebSocket message in time")
        try:
            readable, _, _ = select.select([self._sock], [], [], wait)
        except (OSError, ValueError) as error:
            raise WebSocketClosed(1006, str(error)) from None
        if not readable:
            raise WebSocketTimeout("no complete WebSocket message in time")
        try:
            chunk = self._sock.recv(262144)
        except OSError as error:
            self.closed = True
            raise WebSocketClosed(1006, str(error)) from None
        if not chunk:
            self.closed = True
            raise WebSocketClosed(1006, "connection lost")
        self._buffer += chunk

    def _pop_frame(self):
        """Take one complete frame off the buffer: (fin, opcode, payload) or None."""
        buffer = self._buffer
        if len(buffer) < 2:
            return None
        first, second = buffer[0], buffer[1]
        length = second & 0x7F
        offset = 2
        if length == 126:
            if len(buffer) < 4:
                return None
            (length,) = struct.unpack_from(">H", buffer, 2)
            offset = 4
        elif length == 127:
            if len(buffer) < 10:
                return None
            (length,) = struct.unpack_from(">Q", buffer, 2)
            offset = 10
        masked = bool(second & 0x80)
        if masked:
            offset += 4
        end = offset + length
        if len(buffer) < end:
            return None
        payload = bytes(buffer[offset:end])
        if masked:
            payload = _mask(payload, bytes(buffer[offset - 4:offset]))
        del buffer[:end]
        return bool(first & 0x80), first & 0x0F, payload

    def _send_frame(self, opcode, payload):
        size = len(payload)
        header = bytearray([0x80 | opcode])
        if size < 126:
            header.append(0x80 | size)
        elif size < 65536:
            header.append(0x80 | 126)
            header += struct.pack(">H", size)
        else:
            header.append(0x80 | 127)
            header += struct.pack(">Q", size)
        key = os.urandom(4)
        frame = bytes(header) + key + _mask(payload, key)
        with self._send_lock:
            try:
                self._sock.sendall(frame)
            except OSError as error:
                self.closed = True
                raise WebSocketClosed(1006, str(error)) from None

    def send(self, message):
        """Send one text (`str`) or binary (`bytes`) message."""
        if isinstance(message, str):
            self._send_frame(_OP_TEXT, message.encode("utf-8"))
        else:
            self._send_frame(_OP_BINARY, bytes(message))

    def recv(self, timeout=None):
        """Return the next message: `str` for text, `bytes` for binary.

        Answers pings, reassembles fragmented messages. Raises
        `WebSocketTimeout` when no complete message arrives in `timeout`
        seconds (what was received so far is kept for the next call) and
        `WebSocketClosed` on a close frame or a lost connection.
        """
        deadline = None if timeout is None else time.monotonic() + timeout
        while True:
            frame = self._pop_frame()
            if frame is None:
                self._fill(deadline)
                continue
            fin, opcode, payload = frame
            if opcode == _OP_PING:
                self._send_frame(_OP_PONG, payload)
            elif opcode == _OP_PONG:
                pass
            elif opcode == _OP_CLOSE:
                code = struct.unpack(">H", payload[:2])[0] if len(payload) >= 2 else 1005
                reason = payload[2:].decode("utf-8", "replace")
                self._send_close(code if len(payload) >= 2 else 1000)
                self.closed = True
                raise WebSocketClosed(code, reason)
            elif opcode in (_OP_TEXT, _OP_BINARY):
                if fin:
                    return payload.decode("utf-8") if opcode == _OP_TEXT else payload
                self._fragment_opcode = opcode
                self._fragments = [payload]
            elif opcode == _OP_CONTINUATION:
                if self._fragments is None:
                    raise CdpError("WebSocket continuation frame without a first fragment")
                self._fragments.append(payload)
                if fin:
                    data = b"".join(self._fragments)
                    is_text = self._fragment_opcode == _OP_TEXT
                    self._fragments = None
                    self._fragment_opcode = None
                    return data.decode("utf-8") if is_text else data
            else:
                raise CdpError(f"unsupported WebSocket opcode {opcode:#x}")

    def _send_close(self, code):
        if self._close_sent:
            return
        self._close_sent = True
        try:
            self._send_frame(_OP_CLOSE, struct.pack(">H", code))
        except CdpError:
            pass

    def close(self):
        """Send a close frame (best effort) and release the socket. Safe to call twice."""
        if not self.closed:
            self._send_close(1000)
        self.closed = True
        try:
            self._sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self._sock.close()


# --------------------------------------------------------------------------
# Processes: tree listing, kill-on-exit guard, temp profiles
# --------------------------------------------------------------------------

if os.name == "nt":
    import ctypes
    from ctypes import wintypes

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class _ProcessEntry(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_size_t),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    class _IoCounters(ctypes.Structure):
        _fields_ = [(name, ctypes.c_ulonglong) for name in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class _BasicLimits(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_longlong),
            ("PerJobUserTimeLimit", ctypes.c_longlong),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _ExtendedLimits(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _BasicLimits),
            ("IoInfo", _IoCounters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    _kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    _kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    _kernel32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry)]
    _kernel32.Process32FirstW.restype = wintypes.BOOL
    _kernel32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_ProcessEntry)]
    _kernel32.Process32NextW.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL
    _kernel32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    _kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    _kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, wintypes.LPVOID, wintypes.DWORD]
    _kernel32.SetInformationJobObject.restype = wintypes.BOOL
    _kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    _kernel32.AssignProcessToJobObject.restype = wintypes.BOOL
    _kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _kernel32.TerminateJobObject.restype = wintypes.BOOL

    _TH32CS_SNAPPROCESS = 0x00000002
    _INVALID_HANDLE = wintypes.HANDLE(-1).value
    _JOB_EXTENDED_LIMIT_INFORMATION = 9
    _JOB_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000

    def _process_table():
        """Every running process as {pid: (parent pid, image name)}."""
        snapshot = _kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
        if not snapshot or snapshot == _INVALID_HANDLE:
            return {}
        table = {}
        try:
            entry = _ProcessEntry()
            entry.dwSize = ctypes.sizeof(_ProcessEntry)
            more = _kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
            while more:
                table[entry.th32ProcessID] = (entry.th32ParentProcessID, entry.szExeFile)
                more = _kernel32.Process32NextW(snapshot, ctypes.byref(entry))
        finally:
            _kernel32.CloseHandle(snapshot)
        return table

    class _Job:
        """A Windows job object that kills its processes when the last handle closes.

        The handle lives in this Python process, so the children die even when
        the test runner itself is killed and no Python cleanup code runs.
        """

        def __init__(self, process):
            self._handle = _kernel32.CreateJobObjectW(None, None)
            if not self._handle:
                raise OSError(ctypes.get_last_error(), "CreateJobObjectW failed")
            limits = _ExtendedLimits()
            limits.BasicLimitInformation.LimitFlags = _JOB_LIMIT_KILL_ON_JOB_CLOSE
            configured = _kernel32.SetInformationJobObject(
                self._handle, _JOB_EXTENDED_LIMIT_INFORMATION, ctypes.byref(limits), ctypes.sizeof(limits))
            if not configured or not _kernel32.AssignProcessToJobObject(self._handle, int(process._handle)):
                error = ctypes.get_last_error()
                _kernel32.CloseHandle(self._handle)
                self._handle = None
                raise OSError(error, "the process could not be placed in a job object")

        def terminate(self):
            if self._handle:
                _kernel32.TerminateJobObject(self._handle, 1)
                _kernel32.CloseHandle(self._handle)
                self._handle = None

    def _kill_tree(process):
        subprocess.run(
            ["taskkill", "/T", "/F", "/PID", str(process.pid)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
            timeout=15, check=False, creationflags=subprocess.CREATE_NO_WINDOW)

    _POPEN_OPTIONS = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}

else:
    import signal

    def _process_table():
        try:
            listing = subprocess.run(
                ["ps", "-A", "-o", "pid=,ppid=,comm="],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10, check=False).stdout
        except (OSError, subprocess.SubprocessError):
            return {}
        table = {}
        for line in listing.decode("utf-8", "replace").splitlines():
            fields = line.split(None, 2)
            if len(fields) == 3 and fields[0].isdigit() and fields[1].isdigit():
                table[int(fields[0])] = (int(fields[1]), os.path.basename(fields[2]))
        return table

    class _Job:
        """POSIX stand-in: the child leads its own process group, killed as a whole."""

        def __init__(self, process):
            self._pid = process.pid

        def terminate(self):
            if self._pid:
                try:
                    os.killpg(self._pid, signal.SIGKILL)
                except OSError:
                    pass
                self._pid = None

    def _kill_tree(process):
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except OSError:
            process.kill()

    _POPEN_OPTIONS = {"start_new_session": True}


def kill_on_exit(process):
    """Tie a `subprocess.Popen` child (and its descendants) to this Python process.

    Returns a guard with `terminate()`, or None when the platform refused.
    On Windows the children die even if this process is killed without cleanup.
    On POSIX the child must have been started with `start_new_session=True`.
    """
    try:
        return _Job(process)
    except (OSError, AttributeError):
        return None


def alive_pids(pids, image_name=None):
    """The subset of `pids` that still run, optionally only with this image name."""
    table = _process_table()
    wanted = image_name.lower() if image_name else None
    return [pid for pid in pids if pid in table and (wanted is None or table[pid][1].lower() == wanted)]


def _profile_root():
    return os.path.join(tempfile.gettempdir(), _PROFILE_ROOT_NAME)


def _remove_dir(path, timeout=5.0):
    """Delete a directory, retrying while Chrome still releases its files."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            shutil.rmtree(path)
            return True
        except FileNotFoundError:
            return True
        except OSError:
            if time.monotonic() >= deadline:
                shutil.rmtree(path, ignore_errors=True)
                return not os.path.exists(path)
            time.sleep(0.1)


def sweep_stale_profiles():
    """Remove temp profiles whose owning Python process is gone.

    A test run killed from outside cannot delete its profile; the next run
    does it here. A profile is touched only when its owner PID is not running.
    Returns the removed paths.
    """
    root = _profile_root()
    removed = []
    try:
        names = os.listdir(root)
    except OSError:
        return removed
    table = None
    for name in names:
        path = os.path.join(root, name)
        try:
            with open(os.path.join(path, _OWNER_FILE), encoding="ascii") as handle:
                owner = int(handle.read().strip())
        except (OSError, ValueError):
            # No owner mark: either being created right now or broken. Only old ones go.
            try:
                if time.time() - os.path.getmtime(path) < _ORPHAN_WITHOUT_OWNER_AFTER_S:
                    continue
            except OSError:
                continue
            owner = None
        if owner is not None:
            if table is None:
                table = _process_table()
            if not table or owner in table:
                continue
        if _remove_dir(path, timeout=1.0):
            removed.append(path)
    return removed


def _new_profile_dir():
    root = _profile_root()
    os.makedirs(root, exist_ok=True)
    path = tempfile.mkdtemp(prefix="profile-", dir=root)
    with open(os.path.join(path, _OWNER_FILE), "w", encoding="ascii") as handle:
        handle.write(str(os.getpid()))
    return path


# --------------------------------------------------------------------------
# Locating Chrome
# --------------------------------------------------------------------------

def _chrome_candidates():
    if os.name == "nt":
        for variable in ("PROGRAMFILES", "PROGRAMW6432", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            base = os.environ.get(variable)
            if base:
                yield os.path.join(base, "Google", "Chrome", "Application", "chrome.exe")
        try:
            import winreg
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                try:
                    with winreg.OpenKey(hive, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe") as key:
                        yield winreg.QueryValue(key, None)
                except OSError:
                    continue
        except ImportError:
            pass
    elif sys.platform == "darwin":
        for base in ("/Applications", os.path.expanduser("~/Applications")):
            yield os.path.join(base, "Google Chrome.app", "Contents", "MacOS", "Google Chrome")
            yield os.path.join(base, "Chromium.app", "Contents", "MacOS", "Chromium")
    else:
        for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
            found = shutil.which(name)
            if found:
                yield found
        yield "/opt/google/chrome/chrome"


def find_chrome():
    """Path of the Chrome binary: CHROME_PATH if set, else the usual install locations.

    A CHROME_PATH that points nowhere raises `ChromeNotFound` rather than
    falling back, so a run can be forced to skip its browser tests.
    """
    override = os.environ.get("CHROME_PATH")
    if override:
        if os.path.isfile(override):
            return override
        raise ChromeNotFound(f"CHROME_PATH points to a missing file: {override}")
    for candidate in _chrome_candidates():
        if candidate and os.path.isfile(candidate):
            return candidate
    raise ChromeNotFound("Google Chrome was not found; set CHROME_PATH to the chrome binary")


# --------------------------------------------------------------------------
# CDP connection
# --------------------------------------------------------------------------

class _Waiter:
    __slots__ = ("event", "result", "error")

    def __init__(self):
        self.event = threading.Event()
        self.result = None
        self.error = None


class _Connection:
    """Command/response matching and event dispatch over one WebSocket."""

    def __init__(self, url):
        self._ws = WebSocket(url)
        self._lock = threading.Lock()
        self._next_id = 0
        self._pending = {}
        self._sessions = {}
        self._stop = False
        self.dead_reason = None
        self._thread = threading.Thread(target=self._read_loop, name="cdp-reader", daemon=True)
        self._thread.start()

    def subscribe(self, session_id, handler):
        self._sessions[session_id] = handler

    def unsubscribe(self, session_id):
        self._sessions.pop(session_id, None)

    def _read_loop(self):
        reason = "connection closed"
        while not self._stop:
            try:
                raw = self._ws.recv(timeout=0.2)
            except WebSocketTimeout:
                continue
            except CdpError as error:
                reason = str(error)
                break
            try:
                self._dispatch(json.loads(raw))
            except Exception:  # a broken handler must not stop the reader
                traceback.print_exc()
        with self._lock:
            self.dead_reason = reason
            pending, self._pending = self._pending, {}
        for waiter in pending.values():
            waiter.error = CdpConnectionLost(f"browser connection lost: {reason}")
            waiter.event.set()

    def _dispatch(self, message):
        if "id" in message:
            with self._lock:
                waiter = self._pending.pop(message["id"], None)
            if waiter is not None:
                if "error" in message:
                    waiter.error = message["error"]
                else:
                    waiter.result = message.get("result", {})
                waiter.event.set()
            return
        handler = self._sessions.get(message.get("sessionId"))
        if handler is not None:
            handler(message.get("method", ""), message.get("params", {}))

    def _write(self, method, params, session_id, waiter):
        with self._lock:
            if self.dead_reason is not None:
                raise CdpConnectionLost(f"browser connection lost: {self.dead_reason}")
            self._next_id += 1
            message_id = self._next_id
            if waiter is not None:
                self._pending[message_id] = waiter
        message = {"id": message_id, "method": method, "params": params or {}}
        if session_id:
            message["sessionId"] = session_id
        try:
            self._ws.send(json.dumps(message))
        except CdpError as error:
            with self._lock:
                self._pending.pop(message_id, None)
            raise CdpConnectionLost(f"browser connection lost: {error}") from None
        return message_id

    def send(self, method, params=None, session_id=None, timeout=10.0):
        """Send a command and return its result dict."""
        waiter = _Waiter()
        message_id = self._write(method, params, session_id, waiter)
        if not waiter.event.wait(timeout):
            with self._lock:
                self._pending.pop(message_id, None)
            raise CdpTimeout(f"{method} was not answered within {timeout:g} s")
        if isinstance(waiter.error, Exception):
            raise waiter.error
        if waiter.error is not None:
            detail = waiter.error.get("message", "")
            if waiter.error.get("data"):
                detail += f" ({waiter.error['data']})"
            raise CdpError(f"{method}: {detail}")
        return waiter.result

    def post(self, method, params=None, session_id=None):
        """Send a command without waiting for its result (usable from event handlers)."""
        self._write(method, params, session_id, None)

    def close(self):
        self._stop = True
        if threading.current_thread() is not self._thread:
            self._thread.join(timeout=2.0)
        self._ws.close()


# --------------------------------------------------------------------------
# Page
# --------------------------------------------------------------------------

# name: (key, code, Windows virtual key code, text or None)
_NAMED_KEYS = {
    "Tab": ("Tab", "Tab", 9, None),
    "Enter": ("Enter", "Enter", 13, "\r"),
    "Space": (" ", "Space", 32, " "),
    " ": (" ", "Space", 32, " "),
    "Escape": ("Escape", "Escape", 27, None),
    "Backspace": ("Backspace", "Backspace", 8, None),
    "Delete": ("Delete", "Delete", 46, None),
    "ArrowLeft": ("ArrowLeft", "ArrowLeft", 37, None),
    "ArrowUp": ("ArrowUp", "ArrowUp", 38, None),
    "ArrowRight": ("ArrowRight", "ArrowRight", 39, None),
    "ArrowDown": ("ArrowDown", "ArrowDown", 40, None),
    "Home": ("Home", "Home", 36, None),
    "End": ("End", "End", 35, None),
    "PageUp": ("PageUp", "PageUp", 33, None),
    "PageDown": ("PageDown", "PageDown", 34, None),
}
_SHIFT = 8

_FOCUS_INFO_JS = """(() => {
  const el = document.activeElement;
  if (!el) return {tag: "", id: "", testid: null, "data-testid": null, text: "", dataset: {},
                   role: null, "aria-label": null, value: null};
  const testid = el.getAttribute("data-testid");
  return {
    tag: el.tagName.toLowerCase(),
    id: el.id || "",
    testid,
    "data-testid": testid,
    text: (el.textContent || "").replace(/\\s+/g, " ").trim().slice(0, 80),
    dataset: Object.assign({}, el.dataset),
    role: el.getAttribute("role"),
    "aria-label": el.getAttribute("aria-label"),
    value: typeof el.value === "string" ? el.value : null,
  };
})()"""

# Finds a point inside the element that a real pointer would hit. The centre of
# the bounding box comes first; SVG shapes (a diagonal working, a hollow
# outline) often miss it, so the midpoint along their geometry is tried next.
_TARGET_POINT_JS = """((selector, force) => {
  const el = document.querySelector(selector);
  if (!el) return {error: "not_found"};
  el.scrollIntoView({block: "center", inline: "center", behavior: "instant"});
  const box = el.getBoundingClientRect();
  const isSvg = el instanceof SVGElement;
  if ((box.width <= 0 && box.height <= 0) || (!isSvg && (box.width <= 0 || box.height <= 0))) {
    return {error: "zero_size"};
  }
  const points = [];
  const add = (x, y) => { if (Number.isFinite(x) && Number.isFinite(y)) points.push([x, y]); };
  add(box.left + box.width / 2, box.top + box.height / 2);
  if (isSvg) {
    const shapes = el instanceof SVGGeometryElement ? [el] : [];
    shapes.push(...Array.from(el.querySelectorAll("path,line,polyline,polygon,rect,circle,ellipse")).slice(0, 24));
    for (const shape of shapes) {
      try {
        const middle = shape.getPointAtLength(shape.getTotalLength() / 2);
        const matrix = shape.getScreenCTM();
        if (matrix) {
          const point = new DOMPoint(middle.x, middle.y).matrixTransform(matrix);
          add(point.x, point.y);
        }
      } catch (error) { /* shape without geometry: skip */ }
    }
  }
  for (const rect of el.getClientRects()) add(rect.left + rect.width / 2, rect.top + rect.height / 2);
  const describe = (node) => {
    if (!node) return "nothing (point outside the viewport)";
    let text = node.tagName.toLowerCase();
    if (node.id) text += "#" + node.id;
    const testid = node.getAttribute && node.getAttribute("data-testid");
    if (testid) text += '[data-testid="' + testid + '"]';
    return text;
  };
  let blocker = null;
  for (const [x, y] of points) {
    if (x < 0 || y < 0 || x >= innerWidth || y >= innerHeight) continue;
    const hit = document.elementFromPoint(x, y);
    if (hit && (hit === el || el.contains(hit))) return {x, y};
    if (blocker === null) blocker = describe(hit);
  }
  if (force) return {x: points[0][0], y: points[0][1]};
  return {error: "covered", by: blocker === null ? describe(null) : blocker};
})"""


def _to_python(remote):
    """Convert a CDP RemoteObject (returned by value) to a Python value."""
    if "value" in remote:
        return remote["value"]
    unserializable = remote.get("unserializableValue")
    if unserializable is not None:
        if unserializable == "NaN":
            return math.nan
        if unserializable == "Infinity":
            return math.inf
        if unserializable == "-Infinity":
            return -math.inf
        if unserializable == "-0":
            return -0.0
        if unserializable.endswith("n"):
            return int(unserializable[:-1])
    if remote.get("type") == "undefined":
        return None
    return remote.get("description")


def _js_truthy(remote):
    """JavaScript truthiness of a RemoteObject ([] and {} are truthy, unlike in Python)."""
    kind = remote.get("type")
    if kind == "undefined":
        return False
    if "unserializableValue" in remote:
        return remote["unserializableValue"] not in ("NaN", "-0", "0n")
    if kind == "object":
        return remote.get("subtype") != "null"
    if kind in ("boolean", "number", "string"):
        return bool(remote.get("value"))
    return True


def _console_argument(remote):
    if "value" in remote:
        value = remote["value"]
        return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    preview = remote.get("preview")
    if preview and remote.get("subtype") in (None, "array"):
        # A plain object or array logged to the console: show its first properties, as DevTools does.
        is_array = remote.get("subtype") == "array"
        items = [str(item.get("value", "")) if is_array else f"{item.get('name')}: {item.get('value', '')}"
                 for item in preview.get("properties", [])]
        if preview.get("overflow"):
            items.append("…")
        return ("[" if is_array else "{") + ", ".join(items) + ("]" if is_array else "}")
    return str(remote.get("description") or remote.get("unserializableValue") or remote.get("type"))


def _top_frame(stack_trace):
    frames = (stack_trace or {}).get("callFrames") or []
    if frames:
        return frames[0].get("url", ""), frames[0].get("lineNumber", -1) + 1
    return "", 0


class Page:
    """One tab. Created by `Browser.new_page()`.

    Attributes filled by Chrome's events, in arrival order:

    `console_errors`    uncaught exceptions, unhandled rejections, console.error /
                        failed console.assert, and browser-reported errors other
                        than network ones (a blocked module script, a CSP
                        violation): `{"kind", "text", "url", "line"}`, `line` 1-based.
    `console_messages`  every console.* call: `{"kind", "type", "text", "url", "line"}`.
    `log_entries`       every browser log entry, network failures included:
                        `{"source", "level", "text", "url", "line"}`.
    `requests`          every network request: `{"url", "method", "status" or None,
                        "failed", "error", "type", "post_data", "finished"}`.
    `dialogs`           native alert/confirm/prompt dialogs, dismissed automatically.
    """

    def __init__(self, browser, target_id, session_id):
        self._browser = browser
        self._conn = browser._conn
        self._target_id = target_id
        self._session_id = session_id
        self._closed = False
        self.crashed = False
        self.console_errors = []
        self.console_messages = []
        self.log_entries = []
        self.requests = []
        self.dialogs = []
        self._requests_by_id = {}
        self._events = collections.deque(maxlen=5000)
        self._event_seq = 0
        self._event_cond = threading.Condition()
        self._handlers = {
            "Runtime.consoleAPICalled": self._on_console,
            "Runtime.exceptionThrown": self._on_exception,
            "Log.entryAdded": self._on_log_entry,
            "Network.requestWillBeSent": self._on_request,
            "Network.responseReceived": self._on_response,
            "Network.loadingFinished": self._on_loading_finished,
            "Network.loadingFailed": self._on_loading_failed,
            "Page.javascriptDialogOpening": self._on_dialog,
            "Inspector.targetCrashed": self._on_crash,
        }
        self._conn.subscribe(session_id, self._on_event)

    # ---- protocol access -------------------------------------------------

    def send(self, method, params=None, timeout=10.0):
        """Send any CDP command to this page and return its result dict."""
        if self._closed:
            raise CdpError("the page is closed")
        if self.crashed:
            raise CdpError("the page renderer crashed")
        return self._conn.send(method, params, self._session_id, timeout)

    def event_cursor(self):
        """A position in the event stream, for `wait_for_event(since=...)`."""
        with self._event_cond:
            return self._event_seq

    def wait_for_event(self, method, timeout=10.0, since=0, predicate=None):
        """Return the params of the first `method` event after `since` (and matching `predicate`)."""
        deadline = time.monotonic() + timeout
        with self._event_cond:
            while True:
                for sequence, name, params in self._events:
                    if sequence > since and name == method and (predicate is None or predicate(params)):
                        return params
                    since = max(since, sequence)
                if self._conn.dead_reason is not None:
                    raise CdpConnectionLost(f"browser connection lost: {self._conn.dead_reason}")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise CdpTimeout(f"event {method} did not arrive within {timeout:g} s")
                self._event_cond.wait(min(remaining, 0.25))

    def _on_event(self, method, params):
        handler = self._handlers.get(method)
        if handler is not None:
            handler(params)
        with self._event_cond:
            self._event_seq += 1
            self._events.append((self._event_seq, method, params))
            self._event_cond.notify_all()

    # ---- event recording (reader thread) ---------------------------------

    def _on_console(self, params):
        url, line = _top_frame(params.get("stackTrace"))
        kind = params.get("type", "log")
        entry = {
            "kind": "console." + kind,
            "type": kind,
            "text": " ".join(_console_argument(arg) for arg in params.get("args", [])),
            "url": url,
            "line": line,
        }
        self.console_messages.append(entry)
        if kind in ("error", "assert"):
            self.console_errors.append(entry)

    def _on_exception(self, params):
        details = params.get("exceptionDetails", {})
        thrown = details.get("exception", {})
        description = thrown.get("description")
        if description is None and "value" in thrown:
            description = _console_argument(thrown)
        url, line = _top_frame(details.get("stackTrace"))
        self.console_errors.append({
            "kind": "exception",
            "text": " ".join(part for part in (details.get("text"), description) if part),
            "url": details.get("url") or url,
            "line": details.get("lineNumber", -1) + 1 if "lineNumber" in details else line,
        })

    def _on_log_entry(self, params):
        entry = params.get("entry", {})
        record = {
            "source": entry.get("source", ""),
            "level": entry.get("level", ""),
            "text": entry.get("text", ""),
            "url": entry.get("url", ""),
            "line": entry.get("lineNumber", -1) + 1 if "lineNumber" in entry else 0,
        }
        self.log_entries.append(record)
        if record["level"] == "error" and record["source"] != "network":
            self.console_errors.append({
                "kind": "log." + record["source"],
                "text": record["text"],
                "url": record["url"],
                "line": record["line"],
            })

    def _on_request(self, params):
        request_id = params.get("requestId")
        request = params.get("request", {})
        previous = self._requests_by_id.get(request_id)
        redirect = params.get("redirectResponse")
        if previous is not None and redirect is not None:
            previous["status"] = redirect.get("status")
            previous["finished"] = True
        entry = {
            "url": request.get("url", ""),
            "method": request.get("method", ""),
            "status": None,
            "failed": False,
            "error": None,
            "type": params.get("type"),
            "post_data": request.get("postData"),
            "finished": False,
        }
        self._requests_by_id[request_id] = entry
        self.requests.append(entry)

    def _on_response(self, params):
        entry = self._requests_by_id.get(params.get("requestId"))
        if entry is not None:
            entry["status"] = params.get("response", {}).get("status")

    def _on_loading_finished(self, params):
        entry = self._requests_by_id.get(params.get("requestId"))
        if entry is not None:
            entry["finished"] = True

    def _on_loading_failed(self, params):
        entry = self._requests_by_id.get(params.get("requestId"))
        if entry is not None:
            entry["error"] = params.get("errorText")
            entry["failed"] = True
            entry["finished"] = True

    def _on_dialog(self, params):
        kind = params.get("type", "")
        self.dialogs.append({"type": kind, "message": params.get("message", "")})
        # A native dialog blocks the page; tests never answer one by hand.
        self._conn.post("Page.handleJavaScriptDialog", {"accept": kind in ("alert", "beforeunload")},
                        self._session_id)

    def _on_crash(self, params):
        self.crashed = True

    # ---- navigation and scripting ----------------------------------------

    def goto(self, url, timeout=15.0):
        """Navigate and return after the load event.

        A change of the #fragment only is a same-document navigation: it has
        no load event and returns at once.
        """
        deadline = time.monotonic() + timeout
        cursor = self.event_cursor()
        result = self.send("Page.navigate", {"url": url}, timeout=timeout)
        if result.get("errorText"):
            raise NavigationError(f"{url}: {result['errorText']}")
        if not result.get("loaderId"):
            return
        self._await_load(url, cursor, deadline, timeout)

    def reload(self, timeout=15.0):
        """Reload the document and return after the load event."""
        deadline = time.monotonic() + timeout
        cursor = self.event_cursor()
        self.send("Page.reload", {"ignoreCache": True}, timeout=timeout)
        self._await_load("reload", cursor, deadline, timeout)

    def _await_load(self, what, cursor, deadline, timeout):
        try:
            self.wait_for_event("Page.loadEventFired", timeout=max(deadline - time.monotonic(), 0.0), since=cursor)
        except CdpTimeout:
            raise CdpTimeout(f"{what}: no load event within {timeout:g} s") from None

    def _evaluate_remote(self, expression, timeout):
        result = self.send("Runtime.evaluate", {
            "expression": expression,
            "awaitPromise": True,
            "returnByValue": True,
            "userGesture": True,
        }, timeout=timeout)
        details = result.get("exceptionDetails")
        if details:
            thrown = details.get("exception", {})
            stack = thrown.get("description")
            if stack is None:
                stack = _console_argument(thrown) if "value" in thrown else details.get("text", "JavaScript error")
            raise JsError(stack.split("\n", 1)[0], stack)
        return result.get("result", {})

    def evaluate(self, expression, timeout=10.0):
        """Evaluate a JavaScript expression in the page and return its value.

        A promise is awaited. The value must be JSON-able (`undefined` gives
        None). A throw or a rejection raises `JsError`. The source runs as a
        classic script in the global scope: wrap statements in an IIFE, since
        a top-level `const` would collide on the second call.
        """
        return _to_python(self._evaluate_remote(expression, timeout))

    def wait_for(self, expression, timeout=10.0, interval=0.1, message=""):
        """Poll `expression` until it is truthy in the JavaScript sense; return its value.

        An exception thrown by the expression counts as "not yet" (the element
        may simply not exist so far) and is reported if the wait times out.
        Raises `WaitTimeout` carrying `message`, the last value and the last error.
        """
        deadline = time.monotonic() + timeout
        last_value = None
        last_error = None
        while True:
            try:
                remote = self._evaluate_remote(expression, timeout=max(deadline - time.monotonic(), 0.5))
            except CdpConnectionLost:
                raise
            except CdpError as error:
                last_error = error
            else:
                last_error = None
                last_value = _to_python(remote)
                if _js_truthy(remote):
                    return last_value
            if time.monotonic() + interval > deadline:
                break
            time.sleep(interval)
        text = f"{message or 'condition not met'}: `{expression}` not truthy after {timeout:g} s; "
        if last_error is not None:
            text += f"last error: {last_error}"
        else:
            text += f"last value: {last_value!r}"
        raise WaitTimeout(text, last_value, last_error)

    def wait_for_request(self, url_part, timeout=10.0, method=None):
        """Wait until a request whose URL contains `url_part` has a status or has failed; return its entry."""
        deadline = time.monotonic() + timeout
        while True:
            for entry in list(self.requests):
                if url_part in entry["url"] and (method is None or entry["method"] == method) \
                        and (entry["status"] is not None or entry["failed"]):
                    return entry
            if time.monotonic() >= deadline:
                seen = [f"{entry['method']} {entry['url']}" for entry in list(self.requests)][-10:]
                raise WaitTimeout(f"no completed request containing {url_part!r} within {timeout:g} s; "
                                  f"last requests: {seen}", None, None)
            time.sleep(0.02)

    def add_init_script(self, source):
        """Run `source` before any page script, on every later navigation of this page."""
        return self.send("Page.addScriptToEvaluateOnNewDocument", {"source": source})["identifier"]

    # ---- rendering -------------------------------------------------------

    def set_viewport(self, width, height, device_scale_factor=1):
        """Set the CSS viewport size; the screenshot is `width*dsf` x `height*dsf` pixels."""
        self.send("Emulation.setDeviceMetricsOverride", {
            "width": int(width),
            "height": int(height),
            "deviceScaleFactor": device_scale_factor,
            "mobile": False,
        })
        # The resize reaches the page a moment after the command is answered.
        deadline = time.monotonic() + 2.0
        check = f"window.innerWidth === {int(width)} && window.innerHeight === {int(height)}"
        while time.monotonic() < deadline:
            try:
                if self.evaluate(check, timeout=2.0):
                    return
            except CdpConnectionLost:
                raise
            except CdpError:
                pass
            time.sleep(0.02)

    def screenshot(self, path, full_page=False, clip=None):
        """Save a PNG of the viewport, of the whole document, or of `clip=(x, y, width, height)` in CSS pixels."""
        params = {"format": "png", "captureBeyondViewport": bool(full_page)}
        if clip is not None:
            x, y, width, height = clip
            params["clip"] = {"x": x, "y": y, "width": width, "height": height, "scale": 1}
            params["captureBeyondViewport"] = True
        elif full_page:
            size = self.send("Page.getLayoutMetrics")["cssContentSize"]
            params["clip"] = {"x": 0, "y": 0, "width": math.ceil(size["width"]),
                              "height": math.ceil(size["height"]), "scale": 1}
        self.send("Page.bringToFront")
        data = base64.b64decode(self.send("Page.captureScreenshot", params, timeout=30.0)["data"])
        path = os.path.abspath(os.fspath(path))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(data)
        return path

    def emulate_vision(self, kind):
        """Render as seen with a vision deficiency: "none" or "achromatopsia" (greyscale), and Chrome's other kinds."""
        if kind not in VISION_KINDS:
            raise ValueError(f"unknown vision kind {kind!r}; expected one of {VISION_KINDS}")
        self.send("Emulation.setEmulatedVisionDeficiency", {"type": kind})

    def metrics(self):
        """`Performance.getMetrics` as a dict: Nodes, ScriptDuration, LayoutDuration, JSHeapUsedSize, ..."""
        return {item["name"]: item["value"] for item in self.send("Performance.getMetrics")["metrics"]}

    # ---- input -----------------------------------------------------------

    def _key_event(self, kind, key, code, virtual_key, modifiers, text=None):
        params = {
            "type": kind,
            "key": key,
            "code": code,
            "windowsVirtualKeyCode": virtual_key,
            "nativeVirtualKeyCode": virtual_key,
            "modifiers": modifiers,
        }
        if text is not None and kind == "keyDown":
            params["text"] = text
            params["unmodifiedText"] = text
        self.send("Input.dispatchKeyEvent", params)

    def press(self, key, shift=False):
        """Press and release a key as trusted keyboard input to the focused element.

        `key` is "Tab", "Enter", "Space", "Escape", "ArrowDown", "ArrowUp",
        "ArrowLeft", "ArrowRight", "Home", "End", "PageUp", "PageDown",
        "Backspace", "Delete" or a single character.
        """
        if key in _NAMED_KEYS:
            name, code, virtual_key, text = _NAMED_KEYS[key]
        elif len(key) == 1:
            name = text = key.upper() if shift else key
            if key.isascii() and key.isalpha():
                code, virtual_key = "Key" + key.upper(), ord(key.upper())
            elif key.isascii() and key.isdigit():
                code, virtual_key = "Digit" + key, ord(key)
            else:
                code, virtual_key = "", 0
        else:
            raise ValueError(f"unknown key {key!r}")
        modifiers = _SHIFT if shift else 0
        if shift:
            self._key_event("rawKeyDown", "Shift", "ShiftLeft", 16, _SHIFT)
        self._key_event("keyDown" if text is not None else "rawKeyDown", name, code, virtual_key, modifiers, text)
        self._key_event("keyUp", name, code, virtual_key, modifiers)
        if shift:
            self._key_event("keyUp", "Shift", "ShiftLeft", 16, 0)

    def type_text(self, text):
        """Insert text into the focused field, as if typed or pasted (no key events)."""
        self.send("Input.insertText", {"text": text})

    def _target_point(self, selector, force, timeout):
        deadline = time.monotonic() + timeout
        expression = f"{_TARGET_POINT_JS}({json.dumps(selector)}, {json.dumps(bool(force))})"
        while True:
            found = self.evaluate(expression)
            if "error" not in found:
                return found["x"], found["y"]
            if time.monotonic() >= deadline:
                break
            time.sleep(0.05)
        if found["error"] == "not_found":
            raise ElementError(f"no element matches {selector!r}")
        if found["error"] == "zero_size":
            raise ElementError(f"element {selector!r} has no size (hidden or not laid out)")
        raise ElementError(f"element {selector!r} cannot be hit by the pointer: its place is taken by {found['by']}")

    def click(self, selector, force=False, timeout=0.0):
        """Scroll the element into view and click it with a real mouse press and release.

        Raises `ElementError` when nothing matches, the element has no size,
        or another element covers it (`force=True` clicks the centre anyway).
        `timeout` > 0 keeps retrying that long before raising. Returns the
        clicked viewport point.
        """
        x, y = self._target_point(selector, force, timeout)
        self.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
        button = {"x": x, "y": y, "button": "left", "clickCount": 1}
        self.send("Input.dispatchMouseEvent", {"type": "mousePressed", "buttons": 1, **button})
        self.send("Input.dispatchMouseEvent", {"type": "mouseReleased", "buttons": 0, **button})
        return {"x": x, "y": y}

    def hover(self, selector, timeout=0.0):
        """Move the mouse over the element (same targeting as `click`)."""
        x, y = self._target_point(selector, False, timeout)
        self.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
        return {"x": x, "y": y}

    def focus_info(self):
        """Describe `document.activeElement`.

        Keys: `tag` (lower case), `id`, `data-testid` (also as `testid`),
        `text` (whitespace collapsed, at most 80 characters), `dataset`,
        `role`, `aria-label`, `value`.
        """
        return self.evaluate(_FOCUS_INFO_JS)

    # ---- housekeeping ----------------------------------------------------

    def clear_logs(self):
        """Empty `console_errors`, `console_messages`, `log_entries`, `requests` and `dialogs` in place."""
        for records in (self.console_errors, self.console_messages, self.log_entries, self.requests, self.dialogs):
            del records[:]
        self._requests_by_id.clear()

    def close(self):
        """Close the tab. Safe to call twice and after the browser is gone."""
        if self._closed:
            return
        self._closed = True
        try:
            self._browser._conn.send("Target.closeTarget", {"targetId": self._target_id}, timeout=5.0)
        except CdpError:
            pass
        self._conn.unsubscribe(self._session_id)
        self._browser._forget(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()


# --------------------------------------------------------------------------
# Browser
# --------------------------------------------------------------------------

_LIVE_BROWSERS = weakref.WeakSet()


@atexit.register
def _close_live_browsers():
    for browser in list(_LIVE_BROWSERS):
        browser.close()


class Browser:
    """One Chrome process with its own temporary profile. Use as a context manager.

    `extra_args` are appended to the Chrome command line. `headless=False`
    (or the environment variable CDP_HEADFUL=1) opens a visible window.
    """

    def __init__(self, width=1280, height=720, extra_args=(), headless=None):
        self.width = int(width)
        self.height = int(height)
        self.profile_dir = None
        self.pid = None
        self._proc = None
        self._conn = None
        self._job = None
        self._pages = []
        self._closed = False
        self._close_lock = threading.Lock()
        self.chrome_path = find_chrome()
        if headless is None:
            headless = os.environ.get("CDP_HEADFUL", "").strip().lower() not in ("1", "true", "yes")
        self.headless = bool(headless)
        sweep_stale_profiles()
        _LIVE_BROWSERS.add(self)
        try:
            self.profile_dir = _new_profile_dir()
            self._launch(tuple(extra_args))
            self._conn = _Connection(self._wait_for_endpoint(_STARTUP_TIMEOUT_S))
        except BaseException:
            self.close()
            raise

    def _launch(self, extra_args):
        args = [self.chrome_path]
        if self.headless:
            args += ["--headless=new", "--hide-scrollbars"]
        args += [
            "--disable-gpu",
            "--remote-debugging-port=0",
            f"--user-data-dir={self.profile_dir}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-background-networking",
            "--disable-component-update",
            "--disable-sync",
            "--mute-audio",
            f"--window-size={self.width},{self.height}",
            # Timers and rendering must not slow down in a tab that is not in front,
            # and colours must not depend on the monitor profile of the machine.
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--force-color-profile=srgb",
        ]
        args += list(extra_args)
        args.append("about:blank")
        self._stderr_path = os.path.join(self.profile_dir, "chrome-stderr.log")
        with open(self._stderr_path, "wb") as stderr:
            self._proc = subprocess.Popen(
                args, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=stderr, **_POPEN_OPTIONS)
        self.pid = self._proc.pid
        self._job = kill_on_exit(self._proc)

    def _wait_for_endpoint(self, timeout):
        """Read the port Chrome chose from DevToolsActivePort and return the browser WebSocket URL."""
        port_file = os.path.join(self.profile_dir, "DevToolsActivePort")
        deadline = time.monotonic() + timeout
        while True:
            try:
                with open(port_file, encoding="utf-8") as handle:
                    lines = handle.read().split("\n")
            except OSError:
                lines = []
            if len(lines) >= 2 and lines[0].strip().isdigit() and lines[1].strip():
                return f"ws://127.0.0.1:{lines[0].strip()}{lines[1].strip()}"
            exit_code = self._proc.poll()
            if exit_code is not None:
                raise CdpError(f"Chrome exited with code {exit_code} before opening the DevTools port. "
                               f"{self._stderr_tail()}")
            if time.monotonic() >= deadline:
                raise CdpTimeout(f"Chrome did not open the DevTools port within {timeout:g} s. {self._stderr_tail()}")
            time.sleep(0.05)

    def _stderr_tail(self):
        try:
            with open(self._stderr_path, "rb") as handle:
                text = handle.read()[-2000:].decode("utf-8", "replace").strip()
        except OSError:
            return ""
        return f"Chrome stderr: {text}" if text else ""

    def new_page(self):
        """Open a tab with the browser's viewport size and recording switched on."""
        if self._closed:
            raise CdpError("the browser is closed")
        target_id = self._conn.send("Target.createTarget", {"url": "about:blank"})["targetId"]
        session_id = self._conn.send("Target.attachToTarget", {"targetId": target_id, "flatten": True})["sessionId"]
        page = Page(self, target_id, session_id)
        self._pages.append(page)
        for domain in ("Page", "Runtime", "Network", "Log", "Performance"):
            page.send(domain + ".enable")
        page.send("Network.setCacheDisabled", {"cacheDisabled": True})
        # Headless tabs have no window focus; without this, Tab would not move
        # focus and :focus-visible would never match.
        page.send("Emulation.setFocusEmulationEnabled", {"enabled": True})
        page.set_viewport(self.width, self.height)
        return page

    def _forget(self, page):
        if page in self._pages:
            self._pages.remove(page)

    def version(self):
        """Chrome's product string, e.g. "Chrome/154.0.8037.98"."""
        return self._conn.send("Browser.getVersion")["product"]

    def process_ids(self):
        """PIDs of this browser's Chrome processes that are running now, the main one first."""
        if self.pid is None:
            return []
        table = _process_table()
        if self.pid not in table:
            return []
        image = table[self.pid][1].lower()
        found = [self.pid]
        queue = [self.pid]
        while queue:
            parent = queue.pop()
            for pid, (parent_pid, name) in table.items():
                if parent_pid == parent and pid not in found and name.lower() == image:
                    found.append(pid)
                    queue.append(pid)
        return found

    def close(self):
        """Stop Chrome with all its child processes and delete the profile. Safe to call twice."""
        with self._close_lock:
            if self._closed:
                return
            self._closed = True
        for page in list(self._pages):
            page._closed = True
        self._pages.clear()
        if self._conn is not None:
            try:
                self._conn.post("Browser.close")
            except CdpError:
                pass
        if self._proc is not None:
            try:
                self._proc.wait(timeout=_GRACEFUL_EXIT_S)
            except subprocess.TimeoutExpired:
                try:
                    _kill_tree(self._proc)
                except (OSError, subprocess.SubprocessError):
                    self._proc.kill()
        if self._conn is not None:
            self._conn.close()
        if self._job is not None:
            # Whatever outlived the main process (crash handler, a stuck renderer).
            self._job.terminate()
        if self._proc is not None:
            try:
                self._proc.wait(timeout=10.0)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        if self.profile_dir is not None:
            _remove_dir(self.profile_dir)
            try:
                os.rmdir(_profile_root())
            except OSError:
                pass  # other profiles are in use, or it is already gone
        _LIVE_BROWSERS.discard(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        self.close()
