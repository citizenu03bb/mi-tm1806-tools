/*-----------------------------------------------------------------*\
|  OpenRGBMiTM1806Plugin.cpp                                        |
|                                                                   |
|  Plugin entry point + PresetWidget for browsing and playing       |
|  effect presets from effects/presets inside the OpenRGB GUI.      |
\*-----------------------------------------------------------------*/

#include "OpenRGBMiTM1806Plugin.h"
#include "RGBController_MiTM1806.h"
#include "ResourceManager.h"

#include <QDir>
#include <QFile>
#include <QProcess>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonArray>
#include <QFrame>
#include <QColor>
#include <QLabel>
#include <QFileInfo>
#include <QStyle>
#include <QTimer>
#include <QStandardPaths>
#include <cstdio>
#include <fstream>
#include <string>

/*---------------------------------------------------------------------*\
|  Constants                                                            |
\*---------------------------------------------------------------------*/
const char* const PresetWidget::ZONE_NAMES[4]  =
    { "bar", "left", "mid", "right" };
const char* const PresetWidget::ZONE_LABELS[4] =
    { "Bar\n(Hotkeys)", "Left", "Middle", "Right" };

/*---------------------------------------------------------------------*\
|  sysfs helpers                                                        |
\*---------------------------------------------------------------------*/
bool PresetWidget::sysfsWrite(const QString& path, const QString& value)
{
    std::ofstream f(path.toStdString());
    if(!f.is_open()) return false;
    f << value.toStdString();
    return f.good();
}

QString PresetWidget::presetsDir()
{
    QByteArray env = qgetenv("MI_TM1806_PRESETS_DIR");
    if(!env.isEmpty())
    {
        return QString::fromLocal8Bit(env);
    }

    QString config_home = QStandardPaths::writableLocation(QStandardPaths::ConfigLocation);
    if(config_home.isEmpty())
    {
        config_home = QDir::homePath() + "/.config";
    }
    return config_home + "/OpenRGB/plugins/presets";
}

QString PresetWidget::editorPath()
{
    QByteArray env = qgetenv("MI_TM1806_TOOLS_DIR");
    if(!env.isEmpty())
    {
        QString candidate = QString::fromLocal8Bit(env) + "/effects/editor.py";
        if(QFileInfo::exists(candidate))
        {
            return candidate;
        }
    }

    QFileInfo preset_info(presetsDir());
    QString preset_path = preset_info.isSymLink()
        ? preset_info.symLinkTarget()
        : preset_info.absoluteFilePath();
    QDir dir(preset_path);
    if(dir.dirName() == "presets" && dir.cdUp() && dir.dirName() == "effects" && dir.cdUp())
    {
        QString candidate = dir.filePath("effects/editor.py");
        if(QFileInfo::exists(candidate))
        {
            return candidate;
        }
    }
    return QString();
}

