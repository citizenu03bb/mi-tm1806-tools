# DSDT extracts

The relevant pieces of the TM1806 DSDT (BIOS XMGCF5R0P0202, decompiled with `iasl -d /sys/firmware/acpi/tables/DSDT`). Line numbers below reference the reference DSDT.dsl this project was developed against — re-extract from your own firmware; the layout is informative but offsets will vary across BIOS revisions and TIMI models.

Re-extract (Debian/Ubuntu shown; equivalent packages exist for other distros — Fedora: `acpica-tools`, Arch: `acpica`). Note `iasl -d` writes its output (`DSDT.dsl`) into the current working directory, so `cd` first:

```
sudo apt install acpica-tools
sudo cp /sys/firmware/acpi/tables/DSDT /tmp/
cd /tmp && iasl -d DSDT
less /tmp/DSDT.dsl
```

## EMEM operation region

Declares the System Memory window the EC exposes for register access, including the `KBBR` register `rgbkb` reads via `/dev/mem` mmap.

```asl
OperationRegion (EMEM, SystemMemory, 0xFE708000, 0x0BFF)
Field (EMEM, ByteAcc, NoLock, Preserve)
{
    Offset (0x300),
    F1SP,   16,
    F2SP,   16,
    Offset (0x305),
    TMSW,   8,
    Offset (0x308),
        ,   1,
    VIUF,   1,
    Offset (0x30C),
    PRLL,   8,
    KBBR,   8,    // <-- keyboard backlight brightness register
    KBIT,   16,
    ...
}
```

`KBBR` is at byte offset `0x30D` within the region — i.e. `0xFE708000 + 0x30D`. Values: 0 = max, 5 = off (panel powered down).

## MIAP device + buffer fields

The WMI device the WSAA method lives under. Defines `BUFF` (32-byte input) and `BUFR` (32-byte output) with named bit-fields the AML uses to read out specific values.

```asl
Device (MIAP)
{
    Name (_HID, "PNP0C14")    // Windows Management Instrumentation Device
    Name (_UID, "0x2")
    Name (BUFF, Buffer (0x20) {...})
    CreateField (BUFF, 0x00, 0x10, DAT0)   // bytes 0..1  (opcode prefix, e.g. FB00)
    CreateField (BUFF, 0x10, 0x10, DAT1)   // bytes 2..3  (subcommand, e.g. 0100)
    CreateField (BUFF, 0x20, 0x20, DAT2)   // bytes 4..7
    CreateField (BUFF, 0x20, 0x08, DT2A)   //   byte 4   (LEDZ idx for SetColour)
    CreateField (BUFF, 0x28, 0x08, DT2B)   //   byte 5   (LCAM commit value for SetColour)
    CreateField (BUFF, 0x40, 0x20, DAT3)   // bytes 8..11
    CreateField (BUFF, 0x40, 0x08, DT3A)   //   byte 8   (LETY for SetLightEffect; R for SetColour)
    CreateField (BUFF, 0x48, 0x08, DT3B)   //   byte 9   (LSPD for SetLightEffect; G for SetColour)
    CreateField (BUFF, 0x50, 0x08, DT3C)   //   byte 10  (LEBR for SetLightEffect; B for SetColour)
    ...
    Name (EVBF, Buffer (0x20) {...})        // event buffer for _WED
    CreateField (EVBF, 0x00, 0x10, EVT0)    // group code (0x0100=Fn-bri, 0x0200=M-key, 0x0300=power)
    CreateField (EVBF, 0x10, 0x10, EVT1)    // per-event payload (M-key code, brightness level, ...)
    CreateField (EVBF, 0x20, 0x10, EVT2)    // optional secondary payload
}
```

## WSAA method (color/effect surface)

Reads the 32-byte buffer in `Arg1` into `BUFF`, then dispatches on the opcode prefix `GWF0` and subcommand `GWF1`:

