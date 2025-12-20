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
- [Recipes — shareable environments](#recipes--shareable-environments)
- [Linux / macOS shell integration](#linux--macos-shell-integration)
- [Windows shell integration](#windows-shell-integration)
  - [PowerShell](#powershell)
  - [cmd](#cmd)
- [Configuration](#configuration)
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
uv tool install .
```

This will:

* Create a tool environment in uv's tools directory.
* Copy uvcond into that environment.
* Expose a `uvcond` (or `uvcond.exe` on Windows) script in uv's tool bin directory.

You can safely delete or move the source folder after installation.

**For development** (if you want to hack on uvcond itself):

```bash
uv tool install -e .
```

The `-e` flag creates an editable install that links to your source folder, so changes take effect immediately — but the folder must stay in place.

If uv's tool bin directory is not on your `PATH`, run:

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

### Show an environment's path

```bash
uvcond path py311
# /home/you/.uvcond/py311    (Linux/macOS)
# C:\Users\you\.uvcond\py311 (Windows)
```

### Delete an environment

```bash
uvcond delete py311          # Asks for confirmation
uvcond delete py311 --force  # No confirmation
```

### Spawn a new shell with an env activated

```bash
# Uses the shell from config, or auto-detects
uvcond spawn py311

# Override shell for this spawn:
uvcond spawn py311 pwsh   # PowerShell
uvcond spawn py311 cmd    # cmd.exe
uvcond spawn py311 zsh    # Zsh
```

On Unix, uvcond runs the venv’s `bin/activate` script and then execs a new interactive shell. On Windows, it uses either `Scripts\activate.bat` (cmd) or `Scripts\Activate.ps1` (PowerShell), which are the standard activation scripts for `venv` and uv environments.

---

## Linux / macOS shell integration

On Unix, you can use `uvcond spawn` for "open a new shell with env active", or you can add a **helper function** to activate an env directly in your current shell.

Add this to your `~/.bashrc` or `~/.zshrc`:

> **Note**: This shell function uses the default path `~/.uvcond`. If you've changed `home` in your config, update the `base` variable below to match.

```bash
uvcond-use() {
    local name="$1"
    if [ -z "$name" ]; then
        echo "Usage: uvcond-use <name>" >&2
        return 1
    fi

    # Change this if you set a custom 'home' in uvcond config
    local base="$HOME/.uvcond"
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

## Recipes — shareable environments

Recipes let you export an environment as a small, portable TOML file that can recreate the same setup on another machine. Think of it as a shareable snapshot of your env.

### Recipe format

```toml
[recipe]
name = "ds-stack"
python = "3.11"

[recipe.deps]
packages = ["numpy", "pandas", "matplotlib", "jupyterlab"]
pinned = ["numpy==1.26.2", "pandas==2.1.3", "matplotlib==3.8.2", "jupyterlab==4.0.9"]

[recipe.post_install]
commands = [
    "python -m ipykernel install --user --name ds-stack",
]
```

- **packages**: Flexible dependencies (latest compatible versions)
- **pinned**: Exact versions for reproducibility
- **post_install.commands**: Shell commands to run after installation (requires `--allow-scripts`)

### Export a recipe from an existing env

```bash
# Save recipe inside the env (default location)
uvcond recipe export myenv

# Export to a specific file
uvcond recipe export myenv --output myenv-recipe.toml
```

The recipe captures:
- Python version
- All installed packages (both flexible and pinned versions)
- Any existing post-install commands

### Create an env from a recipe

```bash
# Use flexible package versions (default)
uvcond recipe apply myenv-recipe.toml

# Use pinned versions for exact reproducibility
uvcond recipe apply myenv-recipe.toml --pinned

# Override the env name
uvcond recipe apply myenv-recipe.toml --name my-new-env

# Run post-install commands (opt-in for safety)
uvcond recipe apply myenv-recipe.toml --allow-scripts
```

### View an env's recipe

```bash
uvcond recipe show myenv
```

### Edit a recipe

Open the recipe in your default editor (`$VISUAL`, `$EDITOR`, or fallback to `notepad`/`vi`):

```bash
uvcond recipe edit myenv
```

If no recipe exists yet, this exports the current env state first, then opens the file.

**Setting your editor:**

```bash
# Set your preferred editor (VS Code, vim, nano, etc.)
uvcond config set editor code
```

See the [Configuration](#configuration) section for more details.

### Add post-install commands

```bash
# Append a command to the recipe
uvcond recipe post myenv --add "python -m ipykernel install --user --name myenv"

# Replace all post-install commands
uvcond recipe post myenv --set "echo 'Setup complete'"

# Load commands from a file (one command per line, # comments ignored)
uvcond recipe post myenv --from setup-commands.txt
```

**Example `setup-commands.txt`:**

```text
# Install Jupyter kernel
python -m ipykernel install --user --name myenv

# Install Playwright browsers
playwright install
```

### Workflow example

**On machine A** (your laptop):

```bash
uvcond create ds --python 3.11
uvcond-use ds
uv pip install numpy pandas matplotlib jupyterlab
uvcond recipe post ds --add "python -m ipykernel install --user --name ds"
uvcond recipe export ds --output ds-stack.toml
```

Share `ds-stack.toml` via git, email, Slack, etc.

**On machine B** (your colleague's laptop):

```bash
uvcond recipe apply ds-stack.toml --pinned --allow-scripts
uvcond-use ds
jupyter lab
```

---

## Windows shell integration

### PowerShell

You can always use:

```powershell
uvcond spawn myenv pwsh
```

to open a **new** PowerShell instance with the env active.

If you want a `conda activate`-style experience **in the current PowerShell session**, add this function to your PowerShell profile (`$PROFILE`):

> **Note**: This function uses the default path `~/.uvcond`. If you've changed `home` in your config, update the `$base` variable below to match.

```powershell
function uvcond-use {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )

    # Change this if you set a custom 'home' in uvcond config
    $base = Join-Path $HOME ".uvcond"

    $envDir = Join-Path $base $Name
    $activate = Join-Path $envDir "Scripts\Activate.ps1"

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

To "activate in this cmd session", create a `uvcond-use.bat` file somewhere on your `PATH`, for example `C:\Tools\uvcond-use.bat`:

> **Note**: This script uses the default path `%USERPROFILE%\.uvcond`. If you've changed `home` in your config, update the `BASE` variable below to match.

```bat
@echo off
REM Change this if you set a custom 'home' in uvcond config
set "BASE=%USERPROFILE%\.uvcond"

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

## Configuration

uvcond uses a simple config file instead of environment variables. The config file lives at:

* **Unix**: `~/.uvcond/config.toml`
* **Windows**: `%USERPROFILE%\.uvcond\config.toml`

### Quick setup

```bash
# Create a default config file
uvcond config init

# Edit it in your editor
uvcond config edit

# Or set values directly
uvcond config set editor code
uvcond config set shell pwsh
```

### Config file format

```toml
# Base directory for environments (default: ~/.uvcond)
home = "~/.uvcond"

# Default shell for "uvcond spawn"
# Options: pwsh, powershell, cmd (Windows) / bash, zsh, fish (Unix)
shell = "pwsh"

# Editor for "uvcond recipe edit" and "uvcond config edit"
# Examples: code, vim, nano, notepad
editor = "code"
```

### Config commands

| Command | Description |
|---------|-------------|
| `uvcond config` | Show current configuration |
| `uvcond config path` | Show config file path |
| `uvcond config edit` | Open config in editor |
| `uvcond config init` | Create default config file |
| `uvcond config set <key> <value>` | Set a config value |

### Available settings

| Key | Description | Default |
|-----|-------------|---------|
| `home` | Base directory for environments | `~/.uvcond` |
| `shell` | Default shell for `spawn` | Auto-detect |
| `editor` | Editor for `recipe edit` / `config edit` | `notepad` (Win) / `vi` (Unix) |

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

