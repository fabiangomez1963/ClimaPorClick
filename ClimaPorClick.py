# -*- coding: utf-8 -*-
from qgis.PyQt.QtWidgets import (
    QAction, QMessageBox, QInputDialog, QLabel, QVBoxLayout, QDialog, QPushButton
)
from qgis.PyQt.QtGui import QIcon, QColor, QFont
from qgis.PyQt.QtCore import Qt, QSettings
from qgis.core import (
    QgsProject, QgsVectorLayer, QgsField, QgsPointXY, QgsFeature,
    QgsGeometry, QgsPalLayerSettings, QgsTextFormat, QgsTextBufferSettings,
    QgsVectorLayerSimpleLabeling
)
from qgis.gui import QgsMapToolEmitPoint
from qgis.PyQt.QtCore import QVariant
import requests, os

PLUGIN_NAME = "Clima por Click"

# -------------------------------------------------------------
# Popup flotante verde (más claro) para mostrar resultados
# -------------------------------------------------------------
class WeatherPopup(QDialog):
    def __init__(self, info_text, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Información del clima 🌤️")
        self.setWindowFlags(Qt.WindowStaysOnTopHint | Qt.Dialog)
        self.setStyleSheet("""
            QDialog {
                background-color: rgba(80, 200, 120, 220);
                border-radius: 12px;
            }
            QLabel {
                color: white;
                font-size: 11pt;
            }
            QPushButton {
                background-color: white;
                color: black;
                border-radius: 8px;
                padding: 4px 12px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: lightgray;
            }
        """)

        layout = QVBoxLayout()
        label = QLabel(info_text)
        label.setWordWrap(True)
        layout.addWidget(label)

        btn_close = QPushButton("Cerrar")
        btn_close.clicked.connect(self.close)
        layout.addWidget(btn_close, alignment=Qt.AlignCenter)
        self.setLayout(layout)
        self.resize(360, 300)

# -------------------------------------------------------------
# Herramienta principal
# -------------------------------------------------------------
class ClimaPorClickTool(QgsMapToolEmitPoint):
    def __init__(self, iface, parent):
        super().__init__(iface.mapCanvas())
        self.iface = iface
        self.parent = parent

    def canvasReleaseEvent(self, event):
        pt = self.toMapCoordinates(event.pos())
        lat, lon = pt.y(), pt.x()
        clima = self.parent.get_weather(lat, lon)
        if not clima:
            QMessageBox.warning(None, PLUGIN_NAME, "No se pudieron obtener los datos del clima.")
            return

        texto = self.parent.format_weather_info(clima)
        popup = WeatherPopup(texto)
        popup.exec_()

        layer = self.parent.ensure_temp_layer()
        self.parent.add_weather_point(layer, lat, lon, clima)

# -------------------------------------------------------------
# Plugin principal
# -------------------------------------------------------------
class ClimaPorClickPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.api_key = None
        self.tool = None
        self.layer = None

    def initGui(self):
        icon_path = os.path.join(os.path.dirname(__file__), "icon.png")
        self.action = QAction(QIcon(icon_path), PLUGIN_NAME, self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu(PLUGIN_NAME, self.action)

    def unload(self):
        self.iface.removeToolBarIcon(self.action)
        self.iface.removePluginMenu(PLUGIN_NAME, self.action)

    # ----------------------------------------------------------------
    def run(self):
        self.load_api_key()
        if not self.api_key:
            key, ok = QInputDialog.getText(None, "API Key", "Ingrese su API key de OpenWeatherMap:")
            if not ok or not key:
                QMessageBox.warning(None, PLUGIN_NAME, "Debe ingresar una API key válida.")
                return
            self.api_key = key
            QSettings().setValue("ClimaPorClick/api_key", self.api_key)

        self.tool = ClimaPorClickTool(self.iface, self)
        self.canvas.setMapTool(self.tool)
        self.iface.messageBar().pushMessage("🌦️ Clima por Click",
                                            "Haga clic en el mapa para obtener el clima.",
                                            level=0, duration=5)

    # ----------------------------------------------------------------
    def load_api_key(self):
        self.api_key = QSettings().value("ClimaPorClick/api_key", "")

    def get_weather(self, lat, lon):
        try:
            url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={self.api_key}&units=metric&lang=es"
            r = requests.get(url, timeout=10)
            if r.status_code != 200:
                return None
            return r.json()
        except Exception as e:
            QMessageBox.warning(None, PLUGIN_NAME, f"Error al conectar con la API: {e}")
            return None

    # ----------------------------------------------------------------
    def format_weather_info(self, data):
        temp = data["main"]["temp"]
        feels = data["main"]["feels_like"]
        hum = data["main"]["humidity"]
        wind_ms = data["wind"].get("speed", 0)
        wind_kmh = wind_ms * 3.6
        wind_knots = wind_ms * 1.94384
        gust = data["wind"].get("gust", 0)
        dir_deg = data["wind"].get("deg", 0)
        desc = data["weather"][0]["description"].capitalize()
        city = data.get("name", "")

        dirs = ['N', 'NE', 'E', 'SE', 'S', 'SO', 'O', 'NO']
        dir_txt = dirs[round(dir_deg / 45) % 8]

        city_line = f"📍 Ciudad: {city}<br>" if city else ""

        return (f"<b>Clima actual</b><br>{city_line}<br>"
                f"🌡️ Temperatura: {temp:.1f} °C<br>"
                f"🤔 Sensación térmica: {feels:.1f} °C<br>"
                f"💧 Humedad: {hum}%<br>"
                f"🌬️ Viento: {wind_kmh:.1f} km/h ({wind_knots:.1f} nudos)<br>"
                f"Dirección: {dir_txt} ({dir_deg}°)<br>"
                f"Ráfagas: {gust:.1f} m/s<br>"
                f"Estado: {desc}")

    # ----------------------------------------------------------------
    def ensure_temp_layer(self):
        if self.layer and self.layer.isValid():
            return self.layer

        self.layer = QgsVectorLayer("Point?crs=EPSG:4326", "Clima por Click", "memory")
        pr = self.layer.dataProvider()
        pr.addAttributes([
            QgsField("temperatura_celsius", QVariant.Double),
            QgsField("sensacion_termica", QVariant.Double),
            QgsField("humedad", QVariant.Double),
            QgsField("viento_kmh", QVariant.Double),
            QgsField("viento_nudos", QVariant.Double),
            QgsField("direccion", QVariant.String),
            QgsField("rafagas", QVariant.Double),
            QgsField("descripcion", QVariant.String)
        ])
        self.layer.updateFields()
        QgsProject.instance().addMapLayer(self.layer)
        self.apply_labeling(self.layer)
        return self.layer

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
        try:
            s.placement = QgsPalLayerSettings.Placement.OverPoint
        except AttributeError:
            s.placement = QgsPalLayerSettings.OverPoint
        s.fieldName = "\"descripcion\""
        layer.setLabeling(QgsVectorLayerSimpleLabeling(s))
        layer.setLabelsEnabled(True)
        layer.triggerRepaint()

    def add_weather_point(self, layer, lat, lon, data):
        feat = QgsFeature(layer.fields())
        feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(lon, lat)))
        feat["temperatura_celsius"] = data["main"]["temp"]
        feat["sensacion_termica"] = data["main"]["feels_like"]
        feat["humedad"] = data["main"]["humidity"]
        feat["viento_kmh"] = data["wind"].get("speed", 0) * 3.6
        feat["viento_nudos"] = data["wind"].get("speed", 0) * 1.94384
        feat["direccion"] = data["wind"].get("deg", 0)
        feat["rafagas"] = data["wind"].get("gust", 0)
        feat["descripcion"] = data["weather"][0]["description"].capitalize()
        layer.dataProvider().addFeature(feat)
        layer.updateExtents()
        layer.triggerRepaint()


def classFactory(iface):
    return ClimaPorClickPlugin(iface)