```asl
Method (WSAA, 2, Serialized)
{
    BUFF = Arg1
    GWF0 = DAT0    // opcode (0xFA00 = read, 0xFB00 = write)
    GWF1 = DAT1    // subcommand
    GWF2 = DAT2    // typically zone or LEDZ
    GWF3 = DAT3    // unused for most subcommands

    If ((GWF0 == 0xFA00))                    // === READ ===
    {
        If ((GWF1 == 0x0100))                // GetLedStatus
        {
            ^^PCI0.LPCB.EC0.LEDZ = GWF2     //   side-effect: writes LEDZ
            Sleep (0x3C)
            RT3A = ^^PCI0.LPCB.EC0.LETY     //   read effect type
            RT3B = ^^PCI0.LPCB.EC0.LSPD     //   read speed
            RT3C = ^^PCI0.LPCB.EC0.LEBR     //   read brightness sentinel
            ^^PCI0.LPCB.EC0.LCAM = DT3B     //   side-effect: writes LCAM (commit)
            Switch (DT3A) { ... }            //   selects which C-reg pair to return in RT4/RT5
        }
        ...
    }
    ElseIf ((GWF0 == 0xFB00))                // === WRITE ===
    {
        If ((GWF1 == 0x0100))                // SetLightEffect
        {
            ^^PCI0.LPCB.EC0.LETY = DT3A     //   effect type (1=static, 2=breath, 3=wave, 4=colorful)
            ^^PCI0.LPCB.EC0.LSPD = DT3B     //   speed (0..2)
            ^^PCI0.LPCB.EC0.LEBR = DT3C     //   brightness sentinel — must equal current KBBR
            ^^PCI0.LPCB.EC0.LEDZ = GWF2     //   target zone (4..7 = keyboard zones)
            Sleep (0x3C)
            // NOTE: AML reads NO color bytes from BUFF here. Painter consumes
            // C-registers via internal EC mechanism, not from this buffer.
        }
        ElseIf ((GWF1 == 0x0101))            // SetColour (stage one C-register)
        {
            ^^PCI0.LPCB.EC0.LCAM = DT2B     //   commit value
            Switch (DT2A)                    //   1..8 -> C0Z..C7Z
            {
                Case (One) { C0ZR = DT3A; C0ZG = DT3B; C0ZB = DT3C }
                Case (0x02) { C1ZR = DT3A; C1ZG = DT3B; C1ZB = DT3C }
                ...
                Case (0x08) { C7ZR = DT3A; C7ZG = DT3B; C7ZB = DT3C }
            }
        }
        ElseIf ((GWF1 == 0x0400))            // KeyboardBackLight master
        {
            ^^PCI0.LPCB.EC0.KBBL = DT3A     //   master backlight on/off
            ^^PCI0.LPCB.EC0.KBIT = DAT3     //   intensity bitmap (0xFF safe; 0 leaves the EC in
                                            //   a state where Fn+brightness no longer re-enables
                                            //   the panel until suspend/resume or reboot)
        }
    }
}
```

The relevant takeaway from the SetLightEffect branch: **only LETY/LSPD/LEBR/LEDZ are touched**. There's no per-effect color parameter in the buffer — animated modes therefore can't carry a fresh color, which is why the canonical sequence is "static prepass → animation switch."

## Macro-key _Q-handlers

The five M-keys are mapped via EC Query handlers. Each writes a per-key code into `EVBF`'s `EVT1` field, sets `EVT0` = `0x0200` (M-key group), and notifies MIAP with `0x80`:

```asl
Method (_Q61) { MIAP.EVT0 = 0x0200; MIAP.EVT1 = 0x01; Notify (MIAP, 0x80) }   // M1 press
Method (_Q62) { MIAP.EVT0 = 0x0200; MIAP.EVT1 = 0x02; Notify (MIAP, 0x80) }   // M2 press
Method (_Q63) { MIAP.EVT0 = 0x0200; MIAP.EVT1 = 0x03; Notify (MIAP, 0x80) }   // M3 press
Method (_Q64) { MIAP.EVT0 = 0x0200; MIAP.EVT1 = 0x04; Notify (MIAP, 0x80) }   // M4 press
Method (_Q65) { MIAP.EVT0 = 0x0200; MIAP.EVT1 = 0x05; Notify (MIAP, 0x80) }   // M5 press

Method (_Q71) { MIAP.EVT0 = 0x0200; MIAP.EVT1 = 0x06; Notify (MIAP, 0x80) }   // M1 release
Method (_Q72) { MIAP.EVT0 = 0x0200; MIAP.EVT1 = 0x07; Notify (MIAP, 0x80) }   // M2 release
Method (_Q73) { MIAP.EVT0 = 0x0200; MIAP.EVT1 = 0x08; Notify (MIAP, 0x80) }   // M3 release
Method (_Q74) { MIAP.EVT0 = 0x0200; MIAP.EVT1 = 0x09; Notify (MIAP, 0x80) }   // M4 release
Method (_Q75) { MIAP.EVT0 = 0x0200; MIAP.EVT1 = 0x0A; Notify (MIAP, 0x80) }   // M5 release
```

Fan key has its own group (notifies WMID directly, no MIAP route):

```asl
Method (_Q66)
{
    If ((FANM == One))   { Notify (WMID, 0xA2) }   // fan mode A
    Else                 { Notify (WMID, 0xA9) }   // fan mode B
}
```

Fn+brightness is in `_Q6A`, which sets `EVT0 = 0x0100` (different group code, same notify 0x80) and additionally fires per-level WMID notifies (0x50/0x52/0x54/0x56/0x58/0x5A). The EVT0 difference is what lets the daemon discriminate Fn+brightness from M1–M5:

```asl
Method (_Q6A, 0, Serialized)
{
    MIAP.EVT0 = 0x0100
    MIAP.EVT1 = KBBR
    Notify (MIAP, 0x80)
    Switch (ToInteger (KBBR))
    {
        Case (0x05) { Notify (WMID, 0x50) }
        Case (0x04) { Notify (WMID, 0x52) }
        ... etc
    }
}
```

## Reading the EVBF payload from userspace

The kernel's WMI bus delivers only `(GUID, notify, data=0)` to acpi_listen for unbound GUIDs — the EventDetail buffer is not surfaced. To read it, call `\_SB_.MIAP._WED(0x80)` directly via `acpi_call`:

```sh
echo '\_SB_.MIAP._WED 0x80' > /proc/acpi/call
tr -d '\0' < /proc/acpi/call
```

`acpi_call` returns the buffer as an ASCII string of comma-separated hex bytes (e.g. `{0x00, 0x02, 0x01, 0x00, ...}`), terminated by a NUL byte that `tr -d '\0'` strips. `daemon.py:dispatch_miap` parses this format on every `B74AF83F` notify `0x80` event.
