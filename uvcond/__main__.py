# uvcond/__main__.py
from __future__ import annotations

import os
import sys
import subprocess
from pathlib import Path
from typing import List, Optional
import shutil


def base_dir() -> Path:
    env = os.environ.get("UVCOND_HOME")
    if env:
        return Path(env).expanduser()
    # Default per-OS
    if os.name == "nt":
        # Windows: use %USERPROFILE%\.uvcond
        return Path(os.environ.get("USERPROFILE", str(Path.home()))) / ".uvcond"
    else:
        # Unix: ~/.uvcond
        return Path.home() / ".uvcond"


def env_dir(name: str) -> Path:
    return base_dir() / name


def cmd_list() -> int:
    base = base_dir()
    if not base.is_dir():
        print("No environments yet.")
        return 0
    for child in sorted(base.iterdir()):
        if child.is_dir():
            print(child.name)
    return 0


def cmd_create(name: str, extra_args: List[str]) -> int:
    base = base_dir()
    base.mkdir(parents=True, exist_ok=True)
    target = env_dir(name)
    print(f"[uvcond] creating {name!r} at {target}")
    # delegate to uv venv
    return subprocess.call(["uv", "venv", str(target), *extra_args])


def cmd_path(name: str) -> int:
    print(env_dir(name))
    return 0


def cmd_spawn(name: str, shell: Optional[str]) -> int:
    target = env_dir(name)
    if not target.is_dir():
        print(f"[uvcond] no env named {name!r} at {target}", file=sys.stderr)
        return 1

    if os.name == "nt":
        return _spawn_windows(target, shell)
    else:
        return _spawn_unix(target, shell)


def _spawn_unix(target: Path, shell: Optional[str]) -> int:
    """
    Spawn a new Unix shell with the venv activated.

    Strategy:
    - Determine shell: argument, $UVCOND_SHELL, else $SHELL, else /bin/bash.
    - Build a command to source the venv's activate script, then start an interactive shell.
    """
    venv_bin = target / "bin"
    if not venv_bin.is_dir():
        print(f"[uvcond] {target} does not look like a venv (no bin/)", file=sys.stderr)
        return 1

    shell = (
        shell
        or os.environ.get("UVCOND_SHELL")
        or os.environ.get("SHELL")
        or "/bin/bash"
    )

    shell = os.path.expanduser(shell)

    # For POSIX shells, we can launch: SHELL -c "source ... && exec SHELL"
    activate = venv_bin / "activate"
    if not activate.is_file():
        print(f"[uvcond] no activate script at {activate}", file=sys.stderr)
        return 1

    cmdline = f'. "{activate}" && exec "{shell}" -i'
    return subprocess.call([shell, "-c", cmdline])


def _spawn_windows(target: Path, shell: Optional[str]) -> int:
    import shutil

    scripts = target / "Scripts"
    if not scripts.is_dir():
        print(f"[uvcond] {target} does not look like a Windows venv (no Scripts\\)", file=sys.stderr)
        return 1

    requested = (shell or os.environ.get("UVCOND_SHELL", "")).lower()

    # --- CMD explicitly requested -----------------------------------------
    if requested in {"cmd", "cmd.exe"}:
        activate_bat = scripts / "activate.bat"
        if not activate_bat.is_file():
            print(f"[uvcond] no activate.bat at {activate_bat}", file=sys.stderr)
            return 1

        # Build the FULL command line as ONE STRING.
        # No nested lists, no double quoting.
        full_cmd = f'call "{activate_bat}" && title uvcond:{target.name}'

        # IMPORTANT: use shell=True to let cmd parse properly.
        return subprocess.call(f'cmd.exe /K {full_cmd}', shell=True)

    # --- PowerShell explicitly requested ----------------------------------
    if requested in {"pwsh", "powershell"}:
        exe = shutil.which("pwsh") if requested == "pwsh" else shutil.which("powershell")
        if not exe:
            print(f"[uvcond] requested shell {requested!r} not found on PATH", file=sys.stderr)
            return 1

        activate_ps1 = scripts / "Activate.ps1"
        if not activate_ps1.is_file():
            print(f"[uvcond] no Activate.ps1 at {activate_ps1}", file=sys.stderr)
            return 1

        cmdline = f'& "{activate_ps1}"'
        return subprocess.call([exe, "-NoLogo", "-NoExit", "-Command", cmdline])

    # --- Auto-detect pwsh → powershell → cmd ------------------------------
    exe_pwsh = shutil.which("pwsh")
    exe_ps = shutil.which("powershell")

    activate_ps1 = scripts / "Activate.ps1"
    activate_bat = scripts / "activate.bat"

    if exe_pwsh or exe_ps:
        if not activate_ps1.is_file():
            print(f"[uvcond] no Activate.ps1 at {activate_ps1}", file=sys.stderr)
            return 1
        exe = exe_pwsh or exe_ps
        cmdline = f'& "{activate_ps1}"'
        return subprocess.call([exe, "-NoLogo", "-NoExit", "-Command", cmdline])

    # Fall back to cmd as last resort
    if not activate_bat.is_file():
        print(f"[uvcond] no activate.bat at {activate_bat}", file=sys.stderr)
        return 1

    cmdline = f'call "{activate_bat}" && title uvcond:{target.name}'
    return subprocess.call(["cmd.exe", "/K", cmdline])


def cmd_help() -> int:
    print(
        "Usage:\n"
        "  uvcond list\n"
        "  uvcond create <name> [extra uv venv args...]\n"
        "  uvcond path <name>\n"
        "  uvcond spawn <name> [shell]\n"
        "\n"
        f"Base directory: {base_dir()}\n"
        "Configure with UVCOND_HOME.\n"
        "shell for spawn:\n"
        "  Unix: inferred from $UVCOND_SHELL or $SHELL, or /bin/bash\n"
        "  Windows: cmd | pwsh (default pwsh; override with UVCOND_SHELL)\n"
    )
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    if not argv:
        return cmd_help()

    sub, *rest = argv

    if sub == "list":
        return cmd_list()
    if sub in {"create", "mk"}:
        if not rest:
            print("uvcond create <name> [extra uv venv args...]", file=sys.stderr)
            return 1
        name, *extra = rest
        return cmd_create(name, extra)
    if sub == "path":
        if not rest:
            print("uvcond path <name>", file=sys.stderr)
            return 1
        return cmd_path(rest[0])
    if sub in {"spawn", "shell"}:
        if not rest:
            print("uvcond spawn <name> [shell]", file=sys.stderr)
            return 1
        name = rest[0]
        shell = rest[1] if len(rest) > 1 else None
        return cmd_spawn(name, shell)

    return cmd_help()


if __name__ == "__main__":
    raise SystemExit(main())
