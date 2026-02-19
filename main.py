"""
Video Automation Pipeline - Main GUI
Built with PyQt6. Provides a plugin-based pipeline for:
  - Profanity removal (cleanvid)
  - Silence removal (auto-editor)
  - Sensitive info blur (OpenCV + EasyOCR)
  - Auto clip & reels (PySceneDetect + moviepy)
"""

import os
import shutil
import sys
import tempfile
import threading
from pathlib import Path

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject
from PyQt6.QtGui import QFont, QColor, QPalette, QIcon, QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QFileDialog, QTextEdit, QScrollArea,
    QCheckBox, QSlider, QDoubleSpinBox, QSpinBox, QComboBox,
    QLineEdit, QGroupBox, QSplitter, QProgressBar, QFrame,
    QDialog, QDialogButtonBox, QFormLayout, QTabWidget,
    QMessageBox, QSizePolicy
)

# Add parent dir to path so we can import from project root
sys.path.insert(0, str(Path(__file__).parent))
from plugin_base import PipelinePlugin, SettingSchema
from plugin_loader import load_plugins_from_dir, install_from_github, install_from_pypi


# ─────────────────────────────────────────────
#  Worker thread for running the pipeline
# ─────────────────────────────────────────────

class PipelineWorker(QObject):
    log_signal = pyqtSignal(str)
    progress_signal = pyqtSignal(int)
    finished_signal = pyqtSignal(bool, str)

    def __init__(self, input_path: str, plugins: list, settings_map: dict):
        super().__init__()
        self.input_path = input_path
        self.plugins = plugins  # list of (plugin, enabled)
        self.settings_map = settings_map  # plugin.name -> settings dict
        self._stop = False

    def run(self):
        try:
            active_plugins = [(p, s) for p, enabled, s in [
                (p, en, self.settings_map.get(p.name, p.get_default_settings()))
                for p, en in self.plugins
            ] if enabled]

            if not active_plugins:
                self.finished_signal.emit(False, "No plugins enabled.")
                return

            # Create a temp working directory
            work_dir = tempfile.mkdtemp(prefix="vidpipe_")
            current = self.input_path
            total = len(active_plugins)

            for idx, (plugin, settings) in enumerate(active_plugins):
                if self._stop:
                    self.log_signal.emit("⛔ Pipeline stopped by user.")
                    self.finished_signal.emit(False, "Stopped.")
                    return

                self.log_signal.emit(f"\n{'─'*50}")
                self.log_signal.emit(f"▶ Step {idx+1}/{total}: {plugin.icon} {plugin.name}")
                self.log_signal.emit(f"{'─'*50}")

                suffix = Path(current).suffix or ".mp4"
                out_path = str(Path(work_dir) / f"step_{idx+1:02d}_{plugin.name.replace(' ', '_')}{suffix}")

                try:
                    result = plugin.process(
                        input_path=current,
                        output_path=out_path,
                        settings=settings,
                        log_callback=lambda msg: self.log_signal.emit(msg)
                    )
                    current = result
                except Exception as e:
                    self.log_signal.emit(f"❌ Plugin failed: {e}")
                    self.finished_signal.emit(False, f"Failed at {plugin.name}: {e}")
                    return

                pct = int((idx + 1) / total * 100)
                self.progress_signal.emit(pct)

            # Copy final output to same directory as input
            input_dir = Path(self.input_path).parent
            input_stem = Path(self.input_path).stem
            final_name = f"{input_stem}_processed{Path(current).suffix}"
            final_path = str(input_dir / final_name)
            shutil.copy2(current, final_path)

            self.log_signal.emit(f"\n✅ Pipeline complete!")
            self.log_signal.emit(f"📁 Output saved to: {final_path}")
            self.finished_signal.emit(True, final_path)

        except Exception as e:
            self.log_signal.emit(f"❌ Unexpected error: {e}")
            self.finished_signal.emit(False, str(e))

    def stop(self):
        self._stop = True


