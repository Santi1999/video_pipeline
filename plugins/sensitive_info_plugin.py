"""
Plugin: Sensitive Info Blur
Uses OpenCV to detect and blur faces (via Haar cascade).
"""

import subprocess
import tempfile
from pathlib import Path

from plugin_base import PipelinePlugin, SettingSchema


class SensitiveInfoPlugin(PipelinePlugin):
    name = "Sensitive Info Blur"
    description = "Blurs faces in the video using OpenCV Haar cascade"
    icon = "🕵️"

    def get_settings_schema(self):
        return [
            SettingSchema(
                key="blur_faces",
                label="Blur Faces",
                type_="bool",
                default=True,
                description="Detect and blur human faces in the video",
            ),
            SettingSchema(
                key="blur_strength",
                label="Blur Strength",
                type_="int",
                default=51,
                description="Gaussian blur kernel size (must be odd, higher = more blurred)",
            ),
            SettingSchema(
                key="process_every_n_frames",
                label="Process Every N Frames",
                type_="int",
                default=5,
                description="Run detection every N frames (higher = faster but may miss fast changes)",
            ),
        ]

    def check_dependencies(self):
        try:
            import cv2  # noqa
        except ImportError:
            return False, "Missing: opencv-python"
        return True, "OK"

    def process(self, input_path: str, output_path: str, settings: dict, log_callback=None) -> str:
        self.log("Starting sensitive info blur...", log_callback)

        try:
            import cv2
        except ImportError:
            raise RuntimeError("opencv-python not installed. Run: pip install opencv-python")

        cap = cv2.VideoCapture(input_path)
        if not cap.isOpened():
            raise RuntimeError(f"Could not open video: {input_path}")

        fps = cap.get(cv2.CAP_PROP_FPS)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        # Use a temp file then rename to avoid partial writes
        tmp_output = output_path + ".tmp.mp4"
        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        out = cv2.VideoWriter(tmp_output, fourcc, fps, (width, height))

        # Load face detector
        face_cascade = None
        if settings.get("blur_faces"):
            cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            face_cascade = cv2.CascadeClassifier(cascade_path)
            self.log("Face detector loaded.", log_callback)

        blur_k = settings.get("blur_strength", 51)
        if blur_k % 2 == 0:
            blur_k += 1  # Must be odd
        every_n = max(1, settings.get("process_every_n_frames", 5))

        frame_idx = 0
        last_blur_regions = []  # Cache regions between detection frames

        self.log(f"Processing {total_frames} frames...", log_callback)

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if frame_idx % every_n == 0:
                last_blur_regions = []

                # Face detection
                if face_cascade is not None:
                    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                    faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
                    for (x, y, w, h) in faces:
                        last_blur_regions.append((x, y, x + w, y + h))

            # Apply blur to all cached regions
            for (x1, y1, x2, y2) in last_blur_regions:
                # Clamp to frame bounds
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(width, x2), min(height, y2)
                if x2 > x1 and y2 > y1:
                    roi = frame[y1:y2, x1:x2]
                    frame[y1:y2, x1:x2] = cv2.GaussianBlur(roi, (blur_k, blur_k), 0)

            out.write(frame)
            frame_idx += 1

            if frame_idx % 100 == 0:
                pct = int(frame_idx / total_frames * 100)
                self.log(f"Progress: {pct}% ({frame_idx}/{total_frames} frames)", log_callback)

        cap.release()
        out.release()

        # Re-mux to copy audio from original (VideoWriter drops audio)
        cmd = [
            "ffmpeg", "-y",
            "-i", tmp_output,
            "-i", input_path,
            "-c:v", "copy",
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-c:a", "copy",
            output_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        Path(tmp_output).unlink(missing_ok=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg audio remux failed:\n{result.stderr}")

        self.log("Sensitive info blur complete.", log_callback)
        return output_path
