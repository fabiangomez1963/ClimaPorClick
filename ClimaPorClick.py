import os
import sys
import logging
import requests
from datetime import datetime
from qgis.PyQt.QtCore import Qt, QSettings
from qgis.PyQt.QtGui import QIcon, QColor, QFont
from qgis.PyQt.QtWidgets import QAction, QMessageBox, QCheckBox
from qgis.core import (
    QgsProject,
    QgsVectorLayer,
    QgsField,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsPalLayerSettings,
    QgsVectorLayerSimpleLabeling,
    QgsTextFormat,
    QgsTextBufferSettings,
)
from qgis.utils import iface

# ------------------------------------------------------------
# Verificar e instalar 'requests' si no está disponible
# ------------------------------------------------------------
try:
    import requests
except ImportError:
    from subprocess import check_call
    import sys
    check_call([sys.executable, "-m", "pip", "install", "requests"])
    import requests

# ------------------------------------------------------------
# LOGGING
# ------------------------------------------------------------
logging.basicConfig(level=logging.INFO)

# ------------------------------------------------------------
# Clase principal del plugin
# ------------------------------------------------------------
class ClimaPorClick:
    def __init__(self, iface):
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.toolbar = iface.addToolBar("Clima por Click")
        self.action = QAction(QIcon(":/plugins/ClimaPorClick/icon.png"), "Clima por Click", self.iface.mainWindow())
        self.action.triggered.connect(self.activate)
        self.toolbar.addAction(self.action)
        self.tool = None
        self.api_key = None
        self.guardar_auto = True  # Control de guardado
        self.settings = QSettings()
        self.load_api_key()

    # --------------------------------------------------------
    # Cargar o pedir API Key
    # --------------------------------------------------------
    def load_api_key(self):
        saved_key = self.settings.value("ClimaPorClick/api_key", "")
        if saved_key:
            self.api_key = saved_key
        else:
            self.ask_api_key()

    def ask_api_key(self):
        text, ok = QMessageBox.getText(iface.mainWindow(), "API Key", "Introduce tu API Key de OpenWeatherMap:")
        if ok and text:
            self.api_key = text.strip()
            self.settings.setValue("ClimaPorClick/api_key", self.api_key)
        elif not ok:
            QMessageBox.warning(iface.mainWindow(), "Clima por Click", "No se puede continuar sin una API Key.")

    # --------------------------------------------------------
    # Activar herramienta
    # --------------------------------------------------------
    def activate(self):
        if not self.api_key:
            self.ask_api_key()
            if not self.api_key:
                return

        QMessageBox.information(
            self.iface.mainWindow(),
            "Clima por Click",
            "Haz clic en el mapa para obtener la información del clima 🌦️",
        )
        self.tool = ClimaMapTool(self.canvas, self)
        self.canvas.setMapTool(self.tool)

    # --------------------------------------------------------
    # Obtener clima desde API
    # --------------------------------------------------------
    def get_weather(self, lat, lon):
        try:
            url = (
                f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}"
                f"&appid={self.api_key}&units=metric&lang=es"
            )
            r = requests.get(url, timeout=10)
            data = r.json()

            temp = data["main"]["temp"]
            feels = data["main"]["feels_like"]
            hum = data["main"]["humidity"]
            wind_speed_ms = data["wind"].get("speed", 0)
            wind_deg = data["wind"].get("deg", 0)
            wind_gust = data["wind"].get("gust", 0)
            desc = data["weather"][0]["description"].capitalize()
            icon = data["weather"][0]["icon"]
            city = data.get("name", "Ubicación sin nombre")

            # Conversión de unidades
            wind_speed_kmh = round(wind_speed_ms * 3.6, 1)
            wind_speed_knots = round(wind_speed_ms * 1.94384, 1)
            wind_gust_kmh = round(wind_gust * 3.6, 1)

            return {
                "ciudad": city,
                "descripcion": desc,
                "temperatura_celsius": round(temp, 1),
                "sensacion_termica": round(feels, 1),
                "humedad": hum,
                "viento_vel_kmh": wind_speed_kmh,
                "viento_vel_knots": wind_speed_knots,
                "viento_dir": wind_deg,
                "rafaga_kmh": wind_gust_kmh,
                "icono_clima": icon,
            }

        except Exception as e:
            QMessageBox.critical(self.iface.mainWindow(), "Error", f"Error al obtener datos del clima:\n{e}")
            return None

    # --------------------------------------------------------
    # Crear o actualizar capa temporal
    # --------------------------------------------------------
    def ensure_temp_layer(self):
        layer_name = "Clima por Click"
        existing_layer = None
        for lyr in QgsProject.instance().mapLayers().values():
            if lyr.name() == layer_name:
                existing_layer = lyr
                break

        if existing_layer:
            return existing_layer

        vl = QgsVectorLayer("Point?crs=EPSG:4326", layer_name, "memory")
        pr = vl.dataProvider()
        pr.addAttributes([
            QgsField("ciudad", 10),
            QgsField("descripcion", 20),
            QgsField("temperatura_celsius", 6, 2),
            QgsField("sensacion_termica", 6, 2),
            QgsField("humedad", 6, 2),
            QgsField("viento_vel_kmh", 6, 2),
            QgsField("viento_vel_knots", 6, 2),
            QgsField("viento_dir", 6, 2),
            QgsField("rafaga_kmh", 6, 2),
            QgsField("icono_clima", 10),
        ])
        vl.updateFields()
        QgsProject.instance().addMapLayer(vl)
        self.apply_labeling(vl)
        return vl

    # --------------------------------------------------------
    # Etiquetas sobre puntos (actualizado)
    # --------------------------------------------------------
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
        # Compatibilidad total con versiones de QGIS
        try:
            s.placement = QgsPalLayerSettings.Placement.OverPoint  # QGIS 3.40+
        except AttributeError:
            s.placement = QgsPalLayerSettings.OverPoint  # QGIS ≤3.38

        s.fieldName = "format('%1 %2 %3°C', \"icono_clima\", \"ciudad\", tostring(\"temperatura_celsius\",1))"
        layer.setLabeling(QgsVectorLayerSimpleLabeling(s))
        layer.setLabelsEnabled(True)
        layer.triggerRepaint()

