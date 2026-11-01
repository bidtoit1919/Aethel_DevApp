"""Everything the Windows edition does differently from Linux, in one place.

Each function works on Windows and has a development fallback elsewhere, so
the edition's logic and tests also run on a Linux machine. Fallbacks are
for development only and say so where it matters (secrets).
"""

import os
import re
import shutil
import subprocess
import sys
import time

IS_WINDOWS = sys.platform == "win32"

# Background tools (git, gh, docker, agent CLIs) are console programs; from a
# GUI process each would flash a console window without this flag.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
NEW_CONSOLE = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
NEW_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

# CreateProcess takes one command line of at most 32,767 characters. Opening
# prompts longer than this are handed over in a file instead.
PROMPT_ARG_LIMIT = 20_000


# Data ----------------------------------------------------------------------

def data_dir() -> str:
    """Aethel's own folder. XDG_DATA_HOME still wins so tests can isolate
    state the same way on every platform."""
    base = os.environ.get("XDG_DATA_HOME")
    if not base:
        if IS_WINDOWS:
            base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local")
        else:
            base = os.path.join(os.path.expanduser("~"), ".local", "share")
    path = os.path.join(base, "Aethel" if IS_WINDOWS and not os.environ.get("XDG_DATA_HOME") else "aethel")
    os.makedirs(path, exist_ok=True)
    return path


def data_dir_hint() -> str:
    return r"%LOCALAPPDATA%\Aethel" if IS_WINDOWS else "~/.local/share/aethel"


# Processes -----------------------------------------------------------------

_SHIM_TARGET = re.compile(r'"%(?:~)?dp0%\\?([^"]+?\.(?:js|cjs|mjs))"', re.IGNORECASE)


def _npm_shim_target(cmd_path: str) -> str | None:
    """The Node script behind an npm .cmd shim (cmd-shim format:
    "%_prog%" "%dp0%\\node_modules\\pkg\\bin\\cli.js" %*)."""
    try:
        with open(cmd_path, encoding="utf-8", errors="replace") as f:
            text = f.read(4096)
    except OSError:
        return None
    match = _SHIM_TARGET.search(text)
    if not match:
        return None
    relative = match.group(1).replace("\\", os.sep).replace("/", os.sep)
    script = os.path.normpath(os.path.join(os.path.dirname(cmd_path), relative))
    return script if os.path.isfile(script) else None


def resolve_argv(argv: list[str], env: dict | None = None) -> list[str]:
    """argv with the program resolved the way a shell would.

    CreateProcess finds only .exe files by bare name, so `claude` or `codex`
    installed by npm (claude.cmd, codex.cmd) would not start. Batch files
    also re-parse their arguments through cmd.exe, which breaks multi-line
    prompts and JSON. npm shims are therefore replaced by `node <script>`,
    which receives every argument intact."""
    if not argv:
        return argv
    path = (env or {}).get("PATH") or (env or {}).get("Path") or os.environ.get("PATH")
    found = shutil.which(argv[0], path=path)
    if found is None:
        return list(argv)
    if IS_WINDOWS and found.lower().endswith((".cmd", ".bat")):
        script = _npm_shim_target(found)
        node = shutil.which("node", path=path)
        if script and node:
            return [node, script, *argv[1:]]
    return [found, *argv[1:]]


def run(args, **kwargs) -> subprocess.CompletedProcess:
    """subprocess.run for background tools: program resolved, no console
    window, and UTF-8 text (the Windows default code page mangles git and
    gh output)."""
    if isinstance(args, (list, tuple)):
        args = resolve_argv(list(args), kwargs.get("env"))
    if kwargs.get("text") or kwargs.get("universal_newlines"):
        kwargs.setdefault("encoding", "utf-8")
        kwargs.setdefault("errors", "replace")
    kwargs["creationflags"] = kwargs.get("creationflags", 0) | NO_WINDOW
    return subprocess.run(args, **kwargs)


def shell_run(command: str, cwd: str, env: dict, timeout: int) -> subprocess.CompletedProcess:
    """Run a user-typed command line (the project's test command). cmd.exe
    keeps the command's real exit code and understands `&&`; elsewhere bash
    stands in for development."""
    if IS_WINDOWS:
        comspec = os.environ.get("COMSPEC", "cmd.exe")
        # /s with outer quotes: everything inside is taken literally.
        return subprocess.run(f'"{comspec}" /d /s /c "{command}"', cwd=cwd, env=env, capture_output=True,
                              text=True, encoding="utf-8", errors="replace", timeout=timeout,
                              stdin=subprocess.DEVNULL, creationflags=NO_WINDOW)
    return subprocess.run(["bash", "-lc", command], cwd=cwd, env=env, capture_output=True, text=True,
                          timeout=timeout, stdin=subprocess.DEVNULL)


