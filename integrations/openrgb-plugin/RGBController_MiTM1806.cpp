/*-----------------------------------------------------------------*\
|  RGBController_MiTM1806.cpp                                       |
\*-----------------------------------------------------------------*/

#include "RGBController_MiTM1806.h"
#include <cstdio>
#include <fstream>
#include <sys/stat.h>

/*---------------------------------------------------------------------*\
| Sysfs paths exposed by the mi-tm1806-led kernel module                |
\*---------------------------------------------------------------------*/
static const char* const LED_PATH_FMT  = "/sys/class/leds/mi_tm1806::kbd_%s";
static const char* const WMI_DEV_PATH  =
    "/sys/bus/wmi/devices/E2A89D40-784F-4E91-BE22-AE373CDEA97A";

static const char* const ZONE_NAMES[] = { "bar", "left", "mid", "right" };
static const unsigned int NUM_ZONES   = 4;

/*---------------------------------------------------------------------*\
| Mode IDs map directly onto LETY values in the firmware (1..4). We use |
| 0xFFFF for "Direct" since OpenRGB convention reserves it for direct.  |
\*---------------------------------------------------------------------*/
#define MI_MODE_DIRECT      0xFFFF
#define MI_MODE_STATIC      1
#define MI_MODE_BREATH      2
#define MI_MODE_WAVE        3
#define MI_MODE_COLORFUL    4

#define MI_LSPD_MIN         0
#define MI_LSPD_MAX         2
#define MI_LSPD_DEFAULT     2

/*---------------------------------------------------------------------*\
| Helpers: write one line into a sysfs file. Failures are silent --     |
| missing files / permission denials should not crash the host process. |
\*---------------------------------------------------------------------*/
static bool sysfs_write(const std::string& path, const std::string& value)
{
    std::ofstream f(path);
    if(!f.is_open())
    {
        return false;
    }
    f << value;
    return f.good();
}

static std::string led_path(unsigned int zone_idx, const char* attr)
{
    char buf[256];
    std::snprintf(buf, sizeof(buf), "%s/%s",
                  (std::string("/sys/class/leds/mi_tm1806::kbd_") + ZONE_NAMES[zone_idx]).c_str(),
                  attr);
    return std::string(buf);
}

/*---------------------------------------------------------------------*\
| DeviceAvailable - probe before we try to register a controller        |
\*---------------------------------------------------------------------*/
bool RGBController_MiTM1806::DeviceAvailable()
{
    char path[256];
    std::snprintf(path, sizeof(path), LED_PATH_FMT, "bar");

    struct stat st;
    return stat(path, &st) == 0;
}

