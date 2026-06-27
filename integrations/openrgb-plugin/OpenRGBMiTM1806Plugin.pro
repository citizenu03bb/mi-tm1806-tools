#-----------------------------------------------------------------#
#  OpenRGBMiTM1806Plugin.pro                                      #
#                                                                 #
#  Qt5 plugin for OpenRGB 0.9 (API version 3). Built against      #
#  headers from a release_0.9 checkout of the OpenRGB source.     #
#  Symbols defined in OpenRGB itself (RGBController constructors, #
#  ResourceManager methods, etc.) are resolved at load time by    #
#  the host process via QPluginLoader.                            #
#                                                                 #
#  Set OPENRGB_SRC to your OpenRGB source tree pinned to          #
#  release_0.9 (commit b5f46e3f), e.g.                            #
#    qmake "OPENRGB_SRC=/home/pat/OpenRGB-src"                    #
#-----------------------------------------------------------------#

QT          += core gui widgets
TEMPLATE    = lib
CONFIG      += plugin c++17
TARGET      = OpenRGBMiTM1806Plugin

isEmpty(OPENRGB_SRC) {
    OPENRGB_SRC = $$(OPENRGB_SRC)
}
isEmpty(OPENRGB_SRC) {
    error("OPENRGB_SRC must be set to the OpenRGB source tree (release_0.9). Example: qmake OPENRGB_SRC=/path/to/OpenRGB-src")
}

INCLUDEPATH += $$OPENRGB_SRC \
               $$OPENRGB_SRC/RGBController \
               $$OPENRGB_SRC/hidapi_wrapper \
               $$OPENRGB_SRC/i2c_smbus \
               $$OPENRGB_SRC/net_port \
               $$OPENRGB_SRC/dependencies/json \
               $$OPENRGB_SRC/dependencies/hidapi

HEADERS     += OpenRGBMiTM1806Plugin.h \
               RGBController_MiTM1806.h

SOURCES     += OpenRGBMiTM1806Plugin.cpp \
               RGBController_MiTM1806.cpp \
               $$OPENRGB_SRC/RGBController/RGBController.cpp

# RGBController.cpp pulls in a few headers; nothing else from the OpenRGB
# tree needs to be compiled in -- the rest is resolved by the host at load.
unix:!macx {
    QMAKE_LFLAGS += -Wl,--allow-shlib-undefined
}
