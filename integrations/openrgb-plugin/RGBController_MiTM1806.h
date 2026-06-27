/*-----------------------------------------------------------------*\
|  RGBController_MiTM1806.h                                         |
|                                                                   |
|  4-zone RGB keyboard backlight on the Xiaomi Mi Gaming Laptop     |
|  (TIMI TM1806). Talks to the in-kernel mi-tm1806-led driver       |
|  through its sysfs interface. No hidraw, no I2C.                  |
\*-----------------------------------------------------------------*/

#pragma once

#include "RGBController.h"

class RGBController_MiTM1806 : public RGBController
{
public:
    RGBController_MiTM1806();
    ~RGBController_MiTM1806();

    void        SetupZones();
    void        ResizeZone(int zone, int new_size);

    void        DeviceUpdateLEDs();
    void        UpdateZoneLEDs(int zone);
    void        UpdateSingleLED(int led);

    void        DeviceUpdateMode();

    /*-------------------------------------------------------------*\
    | Static helper: returns true if the kernel driver is loaded    |
    | and the bar zone's sysfs node exists. Used by the plugin's    |
    | Load() to decide whether to register the controller.          |
    \*-------------------------------------------------------------*/
    static bool DeviceAvailable();

private:
    void        WriteZoneColor(unsigned int zone_idx, RGBColor color);
    void        WriteEffect(unsigned int lety_value);
    void        WriteSpeed(unsigned int lspd_value);
    void        WriteSecondaryColor(RGBColor color);
    void        WriteCommit();
};