/*---------------------------------------------------------------------*\
| Constructor                                                           |
\*---------------------------------------------------------------------*/
RGBController_MiTM1806::RGBController_MiTM1806()
{
    name        = "Xiaomi Mi Gaming Laptop Keyboard";
    vendor      = "TIMI";
    type        = DEVICE_TYPE_KEYBOARD;
    description = "Mi TM1806 4-zone keyboard backlight (mi-tm1806-led kernel driver)";
    version     = "0.1";
    location    = WMI_DEV_PATH;

    /*-----------------------------------------------------------------*\
    | Direct - per-zone color, no animation. Maps to LETY=1 internally  |
    | but uses the OpenRGB direct-mode convention (0xFFFF).             |
    \*-----------------------------------------------------------------*/
    mode Direct;
    Direct.name             = "Direct";
    Direct.value            = MI_MODE_DIRECT;
    Direct.flags            = MODE_FLAG_HAS_PER_LED_COLOR;
    Direct.color_mode       = MODE_COLORS_PER_LED;
    modes.push_back(Direct);

    /*-----------------------------------------------------------------*\
    | Static - same as Direct, but explicit                              |
    \*-----------------------------------------------------------------*/
    mode Static;
    Static.name             = "Static";
    Static.value            = MI_MODE_STATIC;
    Static.flags            = MODE_FLAG_HAS_PER_LED_COLOR;
    Static.color_mode       = MODE_COLORS_PER_LED;
    modes.push_back(Static);

    /*-----------------------------------------------------------------*\
    | Breath - each zone breathes its own SRAM color                    |
    \*-----------------------------------------------------------------*/
    mode Breath;
    Breath.name             = "Breath";
    Breath.value            = MI_MODE_BREATH;
    Breath.flags            = MODE_FLAG_HAS_PER_LED_COLOR | MODE_FLAG_HAS_SPEED;
    Breath.color_mode       = MODE_COLORS_PER_LED;
    Breath.speed_min        = MI_LSPD_MIN;
    Breath.speed_max        = MI_LSPD_MAX;
    Breath.speed            = MI_LSPD_DEFAULT;
    modes.push_back(Breath);

    /*-----------------------------------------------------------------*\
    | Wave - each zone shows its own color, animated                    |
    \*-----------------------------------------------------------------*/
    mode Wave;
    Wave.name               = "Wave";
    Wave.value              = MI_MODE_WAVE;
    Wave.flags              = MODE_FLAG_HAS_PER_LED_COLOR | MODE_FLAG_HAS_SPEED;
    Wave.color_mode         = MODE_COLORS_PER_LED;
    Wave.speed_min          = MI_LSPD_MIN;
    Wave.speed_max          = MI_LSPD_MAX;
    Wave.speed              = MI_LSPD_DEFAULT;
    modes.push_back(Wave);

    /*-----------------------------------------------------------------*\
    | Colorful - alternates between two mode-specific colors            |
    | (firmware reads C0Z and C1Z; we drive secondary_color sysfs)      |
    \*-----------------------------------------------------------------*/
    mode Colorful;
    Colorful.name           = "Colorful";
    Colorful.value          = MI_MODE_COLORFUL;
    Colorful.flags          = MODE_FLAG_HAS_MODE_SPECIFIC_COLOR | MODE_FLAG_HAS_SPEED;
    Colorful.color_mode     = MODE_COLORS_MODE_SPECIFIC;
    Colorful.colors_min     = 2;
    Colorful.colors_max     = 2;
    Colorful.colors.resize(2);
    Colorful.speed_min      = MI_LSPD_MIN;
    Colorful.speed_max      = MI_LSPD_MAX;
    Colorful.speed          = MI_LSPD_DEFAULT;
    modes.push_back(Colorful);

    SetupZones();
}

RGBController_MiTM1806::~RGBController_MiTM1806()
{
}

/*---------------------------------------------------------------------*\
| SetupZones - 4 single-LED zones (one per LEDZ in the firmware)        |
\*---------------------------------------------------------------------*/
void RGBController_MiTM1806::SetupZones()
{
    static const char* const ZONE_DISPLAY_NAMES[] =
    {
        "Hotkey Bar", "Keyboard Left", "Keyboard Middle", "Keyboard Right"
    };

    for(unsigned int z = 0; z < NUM_ZONES; z++)
    {
        zone new_zone;
        new_zone.name           = ZONE_DISPLAY_NAMES[z];
        new_zone.type           = ZONE_TYPE_SINGLE;
        new_zone.leds_min       = 1;
        new_zone.leds_max       = 1;
        new_zone.leds_count     = 1;
        new_zone.matrix_map     = nullptr;
        zones.push_back(new_zone);

        led new_led;
        new_led.name            = ZONE_DISPLAY_NAMES[z];
        new_led.value           = z;
        leds.push_back(new_led);
    }

    SetupColors();
}

void RGBController_MiTM1806::ResizeZone(int /*zone*/, int /*new_size*/)
{
    /* zones are fixed-size on this hardware */
}

