"""
Plugin: Silence Removal
Uses auto-editor (https://github.com/WyattBlue/auto-editor) to automatically
cut out silent pauses from video files based on audio threshold.
"""

import subprocess
import sys
from pathlib import Path

from plugin_base import PipelinePlugin, SettingSchema


class SilenceRemovalPlugin(PipelinePlugin):
    name = "Silence Removal"
    description = "Removes silent pauses automatically using auto-editor"
    icon = "🔇"

    def get_settings_schema(self):
        return [
            SettingSchema(
                key="silent_threshold",
                label="Silent Threshold (dB)",
                type_="float",
                default=0.04,
                description="Audio level below which a frame is considered silent (0.0–1.0)",
            ),
            SettingSchema(
                key="margin",
                label="Margin Around Speech (seconds)",
                type_="float",
                default=0.2,
                description="Seconds of padding kept around non-silent segments",
            ),
            SettingSchema(
                key="min_clip_length",
                label="Minimum Clip Length (seconds)",
                type_="float",
                default=0.5,
                description="Clips shorter than this are discarded",
            ),
            SettingSchema(
                key="video_speed",
                label="Loud Speed",
                type_="float",
                default=1.0,
                description="Playback speed for non-silent sections (1.0 = normal)",
            ),
            SettingSchema(
                key="silent_speed",
                label="Silent Speed",
                type_="float",
                default=99999,
                description="Speed for silent sections (99999 effectively removes them)",
            ),
        ]

    def check_dependencies(self):
        result = subprocess.run(["auto-editor", "--version"], capture_output=True, text=True)
        if result.returncode != 0:
            return False, "auto-editor not installed. Run: pip install auto-editor"
        return True, "OK"

    def process(self, input_path: str, output_path: str, settings: dict, log_callback=None) -> str:
        self.log("Starting silence removal...", log_callback)

        cmd = [
            "auto-editor",
            input_path,
            "--output", output_path,
            "--edit", f"audio:threshold={settings['silent_threshold']}",
            "--margin", f"{settings['margin']}sec",
            "--min-clip-length", f"{settings['min_clip_length']}sec",
            "--video-speed", str(settings["video_speed"]),
            "--silent-speed", str(settings["silent_speed"]),
            "--no-open",
        ]

        self.log(f"Running: {' '.join(cmd)}", log_callback)
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.stdout:
            for line in result.stdout.splitlines():
                self.log(line, log_callback)
        if result.returncode != 0:
            raise RuntimeError(f"auto-editor failed:\n{result.stderr}")

        self.log("Silence removal complete.", log_callback)
        return output_path
