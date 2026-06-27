# driver/

Out-of-tree kernel module for the 4-zone keyboard backlight on the TM1806. Replaces the userspace `rgbkb/` stack with a kernel-side LED class driver.

See the [top-level README](../README.md) for hardware context and the [`rgbkb/` README](../rgbkb/README.md) for the buffer-format and protocol notes that this driver implements.

## What it does

Binds to the Quanta WMI device with GUID `E2A89D40-784F-4E91-BE22-AE373CDEA97A` and exposes:

- four multicolor LED classdevs at `/sys/class/leds/mi_tm1806::kbd_{bar,left,mid,right}/`
- four global attributes on the WMI device at `/sys/bus/wmi/devices/E2A89D40-.../`:
  - `effect` — `1`=static, `2`=breath, `3`=wave, `4`=colorful
  - `speed` — `0`..`2` (0=slow, 2=fast)
  - `secondary_color` — `rrggbb` hex; second color used in `effect=4`
  - `panel_brightness` — `0`..`5` (0=max, 5=off; KBBR sentinel)

Each paint goes through the LEBR-bypass: KBBR is read from `\_SB_.PCI0.LPCB.EC0.KBBR` via `acpi_evaluate_integer`, then passed as LEBR in the `FB00/0100` LightEffect packet so the firmware painter consumes the C-registers without blanking the panel.

## Compared to the userspace stack

| Concern         | userspace (`rgbkb`)                       | driver                                |
|-----------------|-------------------------------------------|---------------------------------------|
| ACPI evaluator  | `acpi_call` DKMS module + `/proc/acpi/call` | kernel WMI bus (`wmidev_block_set`)   |
| KBBR read       | `mmap(/dev/mem)` of EMEM                  | `acpi_evaluate_integer` on the named field |
| Secure Boot     | requires acpi_call signed or SB off       | works out of the box (this driver is the only unsigned thing) |
| Interface       | bash CLI (`sudo rgbkb solid red`)         | sysfs (`echo '255 0 0' > .../multi_intensity`) |
| DE integration  | none                                      | standard `/sys/class/leds/` interface |

## Build and load

```sh
make                        # builds against /lib/modules/$(uname -r)/build
sudo insmod mi-tm1806-led.ko
```

The module's `wmi:E2A89D40-...` modalias means once installed under `/lib/modules/$(uname -r)/`, it will autoload when the WMI bus enumerates the device at boot:

```sh
sudo make modules_install
sudo depmod -a
```

To remove: `sudo rmmod mi_tm1806_led`.

### DKMS (rebuild on kernel updates)

A manual `make modules_install` puts the module under `/lib/modules/$(uname -r)/updates/`. That works for the running kernel but does not follow you to a new kernel after an update — you would have to rebuild and reinstall. DKMS handles this automatically.

```sh
# one-time registration, then DKMS rebuilds on every kernel update
sudo cp -r . /usr/src/mi-tm1806-led-0.1
sudo dkms add -m mi-tm1806-led -v 0.1
sudo dkms install -m mi-tm1806-led -v 0.1
```

To remove: `sudo dkms remove -m mi-tm1806-led -v 0.1 --all && sudo rm -rf /usr/src/mi-tm1806-led-0.1`.

If `AUTOINSTALL="yes"` in `dkms.conf` and `dkms autoinstall` runs as part of your kernel-update hooks (default on Debian/Ubuntu), the module is rebuilt for each new kernel without manual action.

## Usage

```sh
# uniform red
echo '255 0 0' | sudo tee /sys/class/leds/mi_tm1806::kbd_left/multi_intensity
echo '255 0 0' | sudo tee /sys/class/leds/mi_tm1806::kbd_mid/multi_intensity
echo '255 0 0' | sudo tee /sys/class/leds/mi_tm1806::kbd_right/multi_intensity
echo '255 0 0' | sudo tee /sys/class/leds/mi_tm1806::kbd_bar/multi_intensity
for z in bar left mid right; do echo 255 | sudo tee /sys/class/leds/mi_tm1806::kbd_$z/brightness; done

# breath, fast, blue
echo 2 | sudo tee /sys/bus/wmi/devices/E2A89D40-*/effect
echo 2 | sudo tee /sys/bus/wmi/devices/E2A89D40-*/speed
echo '0 0 255' | sudo tee /sys/class/leds/mi_tm1806::kbd_*/multi_intensity
echo 255 | sudo tee /sys/class/leds/mi_tm1806::kbd_*/brightness

# colorful (red <-> cyan)
echo 4 | sudo tee /sys/bus/wmi/devices/E2A89D40-*/effect
echo 00ffff | sudo tee /sys/bus/wmi/devices/E2A89D40-*/secondary_color
echo '255 0 0' | sudo tee /sys/class/leds/mi_tm1806::kbd_*/multi_intensity
echo 255 | sudo tee /sys/class/leds/mi_tm1806::kbd_*/brightness

# dim panel to KBBR=3
echo 3 | sudo tee /sys/bus/wmi/devices/E2A89D40-*/panel_brightness
```

## Cold-boot constraint

Same as the userspace stack: if `KBBR=5` (panel power-gated) at boot, software cannot wake the panel — only the matrix-scan ISR responds to Fn+brightness. Press it once after boot, then everything works silently. Subsequent paints from the driver do not blank the panel.

A paint attempt with KBBR=5 returns `-ENXIO` (`write: No such device or address`).

## Hardware-specificity

The constants in this driver — WMI GUID, KBBR ACPI path, WSAA byte layout — were derived from the DSDT of one specific machine (TIMI TM1806, BIOS XMGCF5R0P0202). They are stable across BIOS updates on this model in our testing, but **other TIMI/Quanta laptops have different DSDTs** and are not supported. The `MODULE_DEVICE_TABLE(wmi, ...)` lists only the confirmed GUID, so on an unsupported machine the driver simply won't bind. See [`docs/DSDT-extracts.md`](../docs/DSDT-extracts.md) for the relevant AML.

## License

`SPDX-License-Identifier: MIT OR GPL-2.0` on the source. `MODULE_LICENSE("Dual MIT/GPL")` for the kernel-loaded form, which keeps a future mainline submission viable while the rest of this repo stays MIT.
