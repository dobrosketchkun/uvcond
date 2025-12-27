# uvcond/__main__.py
from __future__ import annotations

import os
import sys
import subprocess
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple
import shutil

from rich.console import Console
from rich.theme import Theme

# TOML support: stdlib in 3.11+, tomli package for older
try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore

# Rich console with uv-like theme
_theme = Theme({
    "info": "cyan",
    "success": "green",
    "warning": "yellow", 
    "error": "red bold",
    "path": "cyan",
    "name": "green bold",
    "dim": "dim",
})
console = Console(theme=_theme, highlight=False)
err_console = Console(theme=_theme, stderr=True, highlight=False)


# =============================================================================
# Config system
# =============================================================================

def _default_base_dir() -> Path:
    """Default base directory (before config is loaded)."""
    if os.name == "nt":
        return Path(os.environ.get("USERPROFILE", str(Path.home()))) / ".uvcond"
    else:
        return Path.home() / ".uvcond"


def config_path() -> Path:
    """Path to the config file."""
    return _default_base_dir() / "config.toml"


def _load_config() -> Dict[str, Any]:
    """Load config from file. Returns empty dict if not found."""
    cfg_path = config_path()
    if cfg_path.is_file():
        try:
            with open(cfg_path, "rb") as f:
                return tomllib.load(f)
        except Exception:
            pass
    return {}


# Cached config (loaded once per run)
_config_cache: Optional[Dict[str, Any]] = None


def get_config() -> Dict[str, Any]:
    """Get the loaded config (cached)."""
    global _config_cache
    if _config_cache is None:
        _config_cache = _load_config()
    return _config_cache


def get_setting(key: str, default: Any = None) -> Any:
    """
    Get a config setting. 
    Looks in config file first, falls back to default.
    """
    cfg = get_config()
    return cfg.get(key, default)


def write_config(cfg: Dict[str, Any]) -> None:
    """Write config to file."""
    cfg_path = config_path()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    
    lines = [
        "# uvcond configuration",
        "# See: uvcond config --help",
        "",
    ]
    
    if "home" in cfg:
        lines.append(f'# Base directory for environments')
        lines.append(f'home = {_toml_value(cfg["home"])}')
        lines.append("")
    
    if "shell" in cfg:
        lines.append(f'# Default shell for "uvcond spawn"')
        lines.append(f'# Options: pwsh, powershell, cmd (Windows) / bash, zsh, fish (Unix)')
        lines.append(f'shell = {_toml_value(cfg["shell"])}')
        lines.append("")
    
    if "editor" in cfg:
        lines.append(f'# Editor for "uvcond recipe edit" and "uvcond config edit"')
        lines.append(f'# Examples: code, vim, nano, notepad')
        lines.append(f'editor = {_toml_value(cfg["editor"])}')
        lines.append("")
    
    cfg_path.write_text("\n".join(lines), encoding="utf-8")


def create_default_config() -> Dict[str, Any]:
    """Create a default config file with commented examples."""
    cfg_path = config_path()
    cfg_path.parent.mkdir(parents=True, exist_ok=True)
    
    if os.name == "nt":
        default_content = """\
# uvcond configuration
# Uncomment and modify settings as needed.

# Base directory for environments (default: ~/.uvcond)
# home = "C:\\\\Users\\\\YourName\\\\.uvcond"

# Default shell for "uvcond spawn"
# Options: pwsh, powershell, cmd
# shell = "pwsh"

# Editor for "uvcond recipe edit" and "uvcond config edit"
# Use full path if the editor isn't on your PATH:
# editor = "notepad"
# editor = "C:\\\\Program Files\\\\Notepad++\\\\notepad++.exe"
# editor = "C:\\\\Program Files\\\\Microsoft VS Code\\\\Code.exe"
# editor = "code"
"""
    else:
        default_content = """\
# uvcond configuration
# Uncomment and modify settings as needed.

# Base directory for environments (default: ~/.uvcond)
# home = "~/.uvcond"

# Default shell for "uvcond spawn"
# Options: bash, zsh, fish, etc.
# shell = "bash"

# Editor for "uvcond recipe edit" and "uvcond config edit"
# Examples: code, vim, nano, emacs
# editor = "code"
"""
    
    cfg_path.write_text(default_content, encoding="utf-8")
    return {}


# =============================================================================
# Path helpers
# =============================================================================

def base_dir() -> Path:
    """Get the base directory for environments."""
    # Config file takes priority
    home = get_setting("home")
    if home:
        return Path(home).expanduser()
    return _default_base_dir()


def env_dir(name: str) -> Path:
    return base_dir() / name


def recipe_path(env_path: Path) -> Path:
    """Path to the recipe file inside an env."""
    return env_path / "recipe.toml"


def get_editor() -> str:
    """Get the configured editor."""
    editor = get_setting("editor")
    if editor:
        return editor
    # Fallback to platform default
    return "notepad" if os.name == "nt" else "vi"


def get_shell() -> Optional[str]:
    """Get the configured shell (or None for auto-detect)."""
    return get_setting("shell")