def powershell() -> str:
    """PowerShell 7 when installed, otherwise Windows PowerShell."""
    return shutil.which("pwsh") or shutil.which("powershell") or "powershell.exe"


def open_console(argv: list[str], cwd: str, env: dict) -> subprocess.Popen:
    """Start argv in its own console window. On Windows 11 that window is
    Windows Terminal when it is the default terminal app; either way the
    process is Aethel's child, so Aethel sees when it exits."""
    argv = resolve_argv(argv, env)
    if IS_WINDOWS:
        return subprocess.Popen(argv, cwd=cwd, env=env, creationflags=NEW_CONSOLE | NEW_GROUP)
    # Development stand-in: the first Linux terminal that is installed.
    for term in ("gnome-terminal", "kgx", "konsole", "xterm"):
        if shutil.which(term):
            extra = ["--wait", "--"] if term == "gnome-terminal" else (["--"] if term == "kgx" else ["-e"])
            return subprocess.Popen([term, *extra, *argv], cwd=cwd, env=env, start_new_session=True,
                                    stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL)
    raise OSError(2, "no console host found")


def open_shell(cwd: str) -> None:
    """A shell in cwd for the user: Windows Terminal when installed,
    otherwise PowerShell in a console window."""
    if IS_WINDOWS and shutil.which("wt"):
        subprocess.Popen([shutil.which("wt"), "-d", cwd], creationflags=NO_WINDOW)
        return
    if IS_WINDOWS:
        open_console([powershell(), "-NoLogo"], cwd, dict(os.environ))
        return
    open_console([os.environ.get("SHELL", "bash")], cwd, dict(os.environ))


def run_installer(command: str, cwd: str) -> subprocess.Popen:
    """An agent's installer one-liner (PowerShell syntax) in a visible
    console that stays open, so the user can watch and answer prompts."""
    if IS_WINDOWS:
        script = f"{command}; Write-Host ''; Write-Host 'Finished. Close this window when you are done.'"
        return open_console([powershell(), "-NoLogo", "-NoExit", "-ExecutionPolicy", "Bypass",
                             "-Command", script], cwd, dict(os.environ))
    return open_console(["bash", "-lc", f"{command}; echo; echo 'Finished. Press Enter to close.'; read _"],
                        cwd, dict(os.environ))


def kill_tree(pid: int) -> None:
    """End a process and everything it started (agents spawn tools)."""
    if IS_WINDOWS:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)], capture_output=True,
                       creationflags=NO_WINDOW)
        return
    import signal

    try:
        os.killpg(os.getpgid(pid), signal.SIGHUP)
    except OSError:
        pass


def fit_prompt(prompt: str) -> str:
    """The opening prompt as it can travel on a Windows command line. Long
    prompts are written to Aethel's folder and the agent is pointed at the
    file; the ledger still records the full prompt."""
    if len(prompt) <= PROMPT_ARG_LIMIT:
        return prompt
    folder = os.path.join(data_dir(), "prompts")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"prompt-{time.strftime('%Y%m%d-%H%M%S')}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(prompt)
    return (f"Your task and context for this session were too long for the command line, so Aethel saved "
            f"them to {path}. Read that file first, then follow it.")


# Memory --------------------------------------------------------------------

def total_ram() -> int:
    if IS_WINDOWS:
        import ctypes
        from ctypes import wintypes

        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", wintypes.DWORD), ("dwMemoryLoad", wintypes.DWORD),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
            return int(status.ullTotalPhys)
        return 0
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    return int(line.split()[1]) * 1024
    except OSError:
        pass
    return 0


# Appearance ----------------------------------------------------------------

def system_prefers_dark() -> bool | None:
    """Windows' "Choose your app mode" setting, or None when unknown. GTK
    does not follow it on its own."""
    if not IS_WINDOWS:
        return None
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize") as key:
            value, _kind = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return value == 0
    except OSError:
        return None


def same_path(a: str | None, b: str | None) -> bool:
    """Path equality as Windows sees it: case and separators do not matter."""
    if not a or not b:
        return False
    return os.path.normcase(os.path.normpath(a)) == os.path.normcase(os.path.normpath(b))


# Secrets: Windows Credential Manager ------------------------------------------

CRED_PREFIX = "Aethel"
# CRED_MAX_CREDENTIAL_BLOB_SIZE: 5 * 512 bytes.
MAX_SECRET_BYTES = 2560
_dev_store: dict[str, str] = {}


class SecretStoreError(Exception):
    pass


def _target(project: str, name: str) -> str:
    return f"{CRED_PREFIX}/{project}/{name}"