/*---------------------------------------------------------------------*\
|  Constructor                                                          |
\*---------------------------------------------------------------------*/
PresetWidget::PresetWidget()
    : timer(nullptr), current_frame(0), playing(false)
{
    QVBoxLayout* main = new QVBoxLayout(this);

    /* ── Zone colour mini-previews ── */
    QHBoxLayout* zone_row = new QHBoxLayout();
    for(int i = 0; i < 4; i++)
    {
        QFrame* box = new QFrame();
        box->setFixedSize(64, 56);
        box->setFrameStyle(QFrame::Box | QFrame::Plain);
        box->setAutoFillBackground(true);
        box->setStyleSheet("QFrame { background-color: #111; border: 2px solid #555; border-radius: 4px; }");
        zone_previews[i] = box;   /* store the QFrame, cast via parentWidget where needed */
        zone_row->addWidget(box, 0, Qt::AlignCenter);
    }
    main->addLayout(zone_row);

    /* ── Preset selector ── */
    QHBoxLayout* preset_row = new QHBoxLayout();
    preset_row->addWidget(new QLabel("Preset:"));
    preset_combo = new QComboBox();
    preset_combo->setMinimumWidth(200);
    scanPresets();
    preset_combo->setCurrentIndex(-1);
    connect(preset_combo, SIGNAL(currentIndexChanged(int)),
            this,         SLOT(onPresetChanged(int)));
    preset_row->addWidget(preset_combo);
    preset_row->addStretch();
    main->addLayout(preset_row);

    /* ── Frame list ── */
    frame_list = new QListWidget();
    frame_list->setMaximumHeight(120);
    connect(frame_list, SIGNAL(currentRowChanged(int)),
            this,       SLOT(onFrameSelected(int)));
    main->addWidget(frame_list);

    /* ── Inline duration editor ── */
    QHBoxLayout* dur_row = new QHBoxLayout();
    QLabel* dur_label = new QLabel("  Selected frame duration:");
    dur_row->addWidget(dur_label);

    dur_spin = new QDoubleSpinBox();
    dur_spin->setRange(0.01, 60.0);
    dur_spin->setSingleStep(0.05);
    dur_spin->setDecimals(2);
    dur_spin->setSuffix(" seconds");
    dur_spin->setEnabled(false);
    dur_spin->setFixedWidth(210);
    connect(dur_spin, SIGNAL(valueChanged(double)),
            this,     SLOT(onDurationChanged(double)));
    dur_row->addWidget(dur_spin);

    btn_save_preset = new QPushButton("💾 Save Preset");
    btn_save_preset->setEnabled(false);
    connect(btn_save_preset, SIGNAL(clicked()), this, SLOT(onSavePreset()));
    dur_row->addWidget(btn_save_preset);

    QPushButton* btn_editor = new QPushButton("🖉 Open Full Editor");
    connect(btn_editor, &QPushButton::clicked, [this](){
        QString editor = editorPath();
        if(editor.isEmpty())
        {
            label_status->setText("Set MI_TM1806_TOOLS_DIR to open the editor");
            return;
        }
        QProcess::startDetached("python3", {editor}, QFileInfo(editor).absolutePath());
    });
    dur_row->addWidget(btn_editor);
    dur_row->addStretch();
    main->addLayout(dur_row);

    /* ── Controls ── */
    QHBoxLayout* ctrl = new QHBoxLayout();
    btn_play = new QPushButton("▶ Play");
    btn_play->setEnabled(false);
    connect(btn_play, SIGNAL(clicked()), this, SLOT(onPlayPause()));
    ctrl->addWidget(btn_play);

    btn_stop = new QPushButton("⏹ Stop");
    btn_stop->setEnabled(false);
    connect(btn_stop, SIGNAL(clicked()), this, SLOT(onStop()));
    ctrl->addWidget(btn_stop);

    label_status = new QLabel("");
    ctrl->addWidget(label_status);
    ctrl->addStretch();
    main->addLayout(ctrl);

    main->addStretch();

    /* ── Timer ── */
    timer = new QTimer(this);
    connect(timer, SIGNAL(timeout()), this, SLOT(onTimerTick()));
}

PresetWidget::~PresetWidget() { }

/*---------------------------------------------------------------------*\
|  Preset scanning                                                     |
\*---------------------------------------------------------------------*/
void PresetWidget::scanPresets()
{
    preset_combo->clear();
    presets.clear();
    preset_names.clear();

    QDir dir(presetsDir());
    if(!dir.exists()) { /* silently skip */ return; }

    QStringList files = dir.entryList({"*.json"}, QDir::Files, QDir::Name);
    for(const QString& fname : files)
    {
        QString path = dir.absoluteFilePath(fname);
        QFile f(path);
        if(!f.open(QIODevice::ReadOnly)) continue;

        QJsonParseError err;
        QJsonDocument doc = QJsonDocument::fromJson(f.readAll(), &err);
        f.close();
        if(err.error != QJsonParseError::NoError) continue;
        if(!doc.isObject()) continue;

        QJsonObject obj = doc.object();
        if(!obj.contains("frames")) continue;
        if(!obj["frames"].isArray()) continue;
        QJsonArray frames = obj["frames"].toArray();
        if(frames.isEmpty()) continue;

        presets.append(obj);
        preset_names.append(QFileInfo(fname).completeBaseName());
        preset_combo->addItem(
            QString("%1  (%2 frames)")
                .arg(QFileInfo(fname).completeBaseName())
                .arg(frames.size()));
    }
}

