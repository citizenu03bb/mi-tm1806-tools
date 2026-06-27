# OpenRGB plugin (Mi TM1806 keyboard)

Surfaces the laptop's 4-zone keyboard inside OpenRGB alongside any USB peripherals (G213 keyboards, Ironclaw mice, etc.) so the whole RGB inventory is controllable from one UI. The plugin is a thin shim — all the real work happens in the `mi-tm1806-led` kernel driver. The plugin reads/writes its sysfs interface; nothing here touches ACPI, USB, or `/dev/mem`.

## What it adds to OpenRGB

A new device in OpenRGB's device list:

```
Xiaomi Mi Gaming Laptop Keyboard
  Type:   Keyboard
  Zones:  Hotkey Bar / Keyboard Left / Keyboard Middle / Keyboard Right
  Modes:  Direct, Static, Breath, Wave, Colorful
```

Each zone is a single LED (1×RGB triplet). Direct/Static let you set per-zone color; Breath/Wave animate the per-zone SRAM colors at one of three speeds; Colorful uses two mode-specific colors via the firmware's `C0Z`/`C1Z` registers.

## Build

Requires:

- The OpenRGB source tree, **pinned to release_0.9** (commit `b5f46e3f`) to match OpenRGB AppImage 0.9 (API version 3). Newer or older revisions have a different `OpenRGBPluginInterface::Load()` signature and will fail to load.
- `qtbase5-dev`, `qttools5-dev`, `g++` with C++17 support.

```sh
git clone --depth=1 https://gitlab.com/CalcProgrammer1/OpenRGB.git ~/OpenRGB-src
cd ~/OpenRGB-src && git fetch --tags origin && git checkout release_0.9
cd ~/Projects/mi-tm1806-tools/integrations/openrgb-plugin
qmake OPENRGB_SRC=$HOME/OpenRGB-src
make
```

Result: `libOpenRGBMiTM1806Plugin.so` (~90 KB).

## Install

```sh
mkdir -p ~/.config/OpenRGB/plugins
cp libOpenRGBMiTM1806Plugin.so ~/.config/OpenRGB/plugins/
```

Restart OpenRGB. On first load, OpenRGB writes a default-enabled entry into `~/.config/OpenRGB/OpenRGB.json` under `Plugins.plugins[]`. Toggling it from there or via the Plugins tab disables it without removing the `.so`.

## Requirements at runtime

- `mi-tm1806-led` kernel module loaded (`lsmod | grep mi_tm1806`). The plugin checks for `/sys/class/leds/mi_tm1806::kbd_bar` at startup; if missing, it logs and silently skips registering the controller.
- The user running OpenRGB needs write access to the LED + WMI sysfs nodes. The driver repo's `integrations/claude-code/99-mi-tm1806-led.rules` udev rule grants `plugdev` group `g+w`, which covers the OpenRGB case too.

## Why pin to OpenRGB 0.9 specifically

Plugin API version compatibility is checked at load time (`PluginManager.cpp` rejects mismatched plugins). The `OpenRGBPluginInterface::Load` signature also changed between API 3 (`Load(bool dark_theme, ResourceManager*)`) and API 4 (`Load(ResourceManagerInterface*)`). Targeting either flavor means choosing one OpenRGB binary to support. We picked 0.9 because that's the version of the AppImage on Pat's machine; rebuilding against `master` is straightforward if you've moved on.

## Why a placeholder widget

`OpenRGBMiTM1806Plugin::GetWidget()` returns a `QLabel` rather than `nullptr`. OpenRGB 0.9's `OpenRGBPluginContainer` constructor unconditionally calls `setParent` on whatever the plugin returns, so `nullptr` would be a null-deref → SIGSEGV during startup. We also set `Location = 0xFF` (an invalid value) so the host's tab-creation path is skipped entirely and the placeholder widget is never actually instantiated by the dialog. The QLabel exists only as a defensive fallback against future host revisions that might construct the container regardless.

## File layout

```
openrgb-plugin/
├── OpenRGBMiTM1806Plugin.{h,cpp}    # Qt plugin entry point + lifecycle
├── RGBController_MiTM1806.{h,cpp}   # Maps OpenRGB zone/LED model -> sysfs writes
├── OpenRGBMiTM1806Plugin.pro        # qmake project (parameterized via OPENRGB_SRC)
└── README.md
```

## Caveats

- **Setting a mode is global on this firmware.** The Mi EC has one shared `LETY` register, so picking "Breath" in OpenRGB switches all 4 zones to breathing — there's no firmware path to "static bar + breathing keyboard area". This is a mirror of the kernel-driver constraint, not a plugin limitation.
- **Cold-boot panel-off case.** If `KBBR=5` (panel power-gated) at OpenRGB launch, the kernel driver returns `-ENXIO` from each color write. The plugin silently swallows the failure; the panel needs one Fn+brightness press to re-enable, after which everything works.
