# uvcond

**uvcond** is a small command-line helper that gives you **conda-like, named environments on top of [uv](https://docs.astral.sh/uv/)**.

Under the hood, uvcond just calls `uv venv` to create standard Python virtual environments at predictable locations, and then helps you list, find, and spawn shells into them. 

- One **central directory** for all your envs (configurable).
- Simple **names** (`uvcond create myenv`).
- Works on **Linux/macOS and Windows**.
- Plays nicely with `uv pip`, `uv run`, etc. 

uvcond does **not** replace uv; it just gives you a thin “env manager” UX layer.

---

## Contents

- [Requirements](#requirements)
- [Installation](#installation)
- [Concepts](#concepts)
- [Basic usage](#basic-usage)
- [Linux / macOS shell integration](#linux--macos-shell-integration)
- [Windows shell integration](#windows-shell-integration)
  - [PowerShell](#powershell)
  - [cmd](#cmd)
- [Environment variables](#environment-variables)
- [Design notes & limitations](#design-notes--limitations)
- [License](#license)

---

## Requirements

- **uv** installed and on your `PATH`.  
  See the official uv installation guide for different platforms (installer script, Homebrew, WinGet, Scoop, etc.). 
- A working Python (uv will handle versions / venvs itself). 
- Python **3.9+** to run uvcond itself (configurable in `pyproject.toml`).

---

## Installation

### 1. Clone this repository

```bash
git clone https://github.com/<you>/uvcond.git
cd uvcond
````

### 2. Install uvcond as a uv tool

uv has built-in support for installing tools into isolated environments and exposing them as commands on your `PATH`.

From the project root:

```bash
uv tool install -e .
```

This will:

* Create a tool environment in uv’s tools directory.
* Install uvcond there.
* Expose a `uvcond` (or `uvcond.exe` on Windows) script in uv’s tool bin directory.

If uv’s tool bin directory is not on your `PATH`, run:

```bash
uv tool update-shell
```

and follow the instructions, then restart your shell.

---

## Concepts

* **Base directory**: where all envs live.

  * Unix default: `~/.uvcond`
  * Windows default: `%USERPROFILE%\.uvcond`
  * Override with `UVCOND_HOME`.

* **Env layout**: each env is a standard `venv` created via `uv venv` at:

  ```text
  <base>/<name>
  ```

  uv supports `uv venv PATH` to create a virtual environment at an arbitrary path, and you can pass `--python` to request a specific version.

* **Activation**:

  uvcond can spawn a new shell with the env activated, but **changing the current shell’s environment** always requires shell-specific glue (functions/aliases/scripts), just like the standard `activate` scripts from `venv`.

---

## Basic usage

Once installed, `uvcond` is available in any shell.

### Create an environment

```bash
uvcond create py311 --python 3.11
```

This is roughly equivalent to:

```bash
uv venv <base>/py311 --python 3.11
```

where `<base>` is derived from `UVCOND_HOME` or the defaults above.

You can pass any additional `uv venv` arguments after the name.

### List environments

```bash
uvcond list
```

Shows the names of all directories under the base directory that look like envs.

### Show an environment’s path

```bash
uvcond path py311
# /home/you/.uvcond/py311    (Linux/macOS)
# C:\Users\you\.uvcond\py311 (Windows)
```

### Spawn a new shell with an env activated

```bash
# Linux/macOS – uses $UVCOND_SHELL or $SHELL or /bin/bash
uvcond spawn py311

# Windows – explicitly choose shell:
uvcond spawn py311 pwsh   # PowerShell
uvcond spawn py311 cmd    # cmd.exe
```

On Unix, uvcond runs the venv’s `bin/activate` script and then execs a new interactive shell. On Windows, it uses either `Scripts\activate.bat` (cmd) or `Scripts\Activate.ps1` (PowerShell), which are the standard activation scripts for `venv` and uv environments.

---

## Linux / macOS shell integration

On Unix, you can use `uvcond spawn` for “open a new shell with env active”, or you can add a **helper function** to activate an env directly in your current shell.

Add this to your `~/.bashrc` or `~/.zshrc`:

```bash
uvcond-use() {
    local name="$1"
    if [ -z "$name" ]; then
        echo "Usage: uvcond-use <name>" >&2
        return 1
    fi

    local base="${UVCOND_HOME:-$HOME/.uvcond}"
    local envdir="$base/$name"

    if [ ! -d "$envdir" ]; then
        echo "[uvcond] env '$name' not found at $envdir" >&2
        return 1
    fi

    if [ ! -f "$envdir/bin/activate" ]; then
        echo "[uvcond] no activate script at $envdir/bin/activate" >&2
        return 1
    fi

    # shellcheck disable=SC1090
    . "$envdir/bin/activate"
    echo "[uvcond] activated '$name' ($envdir)"
}
```

Restart your shell or `source ~/.bashrc`/`~/.zshrc`, then:

```bash
uvcond create ds --python 3.12
uvcond-use ds
uv pip install numpy pandas
```

`uv pip` will now install into that active env, as uv uses the active virtual environment when running the pip interface.

---

## Windows shell integration

### PowerShell

You can always use:

```powershell
uvcond spawn myenv pwsh
```

to open a **new** PowerShell instance with the env active.

If you want a `conda activate`-style experience **in the current PowerShell session**, add this function to your PowerShell profile (`$PROFILE`):

```powershell
function uvcond-use {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    $base = $env:UVCOND_HOME
    if (-not $base) {
        $base = Join-Path $HOME ".uvcond"
    }

    $envDir = Join-Path $base $Name
    $activate = Join-Path $envDir "Scripts\\Activate.ps1"

    if (-not (Test-Path $activate)) {
        Write-Error "[uvcond] env '$Name' not found or no Activate.ps1 at $activate"
        return
    }

    . $activate
    Write-Host "[uvcond] activated '$Name' ($envDir)"
}
```

Usage:

```powershell
uvcond create api --python 3.12
uvcond-use api
uv pip install fastapi
```

PowerShell’s `.` (dot-source) operator lets the activation script modify the current session’s environment, so use `. $PROFILE`.

---

### cmd

From cmd, you can spawn a new env-enabled shell:

```bat
uvcond spawn myenv cmd
```

To “activate in this cmd session”, create a `uvcond-use.bat` file somewhere on your `PATH`, for example `C:\Tools\uvcond-use.bat`:

```bat
@echo off
set "BASE=%UVCOND_HOME%"
if "%BASE%"=="" set "BASE=%USERPROFILE%\.uvcond"

if "%1"=="" (
  echo Usage: uvcond-use ^<name^>
  goto :eof
)

set "TARGET=%BASE%\%1"

if not exist "%TARGET%\Scripts\activate.bat" (
  echo [uvcond] env "%1" not found or no Scripts\activate.bat at "%TARGET%"
  goto :eof
)

call "%TARGET%\Scripts\activate.bat"
echo [uvcond] activated "%1" (%TARGET%)
goto :eof

```

Then:

```bat
uvcond create demo --python 3.11
uvcond-use demo
uv pip list
```

The `call` to `Scripts\activate.bat` is the standard way to activate a venv in cmd.

---

## Environment variables

### `UVCOND_HOME`

* Base directory for envs.
* Default:

  * Unix: `~/.uvcond`
  * Windows: `%USERPROFILE%\.uvcond`

Change it if you want your envs somewhere else, e.g.:

```bash
export UVCOND_HOME="$HOME/.local/share/uvcond-envs"
```

or in PowerShell:

```powershell
$env:UVCOND_HOME = "$HOME\.uvcond-envs"
```

### `UVCOND_SHELL`

* Optional hint for which shell `uvcond spawn` should launch.
* On Unix:

  * Default: `$UVCOND_SHELL` → `$SHELL` → `/bin/bash`.
* On Windows:

  * Default: `"pwsh"` if none provided.

Examples:

```bash
# Always spawn zsh on Unix
export UVCOND_SHELL=/bin/zsh
```

```powershell
# Prefer cmd when not explicitly specified
$env:UVCOND_SHELL = "cmd"
```

---

## Design notes & limitations

* uvcond is intentionally **thin**:

  * It delegates all environment creation to `uv venv`, which uses Python’s standard `venv` mechanism.
  * It doesn’t modify or wrap uv’s project-level behavior (`uv run`, `uv sync`, etc.).

* It is **not** a full replacement for conda:

  * No package solver or non-Python dependencies.
  * No global registry inside uv; uvcond maintains a simple “registry” via the filesystem.
  * Envs are **just venvs** at known paths.

* Anything you can do in a normal venv (activating, running Python, using `uv pip` and `uv run`) works the same inside a uvcond-managed env. uv’s pip interface is designed to be a drop-in replacement for common `pip`/`virtualenv` workflows, and uvcond simply organizes those venvs.

---