/*---------------------------------------------------------------------*\
|  Slots                                                                |
\*---------------------------------------------------------------------*/
void PresetWidget::onPresetChanged(int index)
{
    bool ok = (index >= 0 && index < presets.size());
    btn_play->setEnabled(ok);
    onStop();
    if(!ok) return;

    /* Show frame preview */
    frame_list->clear();
    QJsonArray frames = presets[index]["frames"].toArray();
    for(int i = 0; i < frames.size(); i++)
    {
        QJsonObject f = frames[i].toObject();
        double dur = f["duration"].toDouble(0.5);
        QJsonArray cols = f["zones"].toArray();
        QString preview;
        for(int z = 0; z < 4 && z < cols.size(); z++)
        {
            QString c = cols[z].toString("000000");
            preview += QString("⬤") + c.left(2) + " ";
        }
        frame_list->addItem(
            QString("[%1] %2s  %3").arg(i+1, 2).arg(dur, 4, 'f', 2).arg(preview));
    }
}

void PresetWidget::onFrameSelected(int index)
{
    int pidx = preset_combo->currentIndex();
    if(pidx < 0 || pidx >= presets.size()) return;
    QJsonArray frames = presets[pidx]["frames"].toArray();
    if(index < 0 || index >= frames.size())
    {
        dur_spin->setEnabled(false);
        btn_save_preset->setEnabled(false);
        return;
    }
    dur_spin->setEnabled(true);
    btn_save_preset->setEnabled(true);
    dur_spin->blockSignals(true);
    dur_spin->setValue(frames[index].toObject()["duration"].toDouble(0.5));
    dur_spin->blockSignals(false);
}

void PresetWidget::onDurationChanged(double val)
{
    int pidx = preset_combo->currentIndex();
    int fidx = frame_list->currentRow();
    if(pidx < 0 || pidx >= presets.size()) return;

    QJsonArray frames = presets[pidx]["frames"].toArray();
    if(fidx < 0 || fidx >= frames.size()) return;

    QJsonObject f = frames[fidx].toObject();
    f["duration"] = val;
    frames[fidx] = f;
    presets[pidx]["frames"] = frames;

    /* Update the frame list entry text */
    QJsonArray cols = f["zones"].toArray();
    QString preview;
    for(int z = 0; z < 4 && z < cols.size(); z++)
        preview += QString("⬤") + cols[z].toString("000000").left(2) + " ";
    frame_list->blockSignals(true);
    frame_list->item(fidx)->setText(
        QString("[%1] %2s  %3").arg(fidx+1, 2).arg(val, 5, 'f', 2).arg(preview));
    frame_list->blockSignals(false);
}

void PresetWidget::onSavePreset()
{
    saveCurrentPreset();
}

void PresetWidget::saveCurrentPreset()
{
    int idx = preset_combo->currentIndex();
    if(idx < 0 || idx >= presets.size() || idx >= preset_names.size()) return;

    QString name = preset_names[idx];
    QString path = presetsDir() + "/" + name + ".json";

    QJsonObject obj = presets[idx];
    QJsonDocument doc(obj);

    QFile f(path);
    if(!f.open(QIODevice::WriteOnly))
    {
        label_status->setText("❌ Cannot save " + name);
        return;
    }
    f.write(doc.toJson(QJsonDocument::Indented));
    f.close();

    label_status->setText("✅ Saved " + name);
    QTimer::singleShot(2000, this, [this](){
        if(label_status->text() == "✅ Saved " + preset_names[preset_combo->currentIndex()])
            label_status->setText("");
    });
}

