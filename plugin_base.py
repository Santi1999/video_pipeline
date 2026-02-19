"""
Base class for all pipeline plugins.
Every plugin must subclass PipelinePlugin and implement process().
"""

from abc import ABC, abstractmethod
from typing import Any


class SettingSchema:
    """Describes a single configurable setting for a plugin."""

    def __init__(self, key: str, label: str, type_: str, default: Any, description: str = "", options: list = None):
        """
        Args:
            key: internal key name
            label: human-readable label shown in GUI
            type_: one of 'float', 'int', 'bool', 'str', 'file', 'choice'
            default: default value
            description: tooltip text
            options: list of strings for 'choice' type
        """
        self.key = key
        self.label = label
        self.type_ = type_
        self.default = default
        self.description = description
        self.options = options or []


class PipelinePlugin(ABC):
    """
    Abstract base class for all video pipeline plugins.

    To create a new plugin:
        1. Subclass PipelinePlugin
        2. Set class attributes: name, description, icon
        3. Override get_settings_schema() to return a list of SettingSchema
        4. Override process() to implement your processing logic
    """

    name: str = "Unnamed Plugin"
    description: str = ""
    icon: str = "🔧"
    enabled: bool = True

    def get_settings_schema(self) -> list[SettingSchema]:
        """Return list of SettingSchema objects defining configurable options."""
        return []

    def get_default_settings(self) -> dict:
        """Return dict of {key: default_value} from schema."""
        return {s.key: s.default for s in self.get_settings_schema()}

    @abstractmethod
    def process(self, input_path: str, output_path: str, settings: dict, log_callback=None) -> str:
        """
        Process the video file.

        Args:
            input_path: path to input video file
            output_path: path to write output video file
            settings: dict of setting values (key -> value)
            log_callback: optional callable(str) for logging progress

        Returns:
            path to the output file
        """
        raise NotImplementedError

    def log(self, message: str, log_callback=None):
        """Helper to emit a log message."""
        print(f"[{self.name}] {message}")
        if log_callback:
            log_callback(f"[{self.name}] {message}")

    def check_dependencies(self) -> tuple[bool, str]:
        """
        Check if required dependencies are installed.
        Returns (ok: bool, message: str)
        """
        return True, "OK"