# =============================================================================
# TOML helpers (minimal writer to avoid extra dependencies)
# =============================================================================

def _toml_value(value: Any) -> str:
    """Format a Python value as a TOML value."""
    if isinstance(value, str):
        # Check if string contains newlines - if so, use multi-line string format
        if "\n" in value:
            # For multi-line strings, use triple quotes and minimal escaping
            # TOML multi-line strings don't need to escape quotes inside them
            return f'"""\n{value}\n"""'
        else:
            # Single line string
            escaped = value.replace("\\", "\\\\").replace('"', '\\"')
            return f'"{escaped}"'
    elif isinstance(value, bool):
        return "true" if value else "false"
    elif isinstance(value, (int, float)):
        return str(value)
    elif isinstance(value, list):
        if len(value) == 0:
            return "[]"
        # Multi-line for readability if items are long
        if all(isinstance(v, str) for v in value) and sum(len(str(v)) for v in value) > 60:
            lines = ["["]
            for item in value:
                lines.append(f"    {_toml_value(item)},")
            lines.append("]")
            return "\n".join(lines)
        items = ", ".join(_toml_value(item) for item in value)
        return f"[{items}]"
    else:
        raise ValueError(f"Unsupported TOML type: {type(value)}")


def write_recipe_toml(path: Path, recipe: Dict[str, Any]) -> None:
    """Write a recipe dict to a TOML file."""
    lines = []
    
    # [recipe] section
    lines.append("[recipe]")
    if "name" in recipe:
        lines.append(f'name = {_toml_value(recipe["name"])}')
    if "python" in recipe:
        lines.append(f'python = {_toml_value(recipe["python"])}')
    if "description" in recipe:
        lines.append(f'description = {_toml_value(recipe["description"])}')
    lines.append("")
    
    # [recipe.deps] section
    deps = recipe.get("deps", {})
    if deps:
        lines.append("[recipe.deps]")
        if "packages" in deps and deps["packages"]:
            val = _toml_value(deps["packages"])
            if "\n" in val:
                lines.append(f"packages = {val}")
            else:
                lines.append(f"packages = {val}")
        if "pinned" in deps and deps["pinned"]:
            val = _toml_value(deps["pinned"])
            if "\n" in val:
                lines.append(f"pinned = {val}")
            else:
                lines.append(f"pinned = {val}")
        lines.append("")
    
    # [recipe.post_install] section
    post = recipe.get("post_install", {})
    if post and post.get("commands"):
        lines.append("[recipe.post_install]")
        val = _toml_value(post["commands"])
        if "\n" in val:
            lines.append(f"commands = {val}")
        else:
            lines.append(f"commands = {val}")
        lines.append("")
    
    path.write_text("\n".join(lines), encoding="utf-8")


def read_recipe_toml(path: Path) -> Dict[str, Any]:
    """Read a recipe from a TOML file."""
    with open(path, "rb") as f:
        data = tomllib.load(f)
    return data.get("recipe", data)


# =============================================================================
# Env introspection helpers
# =============================================================================

def get_python_executable(env_path: Path) -> Optional[Path]:
    """Get the Python executable path for an env."""
    if os.name == "nt":
        python = env_path / "Scripts" / "python.exe"
    else:
        python = env_path / "bin" / "python"
    return python if python.is_file() else None


def get_python_version(env_path: Path) -> Optional[str]:
    """Get the Python version (major.minor) from an env's pyvenv.cfg."""
    cfg = env_path / "pyvenv.cfg"
    if cfg.is_file():
        for line in cfg.read_text(encoding="utf-8").splitlines():
            # Look for: version = 3.11.5  OR  version_info = 3.11.5.final.0
            if line.strip().startswith("version"):
                parts = line.split("=", 1)
                if len(parts) == 2:
                    version = parts[1].strip()
                    v_parts = version.split(".")
                    if len(v_parts) >= 2:
                        return f"{v_parts[0]}.{v_parts[1]}"
    return None


def get_installed_packages(env_path: Path) -> Tuple[List[str], List[str]]:
    """
    Get installed packages from an env using `uv pip freeze`.
    
    Returns (unpinned, pinned) where:
    - unpinned: package names only (for flexibility)
    - pinned: full specifiers with versions (for reproducibility)
    """
    python = get_python_executable(env_path)
    if not python:
        return [], []
    
    result = subprocess.run(
        ["uv", "pip", "freeze", "--python", str(python)],
        capture_output=True,
        text=True,
    )
    
    if result.returncode != 0:
        return [], []
    
    pinned: List[str] = []
    unpinned: List[str] = []
    
    for line in result.stdout.strip().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-e"):
            continue
        pinned.append(line)
        # Extract package name (before any version specifier)
        name = line.split("==")[0].split(">=")[0].split("<=")[0]
        name = name.split(">")[0].split("<")[0].split("[")[0].split("~=")[0]
        unpinned.append(name.strip())
    
    return unpinned, pinned


# =============================================================================
# Core commands: list, create, path, spawn
# =============================================================================