void PresetWidget::onPlayPause()
{
    int idx = preset_combo->currentIndex();
    if(idx < 0 || idx >= presets.size()) return;

    if(playing)
    {
        timer->stop();
        playing = false;
        btn_play->setText("▶ Play");
        label_status->setText("Paused");
        return;
    }

    playing = true;
    current_frame = 0;
    btn_play->setText("⏸ Pause");
    btn_stop->setEnabled(true);
    label_status->setText("Playing...");

    /* Paint first frame immediately */
    onTimerTick();

    /* Start timer for subsequent frames */
    QJsonObject frame = presets[idx]["frames"].toArray()[0].toObject();
    int ms = (int)(frame["duration"].toDouble(0.5) * 1000);
    timer->start(ms > 30 ? ms : 30);
}

void PresetWidget::onStop()
{
    timer->stop();
    playing = false;
    btn_play->setText("▶ Play");
    btn_stop->setEnabled(false);
    label_status->setText("Stopped");

    /* Clear zone previews to dark */
    for(int i = 0; i < 4; i++)
    {
        QFrame* preview = qobject_cast<QFrame*>(zone_previews[i]);
        if(preview)
            preview->setStyleSheet("QFrame { background-color: #111; border: 2px solid #555; border-radius: 4px; }");
    }
    frame_list->clearSelection();
}

void PresetWidget::onTimerTick()
{
    int idx = preset_combo->currentIndex();
    if(idx < 0 || idx >= presets.size()) { onStop(); return; }

    QJsonArray frames = presets[idx]["frames"].toArray();
    if(frames.isEmpty()) { onStop(); return; }

    /* Paint current frame */
    QJsonObject frame = frames[current_frame].toObject();
    if(!paintFrame(frame))
    {
        timer->stop();
        playing = false;
        btn_play->setText("▶ Play");
        btn_stop->setEnabled(false);
        return;
    }

    /* Debug: show zone colours in status bar */
    QJsonArray cols = frame["zones"].toArray();
    QString dbg;
    for(int z = 0; z < 4 && z < cols.size(); z++)
        dbg += cols[z].toString("000000") + "  ";
    label_status->setText(QString("Playing  frame %1/%2   [%3]")
        .arg(current_frame+1).arg(frames.size()).arg(dbg.trimmed()));

    /* Highlight in list */
    frame_list->blockSignals(true);
    frame_list->setCurrentRow(current_frame);
    frame_list->blockSignals(false);

    /* Advance */
    current_frame = (current_frame + 1) % frames.size();

    /* Set timer for next frame's duration */
    QJsonObject next = frames[current_frame].toObject();
    int ms = (int)(next["duration"].toDouble(0.5) * 1000);
    timer->start(ms > 30 ? ms : 30);
}