if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    _CRED_TYPE_GENERIC = 1
    _CRED_PERSIST_LOCAL_MACHINE = 2
    _ERROR_NOT_FOUND = 1168

    class _FILETIME(ctypes.Structure):
        _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]

    class _CREDENTIAL(ctypes.Structure):
        _fields_ = [
            ("Flags", wintypes.DWORD),
            ("Type", wintypes.DWORD),
            ("TargetName", wintypes.LPWSTR),
            ("Comment", wintypes.LPWSTR),
            ("LastWritten", _FILETIME),
            ("CredentialBlobSize", wintypes.DWORD),
            ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
            ("Persist", wintypes.DWORD),
            ("AttributeCount", wintypes.DWORD),
            ("Attributes", ctypes.c_void_p),
            ("TargetAlias", wintypes.LPWSTR),
            ("UserName", wintypes.LPWSTR),
        ]

    _PCRED = ctypes.POINTER(_CREDENTIAL)
    _advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    _CredWrite = _advapi.CredWriteW
    _CredWrite.argtypes = [_PCRED, wintypes.DWORD]
    _CredWrite.restype = wintypes.BOOL
    _CredRead = _advapi.CredReadW
    _CredRead.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(_PCRED)]
    _CredRead.restype = wintypes.BOOL
    _CredDelete = _advapi.CredDeleteW
    _CredDelete.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    _CredDelete.restype = wintypes.BOOL
    _CredEnumerate = _advapi.CredEnumerateW
    _CredEnumerate.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD),
                               ctypes.POINTER(ctypes.POINTER(_PCRED))]
    _CredEnumerate.restype = wintypes.BOOL
    _CredFree = _advapi.CredFree
    _CredFree.argtypes = [ctypes.c_void_p]
    _CredFree.restype = None

    def _fail(what: str):
        code = ctypes.get_last_error()
        raise SecretStoreError(f"Windows Credential Manager could not {what} ({ctypes.FormatError(code).strip()}).")


def secret_names(project: str) -> list[str]:
    prefix = _target(project, "")
    if not IS_WINDOWS:
        return sorted(k[len(prefix):] for k in _dev_store if k.startswith(prefix))
    count = wintypes.DWORD()
    creds = ctypes.POINTER(_PCRED)()
    # The filter allows one trailing "*"; a project path never contains one.
    if not _CredEnumerate(prefix + "*", 0, ctypes.byref(count), ctypes.byref(creds)):
        if ctypes.get_last_error() == _ERROR_NOT_FOUND:
            return []
        _fail("list Aethel's secrets")
    try:
        names = []
        for i in range(count.value):
            target = creds[i].contents.TargetName or ""
            if target.startswith(prefix):
                names.append(target[len(prefix):])
        return sorted(names)
    finally:
        _CredFree(creds)


def set_secret(project: str, name: str, value: str) -> None:
    blob = value.encode("utf-8")
    if len(blob) > MAX_SECRET_BYTES:
        raise SecretStoreError(f"Windows Credential Manager holds at most {MAX_SECRET_BYTES} bytes per secret.")
    if not IS_WINDOWS:
        _dev_store[_target(project, name)] = value
        return
    buffer = (ctypes.c_ubyte * len(blob)).from_buffer_copy(blob) if blob else None
    cred = _CREDENTIAL()
    cred.Type = _CRED_TYPE_GENERIC
    cred.TargetName = _target(project, name)
    cred.Comment = f"Aethel secret {name}"
    cred.CredentialBlobSize = len(blob)
    cred.CredentialBlob = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)) if buffer else None
    cred.Persist = _CRED_PERSIST_LOCAL_MACHINE
    cred.UserName = name
    if not _CredWrite(ctypes.byref(cred), 0):
        _fail(f"save {name}")


def get_secret(project: str, name: str) -> str | None:
    if not IS_WINDOWS:
        return _dev_store.get(_target(project, name))
    pcred = _PCRED()
    if not _CredRead(_target(project, name), _CRED_TYPE_GENERIC, 0, ctypes.byref(pcred)):
        if ctypes.get_last_error() == _ERROR_NOT_FOUND:
            return None
        _fail(f"read {name}")
    try:
        cred = pcred.contents
        data = ctypes.string_at(cred.CredentialBlob, cred.CredentialBlobSize) if cred.CredentialBlobSize else b""
        return data.decode("utf-8", "replace")
    finally:
        _CredFree(pcred)


def delete_secret(project: str, name: str) -> None:
    if not IS_WINDOWS:
        _dev_store.pop(_target(project, name), None)
        return
    if not _CredDelete(_target(project, name), _CRED_TYPE_GENERIC, 0):
        if ctypes.get_last_error() != _ERROR_NOT_FOUND:
            _fail(f"delete {name}")
