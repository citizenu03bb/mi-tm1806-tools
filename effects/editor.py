#!/usr/bin/env python3
"""
Mi TM1806 Keyboard Effects Composer
====================================
Visual editor for creating, previewing, and exporting backlight effects
for the Xiaomi Mi Gaming Laptop keyboard.

- Click zone rectangles to pick colours.
- Add frames to build a sequence (colour + duration).
- Preview live on the keyboard.
- Export as a reusable effect for the rgbkb-effects launcher.
"""

import sys, os, json, subprocess, time, re
from pathlib import Path

try:
    from PyQt5.QtWidgets import (
        QApplication, QMainWindow, QWidget, QPushButton, QLabel,
        QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox, QFrame,
        QColorDialog, QSlider, QSpinBox, QComboBox, QListWidget,
        QListWidgetItem, QMessageBox, QFileDialog, QInputDialog,
        QSplitter, QStyle
    )
    from PyQt5.QtCore import Qt, QTimer, QSize
    from PyQt5.QtGui import QColor, QPalette, QFont, QIcon
except ImportError:
    print("PyQt5 required: sudo apt install python3-pyqt5", file=sys.stderr)
    sys.exit(1)

SCRIPT_DIR = Path(__file__).resolve().parent
PRESETS_DIR = SCRIPT_DIR / "presets"
PRESETS_DIR.mkdir(exist_ok=True)

from mi_tm1806_sysfs import DriverUnavailable, paint_frame as sysfs_paint_frame

ZONE_NAMES = ["bar", "kb-left", "kb-mid", "kb-right"]
ZONE_LABELS = ["Bar", "Left", "Mid", "Right"]
EFFECTS = ["static", "breath", "wave", "colorful"]
SPEEDS = [0, 1, 2]

# ── helpers ────────────────────────────────────────────────────────────

def color_to_hex(qcolor):
    return f"{qcolor.red():02X}{qcolor.green():02X}{qcolor.blue():02X}"


def hex_to_color(s):
    s = s.lstrip("#")
    if len(s) >= 6:
        return QColor(int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16))
    return QColor(0, 0, 0)


# ── zone widget ────────────────────────────────────────────────────────

class ZoneWidget(QFrame):
    """Clickable rectangle representing one keyboard zone."""

    def __init__(self, label, color=QColor(0, 0, 0)):
        super().__init__()
        self.label = label
        self._color = color
        self.setFixedSize(70, 70)
        self.setFrameStyle(QFrame.Box | QFrame.Plain)
        self.setCursor(Qt.PointingHandCursor)
        self.update_style()

    def update_style(self):
        hexstr = self._color.name()
        r, g, b = self._color.red(), self._color.green(), self._color.blue()
        # Brightness determines text colour
        lum = 0.299 * r + 0.587 * g + 0.114 * b
        fg = "#000000" if lum > 128 else "#FFFFFF"
        self.setStyleSheet(
            f"QFrame {{ background-color: {hexstr}; border: 2px solid #555; "
            f"border-radius: 6px; }}"
        )

    @property
    def color(self):
        return self._color

    @color.setter
    def color(self, c):
        self._color = c
        self.update_style()

    def mousePressEvent(self, event):
        c = QColorDialog.getColor(self._color, self, f"Pick colour for {self.label}")
        if c.isValid():
            self.color = c
        super().mousePressEvent(event)


# ── preset system ──────────────────────────────────────────────────────

def load_presets():
    presets = {}
    if PRESETS_DIR.exists():
        for f in sorted(PRESETS_DIR.glob("*.json")):
            try:
                data = json.loads(f.read_text())
                presets[f.stem] = data
            except (json.JSONDecodeError, KeyError):
                pass
    return presets


def save_preset(name, data):
    path = PRESETS_DIR / f"{name}.json"
    path.write_text(json.dumps(data, indent=2))


# ── Main window ────────────────────────────────────────────────────────

