# driver/

Out-of-tree kernel module for the 4-zone keyboard backlight on the TM1806. Replaces the userspace `rgbkb/` stack with a kernel-side LED class driver.

See the [top-level README](../README.md) for hardware context and the [`rgbkb/` README](../rgbkb/README.md) for the buffer-format and protocol notes that this driver implements.

## What it does

Binds to the Quanta WMI device with GUID `E2A89D40-784F-4E91-BE22-AE373CDEA97A` and exposes:

- four multicolor LED classdevs at `/sys/class/leds/mi_tm1806::kbd_{bar,left,mid,right}/`
- five global attributes on the WMI device at `/sys/bus/wmi/devices/E2A89D40-.../`:
  - `effect` — `1`=static, `2`=breath, `3`=wave, `4`=colorful
  - `speed` — `0`..`2` (0=slow, 2=fast)
  - `secondary_color` — `rrggbb` hex; second color used in `effect=4`
  - `panel_brightness` — `0`..`5` (0=max, 5=off; KBBR sentinel)
  - `commit` — write `1` to batch-paint all zones (see "Store-and-commit model" below)

Each paint goes through the LEBR-bypass: KBBR is read from `\_SB_.PCI0.LPCB.EC0.KBBR` via `acpi_evaluate_integer`, then passed as LEBR in the `FB00/0100` LightEffect packet so the firmware painter consumes the C-registers without blanking the panel.

## Store-and-commit model

This driver uses a **store-and-commit** brightness model to eliminate flicker.

Writing to `multi_intensity` or `brightness` on any zone **only stores the colour in kernel memory** — no WSAA calls are issued to the EC, and the keyboard does not change. To push all pending colours to the hardware, write `1` to:

```
/sys/bus/wmi/devices/E2A89D40-.../commit
```

This batch-paints all 4 zones in a single atomic cycle:

1. Read KBBR once
2. Stage C0Z (and C1Z if `effect=4`) once — if all zones share the same colour, this is the only C-reg stage; otherwise it repeats per zone
3. Fire LightEffect triggers for every zone (static prepass + mode switch if animated)

Because the whole commit runs under one mutex with no userspace round-trips between zone paints, the zones update **virtually simultaneously** — no sequential wipe, no flicker.

### Workflow examples

```sh
# 1. Store all zone colours (no WSAA, no visual change)
echo '255 0 0' > /sys/class/leds/mi_tm1806::kbd_bar/multi_intensity
echo '255 0 0' > /sys/class/leds/mi_tm1806::kbd_left/multi_intensity
echo '255 0 0' > /sys/class/leds/mi_tm1806::kbd_mid/multi_intensity
echo '255 0 0' > /sys/class/leds/mi_tm1806::kbd_right/multi_intensity

# 2. Configure effect / speed / secondary colour (stored, no paint)
echo 2 > /sys/bus/wmi/devices/E2A89D40-*/effect
echo 1 > /sys/bus/wmi/devices/E2A89D40-*/speed

# 3. Commit everything atomically → one batch paint, zero flicker
echo 1 > /sys/bus/wmi/devices/E2A89D40-*/commit
```

```sh
# One-liner: pipe zone colours, then commit
echo '0 0 255' | sudo tee /sys/class/leds/mi_tm1806::kbd_*/multi_intensity
echo 1 | sudo tee /sys/bus/wmi/devices/E2A89D40-*/commit
```

> **Why this change?** The original approach painted each zone immediately on write, causing 4 sequential WSAA round-trips (stage C0Z → trigger → stage C0Z → trigger …). With the EC processing each packet synchronously, the panel updated zone-by-zone, producing a visible wipe. The store-and-commit model replaces 4×n calls interleaved with userspace latency with a single tight loop inside the kernel.
>
> This is a **breaking change**: existing scripts that wrote to `multi_intensity` and expected instant visual feedback must now add a final `echo 1 > …/commit`.

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

### Secure Boot Module Signing
If you have Secure Boot enabled, loading the unsigned `mi-tm1806-led.ko` module will fail with a `Required key not available` (or `Permission denied`) error. To load it, you must sign it with a key trusted by the system:

1. **Generate a MOK (Machine Owner Key) pair**:
   ```sh
   openssl req -new -x509 -newkey rsa:2048 -keyout MOK.key -out MOK.der -nodes -days 36500 -subj "/CN=TIMI TM1806 Driver Owner/"
   ```
