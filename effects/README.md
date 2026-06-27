# Effects (`effects/`)

Flashy presets, an audio visualizer, and a visual composer for the TM1806 keyboard backlight.

These tools use the `mi-tm1806-led` kernel driver's sysfs store-and-commit interface. Load the driver first and ensure your user can write the LED/WMI sysfs nodes, or run the tools with `sudo`.

## Quick start

```sh
# Diagnose driver/sysfs setup
python3 ./effects/kbdctl.py doctor

# Built-in effects (Ctrl+C to stop, restores green)
sudo ./effects/rgbkb-effects rainbow    # spectrum cycle
sudo ./effects/rgbkb-effects police     # red/blue alternating zones
sudo ./effects/rgbkb-effects matrix     # breathing green + code flickers
sudo ./effects/rgbkb-effects disco      # random colours + modes
sudo ./effects/rgbkb-effects pulse      # breathing with colour shift
sudo ./effects/rgbkb-effects fire       # warm amber flicker
sudo ./effects/rgbkb-effects wave       # wave with cycling colour
sudo ./effects/rgbkb-effects all        # cycle through all 7

# Audio visualizer (keyboard reacts to system audio)
sudo ./effects/audiovisualizer.py pulse  # uniform colour pulses to beat
sudo ./effects/audiovisualizer.py bands  # bass→bar, mids→mid, treble→right
sudo ./effects/audiovisualizer.py disco  # colour shifts with the music
sudo ./effects/audiovisualizer.py fire   # warm glow intensifies with volume

# Custom presets (created in the editor)
sudo ./effects/rgbkb-effects preset my-effect
```

## Visual editor

```sh
python3 ./effects/editor.py
```

A PyQt5 GUI for composing per-zone colour sequences:

**Features:**
- Click zone rectangles to pick colours
- Add / delete / reorder frames
- Set duration per frame (millisecond granularity)
- Choose firmware effect (static / breath / wave / colorful) and speed
- ▶ Play sequence live on the keyboard, ⏸ Pause, ⏹ Stop
- 💾 Save as preset (JSON in `effects/presets/`)
- 📤 Export as standalone shell script

**Presets** are simple JSON files:

```json
{
  "effect": "static",
  "speed": 2,
  "frames": [
    {"zones": ["FF0000", "FF0000", "FF0000", "FF0000"], "duration": 0.35},
    {"zones": ["FF0000", "0000FF", "FF0000", "0000FF"], "duration": 0.15},
    {"zones": ["0000FF", "0000FF", "0000FF", "0000FF"], "duration": 0.35},
    {"zones": ["0000FF", "FF0000", "0000FF", "FF0000"], "duration": 0.15}
  ]
}
```

Presets saved here can be played from:
- The preset launcher: `sudo ./effects/rgbkb-effects preset <name>`
- The OpenRGB plugin's preset player tab
- Any custom script that reads the JSON format

## Dependencies

- `mi-tm1806-led` kernel module loaded
- write access to `/sys/class/leds/mi_tm1806::kbd_*` and `/sys/bus/wmi/devices/E2A89D40-.../`
- `python3` with PyQt5 (`python3-pyqt5`) — for the visual editor
- `pulseaudio-utils` (`pactl`) — audiovisualizer uses it to find the default audio sink
- PipeWire `pw-cat` — audiovisualizer captures the monitor stream