# ─────────────────────────────────────────────
#  Plugin Settings Dialog
# ─────────────────────────────────────────────

class SettingsDialog(QDialog):
    def __init__(self, plugin: PipelinePlugin, current_settings: dict, parent=None):
        super().__init__(parent)
        self.plugin = plugin
        self.settings = dict(current_settings)
        self.widgets = {}

        self.setWindowTitle(f"Settings — {plugin.name}")
        self.setMinimumWidth(420)
        self.setModal(True)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(12)

        for schema in plugin.get_settings_schema():
            widget = self._make_widget(schema)
            self.widgets[schema.key] = widget
            label = QLabel(schema.label)
            label.setToolTip(schema.description)
            widget.setToolTip(schema.description)
            form.addRow(label, widget)

        layout.addLayout(form)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _make_widget(self, schema: SettingSchema) -> QWidget:
        val = self.settings.get(schema.key, schema.default)
        if schema.type_ == "bool":
            w = QCheckBox()
            w.setChecked(bool(val))
            return w
        elif schema.type_ == "float":
            w = QDoubleSpinBox()
            w.setRange(0.0, 999999.0)
            w.setDecimals(3)
            w.setValue(float(val))
            return w
        elif schema.type_ == "int":
            w = QSpinBox()
            w.setRange(0, 999999)
            w.setValue(int(val))
            return w
        elif schema.type_ == "choice":
            w = QComboBox()
            for opt in schema.options:
                w.addItem(opt)
            if val in schema.options:
                w.setCurrentText(str(val))
            return w
        elif schema.type_ == "file":
            container = QWidget()
            h = QHBoxLayout(container)
            h.setContentsMargins(0, 0, 0, 0)
            line = QLineEdit(str(val))
            btn = QPushButton("Browse")
            btn.clicked.connect(lambda: self._browse_file(line))
            h.addWidget(line)
            h.addWidget(btn)
            container._line = line
            return container
        else:
            w = QLineEdit(str(val))
            return w

    def _browse_file(self, line_edit: QLineEdit):
        path, _ = QFileDialog.getOpenFileName(self, "Select File")
        if path:
            line_edit.setText(path)

    def _get_value(self, key: str, schema: SettingSchema):
        widget = self.widgets[key]
        if schema.type_ == "bool":
            return widget.isChecked()
        elif schema.type_ == "float":
            return widget.value()
        elif schema.type_ == "int":
            return widget.value()
        elif schema.type_ == "choice":
            return widget.currentText()
        elif schema.type_ == "file":
            return widget._line.text()
        else:
            return widget.text()

    def _on_accept(self):
        for schema in self.plugin.get_settings_schema():
            self.settings[schema.key] = self._get_value(schema.key, schema)
        self.accept()

    def get_settings(self):
        return self.settings


# ─────────────────────────────────────────────
#  Plugin Card Widget
# ─────────────────────────────────────────────

