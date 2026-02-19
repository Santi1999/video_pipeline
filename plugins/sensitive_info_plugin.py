"""
Plugin: Sensitive Info Blur
Uses OpenCV + EasyOCR to detect and blur:
  - On-screen text matching PII patterns (emails, IPs, passwords, API keys, etc.)
  - Faces (via OpenCV Haar cascade or mediapipe)
"""

import re
import tempfile
from pathlib import Path

from plugin_base import PipelinePlugin, SettingSchema


# Regex patterns for sensitive info detection
PII_PATTERNS = {
    "email": re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"),
    "ip_address": re.compile(r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b"),
    "api_key": re.compile(r"\b[A-Za-z0-9_\-]{20,}\b"),
    "credit_card": re.compile(r"\b(?:\d[ -]?){13,16}\b"),
    "phone": re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b"),
    "password_label": re.compile(r"(?i)(password|passwd|pwd|secret|token|api_key)\s*[:=]\s*\S+"),
}


class SensitiveInfoPlugin(PipelinePlugin):
    name = "Sensitive Info Blur"
    description = "Blurs faces and on-screen PII (emails, IPs, passwords, API keys)"
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
                key="blur_text_pii",
                label="Blur On-Screen Text PII",
                type_="bool",
                default=True,
                description="Detect and blur emails, IPs, API keys, passwords shown on screen",
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
            SettingSchema(
                key="ocr_confidence",
                label="OCR Confidence Threshold",
                type_="float",
                default=0.5,
                description="Minimum EasyOCR confidence to consider a text detection (0.0–1.0)",
            ),
        ]

    def check_dependencies(self):
        missing = []
        try:
            import cv2  # noqa
        except ImportError:
            missing.append("opencv-python")
        try:
            import easyocr  # noqa
        except ImportError:
            missing.append("easyocr")
        if missing:
            return False, "Missing: " + ", ".join(missing)
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
            import cv2
            cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            face_cascade = cv2.CascadeClassifier(cascade_path)
            self.log("Face detector loaded.", log_callback)

        # Load OCR reader (lazy load, only once)
        ocr_reader = None
        if settings.get("blur_text_pii"):
            try:
                import easyocr
                self.log("Loading EasyOCR (first run downloads model ~100MB)...", log_callback)
                ocr_reader = easyocr.Reader(["en"], gpu=False)
                self.log("EasyOCR ready.", log_callback)
            except ImportError:
                self.log("WARNING: easyocr not installed, skipping text PII blur.", log_callback)

        blur_k = settings.get("blur_strength", 51)
        if blur_k % 2 == 0:
            blur_k += 1  # Must be odd
        every_n = max(1, settings.get("process_every_n_frames", 5))
        ocr_conf = settings.get("ocr_confidence", 0.5)

        frame_idx = 0
        last_blur_regions = []  # Cache regions between OCR/detection frames

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

                # OCR-based PII detection
                if ocr_reader is not None:
                    results = ocr_reader.readtext(frame)
                    for (bbox, text, confidence) in results:
                        if confidence < ocr_conf:
                            continue
                        if self._contains_pii(text):
                            # bbox is [[x1,y1],[x2,y1],[x2,y2],[x1,y2]]
                            xs = [int(p[0]) for p in bbox]
                            ys = [int(p[1]) for p in bbox]
                            last_blur_regions.append((min(xs), min(ys), max(xs), max(ys)))

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
        import subprocess
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

    def _contains_pii(self, text: str) -> bool:
        """Return True if text matches any PII pattern."""
        for pattern in PII_PATTERNS.values():
            if pattern.search(text):
                return True
        return False