2. **Import the public key into the system MOK list**:
   ```sh
   sudo mokutil --import MOK.der
   ```
   *Note: This will prompt you to set a temporary password. Reboot the laptop; the BIOS/Shim MOK manager screen will appear. Select **Enroll MOK**, confirm, and enter the password you set.*
3. **Sign the module**:
   ```sh
   sudo /lib/modules/$(uname -r)/build/scripts/sign-file sha256 ./MOK.key ./MOK.der mi-tm1806-led.ko
   ```
4. **Load the module**:
   ```sh
   sudo insmod mi-tm1806-led.ko
   ```
   *(DKMS can also be configured to sign modules automatically by referencing `/etc/dkms/framework.conf` or setting `sign_tool` / `mok_signing_key` options, depending on your Linux distribution's DKMS configuration.)*

### DKMS (rebuild on kernel updates)

A manual `make modules_install` puts the module under `/lib/modules/$(uname -r)/updates/`. That works for the running kernel but does not follow you to a new kernel after an update — you would have to rebuild and reinstall. DKMS handles this automatically.

```sh
# one-time registration, then DKMS rebuilds on every kernel update
sudo ../scripts/install-dkms.sh
```

To remove: `sudo ../scripts/uninstall-dkms.sh`.

If `AUTOINSTALL="yes"` in `dkms.conf` and `dkms autoinstall` runs as part of your kernel-update hooks (default on Debian/Ubuntu), the module is rebuilt for each new kernel without manual action.

## Usage (store-and-commit)

**Every example below must end with `echo 1 > …/commit`** to push colours to the EC. Without the commit, writes to `multi_intensity` / `brightness` are silently stored but have no hardware effect.

```sh
# uniform red
for z in bar left mid right; do
  echo '255 0 0' | sudo tee /sys/class/leds/mi_tm1806::kbd_$z/multi_intensity
done
echo 1 | sudo tee /sys/bus/wmi/devices/E2A89D40-*/commit

# breath, fast, blue
echo 2 | sudo tee /sys/bus/wmi/devices/E2A89D40-*/effect
echo 1 | sudo tee /sys/bus/wmi/devices/E2A89D40-*/speed
echo '0 0 255' | sudo tee /sys/class/leds/mi_tm1806::kbd_*/multi_intensity
echo 1 | sudo tee /sys/bus/wmi/devices/E2A89D40-*/commit

# colorful (red <-> cyan) with per-zone colours
echo 4 | sudo tee /sys/bus/wmi/devices/E2A89D40-*/effect
echo 00ffff | sudo tee /sys/bus/wmi/devices/E2A89D40-*/secondary_color
echo '255 0 0' | sudo tee /sys/class/leds/mi_tm1806::kbd_*/multi_intensity
echo 255 | sudo tee /sys/class/leds/mi_tm1806::kbd_*/brightness
echo 1 | sudo tee /sys/bus/wmi/devices/E2A89D40-*/commit

# dim panel to KBBR=3 (panel_brightness still takes effect immediately)
echo 3 | sudo tee /sys/bus/wmi/devices/E2A89D40-*/panel_brightness
```

## Cold-boot constraint

Same as the userspace stack: if `KBBR=5` (panel power-gated) at boot, software cannot wake the panel — only the matrix-scan ISR responds to Fn+brightness. Press it once after boot, then everything works silently. Subsequent paints from the driver do not blank the panel.

A paint attempt with KBBR=5 returns `-ENXIO` (`write: No such device or address`).

## Hardware-specificity

The constants in this driver — WMI GUID, KBBR ACPI path, WSAA byte layout — were derived from the DSDT of one specific machine (TIMI TM1806, BIOS XMGCF5R0P0202). They are stable across BIOS updates on this model in our testing, but **other TIMI/Quanta laptops have different DSDTs** and are not supported. The `MODULE_DEVICE_TABLE(wmi, ...)` lists only the confirmed GUID, so on an unsupported machine the driver simply won't bind. See [`docs/DSDT-extracts.md`](../docs/DSDT-extracts.md) for the relevant AML.

## License

`SPDX-License-Identifier: MIT OR GPL-2.0` on the source. `MODULE_LICENSE("Dual MIT/GPL")` for the kernel-loaded form, which keeps a future mainline submission viable while the rest of this repo stays MIT.