/*---------------------------------------------------------------------*\
| Sysfs writers                                                         |
\*---------------------------------------------------------------------*/
void RGBController_MiTM1806::WriteZoneColor(unsigned int zone_idx, RGBColor color)
{
    if(zone_idx >= NUM_ZONES)
    {
        return;
    }
    char rgb[32];
    std::snprintf(rgb, sizeof(rgb), "%u %u %u",
                  RGBGetRValue(color), RGBGetGValue(color), RGBGetBValue(color));
    sysfs_write(led_path(zone_idx, "multi_intensity"), rgb);
    sysfs_write(led_path(zone_idx, "brightness"),      "255");
}

void RGBController_MiTM1806::WriteEffect(unsigned int lety_value)
{
    char buf[8];
    std::snprintf(buf, sizeof(buf), "%u", lety_value);
    sysfs_write(std::string(WMI_DEV_PATH) + "/effect", buf);
}

void RGBController_MiTM1806::WriteSpeed(unsigned int lspd_value)
{
    char buf[8];
    std::snprintf(buf, sizeof(buf), "%u", lspd_value);
    sysfs_write(std::string(WMI_DEV_PATH) + "/speed", buf);
}

void RGBController_MiTM1806::WriteSecondaryColor(RGBColor color)
{
    char hex[8];
    std::snprintf(hex, sizeof(hex), "%02x%02x%02x",
                  RGBGetRValue(color), RGBGetGValue(color), RGBGetBValue(color));
    sysfs_write(std::string(WMI_DEV_PATH) + "/secondary_color", hex);
}

/*---------------------------------------------------------------------*\
| DeviceUpdateLEDs - paint every zone with its current color.           |
| The kernel driver does the LEBR=current_KBBR Fn-bypass internally.    |
\*---------------------------------------------------------------------*/
void RGBController_MiTM1806::DeviceUpdateLEDs()
{
    for(unsigned int z = 0; z < NUM_ZONES; z++)
    {
        if(z < colors.size())
        {
            WriteZoneColor(z, colors[z]);
        }
    }
}

void RGBController_MiTM1806::UpdateZoneLEDs(int zone_idx)
{
    if(zone_idx >= 0 && (unsigned int)zone_idx < NUM_ZONES
       && (unsigned int)zone_idx < zones.size()
       && zones[zone_idx].colors != nullptr)
    {
        WriteZoneColor((unsigned int)zone_idx, zones[zone_idx].colors[0]);
    }
}

void RGBController_MiTM1806::UpdateSingleLED(int led_idx)
{
    if(led_idx >= 0 && (unsigned int)led_idx < NUM_ZONES
       && (unsigned int)led_idx < colors.size())
    {
        WriteZoneColor((unsigned int)led_idx, colors[led_idx]);
    }
}

/*---------------------------------------------------------------------*\
| DeviceUpdateMode - apply effect/speed/secondary_color to the kernel   |
| driver, then repaint all zones so the new mode picks up current SRAM  |
\*---------------------------------------------------------------------*/
void RGBController_MiTM1806::DeviceUpdateMode()
{
    if(active_mode < 0 || (unsigned int)active_mode >= modes.size())
    {
        return;
    }

    unsigned int mode_value = modes[active_mode].value;
    unsigned int lety = (mode_value == MI_MODE_DIRECT) ? MI_MODE_STATIC : mode_value;

    WriteEffect(lety);

    if(modes[active_mode].flags & MODE_FLAG_HAS_SPEED)
    {
        WriteSpeed((unsigned int)modes[active_mode].speed);
    }

    if(modes[active_mode].color_mode == MODE_COLORS_MODE_SPECIFIC
       && modes[active_mode].colors.size() >= 2)
    {
        WriteSecondaryColor(modes[active_mode].colors[1]);
        for(unsigned int z = 0; z < NUM_ZONES; z++)
        {
            WriteZoneColor(z, modes[active_mode].colors[0]);
        }
    }
    else
    {
        DeviceUpdateLEDs();
    }
}
