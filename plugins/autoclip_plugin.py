"""
Plugin: Auto Clip & Reels
Uses PySceneDetect + moviepy to:
  1. Detect scene changes / highlight moments
  2. Extract the top N clips
  3. Optionally format them as vertical 9:16 reels with captions
"""

import json
import os
import subprocess
import tempfile
from pathlib import Path

from plugin_base import PipelinePlugin, SettingSchema


class AutoClipPlugin(PipelinePlugin):
    name = "Auto Clip & Reels"
    description = "Detects highlights and exports short clips or vertical reels"
    icon = "✂️"

    def get_settings_schema(self):
        return [
            SettingSchema(
                key="clip_mode",
                label="Clip Mode",
                type_="choice",
                default="scene_detect",
                description="How to find clip boundaries",
                options=["scene_detect", "fixed_interval", "transcript_highlights"],
            ),
            SettingSchema(
                key="max_clips",
                label="Max Number of Clips",
                type_="int",
                default=5,
                description="Maximum number of clips to export",
            ),
            SettingSchema(
                key="min_clip_duration",
                label="Min Clip Duration (seconds)",
                type_="float",
                default=15.0,
                description="Clips shorter than this are skipped",
            ),
            SettingSchema(
                key="max_clip_duration",
                label="Max Clip Duration (seconds)",
                type_="float",
                default=60.0,
                description="Clips longer than this are trimmed at max duration",
            ),
            SettingSchema(
                key="reels_format",
                label="Export as Vertical Reels (9:16)",
                type_="bool",
                default=False,
                description="Crop and resize clips to 1080x1920 for TikTok/Reels/Shorts",
            ),
            SettingSchema(
                key="add_captions",
                label="Burn-In Captions",
                type_="bool",
                default=False,
                description="Burn Whisper-generated captions into reels (requires openai-whisper)",
            ),
            SettingSchema(
                key="scene_threshold",
                label="Scene Detection Threshold",
                type_="float",
                default=27.0,
                description="ContentDetector threshold (lower = more sensitive to scene changes)",
            ),
            SettingSchema(
                key="interval_seconds",
                label="Fixed Interval (seconds)",
                type_="float",
                default=60.0,
                description="Split every N seconds (used when clip_mode = fixed_interval)",
            ),
            SettingSchema(
                key="output_dir",
                label="Clips Output Directory",
                type_="str",
                default="",
                description="Where to save clips (default: same folder as input + '_clips')",
            ),
        ]

    def check_dependencies(self):
        missing = []
        try:
            import scenedetect  # noqa
        except ImportError:
            missing.append("scenedetect (pip install scenedetect[opencv])")
        try:
            from moviepy.editor import VideoFileClip  # noqa
        except ImportError:
            missing.append("moviepy (pip install moviepy)")
        if missing:
            return False, "Missing: " + ", ".join(missing)
        return True, "OK"

    def process(self, input_path: str, output_path: str, settings: dict, log_callback=None) -> str:
        self.log("Starting auto clip extraction...", log_callback)

        # Determine output directory for clips
        output_dir = settings.get("output_dir", "").strip()
        if not output_dir:
            base = Path(input_path).stem
            output_dir = str(Path(input_path).parent / f"{base}_clips")
        Path(output_dir).mkdir(parents=True, exist_ok=True)
        self.log(f"Clips will be saved to: {output_dir}", log_callback)

        # Find clip timestamps
        clip_mode = settings.get("clip_mode", "scene_detect")
        if clip_mode == "scene_detect":
            clips = self._scene_detect(input_path, settings, log_callback)
        elif clip_mode == "fixed_interval":
            clips = self._fixed_interval(input_path, settings, log_callback)
        elif clip_mode == "transcript_highlights":
            clips = self._transcript_highlights(input_path, settings, log_callback)
        else:
            clips = self._scene_detect(input_path, settings, log_callback)

        # Filter by duration
        min_dur = settings.get("min_clip_duration", 15.0)
        max_dur = settings.get("max_clip_duration", 60.0)
        clips = [(s, min(e, s + max_dur)) for s, e in clips if (e - s) >= min_dur]

        # Limit count
        max_clips = settings.get("max_clips", 5)
        clips = clips[:max_clips]

        if not clips:
            self.log("No clips found matching criteria.", log_callback)
            # Still copy input to output so pipeline continues
            import shutil
            shutil.copy2(input_path, output_path)
            return output_path

        self.log(f"Exporting {len(clips)} clips...", log_callback)

        exported_paths = []
        for i, (start, end) in enumerate(clips):
            clip_name = f"clip_{i+1:02d}_{int(start)}s-{int(end)}s.mp4"
            clip_path = str(Path(output_dir) / clip_name)
            self._export_clip(input_path, clip_path, start, end, settings, log_callback)
            exported_paths.append(clip_path)
            self.log(f"Exported: {clip_name}", log_callback)

        # Write a manifest JSON
        manifest_path = str(Path(output_dir) / "clips_manifest.json")
        with open(manifest_path, "w") as f:
            json.dump({
                "source": input_path,
                "clips": [{"index": i+1, "start": s, "end": e, "path": p}
                          for i, ((s, e), p) in enumerate(zip(clips, exported_paths))]
            }, f, indent=2)
        self.log(f"Manifest saved: {manifest_path}", log_callback)

        # Copy input through as the main output (clips are in output_dir)
        import shutil
        shutil.copy2(input_path, output_path)

        self.log(f"Auto clip complete. {len(exported_paths)} clips saved to {output_dir}", log_callback)
        return output_path

    def _scene_detect(self, input_path: str, settings: dict, log_callback=None) -> list[tuple[float, float]]:
        self.log("Running scene detection...", log_callback)
        try:
            from scenedetect import open_video, SceneManager
            from scenedetect.detectors import ContentDetector
        except ImportError:
            raise RuntimeError("scenedetect not installed. Run: pip install scenedetect[opencv]")

        video = open_video(input_path)
        scene_manager = SceneManager()
        scene_manager.add_detector(ContentDetector(threshold=settings.get("scene_threshold", 27.0)))
        scene_manager.detect_scenes(video, show_progress=False)
        scene_list = scene_manager.get_scene_list()

        clips = []
        for scene in scene_list:
            start = scene[0].get_seconds()
            end = scene[1].get_seconds()
            clips.append((start, end))

        self.log(f"Found {len(clips)} scenes.", log_callback)
        return clips

    def _fixed_interval(self, input_path: str, settings: dict, log_callback=None) -> list[tuple[float, float]]:
        self.log("Using fixed interval splitting...", log_callback)
        interval = settings.get("interval_seconds", 60.0)

        # Get video duration via ffprobe
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", input_path],
            capture_output=True, text=True
        )
        try:
            duration = float(result.stdout.strip())
        except ValueError:
            duration = 600.0  # fallback 10 min

        clips = []
        start = 0.0
        while start < duration:
            end = min(start + interval, duration)
            clips.append((start, end))
            start = end

        self.log(f"Split into {len(clips)} fixed-interval clips.", log_callback)
        return clips

    def _transcript_highlights(self, input_path: str, settings: dict, log_callback=None) -> list[tuple[float, float]]:
        """Use Whisper to transcribe and score segments by keyword density."""
        self.log("Using transcript-based highlight detection...", log_callback)
        try:
            import whisper
        except ImportError:
            self.log("openai-whisper not installed, falling back to scene detect.", log_callback)
            return self._scene_detect(input_path, settings, log_callback)

        model = whisper.load_model("base")
        result = model.transcribe(input_path, word_timestamps=True)

        # Score each segment by word count (simple energy proxy)
        segments = result.get("segments", [])
        if not segments:
            return self._scene_detect(input_path, settings, log_callback)

        # Score by words per second (denser speech = more interesting)
        scored = []
        for seg in segments:
            duration = max(seg["end"] - seg["start"], 0.01)
            word_count = len(seg["text"].split())
            score = word_count / duration
            scored.append((score, seg["start"], seg["end"]))

        # Sort by score descending, pick top clips
        scored.sort(reverse=True)
        max_clips = settings.get("max_clips", 5)
        top = sorted(scored[:max_clips], key=lambda x: x[1])  # re-sort by time

        clips = [(start, end) for _, start, end in top]
        self.log(f"Found {len(clips)} highlight segments.", log_callback)
        return clips

    def _export_clip(self, input_path: str, output_path: str, start: float, end: float,
                     settings: dict, log_callback=None):
        """Export a single clip, optionally as 9:16 vertical reel with captions."""

        reels = settings.get("reels_format", False)
        captions = settings.get("add_captions", False)

        if not reels and not captions:
            # Fast path: just use ffmpeg to cut
            cmd = [
                "ffmpeg", "-y",
                "-ss", str(start),
                "-to", str(end),
                "-i", input_path,
                "-c", "copy",
                output_path
            ]
            subprocess.run(cmd, capture_output=True, check=True)
            return

        # Use moviepy for more complex operations
        try:
            from moviepy.editor import VideoFileClip, TextClip, CompositeVideoClip
        except ImportError:
            raise RuntimeError("moviepy not installed. Run: pip install moviepy")

        clip = VideoFileClip(input_path).subclip(start, end)

        if reels:
            # Crop center to 9:16 aspect ratio
            target_ratio = 9 / 16
            w, h = clip.size
            current_ratio = w / h
            if current_ratio > target_ratio:
                # Too wide: crop sides
                new_w = int(h * target_ratio)
                x_center = w // 2
                clip = clip.crop(x_center=x_center, width=new_w)
            clip = clip.resize(height=1920)
            clip = clip.crop(x_center=clip.w // 2, width=1080)

        if captions:
            # Try to add burned-in captions from whisper
            try:
                import whisper
                model = whisper.load_model("tiny")
                # Extract the clip audio to a temp file for transcription
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_audio:
                    tmp_audio_path = tmp_audio.name
                clip.audio.write_audiofile(tmp_audio_path, logger=None)
                transcript = model.transcribe(tmp_audio_path)
                os.unlink(tmp_audio_path)

                # Build caption clips from segments
                txt_clips = []
                for seg in transcript.get("segments", []):
                    seg_start = seg["start"]
                    seg_end = seg["end"]
                    text = seg["text"].strip()
                    if not text:
                        continue
                    txt = (
                        TextClip(text, fontsize=40, color="white", stroke_color="black",
                                 stroke_width=2, method="caption", size=(clip.w - 40, None))
                        .set_start(seg_start)
                        .set_end(seg_end)
                        .set_position(("center", "bottom"))
                    )
                    txt_clips.append(txt)

                if txt_clips:
                    clip = CompositeVideoClip([clip] + txt_clips)
            except Exception as e:
                self.log(f"WARNING: Caption generation failed: {e}", log_callback)

        clip.write_videofile(output_path, codec="libx264", audio_codec="aac",
                             logger=None, threads=4)
        clip.close()