# ------------------------------------------------------------
# Herramienta de mapa
# ------------------------------------------------------------
from qgis.gui import QgsMapTool

class ClimaMapTool(QgsMapTool):
    def __init__(self, canvas, parent):
        super().__init__(canvas)
        self.canvas = canvas
        self.parent = parent

    def canvasReleaseEvent(self, event):
        point = self.toMapCoordinates(event.pos())
        lat, lon = point.y(), point.x()
        clima = self.parent.get_weather(lat, lon)
        if not clima:
            return

        # Crear o actualizar capa
        layer = self.parent.ensure_temp_layer()
        pr = layer.dataProvider()

        feat = QgsFeature()
        feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(lon, lat)))
        feat.setAttributes([
            clima["ciudad"],
            clima["descripcion"],
            clima["temperatura_celsius"],
            clima["sensacion_termica"],
            clima["humedad"],
            clima["viento_vel_kmh"],
            clima["viento_vel_knots"],
            clima["viento_dir"],
            clima["rafaga_kmh"],
            clima["icono_clima"],
        ])
        pr.addFeature(feat)
        layer.updateExtents()
        layer.triggerRepaint()

        # Mostrar datos
        msg = (
            f"🌦️ Ciudad: {clima['ciudad']}\n"
            f"Descripción: {clima['descripcion']}\n"
            f"Temperatura: {clima['temperatura_celsius']} °C\n"
            f"Sensación térmica: {clima['sensacion_termica']} °C\n"
            f"Humedad: {clima['humedad']}%\n"
            f"Viento: {clima['viento_vel_kmh']} km/h ({clima['viento_vel_knots']} nudos), "
            f"Dirección: {clima['viento_dir']}°, Ráfaga: {clima['rafaga_kmh']} km/h"
        )
        QMessageBox.information(self.parent.iface.mainWindow(), "Datos del clima", msg)

# ------------------------------------------------------------
# Instancia del plugin
# ------------------------------------------------------------
def classFactory(iface):
    return ClimaPorClick(iface)