class EffectsComposer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Mi TM1806 Keyboard Effects Composer")
        self.setMinimumSize(620, 520)

        self.frames = []  # list of {"zones": [QColor x4], "duration": float}
        self.playing = False
        self.play_index = 0
        self.play_timer = QTimer()
        self.play_timer.timeout.connect(self._play_next)

        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        # ── zone preview ──
        zone_group = QGroupBox("Keyboard Zones (click to pick colour)")
        zone_layout = QHBoxLayout()
        self.zones = []
        for lbl in ZONE_LABELS:
            zw = ZoneWidget(lbl, QColor(0, 0, 0))
            zone_layout.addWidget(zw)
            self.zones.append(zw)
        zone_layout.addStretch()
        zone_group.setLayout(zone_layout)
        main_layout.addWidget(zone_group)

        # ── effect / speed ──
        ctrl_row = QHBoxLayout()
        ctrl_row.addWidget(QLabel("Effect:"))
        self.effect_combo = QComboBox()
        self.effect_combo.addItems(EFFECTS)
        self.effect_combo.setCurrentText("static")
        ctrl_row.addWidget(self.effect_combo)

        ctrl_row.addWidget(QLabel("Speed:"))
        self.speed_combo = QComboBox()
        self.speed_combo.addItems([str(s) for s in SPEEDS])
        self.speed_combo.setCurrentText("2")
        ctrl_row.addWidget(self.speed_combo)

        ctrl_row.addStretch()
        main_layout.addLayout(ctrl_row)

        # ── frame timeline ──
        splitter = QSplitter(Qt.Vertical)
        frame_group = QGroupBox("Frame Timeline")
        frame_layout = QVBoxLayout()

        self.frame_list = QListWidget()
        self.frame_list.currentRowChanged.connect(self._on_frame_select)
        frame_layout.addWidget(self.frame_list)

        btn_row = QHBoxLayout()
        self.btn_add_frame = QPushButton("➕ Add Frame")
        self.btn_add_frame.clicked.connect(self._add_frame)
        btn_row.addWidget(self.btn_add_frame)

        self.btn_del_frame = QPushButton("🗑 Delete")
        self.btn_del_frame.clicked.connect(self._del_frame)
        btn_row.addWidget(self.btn_del_frame)

        self.btn_up = QPushButton("▲ Up")
        self.btn_up.clicked.connect(lambda: self._move_frame(-1))
        btn_row.addWidget(self.btn_up)

        self.btn_down = QPushButton("▼ Down")
        self.btn_down.clicked.connect(lambda: self._move_frame(1))
        btn_row.addWidget(self.btn_down)
        btn_row.addStretch()

        dur_row = QHBoxLayout()
        dur_row.addWidget(QLabel("Duration (seconds):"))
        self.dur_spin = QSpinBox()
        self.dur_spin.setRange(0, 999)
        self.dur_spin.setSuffix(" ms")
        self.dur_spin.setValue(500)
        self.dur_spin.valueChanged.connect(self._on_duration_change)
        dur_row.addWidget(self.dur_spin)
        dur_row.addStretch()

        frame_layout.addLayout(btn_row)
        frame_layout.addLayout(dur_row)
        frame_group.setLayout(frame_layout)
        splitter.addWidget(frame_group)

        # ── play / export ──
        control_panel = QWidget()
        cp_layout = QVBoxLayout(control_panel)

        # Preview row
        preview_row = QHBoxLayout()
        self.btn_preview = QPushButton("▶ Play Sequence")
        self.btn_preview.clicked.connect(self._toggle_play)
        preview_row.addWidget(self.btn_preview)

        self.btn_stop = QPushButton("⏹ Stop")
        self.btn_stop.clicked.connect(self._stop)
        preview_row.addWidget(self.btn_stop)

        self.btn_paint_now = QPushButton("🎨 Paint Current Frame")
        self.btn_paint_now.clicked.connect(self._paint_current)
        preview_row.addWidget(self.btn_paint_now)
        preview_row.addStretch()
        cp_layout.addLayout(preview_row)

        # Preset row
        preset_row = QHBoxLayout()
        preset_row.addWidget(QLabel("Preset:"))
        self.preset_combo = QComboBox()
        self._reload_presets()
        preset_row.addWidget(self.preset_combo)

        self.btn_load = QPushButton("Load")
        self.btn_load.clicked.connect(self._load_preset)
        preset_row.addWidget(self.btn_load)

        self.btn_save = QPushButton("Save As...")
        self.btn_save.clicked.connect(self._save_preset)
        preset_row.addWidget(self.btn_save)

        self.btn_export = QPushButton("Export Script")
        self.btn_export.clicked.connect(self._export_script)
        preset_row.addWidget(self.btn_export)
        preset_row.addStretch()
        cp_layout.addLayout(preset_row)

        splitter.addWidget(control_panel)
        main_layout.addWidget(splitter)

        # ── initial frame ──
        self._add_frame()

    # ── frame management ────────────────────────────────────────────

    def _add_frame(self, select=True):
        colors = [zw.color for zw in self.zones]
        self.frames.append({
            "zones": [color_to_hex(c) for c in colors],
            "duration": self.dur_spin.value() / 1000.0
        })
        self._refresh_frame_list()
        if select:
            self.frame_list.setCurrentRow(len(self.frames) - 1)

    def _del_frame(self):
        idx = self.frame_list.currentRow()
        if 0 <= idx < len(self.frames):
            del self.frames[idx]
            self._refresh_frame_list()

    def _move_frame(self, delta):
        idx = self.frame_list.currentRow()
        new = idx + delta
        if 0 <= idx < len(self.frames) and 0 <= new < len(self.frames):
            self.frames[idx], self.frames[new] = self.frames[new], self.frames[idx]
            self._refresh_frame_list()
            self.frame_list.setCurrentRow(new)

    def _refresh_frame_list(self):
        sel = self.frame_list.currentRow()
        self.frame_list.blockSignals(True)
        self.frame_list.clear()
        for i, f in enumerate(self.frames):
            dur = f["duration"]
            colours = "  ".join(f"⬤{c}" for c in f["zones"])
            item = QListWidgetItem(f"[{i+1}]  {dur:.2f}s  {colours}")
            item.setData(Qt.UserRole, i)
            self.frame_list.addItem(item)
        if 0 <= sel < len(self.frames):
            self.frame_list.setCurrentRow(sel)
        self.frame_list.blockSignals(False)

    def _on_frame_select(self, row):
        if 0 <= row < len(self.frames):
            f = self.frames[row]
            self.dur_spin.blockSignals(True)
            self.dur_spin.setValue(int(f["duration"] * 1000))
            self.dur_spin.blockSignals(False)
            for i, zw in enumerate(self.zones):
                zw.color = hex_to_color(f["zones"][i])

    def _on_duration_change(self, val):
        idx = self.frame_list.currentRow()
        if 0 <= idx < len(self.frames):
            self.frames[idx]["duration"] = val / 1000.0
            self._refresh_frame_list()

    # ── playback ────────────────────────────────────────────────────

    def _paint_current(self):
        """Paint the current frame colours to the keyboard."""
        idx = self.frame_list.currentRow()
        if 0 <= idx < len(self.frames):
            self._paint_frame(self.frames[idx])

    def _paint_frame(self, frame):
        """Send one frame to the keyboard hardware via the kernel driver."""
        effect = self.effect_combo.currentText()
        speed = int(self.speed_combo.currentText())
        try:
            sysfs_paint_frame(frame["zones"], effect, speed)
        except (DriverUnavailable, ValueError) as exc:
            self._stop()
            QMessageBox.warning(self, "Keyboard unavailable", str(exc))

    def _toggle_play(self):
        if self.playing:
            self._stop()
            return
        if not self.frames:
            return
        self.playing = True
        self.play_index = 0
        self.btn_preview.setText("⏸ Pause")
        self._paint_frame(self.frames[0])
        self.frame_list.setCurrentRow(0)
        dur_ms = int(self.frames[0]["duration"] * 1000)
        self.play_timer.start(dur_ms if dur_ms > 50 else 50)

    def _play_next(self):
        if not self.playing:
            return
        self.play_index = (self.play_index + 1) % len(self.frames)
        frame = self.frames[self.play_index]
        self._paint_frame(frame)
        self.frame_list.setCurrentRow(self.play_index)
        dur_ms = int(frame["duration"] * 1000)
        self.play_timer.start(dur_ms if dur_ms > 50 else 50)

    def _stop(self):
        self.playing = False
        self.play_timer.stop()
        self.btn_preview.setText("▶ Play Sequence")

    # ── presets ─────────────────────────────────────────────────────

    def _reload_presets(self):
        self.presets = load_presets()
        self.preset_combo.clear()
        self.preset_combo.addItems([""] + sorted(self.presets.keys()))

    def _load_preset(self):
        name = self.preset_combo.currentText()
        if not name or name not in self.presets:
            return
        data = self.presets[name]
        self.effect_combo.setCurrentText(data.get("effect", "static"))
        self.speed_combo.setCurrentText(str(data.get("speed", 2)))
        self.frames.clear()
        for f in data.get("frames", []):
            self.frames.append({"zones": f["zones"], "duration": f["duration"]})
        self._refresh_frame_list()
        if self.frames:
            self.frame_list.setCurrentRow(0)

    def _save_preset(self):
        name, ok = QInputDialog.getText(self, "Save Preset", "Preset name:")
        if not ok or not name.strip():
            return
        name = name.strip()
        data = {
            "effect": self.effect_combo.currentText(),
            "speed": int(self.speed_combo.currentText()),
            "frames": self.frames
        }
        save_preset(name, data)
        self._reload_presets()
        QMessageBox.information(self, "Saved", f"Preset saved to {PRESETS_DIR / name}.json")

    def _export_script(self):
        """Export as a standalone effect function for rgbkb-effects."""
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Effect Script",
            str(SCRIPT_DIR / "my-effect.sh"),
            "Shell Script (*.sh)")
        if not path:
            return

        effect = self.effect_combo.currentText()
        speed = self.speed_combo.currentText()
        lines = ["#!/bin/bash",
                 f"# Auto-generated by Effects Composer",
                 f"# Effect: {effect} speed={speed}",
                 "set -eu",
                 f'KBDCTL="{SCRIPT_DIR / "kbdctl.py"}"',
                 "cleanup() { echo; exit 0; }; trap cleanup INT TERM",
                 ""]

        if effect != "static" and len(self.frames) == 1 and \
           len(set(self.frames[0]["zones"])) == 1:
            # Single uniform frame with animation → one-liner
            c = self.frames[0]["zones"][0]
            lines.append(f'"$KBDCTL" {effect} "0x{c}" --speed {speed}')
        else:
            lines.append("while true; do")
            for f in self.frames:
                dur = f["duration"]
                colors = " ".join(f'"0x{c}"' for c in f["zones"])
                lines.append(f'    "$KBDCTL" frame {colors} --effect {effect} --speed {speed}'
                             f' >/dev/null 2>&1 || true')
                lines.append(f"    sleep {dur:.2f}")
            lines.append("done")

        Path(path).write_text("\n".join(lines) + "\n")
        Path(path).chmod(0o755)
        QMessageBox.information(self, "Exported",
                                f"Saved to {path}\n\nRun with: sudo {path}")


# ── Main ───────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    # Dark-ish palette
    p = QPalette()
    p.setColor(QPalette.Window, QColor(45, 45, 48))
    p.setColor(QPalette.WindowText, QColor(220, 220, 220))
    p.setColor(QPalette.Base, QColor(30, 30, 30))
    p.setColor(QPalette.Text, QColor(220, 220, 220))
    p.setColor(QPalette.Button, QColor(55, 55, 58))
    p.setColor(QPalette.ButtonText, QColor(220, 220, 220))
    p.setColor(QPalette.Highlight, QColor(0, 120, 215))
    app.setPalette(p)

    win = EffectsComposer()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
