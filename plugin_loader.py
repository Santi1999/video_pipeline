"""
Dynamic plugin loader.
Discovers plugins from the /plugins directory and can install new ones from GitHub.
"""

import importlib
import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from plugin_base import PipelinePlugin


PLUGINS_DIR = Path(__file__).parent / "plugins"


def load_plugins_from_dir(plugin_dir: Path = PLUGINS_DIR) -> list[PipelinePlugin]:
    """
    Scan plugin_dir for *_plugin.py files and load all PipelinePlugin subclasses found.
    Returns list of instantiated plugin objects.
    """
    plugins = []
    for fname in sorted(plugin_dir.glob("*_plugin.py")):
        module_name = fname.stem
        spec = importlib.util.spec_from_file_location(module_name, fname)
        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as e:
            print(f"[PluginLoader] Failed to load {fname.name}: {e}")
            continue

        for attr_name in dir(module):
            cls = getattr(module, attr_name)
            if (
                isinstance(cls, type)
                and issubclass(cls, PipelinePlugin)
                and cls is not PipelinePlugin
            ):
                try:
                    plugins.append(cls())
                    print(f"[PluginLoader] Loaded plugin: {cls.name}")
                except Exception as e:
                    print(f"[PluginLoader] Failed to instantiate {cls.__name__}: {e}")

    return plugins


def install_from_github(github_url: str, log_callback=None) -> tuple[bool, str]:
    """
    pip-install a package directly from a GitHub URL.
    Returns (success: bool, message: str)
    """
    def log(msg):
        print(msg)
        if log_callback:
            log_callback(msg)

    log(f"[PluginLoader] Installing from: {github_url}")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", f"git+{github_url}"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            log(f"[PluginLoader] Successfully installed: {github_url}")
            return True, "Installation successful"
        else:
            msg = result.stderr or result.stdout
            log(f"[PluginLoader] Install failed: {msg}")
            return False, msg
    except subprocess.TimeoutExpired:
        return False, "Installation timed out"
    except Exception as e:
        return False, str(e)


def install_from_pypi(package_name: str, log_callback=None) -> tuple[bool, str]:
    """pip-install a package from PyPI."""
    def log(msg):
        print(msg)
        if log_callback:
            log_callback(msg)

    log(f"[PluginLoader] Installing from PyPI: {package_name}")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", package_name],
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode == 0:
            log(f"[PluginLoader] Installed: {package_name}")
            return True, "OK"
        else:
            return False, result.stderr or result.stdout
    except Exception as e:
        return False, str(e)
