# Effects (`effects/`)

Flashy presets and a visual composer for the TM1806 keyboard backlight.

## Quick start

```sh
# Built-in effects (Ctrl+C to stop, restores green)
sudo ./effects/rgbkb-effects rainbow    # spectrum cycle
sudo ./effects/rgbkb-effects police     # red/blue alternating zones
sudo ./effects/rgbkb-effects matrix     # breathing green + code flickers
sudo ./effects/rgbkb-effects disco      # random colours + modes
sudo ./effects/rgbkb-effects pulse      # breathing with colour shift
sudo ./effects/rgbkb-effects fire       # warm amber flicker
sudo ./effects/rgbkb-effects wave       # wave with cycling colour
sudo ./effects/rgbkb-effects all        # cycle through all 7

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
- The Bash CLI: `sudo ./effects/rgbkb-effects preset <name>`
- The OpenRGB plugin's preset player tab
- Any custom script that reads the JSON format

## Dependencies

- `python3` with PyQt5 (`python3-pyqt5`)
- `sudo` access to `rgbkb/rgbkb` (for painting to hardware)
