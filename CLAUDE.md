# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the Application

```bash
# Install dependencies (requires FFmpeg installed via brew/apt/winget)
pip install -r requirements.txt

# Run the GUI
python main.py
```

There is no test suite, linter configuration, or build system.

## Architecture

Plugin-based video processing pipeline with a PyQt6 desktop GUI. Videos pass sequentially through enabled plugins — each plugin's output file becomes the next plugin's input.

### Core Files

- **`plugin_base.py`** — `PipelinePlugin` ABC and `SettingSchema` descriptor. All plugins subclass `PipelinePlugin` and must implement `process(input_path, output_path, settings, log_callback)` returning the output path. Plugins declare their configuration via `get_settings_schema()` returning `SettingSchema` objects (types: float, int, bool, str, file, choice).
- **`plugin_loader.py`** — Auto-discovers `*_plugin.py` files in `plugins/` via `importlib.util`, instantiates all `PipelinePlugin` subclasses. Also handles pip-installing plugins from GitHub URLs or PyPI.
- **`main.py`** — PyQt6 GUI (dark theme). `PipelineWorker` (QThread) runs the plugin chain in a background thread using temp files, copying the final result as `<name>_processed.mp4`. Settings dialogs are dynamically generated from each plugin's schema.

### Plugins (`plugins/`)

| Plugin | External tools | What it wraps |
|--------|---------------|---------------|
| `profanity_plugin.py` | Whisper, cleanvid CLI | Transcribes audio, mutes profanity |
| `silence_plugin.py` | auto-editor CLI | Removes silent segments |
| `sensitive_info_plugin.py` | OpenCV, EasyOCR, ffmpeg | Blurs faces and PII (regex-based) per frame |
| `autoclip_plugin.py` | PySceneDetect, moviepy, Whisper | Splits into clips; supports 9:16 reels export |

### Key Patterns

- Plugins wrap external CLI tools via `subprocess` — most require FFmpeg on PATH.
- Each plugin implements `check_dependencies() -> (bool, str)` so the GUI can warn about missing tools.
- Pipeline execution uses a temp directory; only the final output is copied to the source directory.
- GUI runs processing on a `QThread` to stay responsive; logging goes through `log_callback`.

## Creating a New Plugin

Add a `*_plugin.py` file to `plugins/` subclassing `PipelinePlugin` from `plugin_base`. Set `name`, `description`, `icon` class attributes. Implement `process()` (must write a video file to `output_path`) and `get_settings_schema()`. The plugin is auto-discovered on next launch.
