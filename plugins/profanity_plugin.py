"""
Plugin: Profanity Removal
Uses cleanvid (https://github.com/mmguero/cleanvid) + OpenAI Whisper to:
  1. Transcribe audio to SRT using Whisper
  2. Pass video + SRT to cleanvid to mute profanity segments
"""

import os
import subprocess
import tempfile
from pathlib import Path

from plugin_base import PipelinePlugin, SettingSchema


class ProfanityPlugin(PipelinePlugin):
    name = "Profanity Removal"
    description = "Transcribes audio with Whisper and mutes profanity using cleanvid"
    icon = "🤬"

    def get_settings_schema(self):
        return [
            SettingSchema(
                key="whisper_model",
                label="Whisper Model",
                type_="choice",
                default="base",
                description="Larger models are more accurate but slower",
                options=["tiny", "base", "small", "medium", "large"],
            ),
            SettingSchema(
                key="pad_seconds",
                label="Mute Padding (seconds)",
                type_="float",
                default=0.25,
                description="Extra seconds of silence before/after each profanity hit",
            ),
            SettingSchema(
                key="embed_subs",
                label="Embed Subtitles in Output",
                type_="bool",
                default=False,
                description="Embed the cleaned subtitle track into the output video",
            ),
            SettingSchema(
                key="swears_file",
                label="Custom Swears List (optional)",
                type_="file",
                default="",
                description="Path to a custom profanity word list .txt file",
            ),
            SettingSchema(
                key="language",
                label="Language",
                type_="str",
                default="en",
                description="Language code for Whisper transcription (e.g. en, es, fr)",
            ),
        ]

    def check_dependencies(self):
        missing = []
        try:
            import whisper  # noqa
        except ImportError:
            missing.append("openai-whisper")
        result = subprocess.run(["cleanvid", "--help"], capture_output=True)
        if result.returncode != 0 and b"cleanvid" not in result.stdout + result.stderr:
            missing.append("cleanvid (pip install cleanvid)")
        result2 = subprocess.run(["ffmpeg", "-version"], capture_output=True)
        if result2.returncode != 0:
            missing.append("ffmpeg (install from ffmpeg.org)")
        if missing:
            return False, "Missing: " + ", ".join(missing)
        return True, "OK"

    def process(self, input_path: str, output_path: str, settings: dict, log_callback=None) -> str:
        self.log("Starting profanity removal...", log_callback)

        # Step 1: Generate SRT with Whisper
        srt_path = self._generate_srt(input_path, settings, log_callback)

        # Step 2: Run cleanvid
        self._run_cleanvid(input_path, output_path, srt_path, settings, log_callback)

        self.log("Profanity removal complete.", log_callback)
        return output_path

    def _generate_srt(self, video_path: str, settings: dict, log_callback=None) -> str:
        self.log(f"Transcribing with Whisper ({settings['whisper_model']})...", log_callback)
        try:
            import whisper
            from whisper.utils import WriteSRT
        except ImportError:
            raise RuntimeError("openai-whisper is not installed. Run: pip install openai-whisper")

        model = whisper.load_model(settings["whisper_model"])
        result = model.transcribe(video_path, language=settings.get("language", "en"))

        # Write SRT next to input file
        srt_path = str(Path(video_path).with_suffix(".srt"))
        with open(srt_path, "w", encoding="utf-8") as f:
            writer = WriteSRT(output_dir=str(Path(srt_path).parent))
            writer.write_result(result, f, options={})

        self.log(f"SRT saved to: {srt_path}", log_callback)
        return srt_path

    def _run_cleanvid(self, input_path: str, output_path: str, srt_path: str, settings: dict, log_callback=None):
        self.log("Running cleanvid...", log_callback)
        cmd = [
            "cleanvid",
            "-i", input_path,
            "-o", output_path,
            "-s", srt_path,
            "--offline",
        ]
        if settings.get("pad_seconds", 0) > 0:
            cmd += ["-p", str(settings["pad_seconds"])]
        if settings.get("embed_subs"):
            cmd.append("-e")
        if settings.get("swears_file"):
            cmd += ["-w", settings["swears_file"]]

        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.stdout:
            self.log(result.stdout, log_callback)
        if result.returncode != 0:
            raise RuntimeError(f"cleanvid failed:\n{result.stderr}")
        self.log("cleanvid finished.", log_callback)
