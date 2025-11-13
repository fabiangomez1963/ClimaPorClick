# -*- coding: utf-8 -*-
"""
ClimaPorClick – versión con ventana emergente (pop-up)
Compatible con QGIS 3.22–3.40
"""

import os
import sys
import subprocess
from datetime import datetime
from qgis.PyQt.QtCore import Qt, QVariant, QSettings
from qgis.PyQt.QtGui import QColor, QFont
from qgis.PyQt.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QCheckBox, QGraphicsDropShadowEffect,
    QPushButton, QToolBar, QAction, QInputDialog, QLineEdit, QMessageBox
)
from qgis.gui import QgsMapToolEmitPoint
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsField, QgsFeature, QgsGeometry, QgsPointXY,
    QgsVectorFileWriter, QgsTextFormat, QgsTextBufferSettings, QgsPalLayerSettings,
    QgsVectorLayerSimpleLabeling, QgsMessageLog, Qgis
)
from qgis.utils import iface

# Asegurar requests
try:
    import requests
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests"])
    import requests


PLUGIN_NAME = "ClimaPorClick"
TEMP_LAYER_NAME = "Clima por Click (temporal)"
SETTINGS_GROUP = "ClimaPorClick"
SETTINGS_API_KEY = "api_key"

ICON_EMOJI = {
    "01d": "☀️", "01n": "🌙", "02d": "⛅", "02n": "☁️",
    "03d": "☁️", "03n": "☁️", "04d": "☁️", "04n": "☁️",
    "09d": "🌧️", "09n": "🌧️", "10d": "🌦️", "10n": "🌧️",
    "11d": "⛈️", "11n": "⛈️", "13d": "❄️", "13n": "❄️",
    "50d": "🌫️", "50n": "🌫️"
}


class ClimaPorClickPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.toolbar = None
        self.map_tool = None
        self.legend_widget = None
        self.checkbox_save = None
        self.save_enabled = True
        self.settings = QSettings()
        self.api_key = self.settings.value(f"{SETTINGS_GROUP}/{SETTINGS_API_KEY}", type=str) or ""

    def initGui(self):
        main = self.iface.mainWindow()
        tb = main.findChild(QToolBar, "ClimaPorClickToolbar")
        if not tb:
            tb = QToolBar("Clima por Click")
            tb.setObjectName("ClimaPorClickToolbar")
            main.addToolBar(tb)
        self.toolbar = tb

        btn = QPushButton("🌦️ Clima por Click")
        btn.setToolTip("Activar herramienta Clima por Click")
        btn.clicked.connect(self.activate_tool)
        tb.addWidget(btn)

        self.action = QAction("Configurar Clima por Click", main)
        self.action.triggered.connect(self.configure_api_key_dialog)
        self.iface.addPluginToMenu("&Clima por Click", self.action)

    def unload(self):
        try:
            main = self.iface.mainWindow()
            tb = main.findChild(QToolBar, "ClimaPorClickToolbar")
            if tb:
                for w in tb.findChildren(QPushButton):
                    if w.text().startswith("🌦️"):
                        tb.removeWidget(w)
            if self.action:
                self.iface.removePluginMenu("&Clima por Click", self.action)
        except Exception as e:
            QgsMessageLog.logMessage(f"Error al descargar complemento: {e}", PLUGIN_NAME, Qgis.Warning)

    def configure_api_key_dialog(self):
        text, ok = QInputDialog.getText(
            self.iface.mainWindow(),
            "Clave API OpenWeatherMap",
            "Ingrese su clave de OpenWeatherMap (puede obtenerla gratis en openweathermap.org):",
            QLineEdit.Normal,
            self.api_key or ""
        )
        if ok:
            self.api_key = text.strip()
            self.settings.setValue(f"{SETTINGS_GROUP}/{SETTINGS_API_KEY}", self.api_key)
            QMessageBox.information(self.iface.mainWindow(), "Clima por Click", "API Key guardada correctamente.")

    def ensure_api_key(self):
        if not self.api_key:
            self.configure_api_key_dialog()

    def activate_tool(self):
        self.ensure_api_key()
        if not self.map_tool:
            self.map_tool = self.ClickTool(self)
        self.canvas.setMapTool(self.map_tool)
        self.iface.messageBar().pushMessage("Clima por Click", "Haz clic en el mapa para obtener el clima.", level=Qgis.Info, duration=3)

    def ensure_temp_layer(self):
        for lyr in QgsProject.instance().mapLayers().values():
            if lyr.name() == TEMP_LAYER_NAME:
                return lyr

        lyr = QgsVectorLayer("Point?crs=EPSG:4326", TEMP_LAYER_NAME, "memory")
        prov = lyr.dataProvider()
        prov.addAttributes([
            QgsField("ciudad", QVariant.String),
            QgsField("descripcion_clima", QVariant.String),
            QgsField("icono_clima", QVariant.String),
            QgsField("temperatura_celsius", QVariant.Double),
            QgsField("sensacion_termica_celsius", QVariant.Double),
            QgsField("humedad_porcentaje", QVariant.Double),
            QgsField("velocidad_viento_kmh", QVariant.Double),
            QgsField("velocidad_viento_nudos", QVariant.Double),
            QgsField("direccion_viento_grados", QVariant.Double),
            QgsField("rafaga_viento_kmh", QVariant.Double)
        ])
        lyr.updateFields()
        QgsProject.instance().addMapLayer(lyr)
        self.apply_labeling(lyr)
        return lyr

    def apply_labeling(self, layer):
        fmt = QgsTextFormat()
        fmt.setFont(QFont("Arial", 9))
        fmt.setSize(9)
        fmt.setColor(QColor(0, 0, 0))

        buf = QgsTextBufferSettings()
        buf.setEnabled(True)
        buf.setSize(1)
        buf.setColor(QColor(255, 255, 255))
        fmt.setBuffer(buf)

        s = QgsPalLayerSettings()
        s.setFormat(fmt)
        s.enabled = True
        s.placement = QgsPalLayerSettings.OverPoint
        s.fieldName = "format('%1 %2 %3°C', \"icono_clima\", \"ciudad\", tostring(\"temperatura_celsius\",1))"
        layer.setLabeling(QgsVectorLayerSimpleLabeling(s))
        layer.setLabelsEnabled(True)
        layer.triggerRepaint()

    def get_weather(self, lat, lon):
        if not self.api_key:
            return None
        url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={self.api_key}&units=metric&lang=es"
        try:
            r = requests.get(url, timeout=10)
            data = r.json()
            if r.status_code != 200:
                QgsMessageLog.logMessage(f"Error API: {data.get('message')}", PLUGIN_NAME, Qgis.Warning)
                return None

            main = data.get("main", {})
            wind = data.get("wind", {})
            weather = data.get("weather", [{}])[0]

            vel_ms = wind.get("speed", 0.0)
            vel_kt = round(vel_ms * 1.94384, 1)
            vel_kmh = round(vel_ms * 3.6, 1)
            gust_ms = wind.get("gust", 0.0)
            gust_kt = round(gust_ms * 1.94384, 1)
            gust_kmh = round(gust_ms * 3.6, 1)

            return {
                "ciudad": data.get("name", "Desconocida"),
                "descripcion_clima": weather.get("description", ""),
                "icono_clima": ICON_EMOJI.get(weather.get("icon", ""), ""),
                "temperatura_celsius": main.get("temp", 0.0),
                "sensacion_termica_celsius": main.get("feels_like", 0.0),
                "humedad_porcentaje": main.get("humidity", 0.0),
                "velocidad_viento_kmh": vel_kmh,
                "velocidad_viento_nudos": vel_kt,
                "direccion_viento_grados": wind.get("deg", 0.0),
                "rafaga_viento_kmh": gust_kmh,
                "rafaga_viento_nudos": gust_kt
            }
        except Exception as e:
            QgsMessageLog.logMessage(f"Error de conexión: {e}", PLUGIN_NAME, Qgis.Critical)
            return None

    class ClickTool(QgsMapToolEmitPoint):
        def __init__(self, parent):
            super().__init__(parent.iface.mapCanvas())
            self.parent = parent

        def canvasReleaseEvent(self, event):
            pt = self.parent.canvas.getCoordinateTransform().toMapCoordinates(event.pos().x(), event.pos().y())
            lon, lat = pt.x(), pt.y()

            clima = self.parent.get_weather(lat, lon)
            if not clima:
                QMessageBox.warning(self.parent.iface.mainWindow(), "Clima por Click", "No se pudieron obtener datos meteorológicos.")
                return

            layer = self.parent.ensure_temp_layer()
            feat = QgsFeature()
            feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(lon, lat)))
            feat.setAttributes([
                clima["ciudad"], clima["descripcion_clima"], clima["icono_clima"],
                clima["temperatura_celsius"], clima["sensacion_termica_celsius"],
                clima["humedad_porcentaje"], clima["velocidad_viento_kmh"],
                clima["velocidad_viento_nudos"], clima["direccion_viento_grados"],
                clima["rafaga_viento_kmh"]
            ])
            layer.startEditing()
            layer.dataProvider().addFeature(feat)
            layer.commitChanges()
            layer.triggerRepaint()

            # --- POP-UP flotante con datos del clima ---
            sens = clima["sensacion_termica_celsius"]
            sens_txt = f" (sens. {sens}°C)" if sens else ""
            dirg = direccion_viento_desc(clima["direccion_viento_grados"])
            msg = (
                f"{clima['icono_clima']}  {clima['ciudad']}\n\n"
                f"Temperatura: {clima['temperatura_celsius']}°C{sens_txt}\n"
                f"Humedad: {clima['humedad_porcentaje']}%\n"
                f"Viento: {clima['velocidad_viento_nudos']} kt / {clima['velocidad_viento_kmh']} km/h {dirg}\n"
                f"Ráfaga: {clima['rafaga_viento_nudos']} kt\n"
                f"Descripción: {clima['descripcion_clima'].capitalize()}"
            )
            QMessageBox.information(self.parent.iface.mainWindow(), "🌦️ Clima por Click", msg)


def direccion_viento_desc(deg):
    try:
        d = float(deg) % 360
    except Exception:
        return "-"
    dirs = ["N","NNE","NE","ENE","E","ESE","SE","SSE","S","SSW","SW","WSW","W","WNW","NW","NNW"]
    idx = int((d + 11.25) // 22.5) % 16
    return dirs[idx]
