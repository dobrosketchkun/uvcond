# uvcond/__main__.py
from __future__ import annotations

import os
import sys
import subprocess
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple
import shutil

# TOML support: stdlib in 3.11+, tomli package for older
try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore


# =============================================================================
# Path helpers
# =============================================================================

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


def recipe_path(env_path: Path) -> Path:
    """Path to the recipe file inside an env."""
    return env_path / "recipe.toml"


# =============================================================================
# TOML helpers (minimal writer to avoid extra dependencies)
# =============================================================================

def _toml_value(value: Any) -> str:
    """Format a Python value as a TOML value."""
    if isinstance(value, str):
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
        print("No environments yet.")
        return 0
    for child in sorted(base.iterdir()):
        if child.is_dir():
            # Check if it has a recipe
            has_recipe = recipe_path(child).is_file()
            suffix = " [recipe]" if has_recipe else ""
            print(f"{child.name}{suffix}")
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

    activate = venv_bin / "activate"
    if not activate.is_file():
        print(f"[uvcond] no activate script at {activate}", file=sys.stderr)
        return 1

    cmdline = f'. "{activate}" && exec "{shell}" -i'
    return subprocess.call([shell, "-c", cmdline])


def _spawn_windows(target: Path, shell: Optional[str]) -> int:
    scripts = target / "Scripts"
    if not scripts.is_dir():
        print(f"[uvcond] {target} does not look like a Windows venv (no Scripts\\)", file=sys.stderr)
        return 1

    requested = (shell or os.environ.get("UVCOND_SHELL", "")).lower()

    # CMD explicitly requested
    if requested in {"cmd", "cmd.exe"}:
        activate_bat = scripts / "activate.bat"
        if not activate_bat.is_file():
            print(f"[uvcond] no activate.bat at {activate_bat}", file=sys.stderr)
            return 1
        full_cmd = f'call "{activate_bat}" && title uvcond:{target.name}'
        return subprocess.call(f'cmd.exe /K {full_cmd}', shell=True)

    # PowerShell explicitly requested
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

    # Auto-detect pwsh → powershell → cmd
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

    # Fall back to cmd
    if not activate_bat.is_file():
        print(f"[uvcond] no activate.bat at {activate_bat}", file=sys.stderr)
        return 1
    cmdline = f'call "{activate_bat}" && title uvcond:{target.name}'
    return subprocess.call(["cmd.exe", "/K", cmdline])


# =============================================================================
# Recipe commands
# =============================================================================

def cmd_recipe_export(name: str, output: Optional[str]) -> int:
    """Export a recipe from an existing environment."""
    target = env_dir(name)
    if not target.is_dir():
        print(f"[uvcond] no env named {name!r} at {target}", file=sys.stderr)
        return 1
    
    # Gather env info
    python_ver = get_python_version(target)
    if not python_ver:
        print(f"[uvcond] could not determine Python version for {name!r}", file=sys.stderr)
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
    print(f"[uvcond] recipe exported to {out_path}")
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
        print(f"[uvcond] recipe file not found: {recipe_file}", file=sys.stderr)
        return 1
    
    try:
        recipe = read_recipe_toml(recipe_src)
    except Exception as e:
        print(f"[uvcond] failed to parse recipe: {e}", file=sys.stderr)
        return 1
    
    # Determine env name
    env_name = name or recipe.get("name")
    if not env_name:
        print("[uvcond] no env name provided and recipe has no 'name' field", file=sys.stderr)
        return 1
    
    target = env_dir(env_name)
    if target.exists():
        print(f"[uvcond] env {env_name!r} already exists at {target}", file=sys.stderr)
        return 1
    
    # Get Python version
    python_ver = recipe.get("python")
    
    # Create the venv
    print(f"[uvcond] creating env {env_name!r} from recipe...")
    create_args = ["uv", "venv", str(target)]
    if python_ver:
        create_args.extend(["--python", python_ver])
    
    ret = subprocess.call(create_args)
    if ret != 0:
        print(f"[uvcond] failed to create venv", file=sys.stderr)
        return ret
    
    # Install dependencies
    deps = recipe.get("deps", {})
    packages_to_install: List[str] = []
    
    if use_pinned and deps.get("pinned"):
        packages_to_install = deps["pinned"]
        print(f"[uvcond] installing {len(packages_to_install)} pinned packages...")
    elif deps.get("packages"):
        packages_to_install = deps["packages"]
        print(f"[uvcond] installing {len(packages_to_install)} packages...")
    
    if packages_to_install:
        python = get_python_executable(target)
        if not python:
            print(f"[uvcond] could not find Python in created env", file=sys.stderr)
            return 1
        
        install_cmd = ["uv", "pip", "install", "--python", str(python)] + packages_to_install
        ret = subprocess.call(install_cmd)
        if ret != 0:
            print(f"[uvcond] failed to install packages", file=sys.stderr)
            return ret
    
    # Run post-install commands (only if --allow-scripts)
    post_install = recipe.get("post_install", {})
    commands = post_install.get("commands", [])
    
    if commands and not allow_scripts:
        print(f"[uvcond] recipe has {len(commands)} post-install command(s), skipped (use --allow-scripts to run)")
    elif commands and allow_scripts:
        print(f"[uvcond] running {len(commands)} post-install command(s)...")
        
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
            print(f"[uvcond]   ({i}/{len(commands)}) {cmd}")
            ret = subprocess.call(cmd, shell=True, env=env, cwd=str(target))
            if ret != 0:
                print(f"[uvcond] post-install command failed with exit code {ret}", file=sys.stderr)
                return ret
    
    # Save the recipe into the env
    write_recipe_toml(recipe_path(target), recipe)
    print(f"[uvcond] env {env_name!r} created successfully at {target}")
    return 0


