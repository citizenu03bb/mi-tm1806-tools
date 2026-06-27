/*-----------------------------------------------------------------*\
|  OpenRGBMiTM1806Plugin.cpp                                        |
\*-----------------------------------------------------------------*/

#include "OpenRGBMiTM1806Plugin.h"
#include "RGBController_MiTM1806.h"
#include "ResourceManager.h"
#include <QLabel>

OpenRGBMiTM1806Plugin::OpenRGBMiTM1806Plugin()
    : resource_manager(nullptr), controller(nullptr)
{
}

OpenRGBMiTM1806Plugin::~OpenRGBMiTM1806Plugin()
{
}

OpenRGBPluginInfo OpenRGBMiTM1806Plugin::GetPluginInfo()
{
    OpenRGBPluginInfo info;
    info.Name           = "Mi TM1806 Keyboard";
    info.Description    = "4-zone RGB backlight on the Xiaomi Mi Gaming Laptop (TIMI TM1806). "
                          "Requires the mi-tm1806-led kernel driver.";
    info.Version        = "0.1";
    info.Commit         = "";
    info.URL            = "";
    /* Location set to an invalid value so OpenRGBDialog2 skips constructing
     * a tab for this plugin -- our value is the registered RGBController,
     * which gets its own tab in the Devices list automatically; we don't
     * need a separate plugin tab. (Returning nullptr from GetWidget below
     * causes a null-deref in OpenRGBPluginContainer; an invalid Location
     * value sidesteps the whole tab-construction path. Per the comment
     * in OpenRGBPluginInterface.h, "an invalid value will prevent plugin
     * tab from being displayed".) */
    info.Location       = 0xFF;
    info.Label          = "Mi TM1806";
    info.TabIconString  = "";
    return info;
}

unsigned int OpenRGBMiTM1806Plugin::GetPluginAPIVersion()
{
    return OPENRGB_PLUGIN_API_VERSION;
}

void OpenRGBMiTM1806Plugin::Load(bool /*dark_theme*/, ResourceManager* resource_manager_ptr)
{
    resource_manager = resource_manager_ptr;

    if(resource_manager == nullptr)
    {
        return;
    }

    if(!RGBController_MiTM1806::DeviceAvailable())
    {
        /* Kernel driver not loaded or sysfs not exposed -- silently skip */
        return;
    }

    controller = new RGBController_MiTM1806();
    resource_manager->RegisterRGBController(controller);
}

QWidget* OpenRGBMiTM1806Plugin::GetWidget()
{
    /* Defensive: still return a non-null widget in case a future host
     * revision constructs the plugin container regardless of Location. */
    return new QLabel("Mi TM1806 Keyboard plugin loaded.");
}

QMenu* OpenRGBMiTM1806Plugin::GetTrayMenu()
{
    return nullptr;
}

void OpenRGBMiTM1806Plugin::Unload()
{
    if(controller != nullptr && resource_manager != nullptr)
    {
        resource_manager->UnregisterRGBController(controller);
        delete controller;
        controller = nullptr;
    }
}
