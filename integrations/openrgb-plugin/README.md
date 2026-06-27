# OpenRGB plugin (Mi TM1806 keyboard)

Surfaces the laptop's 4-zone keyboard inside OpenRGB alongside any USB peripherals. The plugin talks to the `mi-tm1806-led` kernel driver via sysfs; nothing here touches ACPI, USB, or `/dev/mem`.

## What it adds to OpenRGB

### Device tab

A new device in OpenRGB's device list:

```
Xiaomi Mi Gaming Laptop Keyboard
  Type:   Keyboard
  Zones:  Hotkey Bar / Keyboard Left / Keyboard Middle / Keyboard Right
  Modes:  Direct, Static, Breath, Wave, Colorful
```

Each zone is a single LED (1×RGB). Uses the kernel driver's store-and-commit model — writes to `multi_intensity` + `brightness` + `effect` + `speed`, then calls `commit` to batch-paint all zones simultaneously.

### Preset player tab

A browser + player for custom effect sequences created with `effects/editor.py`:

```
┌─ Mi TM1806 Presets & Status ──────────────────────────┐
│  [███ Bar] [███Left] [███ Mid] [███Right]              │  ← live zone colour previews
│                                                        │
│  Preset: [police ▾]  (4 frames)                        │
│  ┌──────────────────────────────────────────┐          │
│  │ [1] 0.35s  ⬤FF ⬤FF ⬤FF ⬤FF            │          │  ← click a frame
│  │ [2] 0.15s  ⬤FF ⬤00 ⬤FF ⬤00            │          │
│  └──────────────────────────────────────────┘          │
│  Duration: [0.15 s ▾]  [💾 Save]  [🖉 Open Full Editor] │          │
│                                                        │
│  [▶ Play]  [⏹ Stop]   Playing frame 2/4 [FF 00 FF 00]│
└────────────────────────────────────────────────────────┘
```

**Features:**
- **Preset dropdown** — scans `effects/presets/*.json`
- **Frame list** — click to select; shows per-zone colours
- **Inline duration editor** — change the selected frame's timing; updates in real-time
- **💾 Save** — writes the modified preset back to disk
- **🖉 Open Full Editor** — launches `effects/editor.py` for full colour/frame editing
- **▶ Play / ⏸ Pause / ⏹ Stop** — QTimer loops through frames, painting each via sysfs
- **Live zone previews** — 4 colour boxes that update per frame, matching the keyboard

## Build

Requires:

- The OpenRGB source tree, **pinned to release_0.9** (commit `b5f46e3f`) to match OpenRGB AppImage 0.9 (API version 3).
- `qtbase5-dev`, `qttools5-dev`, `g++` with C++17 support.

```sh
git clone --depth=1 https://gitlab.com/CalcProgrammer1/OpenRGB.git ~/OpenRGB-src
cd ~/OpenRGB-src && git fetch --tags origin && git checkout release_0.9
cd ~/Projects/mi-tm1806-tools/integrations/openrgb-plugin
qmake OPENRGB_SRC=$HOME/OpenRGB-src
make
```

## Install

```sh
mkdir -p ~/.config/OpenRGB/plugins
cp libOpenRGBMiTM1806Plugin.so ~/.config/OpenRGB/plugins/

# Symlink presets so the plugin can find them
ln -s /path/to/mi-tm1806-tools/effects/presets ~/.config/OpenRGB/plugins/presets
```

Restart OpenRGB.

## Requirements at runtime

- `mi-tm1806-led` kernel module loaded.
- The user running OpenRGB needs write access to the LED + WMI sysfs nodes (effect, speed, secondary_color, panel_brightness, **commit**). See `integrations/claude-code/99-mi-tm1806-led.rules` for a udev rule that grants `plugdev` group access.

## File layout

```
openrgb-plugin/
├── OpenRGBMiTM1806Plugin.{h,cpp}        # Qt plugin entry + PresetWidget
├── RGBController_MiTM1806.{h,cpp}       # Maps OpenRGB zone/LED model → sysfs
├── OpenRGBMiTM1806Plugin.pro            # qmake project
└── README.md
```

## Caveats

- **Setting a mode is global.** The Mi EC has one shared `LETY` register, so picking "Breath" in OpenRGB switches all 4 zones to breathing — there's no firmware path to "static bar + breathing keyboard area".
- **Cold-boot panel-off case.** If `KBBR=5` at OpenRGB launch, the kernel driver returns `-ENXIO`. Press Fn+brightness once to wake.
- **Preset path.** The plugin looks for presets at `~/.config/OpenRGB/plugins/presets/`. The install step above creates a symlink from your repo's `effects/presets/`.
