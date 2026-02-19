# 🎬 Video Automation Pipeline

A plugin-based desktop GUI for automating video post-production from OBS recordings.

## Pipeline Stages

| # | Plugin | Tool | What it does |
|---|--------|------|-------------|
| 1 | **Profanity Removal** | cleanvid + Whisper | Transcribes audio → mutes swear words |
| 2 | **Silence Removal** | auto-editor | Cuts out dead air and silent pauses |
| 3 | **Sensitive Info Blur** | OpenCV + EasyOCR | Blurs faces and on-screen PII (emails, IPs, passwords) |
| 4 | **Auto Clip & Reels** | PySceneDetect + moviepy | Splits into highlight clips, optionally exports 9:16 reels |

---

## Setup

### 1. Install FFmpeg (required by most plugins)

**Windows:**
```
winget install ffmpeg
```
or download from https://ffmpeg.org/download.html and add to PATH.

**macOS:**
```
brew install ffmpeg
```

**Ubuntu/Debian:**
```
sudo apt install ffmpeg
```

---

### 2. Install Python dependencies

```bash
pip install -r requirements.txt
```

> **Note:** `easyocr` will download a ~100MB model on first use.  
> `openai-whisper` will download its model on first use (base = ~140MB).

---

### 3. Run the app

```bash
python main.py
```

---

## Usage

1. **Select your OBS recording** — drag & drop a `.mp4` / `.mkv` file onto the window, or click Browse
2. **Configure each plugin** — click the ⚙ Settings button on any stage to adjust parameters
3. **Enable/disable stages** — toggle the checkbox on each plugin card
4. **Click ▶ Run Pipeline** — the video processes through each active stage in order
5. **Output** is saved alongside the original file as `<name>_processed.mp4`
6. **Clips** (if Auto Clip is enabled) are saved in `<name>_clips/` folder

---

## Adding Plugins

Click **+ Add Plugin** in the GUI and paste either:
- A **GitHub URL**: `https://github.com/username/repo`
- A **PyPI package name**: `some-package`

The app will pip-install it. On next launch, any `*_plugin.py` file in the `plugins/` folder containing a `PipelinePlugin` subclass will be auto-discovered.

---

## Creating Your Own Plugin

```python
# plugins/my_plugin.py
from plugin_base import PipelinePlugin, SettingSchema

class MyPlugin(PipelinePlugin):
    name = "My Custom Plugin"
    description = "Does something cool"
    icon = "🔥"

    def get_settings_schema(self):
        return [
            SettingSchema("strength", "Effect Strength", "float", 1.0, "Higher = stronger"),
        ]

    def process(self, input_path, output_path, settings, log_callback=None):
        self.log("Running my plugin...", log_callback)
        # ... do your processing ...
        # must write a video file to output_path
        return output_path
```

Drop the file in the `plugins/` folder and restart the app. It will appear automatically.

---

## Project Structure

```
video_pipeline/
├── main.py               # PyQt6 GUI
├── plugin_base.py        # PipelinePlugin base class
├── plugin_loader.py      # Dynamic plugin discovery & GitHub install
├── requirements.txt
├── plugins/
│   ├── profanity_plugin.py     # cleanvid + Whisper
│   ├── silence_plugin.py       # auto-editor
│   ├── sensitive_info_plugin.py # OpenCV + EasyOCR
│   └── autoclip_plugin.py      # PySceneDetect + moviepy
```

---

## Troubleshooting

**⚠️ icon on a plugin card** — that plugin has missing dependencies. Hover over it to see what's missing, then install via pip.

**cleanvid not found** — run `pip install cleanvid` and ensure it's on your PATH.

**FFmpeg not found** — install FFmpeg and ensure it's accessible from your terminal.

**EasyOCR slow on first run** — it downloads a model the first time. Subsequent runs are fast.