def cmd_recipe_show(name: str) -> int:
    """Show the recipe for an environment."""
    target = env_dir(name)
    if not target.is_dir():
        print(f"[uvcond] no env named {name!r} at {target}", file=sys.stderr)
        return 1
    
    rpath = recipe_path(target)
    if not rpath.is_file():
        print(f"[uvcond] env {name!r} has no recipe (use 'uvcond recipe export {name}' to create one)")
        return 0
    
    print(rpath.read_text(encoding="utf-8"))
    return 0


def cmd_recipe_edit_post(name: str, commands: List[str], append: bool) -> int:
    """Add or replace post-install commands in a recipe."""
    target = env_dir(name)
    if not target.is_dir():
        print(f"[uvcond] no env named {name!r} at {target}", file=sys.stderr)
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
    print(f"[uvcond] updated post-install commands for {name!r}")
    return 0


def cmd_recipe_edit(name: str) -> int:
    """Open the recipe file in $EDITOR."""
    target = env_dir(name)
    if not target.is_dir():
        print(f"[uvcond] no env named {name!r} at {target}", file=sys.stderr)
        return 1
    
    rpath = recipe_path(target)
    
    # If no recipe exists, create one first
    if not rpath.is_file():
        print(f"[uvcond] no recipe found, exporting current env state...")
        ret = cmd_recipe_export(name, None)
        if ret != 0:
            return ret
    
    # Find editor
    editor = (
        os.environ.get("VISUAL")
        or os.environ.get("EDITOR")
        or ("notepad" if os.name == "nt" else "vi")
    )
    
    print(f"[uvcond] opening {rpath} in {editor}")
    return subprocess.call([editor, str(rpath)])


def cmd_recipe(args: List[str]) -> int:
    """Handle 'uvcond recipe <subcommand>' commands."""
    if not args:
        print(
            "Usage:\n"
            "  uvcond recipe export <name> [--output FILE]\n"
            "  uvcond recipe apply <file> [--name NAME] [--pinned] [--allow-scripts]\n"
            "  uvcond recipe show <name>\n"
            "  uvcond recipe edit <name>\n"
            "  uvcond recipe post <name> --add 'cmd' / --set 'cmd' / --from FILE\n",
            file=sys.stderr,
        )
        return 1
    
    sub, *rest = args
    
    if sub == "export":
        # Parse: export <name> [--output FILE]
        if not rest:
            print("uvcond recipe export <name> [--output FILE]", file=sys.stderr)
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
            print("uvcond recipe apply <file> [--name NAME] [--pinned] [--allow-scripts]", file=sys.stderr)
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
            print("uvcond recipe show <name>", file=sys.stderr)
            return 1
        return cmd_recipe_show(rest[0])
    
    elif sub == "edit":
        if not rest:
            print("uvcond recipe edit <name>", file=sys.stderr)
            return 1
        return cmd_recipe_edit(rest[0])
    
    elif sub == "post":
        # Parse: post <name> --add 'cmd' / --set 'cmd' / --from FILE
        if not rest:
            print("uvcond recipe post <name> --add 'cmd' / --set 'cmd' / --from FILE", file=sys.stderr)
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
                print(f"[uvcond] file not found: {from_file}", file=sys.stderr)
                return 1
            file_commands = [
                line.strip()
                for line in from_path.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]
            if not file_commands:
                print(f"[uvcond] no commands found in {from_file}", file=sys.stderr)
                return 1
            commands.extend(file_commands)
        
        if not commands:
            print("uvcond recipe post <name> --add 'cmd' / --set 'cmd' / --from FILE", file=sys.stderr)
            return 1
        return cmd_recipe_edit_post(name, commands, append)
    
    else:
        print(f"Unknown recipe subcommand: {sub}", file=sys.stderr)
        return 1


# =============================================================================
# Help and main
# =============================================================================

def cmd_help() -> int:
    print(
        "Usage:\n"
        "  uvcond list                              List all environments\n"
        "  uvcond create <name> [uv venv args...]   Create a new environment\n"
        "  uvcond path <name>                       Print env path\n"
        "  uvcond spawn <name> [shell]              Spawn shell with env activated\n"
        "\n"
        "Recipe commands:\n"
        "  uvcond recipe export <name> [-o FILE]    Export recipe from env\n"
        "  uvcond recipe apply <file> [options]     Create env from recipe\n"
        "      --name NAME          Override env name\n"
        "      --pinned             Use pinned versions (exact reproducibility)\n"
        "      --allow-scripts      Run post-install commands\n"
        "  uvcond recipe show <name>                Show env's recipe\n"
        "  uvcond recipe edit <name>                Edit recipe in $EDITOR\n"
        "  uvcond recipe post <name> [options]      Manage post-install commands\n"
        "      --add 'cmd'          Append a command\n"
        "      --set 'cmd'          Replace all commands\n"
        "      --from FILE          Load commands from file\n"
        "\n"
        f"Base directory: {base_dir()}\n"
        "Configure with UVCOND_HOME.\n"
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
    if sub == "recipe":
        return cmd_recipe(rest)

    return cmd_help()


if __name__ == "__main__":
    raise SystemExit(main())