def cmd_list() -> int:
    base = base_dir()
    if not base.is_dir():
        console.print("[dim]No environments yet.[/dim]")
        return 0
    envs = [c for c in sorted(base.iterdir()) if c.is_dir() and c.name != "config.toml"]
    if not envs:
        console.print("[dim]No environments yet.[/dim]")
        return 0
    for child in envs:
        has_recipe = recipe_path(child).is_file()
        if has_recipe:
            console.print(f"[name]{child.name}[/name] [dim]\\[recipe][/dim]")
        else:
            console.print(f"[name]{child.name}[/name]")
    return 0


def cmd_create(name: str, extra_args: List[str]) -> int:
    base = base_dir()
    base.mkdir(parents=True, exist_ok=True)
    target = env_dir(name)
    console.print(f"[info]Creating[/info] [name]{name}[/name] [dim]at[/dim] [path]{target}[/path]")
    # delegate to uv venv
    return subprocess.call(["uv", "venv", str(target), *extra_args])


def cmd_path(name: str) -> int:
    console.print(f"[path]{env_dir(name)}[/path]")
    return 0


def cmd_delete(name: str, force: bool) -> int:
    """Delete an environment."""
    target = env_dir(name)
    if not target.is_dir():
        err_console.print(f"[error]error[/error]: no env named [name]{name}[/name] at [path]{target}[/path]")
        return 1
    
    if not force:
        console.print(f"[warning]This will delete[/warning] [path]{target}[/path]")
        try:
            confirm = console.input("[dim]Are you sure?[/dim] [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            console.print()
            return 1
        if confirm not in {"y", "yes"}:
            console.print("[dim]Cancelled[/dim]")
            return 0
    
    console.print(f"[info]Deleting[/info] [name]{name}[/name]...")
    shutil.rmtree(target)
    console.print(f"[success]Deleted[/success] [name]{name}[/name]")
    return 0


def cmd_spawn(name: str, shell_arg: Optional[str]) -> int:
    target = env_dir(name)
    if not target.is_dir():
        err_console.print(f"[error]error[/error]: no env named [name]{name}[/name] at [path]{target}[/path]")
        return 1

    # CLI arg > config > auto-detect
    shell = shell_arg or get_shell()

    if os.name == "nt":
        return _spawn_windows(target, shell)
    else:
        return _spawn_unix(target, shell)


def _spawn_unix(target: Path, shell: Optional[str]) -> int:
    venv_bin = target / "bin"
    if not venv_bin.is_dir():
        err_console.print(f"[error]error[/error]: [path]{target}[/path] does not look like a venv (no bin/)")
        return 1

    shell = shell or os.environ.get("SHELL") or "/bin/bash"
    shell = os.path.expanduser(shell)

    activate = venv_bin / "activate"
    if not activate.is_file():
        err_console.print(f"[error]error[/error]: no activate script at [path]{activate}[/path]")
        return 1

    cmdline = f'. "{activate}" && exec "{shell}" -i'
    return subprocess.call([shell, "-c", cmdline])


def _spawn_windows(target: Path, shell: Optional[str]) -> int:
    scripts = target / "Scripts"
    if not scripts.is_dir():
        err_console.print(f"[error]error[/error]: [path]{target}[/path] does not look like a Windows venv (no Scripts\\)")
        return 1

    requested = (shell or "").lower()

    # CMD explicitly requested
    if requested in {"cmd", "cmd.exe"}:
        activate_bat = scripts / "activate.bat"
        if not activate_bat.is_file():
            err_console.print(f"[error]error[/error]: no activate.bat at [path]{activate_bat}[/path]")
            return 1
        full_cmd = f'call "{activate_bat}" && title uvcond:{target.name}'
        return subprocess.call(f'cmd.exe /K {full_cmd}', shell=True)

    # PowerShell explicitly requested
    if requested in {"pwsh", "powershell"}:
        exe = shutil.which("pwsh") if requested == "pwsh" else shutil.which("powershell")
        if not exe:
            err_console.print(f"[error]error[/error]: requested shell [name]{requested}[/name] not found on PATH")
            return 1
        activate_ps1 = scripts / "Activate.ps1"
        if not activate_ps1.is_file():
            err_console.print(f"[error]error[/error]: no Activate.ps1 at [path]{activate_ps1}[/path]")
            return 1
        cmdline = f'& "{activate_ps1}"'
        return subprocess.call([exe, "-NoLogo", "-NoExit", "-Command", cmdline])

    # Auto-detect pwsh → powershell → cmd
    exe_pwsh = shutil.which("pwsh")
    exe_ps = shutil.which("powershell")
    activate_ps1 = scripts / "Activate.ps1"
    activate_bat = scripts / "activate.bat"

    if exe_pwsh or exe_ps:
        if not activate_ps1.is_file():
            err_console.print(f"[error]error[/error]: no Activate.ps1 at [path]{activate_ps1}[/path]")
            return 1
        exe = exe_pwsh or exe_ps
        cmdline = f'& "{activate_ps1}"'
        return subprocess.call([exe, "-NoLogo", "-NoExit", "-Command", cmdline])

    # Fall back to cmd
    if not activate_bat.is_file():
        err_console.print(f"[error]error[/error]: no activate.bat at [path]{activate_bat}[/path]")
        return 1
    cmdline = f'call "{activate_bat}" && title uvcond:{target.name}'
    return subprocess.call(["cmd.exe", "/K", cmdline])


# =============================================================================
# Config commands
# =============================================================================

def cmd_config(args: List[str]) -> int:
    """Handle 'uvcond config' commands."""
    if not args:
        # Show current config
        return cmd_config_show()
    
    sub, *rest = args
    
    if sub == "path":
        console.print(f"[path]{config_path()}[/path]")
        return 0
    
    elif sub == "edit":
        return cmd_config_edit()
    
    elif sub == "init":
        return cmd_config_init()
    
    elif sub == "set":
        # config set <key> <value>
        if len(rest) < 2:
            err_console.print("[dim]Usage:[/dim] uvcond config set <key> <value>")
            err_console.print("[dim]  Keys: home, shell, editor[/dim]")
            return 1
        return cmd_config_set(rest[0], rest[1])
    
    elif sub in {"--help", "-h", "help"}:
        console.print(
            "[dim]Usage:[/dim]\n"
            "  uvcond config              Show current configuration\n"
            "  uvcond config path         Show config file path\n"
            "  uvcond config edit         Open config in editor\n"
            "  uvcond config init         Create default config file\n"
            "  uvcond config set <k> <v>  Set a config value\n"
            "\n"
            "[dim]Config keys:[/dim]\n"
            "  [info]home[/info]     Base directory for environments\n"
            "  [info]shell[/info]    Default shell for 'uvcond spawn'\n"
            "  [info]editor[/info]   Editor for 'uvcond recipe edit'"
        )
        return 0
    
    else:
        err_console.print(f"[error]error[/error]: unknown config subcommand: [name]{sub}[/name]")
        return 1


def cmd_config_show() -> int:
    """Show current configuration."""
    cfg_file = config_path()
    cfg = get_config()
    
    console.print(f"[dim]Config file:[/dim] [path]{cfg_file}[/path]")
    if cfg_file.is_file():
        console.print(f"  [success](exists)[/success]")
    else:
        console.print(f"  [dim](not created yet - run 'uvcond config init')[/dim]")
    console.print()
    
    console.print("[dim]Current settings:[/dim]")
    console.print(f"  [info]home[/info]   = [path]{base_dir()}[/path]")
    console.print(f"  [info]shell[/info]  = [name]{get_shell() or '(auto-detect)'}[/name]")
    console.print(f"  [info]editor[/info] = [name]{get_editor()}[/name]")
    
    return 0


def _open_in_editor(filepath: Path) -> int:
    """Open a file in the configured editor."""
    editor = get_editor()
    
    # Check if editor exists
    editor_path = shutil.which(editor)
    
    if editor_path:
        console.print(f"[info]Opening[/info] [path]{filepath}[/path] [dim]in {editor}[/dim]")
        return subprocess.call([editor_path, str(filepath)])
    
    # On Windows, try common install locations for popular editors
    if os.name == "nt":
        common_paths = {
            "notepad++": [
                r"C:\Program Files\Notepad++\notepad++.exe",
                r"C:\Program Files (x86)\Notepad++\notepad++.exe",
            ],
            "code": [
                os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"),
                r"C:\Program Files\Microsoft VS Code\Code.exe",
            ],
            "sublime": [
                r"C:\Program Files\Sublime Text\sublime_text.exe",
                r"C:\Program Files\Sublime Text 3\sublime_text.exe",
            ],
        }
        
        for name, paths in common_paths.items():
            if editor.lower().replace("_", "").replace("-", "") in name.lower().replace("_", "").replace("-", ""):
                for path in paths:
                    if os.path.isfile(path):
                        console.print(f"[info]Opening[/info] [path]{filepath}[/path] [dim]in {path}[/dim]")
                        return subprocess.call([path, str(filepath)])
        
        # Last resort: try shell=True which might find it via App Paths registry
        console.print(f"[info]Opening[/info] [path]{filepath}[/path] [dim]in {editor}[/dim]")
        result = subprocess.call(f'"{editor}" "{filepath}"', shell=True)
        if result != 0:
            err_console.print(f"[error]error[/error]: editor [name]{editor}[/name] not found")
            err_console.print(f'[dim]Try: uvcond config set editor "C:\\path\\to\\editor.exe"[/dim]')
        return result
    else:
        console.print(f"[info]Opening[/info] [path]{filepath}[/path] [dim]in {editor}[/dim]")
        return subprocess.call([editor, str(filepath)])


def cmd_config_edit() -> int:
    """Open config file in editor."""
    cfg_file = config_path()
    
    # Create default if doesn't exist
    if not cfg_file.is_file():
        console.print(f"[info]Creating[/info] default config at [path]{cfg_file}[/path]")
        create_default_config()
    
    return _open_in_editor(cfg_file)


def cmd_config_init() -> int:
    """Create default config file."""
    cfg_file = config_path()
    
    if cfg_file.is_file():
        console.print(f"[warning]Config already exists[/warning] at [path]{cfg_file}[/path]")
        console.print(f"[dim]Use 'uvcond config edit' to modify it[/dim]")
        return 0
    
    create_default_config()
    console.print(f"[success]Created[/success] config at [path]{cfg_file}[/path]")
    console.print(f"[dim]Edit it with 'uvcond config edit'[/dim]")
    return 0


def cmd_config_set(key: str, value: str) -> int:
    """Set a config value."""
    valid_keys = {"home", "shell", "editor"}
    if key not in valid_keys:
        err_console.print(f"[error]error[/error]: unknown config key [name]{key}[/name]")
        err_console.print(f"[dim]Valid keys: {', '.join(sorted(valid_keys))}[/dim]")
        return 1
    
    # Load existing config
    cfg = get_config().copy()
    cfg[key] = value
    
    write_config(cfg)
    console.print(f"[success]Set[/success] [info]{key}[/info] = [name]{value}[/name]")
    
    # Clear cache so next call sees new value
    global _config_cache
    _config_cache = None
    
    return 0


# =============================================================================
# Recipe commands
# =============================================================================

def cmd_recipe_export(name: str, output: Optional[str]) -> int:
    """Export a recipe from an existing environment."""
    target = env_dir(name)
    if not target.is_dir():
        err_console.print(f"[error]error[/error]: no env named [name]{name}[/name] at [path]{target}[/path]")
        return 1
    
    # Gather env info
    python_ver = get_python_version(target)
    if not python_ver:
        err_console.print(f"[error]error[/error]: could not determine Python version for [name]{name}[/name]")
        return 1
    
    unpinned, pinned = get_installed_packages(target)
    
    # Build recipe dict
    recipe: Dict[str, Any] = {
        "name": name,
        "python": python_ver,
    }
    
    if unpinned or pinned:
        recipe["deps"] = {}
        if unpinned:
            recipe["deps"]["packages"] = unpinned
        if pinned:
            recipe["deps"]["pinned"] = pinned
    
    # Check for existing post_install commands (preserve them if re-exporting)
    existing_recipe_path = recipe_path(target)
    if existing_recipe_path.is_file():
        try:
            existing = read_recipe_toml(existing_recipe_path)
            if "post_install" in existing and existing["post_install"].get("commands"):
                recipe["post_install"] = existing["post_install"]
        except Exception:
            pass  # Ignore parse errors on existing recipe
    
    # Write recipe
    if output:
        out_path = Path(output)
    else:
        out_path = existing_recipe_path
    
    write_recipe_toml(out_path, recipe)
    console.print(f"[success]Exported[/success] recipe to [path]{out_path}[/path]")
    return 0


def cmd_recipe_apply(
    recipe_file: str,
    name: Optional[str],
    allow_scripts: bool,
    use_pinned: bool,
) -> int:
    """Create an environment from a recipe file."""
    recipe_src = Path(recipe_file)
    if not recipe_src.is_file():
        err_console.print(f"[error]error[/error]: recipe file not found: [path]{recipe_file}[/path]")
        return 1
    
    try:
        recipe = read_recipe_toml(recipe_src)
    except Exception as e:
        err_console.print(f"[error]error[/error]: failed to parse recipe: {e}")
        return 1
    
    # Determine env name
    env_name = name or recipe.get("name")
    if not env_name:
        err_console.print("[error]error[/error]: no env name provided and recipe has no 'name' field")
        return 1
    
    target = env_dir(env_name)
    if target.exists():
        err_console.print(f"[error]error[/error]: env [name]{env_name}[/name] already exists at [path]{target}[/path]")
        return 1
    
    # Get Python version
    python_ver = recipe.get("python")
    
    # Create the venv
    console.print(f"[info]Creating[/info] env [name]{env_name}[/name] from recipe...")
    create_args = ["uv", "venv", str(target)]
    if python_ver:
        create_args.extend(["--python", python_ver])
    
    ret = subprocess.call(create_args)
    if ret != 0:
        err_console.print(f"[error]error[/error]: failed to create venv")
        return ret
    
    # Install dependencies
    deps = recipe.get("deps", {})
    packages_to_install: List[str] = []
    
    if use_pinned and deps.get("pinned"):
        packages_to_install = deps["pinned"]
        console.print(f"[info]Installing[/info] {len(packages_to_install)} pinned packages...")
    elif deps.get("packages"):
        packages_to_install = deps["packages"]
        console.print(f"[info]Installing[/info] {len(packages_to_install)} packages...")
    
    if packages_to_install:
        python = get_python_executable(target)
        if not python:
            err_console.print(f"[error]error[/error]: could not find Python in created env")
            return 1
        
        install_cmd = ["uv", "pip", "install", "--python", str(python)] + packages_to_install
        ret = subprocess.call(install_cmd)
        if ret != 0:
            err_console.print(f"[error]error[/error]: failed to install packages")
            return ret
    
    # Run post-install commands (only if --allow-scripts)
    post_install = recipe.get("post_install", {})
    commands = post_install.get("commands", [])
    
    if commands and not allow_scripts:
        console.print(f"[warning]Skipped[/warning] {len(commands)} post-install command(s) [dim](use --allow-scripts to run)[/dim]")
    elif commands and allow_scripts:
        console.print(f"[info]Running[/info] {len(commands)} post-install command(s)...")
        
        # Set up environment with venv activated
        env = os.environ.copy()
        if os.name == "nt":
            scripts = target / "Scripts"
            env["PATH"] = f"{scripts}{os.pathsep}{env.get('PATH', '')}"
            env["VIRTUAL_ENV"] = str(target)
        else:
            bin_dir = target / "bin"
            env["PATH"] = f"{bin_dir}{os.pathsep}{env.get('PATH', '')}"
            env["VIRTUAL_ENV"] = str(target)
        
        for i, cmd in enumerate(commands, 1):
            console.print(f"  [dim]({i}/{len(commands)})[/dim] {cmd}")
            ret = subprocess.call(cmd, shell=True, env=env, cwd=str(target))
            if ret != 0:
                err_console.print(f"[error]error[/error]: post-install command failed with exit code {ret}")
                return ret
    
    # Save the recipe into the env
    write_recipe_toml(recipe_path(target), recipe)
    console.print(f"[success]Created[/success] [name]{env_name}[/name] at [path]{target}[/path]")
    return 0


def cmd_recipe_show(name: str) -> int:
    """Show the recipe for an environment."""
    target = env_dir(name)
    if not target.is_dir():
        err_console.print(f"[error]error[/error]: no env named [name]{name}[/name] at [path]{target}[/path]")
        return 1

    rpath = recipe_path(target)
    if not rpath.is_file():
        console.print(f"[dim]Env[/dim] [name]{name}[/name] [dim]has no recipe (use 'uvcond recipe export {name}' to create one)[/dim]")
        return 0

    # Parse the recipe to display description nicely
    recipe = read_recipe_toml(rpath)
    description = recipe.get("description")

    console.print(f"[bold]Recipe for:[/bold] [name]{name}[/name]")
    console.print(f"[dim]Path:[/dim] [path]{rpath}[/path]")
    console.print()

    if description:
        console.print("[bold]Description:[/bold]")
        console.print(description)
        console.print()

    console.print("[bold]Full recipe:[/bold]")
    console.print(rpath.read_text(encoding="utf-8"))
    return 0


def cmd_recipe_describe(name: str, description: str) -> int:
    """Set the description for an environment."""
    target = env_dir(name)
    if not target.is_dir():
        err_console.print(f"[error]error[/error]: no env named [name]{name}[/name] at [path]{target}[/path]")
        return 1

    rpath = recipe_path(target)

    # Load existing recipe or create minimal one
    if rpath.is_file():
        recipe = read_recipe_toml(rpath)
    else:
        # Create a new recipe with current env state
        python_ver = get_python_version(target)
        unpinned, pinned = get_installed_packages(target)
        recipe = {"name": name}
        if python_ver:
            recipe["python"] = python_ver
        if unpinned or pinned:
            recipe["deps"] = {}
            if unpinned:
                recipe["deps"]["packages"] = unpinned
            if pinned:
                recipe["deps"]["pinned"] = pinned

    # Set the description
    recipe["description"] = description

    write_recipe_toml(rpath, recipe)
    console.print(f"[success]Set description[/success] for [name]{name}[/name]")
    return 0


def cmd_recipe_edit_post(name: str, commands: List[str], append: bool) -> int:
    """Add or replace post-install commands in a recipe."""
    target = env_dir(name)
    if not target.is_dir():
        err_console.print(f"[error]error[/error]: no env named [name]{name}[/name] at [path]{target}[/path]")
        return 1
    
    rpath = recipe_path(target)
    
    # Load existing recipe or create minimal one
    if rpath.is_file():
        recipe = read_recipe_toml(rpath)
    else:
        # Create a new recipe from current env state
        python_ver = get_python_version(target)
        unpinned, pinned = get_installed_packages(target)
        recipe = {"name": name}
        if python_ver:
            recipe["python"] = python_ver
        if unpinned or pinned:
            recipe["deps"] = {}
            if unpinned:
                recipe["deps"]["packages"] = unpinned
            if pinned:
                recipe["deps"]["pinned"] = pinned
    
    # Update post_install
    if "post_install" not in recipe:
        recipe["post_install"] = {}
    
    existing_cmds = recipe["post_install"].get("commands", [])
    if append:
        recipe["post_install"]["commands"] = existing_cmds + commands
    else:
        recipe["post_install"]["commands"] = commands
    
    write_recipe_toml(rpath, recipe)
    console.print(f"[success]Updated[/success] post-install commands for [name]{name}[/name]")
    return 0


def cmd_recipe_edit(name: str) -> int:
    """Open the recipe file in editor."""
    target = env_dir(name)
    if not target.is_dir():
        err_console.print(f"[error]error[/error]: no env named [name]{name}[/name] at [path]{target}[/path]")
        return 1
    
    rpath = recipe_path(target)
    
    # If no recipe exists, create one first
    if not rpath.is_file():
        console.print(f"[info]No recipe found[/info], exporting current env state...")
        ret = cmd_recipe_export(name, None)
        if ret != 0:
            return ret
    
    return _open_in_editor(rpath)


def cmd_recipe(args: List[str]) -> int:
    """Handle 'uvcond recipe <subcommand>' commands."""
    if not args:
        err_console.print(
            "[dim]Usage:[/dim]\n"
            "  uvcond recipe export <name> [--output FILE]\n"
            "  uvcond recipe apply <file> [--name NAME] [--pinned] [--allow-scripts]\n"
            "  uvcond recipe show <name>\n"
            "  uvcond recipe describe <name> <description>\n"
            "  uvcond recipe edit <name>\n"
            "  uvcond recipe post <name> --add 'cmd' / --set 'cmd' / --from FILE"
        )
        return 1
    
    sub, *rest = args
    
    if sub == "export":
        # Parse: export <name> [--output FILE]
        if not rest:
            err_console.print("[dim]Usage:[/dim] uvcond recipe export <name> [--output FILE]")
            return 1
        name = rest[0]
        output = None
        i = 1
        while i < len(rest):
            if rest[i] in {"--output", "-o"} and i + 1 < len(rest):
                output = rest[i + 1]
                i += 2
            else:
                i += 1
        return cmd_recipe_export(name, output)
    
    elif sub == "apply":
        # Parse: apply <file> [--name NAME] [--pinned] [--allow-scripts]
        if not rest:
            err_console.print("[dim]Usage:[/dim] uvcond recipe apply <file> [--name NAME] [--pinned] [--allow-scripts]")
            return 1
        recipe_file = rest[0]
        name = None
        use_pinned = False
        allow_scripts = False
        i = 1
        while i < len(rest):
            if rest[i] in {"--name", "-n"} and i + 1 < len(rest):
                name = rest[i + 1]
                i += 2
            elif rest[i] == "--pinned":
                use_pinned = True
                i += 1
            elif rest[i] == "--allow-scripts":
                allow_scripts = True
                i += 1
            else:
                i += 1
        return cmd_recipe_apply(recipe_file, name, allow_scripts, use_pinned)
    
    elif sub == "show":
        if not rest:
            err_console.print("[dim]Usage:[/dim] uvcond recipe show <name>")
            return 1
        return cmd_recipe_show(rest[0])

    elif sub == "describe":
        # Parse: describe <name> <description>
        if len(rest) < 2:
            err_console.print("[dim]Usage:[/dim] uvcond recipe describe <name> <description>")
            return 1
        name = rest[0]
        description = " ".join(rest[1:])
        return cmd_recipe_describe(name, description)

    elif sub == "edit":
        if not rest:
            err_console.print("[dim]Usage:[/dim] uvcond recipe edit <name>")
            return 1
        return cmd_recipe_edit(rest[0])
    
    elif sub == "post":
        # Parse: post <name> --add 'cmd' / --set 'cmd' / --from FILE
        if not rest:
            err_console.print("[dim]Usage:[/dim] uvcond recipe post <name> --add 'cmd' / --set 'cmd' / --from FILE")
            return 1
        name = rest[0]
        commands: List[str] = []
        append = True
        from_file: Optional[str] = None
        i = 1
        while i < len(rest):
            if rest[i] == "--add" and i + 1 < len(rest):
                commands.append(rest[i + 1])
                append = True
                i += 2
            elif rest[i] == "--set" and i + 1 < len(rest):
                commands.append(rest[i + 1])
                append = False
                i += 2
            elif rest[i] == "--from" and i + 1 < len(rest):
                from_file = rest[i + 1]
                i += 2
            else:
                i += 1
        
        # Load commands from file if specified
        if from_file:
            from_path = Path(from_file)
            if not from_path.is_file():
                err_console.print(f"[error]error[/error]: file not found: [path]{from_file}[/path]")
                return 1
            file_commands = [
                line.strip()
                for line in from_path.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]
            if not file_commands:
                err_console.print(f"[error]error[/error]: no commands found in [path]{from_file}[/path]")
                return 1
            commands.extend(file_commands)
        
        if not commands:
            err_console.print("[dim]Usage:[/dim] uvcond recipe post <name> --add 'cmd' / --set 'cmd' / --from FILE")
            return 1
        return cmd_recipe_edit_post(name, commands, append)
    
    else:
        err_console.print(f"[error]error[/error]: unknown recipe subcommand: [name]{sub}[/name]")
        return 1


# =============================================================================
# Help and main
# =============================================================================

def cmd_info(name: str) -> int:
    """Show information about an environment."""
    target = env_dir(name)
    if not target.is_dir():
        err_console.print(f"[error]error[/error]: no env named [name]{name}[/name] at [path]{target}[/path]")
        return 1

    console.print(f"[bold]Environment:[/bold] [name]{name}[/name]")
    console.print(f"[dim]Path:[/dim] [path]{target}[/path]")

    # Show Python version
    python_ver = get_python_version(target)
    if python_ver:
        console.print(f"[dim]Python:[/dim] {python_ver}")
    else:
        console.print(f"[dim]Python:[/dim] [dim](unknown)[/dim]")

    # Show description if available
    rpath = recipe_path(target)
    if rpath.is_file():
        recipe = read_recipe_toml(rpath)
        description = recipe.get("description")
        if description:
            console.print(f"[dim]Description:[/dim]")
            console.print(description)
        else:
            console.print(f"[dim]Description:[/dim] [dim](none)[/dim]")
    else:
        console.print(f"[dim]Description:[/dim] [dim](no recipe file)[/dim]")

    # Show package count
    unpinned, pinned = get_installed_packages(target)
    total_packages = len(unpinned) + len(pinned)
    console.print(f"[dim]Packages:[/dim] {total_packages} installed")

    return 0


def cmd_help() -> int:
    console.print(
        "[bold]uvcond[/bold] - Conda-like named environments on top of uv\n"
        "\n"
        "[dim]Usage:[/dim]\n"
        "  uvcond [info]list[/info]                              List all environments\n"
        "  uvcond [info]create[/info] <name> [uv venv args...]   Create a new environment\n"
        "  uvcond [info]delete[/info] <name> [--force]           Delete an environment\n"
        "  uvcond [info]path[/info] <name>                       Print env path\n"
        "  uvcond [info]spawn[/info] <name> [shell]              Spawn shell with env activated\n"
        "\n"
        "[dim]Recipe commands:[/dim]\n"
        "  uvcond recipe [info]export[/info] <name> [-o FILE]    Export recipe from env\n"
        "  uvcond recipe [info]apply[/info] <file> [options]     Create env from recipe\n"
        "      --name NAME          Override env name\n"
        "      --pinned             Use pinned versions (exact reproducibility)\n"
        "      --allow-scripts      Run post-install commands\n"
        "  uvcond recipe [info]show[/info] <name>                Show env's recipe\n"
        "  uvcond recipe [info]describe[/info] <name> <desc>     Set env description\n"
        "  uvcond recipe [info]edit[/info] <name>                Edit recipe in editor\n"
        "  uvcond recipe [info]post[/info] <name> [options]      Manage post-install commands\n"
        "      --add 'cmd'          Append a command\n"
        "      --set 'cmd'          Replace all commands\n"
        "      --from FILE          Load commands from file\n"
        "\n"
        "[dim]Other commands:[/dim]\n"
        "  uvcond [info]describe[/info] <name> <desc>            Set env description\n"
        "  uvcond [info]info[/info] <name>                       Show env information\n"
        "\n"
        "[dim]Config commands:[/dim]\n"
        "  uvcond [info]config[/info]                            Show current configuration\n"
        "  uvcond config [info]path[/info]                       Show config file path\n"
        "  uvcond config [info]edit[/info]                       Edit config in editor\n"
        "  uvcond config [info]init[/info]                       Create default config file\n"
        "  uvcond config [info]set[/info] <key> <value>          Set a config value\n"
        "\n"
        f"[dim]Base directory:[/dim] [path]{base_dir()}[/path]\n"
        f"[dim]Config file:[/dim]    [path]{config_path()}[/path]"
    )
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    if not argv:
        return cmd_help()

    sub, *rest = argv

    if sub in {"help", "--help", "-h"}:
        return cmd_help()
    if sub == "list":
        return cmd_list()
    if sub in {"create", "mk"}:
        if not rest:
            err_console.print("[dim]Usage:[/dim] uvcond create <name> [extra uv venv args...]")
            return 1
        name, *extra = rest
        return cmd_create(name, extra)
    if sub == "path":
        if not rest:
            err_console.print("[dim]Usage:[/dim] uvcond path <name>")
            return 1
        return cmd_path(rest[0])
    if sub in {"delete", "rm"}:
        if not rest:
            err_console.print("[dim]Usage:[/dim] uvcond delete <name> [--force]")
            return 1
        name = rest[0]
        force = "--force" in rest or "-f" in rest
        return cmd_delete(name, force)
    if sub in {"spawn", "shell"}:
        if not rest:
            err_console.print("[dim]Usage:[/dim] uvcond spawn <name> [shell]")
            return 1
        name = rest[0]
        shell = rest[1] if len(rest) > 1 else None
        return cmd_spawn(name, shell)
    if sub == "recipe":
        return cmd_recipe(rest)
    if sub == "config":
        return cmd_config(rest)
    if sub == "describe":
        if not rest:
            err_console.print("[dim]Usage:[/dim] uvcond describe <name> <description>")
            return 1
        name = rest[0]
        if len(rest) < 2:
            # Just show description
            return cmd_info(name)
        description = " ".join(rest[1:])
        return cmd_recipe_describe(name, description)
    if sub == "info":
        if not rest:
            err_console.print("[dim]Usage:[/dim] uvcond info <name>")
            return 1
        return cmd_info(rest[0])

    return cmd_help()


if __name__ == "__main__":
    raise SystemExit(main())