class PluginCard(QFrame):
    settings_changed = pyqtSignal(str, dict)  # plugin name, new settings

    def __init__(self, plugin: PipelinePlugin, parent=None):
        super().__init__(parent)
        self.plugin = plugin
        self.current_settings = plugin.get_default_settings()

        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet("""
            PluginCard {
                background: #2a2a3a;
                border-radius: 8px;
                border: 1px solid #3a3a5a;
            }
            PluginCard:hover {
                border: 1px solid #6060aa;
            }
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(10)

        # Enable toggle
        self.toggle = QCheckBox()
        self.toggle.setChecked(True)
        self.toggle.setToolTip("Enable/disable this plugin")
        layout.addWidget(self.toggle)

        # Drag handle (visual only)
        handle = QLabel("⠿")
        handle.setStyleSheet("color: #555; font-size: 18px;")
        handle.setToolTip("Drag to reorder (coming soon)")
        layout.addWidget(handle)

        # Icon + Name
        icon_label = QLabel(plugin.icon)
        icon_label.setFont(QFont("Segoe UI Emoji", 18))
        layout.addWidget(icon_label)

        name_col = QVBoxLayout()
        name_col.setSpacing(2)
        name_lbl = QLabel(plugin.name)
        name_lbl.setFont(QFont("Segoe UI", 11, QFont.Weight.Bold))
        name_lbl.setStyleSheet("color: #e0e0ff;")
        desc_lbl = QLabel(plugin.description)
        desc_lbl.setStyleSheet("color: #8888aa; font-size: 10px;")
        name_col.addWidget(name_lbl)
        name_col.addWidget(desc_lbl)
        layout.addLayout(name_col, stretch=1)

        # Dependency status
        ok, msg = plugin.check_dependencies()
        self.status_lbl = QLabel("✅" if ok else "⚠️")
        self.status_lbl.setToolTip(msg if not ok else "All dependencies installed")
        self.status_lbl.setFont(QFont("Segoe UI Emoji", 14))
        layout.addWidget(self.status_lbl)

        # Settings button
        if plugin.get_settings_schema():
            settings_btn = QPushButton("⚙ Settings")
            settings_btn.setFixedWidth(90)
            settings_btn.setStyleSheet("""
                QPushButton {
                    background: #3a3a6a;
                    color: #ccc;
                    border-radius: 4px;
                    padding: 4px 8px;
                    font-size: 11px;
                }
                QPushButton:hover { background: #5050aa; }
            """)
            settings_btn.clicked.connect(self._open_settings)
            layout.addWidget(settings_btn)

    def _open_settings(self):
        dialog = SettingsDialog(self.plugin, self.current_settings, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.current_settings = dialog.get_settings()
            self.settings_changed.emit(self.plugin.name, self.current_settings)

    def is_enabled(self):
        return self.toggle.isChecked()


# ─────────────────────────────────────────────
#  Add Plugin Dialog
# ─────────────────────────────────────────────

class AddPluginDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Add Plugin from GitHub")
        self.setMinimumWidth(500)
        self.setModal(True)

        layout = QVBoxLayout(self)

        info = QLabel(
            "Paste a GitHub repository URL to install it as a plugin.\n"
            "The repo must contain a Python file matching *_plugin.py with a PipelinePlugin subclass."
        )
        info.setWordWrap(True)
        info.setStyleSheet("color: #aaa; font-size: 11px;")
        layout.addWidget(info)

        form = QFormLayout()
        self.url_input = QLineEdit()
        self.url_input.setPlaceholderText("https://github.com/username/repo")
        form.addRow("GitHub URL:", self.url_input)

        self.pypi_input = QLineEdit()
        self.pypi_input.setPlaceholderText("e.g. cleanvid  or  openai-whisper")
        form.addRow("Or PyPI package:", self.pypi_input)

        layout.addLayout(form)

        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setMaximumHeight(120)
        self.log_area.setStyleSheet("background: #1a1a2a; color: #aaffaa; font-family: monospace;")
        layout.addWidget(self.log_area)

        buttons = QDialogButtonBox()
        self.install_btn = buttons.addButton("Install", QDialogButtonBox.ButtonRole.AcceptRole)
        buttons.addButton("Close", QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self._install)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _install(self):
        self.log_area.clear()
        url = self.url_input.text().strip()
        pkg = self.pypi_input.text().strip()

        def log(msg):
            self.log_area.append(msg)
            QApplication.processEvents()

        if url:
            ok, msg = install_from_github(url, log_callback=log)
        elif pkg:
            ok, msg = install_from_pypi(pkg, log_callback=log)
        else:
            log("Please enter a GitHub URL or PyPI package name.")
            return

        if ok:
            log("✅ Installation successful! Restart the app to load new plugins.")
        else:
            log(f"❌ Failed: {msg}")


# ─────────────────────────────────────────────
#  Main Window
# ─────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("🎬 Video Automation Pipeline")
        self.setMinimumSize(900, 700)
        self.resize(1000, 780)
        self.setAcceptDrops(True)

        self.plugins: list[PipelinePlugin] = load_plugins_from_dir()
        self.plugin_cards: list[PluginCard] = []
        self.settings_map: dict[str, dict] = {}
        self.worker = None
        self.worker_thread = None

        self._setup_style()
        self._build_ui()

    def _setup_style(self):
        self.setStyleSheet("""
            QMainWindow, QWidget {
                background-color: #1a1a2e;
                color: #e0e0ff;
                font-family: 'Segoe UI', Arial, sans-serif;
            }
            QLabel { color: #e0e0ff; }
            QGroupBox {
                border: 1px solid #3a3a5a;
                border-radius: 6px;
                margin-top: 8px;
                font-weight: bold;
                color: #aaaaff;
                padding: 8px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
            QTextEdit {
                background: #0f0f1a;
                color: #00ff88;
                border: 1px solid #2a2a4a;
                border-radius: 4px;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 11px;
            }
            QLineEdit {
                background: #2a2a3e;
                color: #e0e0ff;
                border: 1px solid #3a3a5a;
                border-radius: 4px;
                padding: 6px;
            }
            QLineEdit:focus { border: 1px solid #6060cc; }
            QPushButton {
                background: #3a3a6e;
                color: #e0e0ff;
                border: 1px solid #5050aa;
                border-radius: 6px;
                padding: 8px 16px;
                font-weight: bold;
            }
            QPushButton:hover { background: #5050aa; }
            QPushButton:pressed { background: #2a2a5a; }
            QPushButton:disabled { background: #2a2a3a; color: #555; }
            QProgressBar {
                border: 1px solid #3a3a5a;
                border-radius: 4px;
                background: #1a1a2e;
                text-align: center;
                color: white;
            }
            QProgressBar::chunk {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #4040cc, stop:1 #00ccaa);
                border-radius: 4px;
            }
            QScrollArea { border: none; }
            QScrollBar:vertical {
                background: #1a1a2e;
                width: 8px;
            }
            QScrollBar::handle:vertical {
                background: #3a3a6a;
                border-radius: 4px;
            }
        """)

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        # ── Header ──
        header = QWidget()
        header.setStyleSheet("background: #0f0f1e; padding: 0px;")
        header.setFixedHeight(70)
        hl = QHBoxLayout(header)
        hl.setContentsMargins(20, 10, 20, 10)
        title = QLabel("🎬  Video Automation Pipeline")
        title.setFont(QFont("Segoe UI", 18, QFont.Weight.Bold))
        title.setStyleSheet("color: #aaaaff;")
        subtitle = QLabel("OBS → Profanity Removal → Silence Cut → Privacy Blur → Reels")
        subtitle.setStyleSheet("color: #666688; font-size: 11px;")
        title_col = QVBoxLayout()
        title_col.addWidget(title)
        title_col.addWidget(subtitle)
        hl.addLayout(title_col, stretch=1)
        root.addWidget(header)

        # ── Main body ──
        body = QSplitter(Qt.Orientation.Vertical)
        body.setHandleWidth(4)
        body.setStyleSheet("QSplitter::handle { background: #2a2a4a; }")

        top_half = QWidget()
        top_layout = QVBoxLayout(top_half)
        top_layout.setContentsMargins(16, 16, 16, 8)
        top_layout.setSpacing(12)

        # ── Input file ──
        file_group = QGroupBox("📂  Input Video")
        fl = QHBoxLayout(file_group)
        self.file_input = QLineEdit()
        self.file_input.setPlaceholderText("Drop a video file here or click Browse…")
        self.file_input.setReadOnly(True)
        browse_btn = QPushButton("Browse")
        browse_btn.setFixedWidth(90)
        browse_btn.clicked.connect(self._browse_input)
        fl.addWidget(self.file_input)
        fl.addWidget(browse_btn)
        top_layout.addWidget(file_group)

        # ── Pipeline stages ──
        stages_group = QGroupBox("⚙  Pipeline Stages")
        stages_outer = QVBoxLayout(stages_group)

        # Toolbar above cards
        stage_toolbar = QHBoxLayout()
        stages_lbl = QLabel("Drag to reorder • Toggle checkbox to enable/disable")
        stages_lbl.setStyleSheet("color: #666688; font-size: 10px;")
        stage_toolbar.addWidget(stages_lbl, stretch=1)
        add_btn = QPushButton("+ Add Plugin")
        add_btn.setFixedWidth(110)
        add_btn.setStyleSheet("""
            QPushButton {
                background: #2a4a2a;
                border: 1px solid #3a8a3a;
                color: #88ff88;
            }
            QPushButton:hover { background: #3a6a3a; }
        """)
        add_btn.clicked.connect(self._add_plugin)
        stage_toolbar.addWidget(add_btn)
        stages_outer.addLayout(stage_toolbar)

        # Scrollable list of plugin cards
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True)
        scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        card_container = QWidget()
        self.cards_layout = QVBoxLayout(card_container)
        self.cards_layout.setSpacing(6)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)

        for plugin in self.plugins:
            self._add_plugin_card(plugin)

        if not self.plugins:
            empty = QLabel("No plugins loaded. Click '+ Add Plugin' to install one.")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setStyleSheet("color: #555588; padding: 20px;")
            self.cards_layout.addWidget(empty)

        self.cards_layout.addStretch()
        scroll_area.setWidget(card_container)
        stages_outer.addWidget(scroll_area)
        top_layout.addWidget(stages_group, stretch=1)

        # ── Run controls ──
        run_group = QGroupBox("▶  Run Pipeline")
        rl = QVBoxLayout(run_group)

        run_row = QHBoxLayout()
        self.run_btn = QPushButton("▶  Run Pipeline")
        self.run_btn.setFixedHeight(42)
        self.run_btn.setStyleSheet("""
            QPushButton {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #3040cc, stop:1 #00aa88);
                color: white;
                font-size: 14px;
                border-radius: 8px;
                border: none;
            }
            QPushButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #4050ee, stop:1 #00ccaa);
            }
            QPushButton:disabled { background: #2a2a3a; color: #555; }
        """)
        self.run_btn.clicked.connect(self._run_pipeline)

        self.stop_btn = QPushButton("⏹  Stop")
        self.stop_btn.setFixedHeight(42)
        self.stop_btn.setFixedWidth(100)
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet("""
            QPushButton {
                background: #4a1a1a;
                color: #ff8888;
                border: 1px solid #8a3a3a;
                border-radius: 8px;
            }
            QPushButton:hover { background: #6a2a2a; }
            QPushButton:disabled { background: #2a2a3a; color: #555; border: none; }
        """)
        self.stop_btn.clicked.connect(self._stop_pipeline)

        run_row.addWidget(self.run_btn)
        run_row.addWidget(self.stop_btn)
        rl.addLayout(run_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(14)
        self.progress_bar.setTextVisible(True)
        rl.addWidget(self.progress_bar)

        top_layout.addWidget(run_group)
        body.addWidget(top_half)

        # ── Log area ──
        log_widget = QWidget()
        log_layout = QVBoxLayout(log_widget)
        log_layout.setContentsMargins(16, 8, 16, 16)
        log_layout.setSpacing(4)

        log_header = QHBoxLayout()
        log_label = QLabel("📋  Pipeline Log")
        log_label.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
        log_label.setStyleSheet("color: #8888cc;")
        clear_btn = QPushButton("Clear")
        clear_btn.setFixedWidth(60)
        clear_btn.setFixedHeight(24)
        clear_btn.setStyleSheet("""
            QPushButton {
                background: #2a2a3a;
                color: #888;
                border: 1px solid #3a3a4a;
                border-radius: 4px;
                font-size: 10px;
                padding: 2px;
            }
            QPushButton:hover { color: #ccc; }
        """)
        clear_btn.clicked.connect(lambda: self.log_area.clear())
        log_header.addWidget(log_label, stretch=1)
        log_header.addWidget(clear_btn)
        log_layout.addLayout(log_header)

        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        self.log_area.setPlaceholderText("Pipeline output will appear here…")
        log_layout.addWidget(self.log_area)
        body.addWidget(log_widget)

        body.setSizes([480, 260])
        root.addWidget(body)

        self._log("🚀 Video Pipeline ready. Select a video file and click Run.")
        self._log("💡 Tip: Click ⚙ Settings on each plugin to configure it before running.\n")

    def _add_plugin_card(self, plugin: PipelinePlugin):
        card = PluginCard(plugin, self)
        card.settings_changed.connect(self._on_settings_changed)
        self.plugin_cards.append(card)
        # Insert before the stretch at the end
        count = self.cards_layout.count()
        self.cards_layout.insertWidget(count - 1 if count > 0 else 0, card)

    def _on_settings_changed(self, plugin_name: str, settings: dict):
        self.settings_map[plugin_name] = settings

    def _browse_input(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Video File", "",
            "Video Files (*.mp4 *.mkv *.mov *.avi *.webm *.flv);;All Files (*)"
        )
        if path:
            self.file_input.setText(path)
            self._log(f"📂 Selected: {path}")

    def _add_plugin(self):
        dialog = AddPluginDialog(self)
        dialog.exec()
        # Suggest restart to pick up new plugins
        QMessageBox.information(
            self, "Plugins Updated",
            "If you installed a new plugin, please restart the application to load it."
        )

    def _run_pipeline(self):
        input_path = self.file_input.text().strip()
        if not input_path or not Path(input_path).exists():
            QMessageBox.warning(self, "No Input", "Please select a valid input video file.")
            return

        enabled_plugins = [
            (card.plugin, card.is_enabled())
            for card in self.plugin_cards
        ]

        active = [(p, en) for p, en in enabled_plugins if en]
        if not active:
            QMessageBox.warning(self, "No Plugins", "Please enable at least one pipeline plugin.")
            return

        # Merge stored settings with defaults
        settings_map = {}
        for card in self.plugin_cards:
            settings_map[card.plugin.name] = card.current_settings

        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        self._log(f"\n{'═'*50}")
        self._log(f"🎬 Starting pipeline on: {Path(input_path).name}")
        self._log(f"   Active stages: {', '.join(p.name for p, en in active)}")

        self.worker = PipelineWorker(input_path, enabled_plugins, settings_map)
        self.worker_thread = QThread()
        self.worker.moveToThread(self.worker_thread)

        self.worker.log_signal.connect(self._log)
        self.worker.progress_signal.connect(self.progress_bar.setValue)
        self.worker.finished_signal.connect(self._on_pipeline_finished)
        self.worker_thread.started.connect(self.worker.run)

        self.worker_thread.start()

    def _stop_pipeline(self):
        if self.worker:
            self.worker.stop()
        self.stop_btn.setEnabled(False)

    def _on_pipeline_finished(self, success: bool, message: str):
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        if self.worker_thread:
            self.worker_thread.quit()
            self.worker_thread.wait()

        if success:
            self.progress_bar.setValue(100)
            QMessageBox.information(self, "Done!", f"Pipeline complete!\n\nOutput: {message}")
        else:
            QMessageBox.critical(self, "Pipeline Failed", f"Error: {message}")

    def _log(self, message: str):
        self.log_area.append(message)
        self.log_area.verticalScrollBar().setValue(
            self.log_area.verticalScrollBar().maximum()
        )

    # ── Drag & Drop ──
    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent):
        urls = event.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if Path(path).suffix.lower() in {".mp4", ".mkv", ".mov", ".avi", ".webm", ".flv"}:
                self.file_input.setText(path)
                self._log(f"📂 Dropped: {path}")
            else:
                self._log(f"⚠️  Unsupported file type: {path}")


# ─────────────────────────────────────────────
#  Entry point
# ─────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