/*---------------------------------------------------------------------*\
|  Hardware paint                                                        |
\*---------------------------------------------------------------------*/
bool PresetWidget::paintFrame(const QJsonObject& frame)
{
    QJsonArray colours = frame["zones"].toArray();
    QString effect = presets[preset_combo->currentIndex()]["effect"].toString("static");
    if(effect.isEmpty()) effect = "static";
    bool ok = true;

    /* Build sysfs paths */
    char led_path[128], wmi_effect[128], wmi_speed[128], wmi_commit[128];
    const char* wmi_base = "/sys/bus/wmi/devices/E2A89D40-784F-4E91-BE22-AE373CDEA97A";

    for(int z = 0; z < 4 && z < colours.size(); z++)
    {
        QString raw = colours[z].toString("000000");
        /* Write multi_intensity */
        int r, g, b;
        sscanf(raw.toStdString().c_str(), "%2x%2x%2x", &r, &g, &b);
        char rgb[32];
        std::snprintf(rgb, sizeof(rgb), "%d %d %d", r, g, b);

        std::snprintf(led_path, sizeof(led_path),
                      "/sys/class/leds/mi_tm1806::kbd_%s/multi_intensity",
                      ZONE_NAMES[z]);
        ok = sysfsWrite(led_path, rgb) && ok;

        /* Also write brightness=255 so scaling doesn't zero us out */
        std::snprintf(led_path, sizeof(led_path),
                      "/sys/class/leds/mi_tm1806::kbd_%s/brightness", ZONE_NAMES[z]);
        ok = sysfsWrite(led_path, "255") && ok;

        /* Update zone preview colour */
        QFrame* preview = qobject_cast<QFrame*>(zone_previews[z]);
        if(preview)
            preview->setStyleSheet(
                QString("QFrame { background-color: #%1; border: 2px solid #888; border-radius: 4px; }")
                    .arg(raw));
    }

    /* Write effect + speed */
    std::snprintf(wmi_effect, sizeof(wmi_effect), "%s/effect", wmi_base);
    std::snprintf(wmi_speed,  sizeof(wmi_speed),  "%s/speed",  wmi_base);

    int lety = 1; /* static */
    if(effect == "breath")    lety = 2;
    else if(effect == "wave") lety = 3;
    else if(effect == "colorful") lety = 4;

    int speed = presets[preset_combo->currentIndex()]["speed"].toInt(2);
    speed = (speed < 0) ? 0 : (speed > 2) ? 2 : speed;

    char buf[8];
    std::snprintf(buf, sizeof(buf), "%d", lety);
    ok = sysfsWrite(wmi_effect, buf) && ok;
    std::snprintf(buf, sizeof(buf), "%d", speed);
    ok = sysfsWrite(wmi_speed,  buf) && ok;

    /* Commit */
    std::snprintf(wmi_commit, sizeof(wmi_commit), "%s/commit", wmi_base);
    ok = sysfsWrite(wmi_commit, "1") && ok;
    if(!ok)
    {
        label_status->setText("Sysfs write failed; check driver, permissions, and KBBR");
        return false;
    }
    return true;
}


/* ================================================================== *\
|  Plugin entry point                                                  |
\* ================================================================== */

OpenRGBMiTM1806Plugin::OpenRGBMiTM1806Plugin()
    : resource_manager(nullptr), controller(nullptr), widget(nullptr)
{
}

OpenRGBMiTM1806Plugin::~OpenRGBMiTM1806Plugin()
{
}

OpenRGBPluginInfo OpenRGBMiTM1806Plugin::GetPluginInfo()
{
    OpenRGBPluginInfo info;
    info.Name           = "Mi TM1806 Keyboard";
    info.Description    = "4-zone RGB backlight on Xiaomi Mi Gaming Laptop 15.6 (TIMI TM1806).\n"
                          "Requires the mi-tm1806-led kernel driver.\n\n"
                          "Also provides a preset player tab for custom effect sequences\n"
                          "created with effects/editor.py.";
    info.Version        = "0.2";
    info.Commit         = "";
    info.URL            = "";
    /* PLUGIN_LOCATION_PLUGIN_TAB (0) – we want the plugin tab for our preset browser,
     * even though the device tab is handled separately by the registered RGBController. */
    info.Location       = 0;
    info.Label          = "Mi TM1806 Presets & Status";
    info.TabIconString  = "🎹";
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
        return;
    }

    controller = new RGBController_MiTM1806();
    resource_manager->RegisterRGBController(controller);
}

QWidget* OpenRGBMiTM1806Plugin::GetWidget()
{
    if(widget == nullptr)
    {
        widget = new PresetWidget();
    }
    return widget;
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
    if(widget != nullptr)
    {
        delete widget;
        widget = nullptr;
    }
}
