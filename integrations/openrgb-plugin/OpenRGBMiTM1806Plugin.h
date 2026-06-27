/*-----------------------------------------------------------------*\
|  OpenRGBMiTM1806Plugin.h                                          |
|                                                                   |
|  OpenRGB plugin that registers the Xiaomi Mi Gaming Laptop's      |
|  4-zone keyboard as an RGBController by talking to the            |
|  mi-tm1806-led kernel driver via /sys/class/leds.                 |
\*-----------------------------------------------------------------*/

#pragma once

#include <QObject>
#include "OpenRGBPluginInterface.h"

class RGBController_MiTM1806;

class OpenRGBMiTM1806Plugin : public QObject, public OpenRGBPluginInterface
{
    Q_OBJECT
    Q_PLUGIN_METADATA(IID OpenRGBPluginInterface_IID)
    Q_INTERFACES(OpenRGBPluginInterface)

public:
    OpenRGBMiTM1806Plugin();
    ~OpenRGBMiTM1806Plugin() override;

    OpenRGBPluginInfo   GetPluginInfo() override;
    unsigned int        GetPluginAPIVersion() override;

    void                Load(bool dark_theme, ResourceManager* resource_manager_ptr) override;
    QWidget*            GetWidget() override;
    QMenu*              GetTrayMenu() override;
    void                Unload() override;

private:
    ResourceManager*        resource_manager;
    RGBController_MiTM1806* controller;
};
