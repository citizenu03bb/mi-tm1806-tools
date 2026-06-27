/*-----------------------------------------------------------------*\
|  OpenRGBMiTM1806Plugin.h                                          |
|                                                                   |
\*-----------------------------------------------------------------*/

#pragma once

#include <QObject>
#include <QWidget>
#include <QLabel>
#include <QComboBox>
#include <QPushButton>
#include <QDoubleSpinBox>
#include <QTimer>
#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QListWidget>
#include <QJsonObject>
#include <QJsonArray>
#include "OpenRGBPluginInterface.h"

class RGBController_MiTM1806;

class PresetWidget : public QWidget
{
    Q_OBJECT

public:
    PresetWidget();
    ~PresetWidget() override;

private slots:
    void onPlayPause();
    void onStop();
    void onPresetChanged(int index);
    void onFrameSelected(int index);
    void onDurationChanged(double val);
    void onSavePreset();
    void onTimerTick();

private:
    void scanPresets();
    void paintFrame(const QJsonObject& frame);
    void saveCurrentPreset();

    QComboBox*      preset_combo;
    QPushButton*    btn_play;
    QPushButton*    btn_stop;
    QLabel*         label_status;
    QListWidget*    frame_list;
    QDoubleSpinBox* dur_spin;
    QPushButton*    btn_save_preset;
    QWidget*        zone_previews[4];

    QList<QJsonObject>  presets;
    QStringList         preset_names;
    QTimer*             timer;
    int                 current_frame;
    bool                playing;

    static const char* const ZONE_NAMES[4];
    static const char* const ZONE_LABELS[4];
    static const char*       PRESETS_DIR;

    static bool sysfsWrite(const QString& path, const QString& value);
};

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
    PresetWidget*           widget;
};
