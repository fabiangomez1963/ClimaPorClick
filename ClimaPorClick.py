# -*- coding: utf-8 -*-
"""
ClimaPorClick - Plugin QGIS
Obtiene datos del clima al hacer click sobre el mapa.
Soporta múltiples APIs con configuración persistente.
"""

# ------------------------------------------------------------
# IMPORTS
# ------------------------------------------------------------
from qgis.PyQt.QtWidgets import (
    QAction, QInputDialog, QMessageBox,
    QDialog, QVBoxLayout, QLabel, QComboBox, QLineEdit,
    QPushButton
)
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtCore import QSettings
from qgis.core import (
    Qgis, QgsCoordinateReferenceSystem, 
    QgsCoordinateTransform, QgsProject
)
from qgis.gui import QgsMapToolEmitPoint 
import requests
import logging
import os # <-- Módulo necesario para obtener la ruta local del ícono

# Logging (útil en la consola de QGIS)
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# ------------------------------------------------------------
# Clase principal del plugin
# ------------------------------------------------------------
class ClimaPorClick:
    """Plugin QGIS que muestra el clima al hacer click."""

    API_OPTIONS = {
        "OpenWeatherMap (Requiere Key)": "openweathermap",
        "Open-Meteo (Sin Key)": "openmeteo",
        "Tomorrow.io (Requiere Key)": "tomorrowio",
        "AccuWeather (Requiere Key)": "accuweather",
        "Visual Crossing (Requiere Key)": "visualcrossing",
    }

    # Mapeo WMO → descripción + emoji (usado por Open-Meteo y Tomorrow.io)
    WMO_WEATHER_MAP = {
        0: ("Cielo despejado", "☀️"),
        1: ("Mayormente despejado", "🌤️"),
        2: ("Parcialmente nublado", "⛅"),
        3: ("Nublado", "☁️"),
        45: ("Niebla", "🌫️"),
        48: ("Niebla helada", "🌫️"),
        51: ("Llovizna ligera", "🌦️"),
        53: ("Llovizna moderada", "🌦️"),
        55: ("Llovizna intensa", "🌧️"),
        61: ("Lluvia ligera", "🌦️"),
        63: ("Lluvia moderada", "🌧️"),
        65: ("Lluvia intensa", "🌧️"),
        71: ("Nieve ligera", "🌨️"),
        73: ("Nieve moderada", "❄️"),
        75: ("Nieve intensa", "❄️"),
        95: ("Tormenta", "⛈️"),
    }

    def __init__(self, iface):
        self.iface = iface
        self.canvas = iface.mapCanvas()
        
        self.toolbar = None
        self.action = None
        self.config_action = None

        self.tool = None
        self.api_key = None
        self.api_id = None
        self.settings = QSettings()
        self.load_settings()

    # --------------------------------------------------------
    # CICLO DE VIDA DEL PLUGIN: GUI
    # --------------------------------------------------------
    def initGui(self):
        """Inicializa la interfaz gráfica del plugin. Llamado por QGIS."""
        
        # OBTENER RUTA LOCAL DEL ÍCONO para evitar depender del sistema de recursos (.qrc)
        plugin_dir = os.path.dirname(os.path.abspath(__file__))
        icon_path = os.path.join(plugin_dir, 'icon.png')
        icon = QIcon(icon_path)
        
        self.toolbar = self.iface.addToolBar("Clima por Click")

        # Acción principal
        self.action = QAction(
            icon,
            "Clima por Click",
            self.iface.mainWindow()
        )
        self.action.triggered.connect(self.activate)

        # Acción de configuración
        self.config_action = QAction(
            icon,
            "Configurar API",
            self.iface.mainWindow()
        )
        self.config_action.triggered.connect(self.show_config_dialog)

        self.toolbar.addAction(self.action)
        self.toolbar.addAction(self.config_action)

    def unload(self):
        """Limpia los elementos de la interfaz al desactivar el plugin. Llamado por QGIS."""
        if self.toolbar:
            self.iface.removeToolBar(self.toolbar)
        
        if self.tool and self.canvas.mapTool() == self.tool:
            self.canvas.unsetMapTool(self.tool)
        
    # --------------------------------------------------------
    # Persistencia
    # --------------------------------------------------------
    def load_settings(self):
        self.api_id = self.settings.value(
            "ClimaPorClick/api_id", "openweathermap", type=str
        )
        self.api_key = self.settings.value(
            f"ClimaPorClick/api_key_{self.api_id}", "", type=str
        )

    def _requires_key(self):
        return any(
            self.api_id == api_id and "Requiere Key" in name
            for name, api_id in self.API_OPTIONS.items()
        )

    # --------------------------------------------------------
    # Diálogo de configuración
    # --------------------------------------------------------
    def show_config_dialog(self, ask_key_only=False):
        """Diálogo completo o solo clave."""
        if ask_key_only:
            name = next(
                n for n, i in self.API_OPTIONS.items() if i == self.api_id
            )
            text, ok = QInputDialog.getText(
                self.iface.mainWindow(),
                f"API Key para {name}",
                "Introduce tu API Key:",
                QLineEdit.Normal,
                self.api_key or ""
            )
            if ok and text.strip():
                self.api_key = text.strip()
                self.settings.setValue(
                    f"ClimaPorClick/api_key_{self.api_id}", self.api_key
                )
            elif not ok:
                QMessageBox.warning(
                    self.iface.mainWindow(),
                    "Configuración",
                    "La API requiere una clave. Cambia la API o proporciona la clave."
                )
            return

        dlg = QDialog(self.iface.mainWindow())
        dlg.setWindowTitle("Configuración de API de Clima")
        dlg.setModal(True)
        layout = QVBoxLayout()

        lbl_api = QLabel("Selecciona la API:")
        combo_api = QComboBox()
        for n in self.API_OPTIONS.keys():
            combo_api.addItem(n)
        try:
            current_name = next(
                n for n, i in self.API_OPTIONS.items() if i == self.api_id
            )
            idx = list(self.API_OPTIONS.keys()).index(current_name)
            combo_api.setCurrentIndex(idx)
        except StopIteration:
            pass 
        layout.addWidget(lbl_api)
        layout.addWidget(combo_api)

        lbl_key = QLabel("API Key (solo si es requerida):")
        edit_key = QLineEdit()
        edit_key.setEchoMode(QLineEdit.Password)
        key_for_current_api = self.settings.value(f"ClimaPorClick/api_key_{self.api_id}", "", type=str)
        edit_key.setText(key_for_current_api)
        
        layout.addWidget(lbl_key)
        layout.addWidget(edit_key)

        btn_ok = QPushButton("Aceptar")
        btn_ok.clicked.connect(dlg.accept)
        layout.addWidget(btn_ok)

        dlg.setLayout(layout)

        if dlg.exec_() == QDialog.Accepted:
            new_name = combo_api.currentText()
            new_id = self.API_OPTIONS[new_name]
            self.api_id = new_id
            self.settings.setValue("ClimaPorClick/api_id", self.api_id)

            if "Requiere Key" in new_name:
                key = edit_key.text().strip()
                if not key:
                    self.show_config_dialog(ask_key_only=True)
                else:
                    self.api_key = key
                    self.settings.setValue(
                        f"ClimaPorClick/api_key_{self.api_id}", self.api_key
                    )
            else:
                self.api_key = None
                self.settings.setValue(f"ClimaPorClick/api_key_{self.api_id}", "")
                QMessageBox.information(
                    self.iface.mainWindow(),
                    "Configuración",
                    f"API seleccionada: {new_name}. No requiere clave."
                )
        else:
            QMessageBox.warning(
                self.iface.mainWindow(),
                "Configuración",
                "Operación cancelada."
            )

    # --------------------------------------------------------
    # Activación de la herramienta
    # --------------------------------------------------------
    def activate(self):
        if self._requires_key() and not self.api_key:
            self.show_config_dialog(ask_key_only=True)
            if not self.api_key:
                return

        self.tool = QgsMapToolEmitPoint(self.canvas)
        self.tool.canvasClicked.connect(self.on_map_click)
        self.canvas.setMapTool(self.tool)

        self.iface.messageBar().pushMessage(
            "Clima por Click",
            f"Haz click en el mapa para obtener el clima usando {self.api_id}.",
            level=Qgis.Info,
            duration=5
        )

    def on_map_click(self, point, _):
        try:
            # Reproyectar a WGS84 (EPSG:4326)
            src_crs = self.canvas.mapSettings().destinationCrs()
            dst_crs = QgsCoordinateReferenceSystem("EPSG:4326")
            xform = QgsCoordinateTransform(src_crs, dst_crs, QgsProject.instance())
            wgs_pt = xform.transform(point)
            lat, lon = wgs_pt.y(), wgs_pt.x()

            data = self.get_weather(lat, lon)
            if data:
                self.show_weather_popup(data)
        except Exception as e:
            log.exception("Error en click")
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Error",
                f"Error inesperado:\n{e}"
            )

    # --------------------------------------------------------
    # Obtención de datos
    # --------------------------------------------------------
    def get_weather(self, lat, lon):
        try:
            if self.api_id == "openweathermap":
                return self._get_openweathermap_data(lat, lon)
            if self.api_id == "openmeteo":
                return self._get_openmeteo_data(lat, lon)
            if self.api_id == "tomorrowio":
                return self._get_tomorrowio_data(lat, lon)
            if self.api_id == "accuweather":
                return self._get_accuweather_data(lat, lon)
            if self.api_id == "visualcrossing":
                return self._get_visualcrossing_data(lat, lon)

            QMessageBox.critical(
                self.iface.mainWindow(),
                "Error",
                f"API '{self.api_id}' no implementada."
            )
            return None
        except requests.RequestException as e:
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Error de red",
                f"No se pudo conectar con la API:\n{e}"
            )
            return None
        except Exception as e:
            log.exception("Error al procesar clima")
            QMessageBox.critical(
                self.iface.mainWindow(),
                "Error",
                f"Error al procesar datos de la API {self.api_id}:\n{e}"
            )
            return None

    # --------------------------------------------------------
    # APIs específicas (Parseo e implementación)
    # --------------------------------------------------------
    def _get_openweathermap_data(self, lat, lon):
        """Implementación para OpenWeatherMap."""
        url = (
            f"https://api.openweathermap.org/data/2.5/weather"
            f"?lat={lat}&lon={lon}&appid={self.api_key}"
            f"&units=metric&lang=es"
        )
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        d = r.json()

        temp = d["main"]["temp"]
        feels = d["main"]["feels_like"]
        hum = d["main"]["humidity"]
        ws_ms = d["wind"].get("speed", 0)
        wd = d["wind"].get("deg", 0)
        gust = d["wind"].get("gust", 0)
        desc = d["weather"][0]["description"].capitalize()
        icon = d["weather"][0]["icon"]
        city = d.get("name", "Ubicación sin nombre")

        return {
            "ciudad": city,
            "descripcion": desc,
            "temperatura_celsius": round(temp, 1),
            "sensacion_termica": round(feels, 1),
            "humedad": hum,
            "viento_vel_kmh": round(ws_ms * 3.6, 1),
            "viento_vel_knots": round(ws_ms * 1.94384, 1),
            "viento_dir": wd,
            "rafaga_kmh": round(gust * 3.6, 1),
            "icono_clima": icon,
        }

    def _get_openmeteo_data(self, lat, lon):
        """Implementación para Open-Meteo (Sin Key)."""
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            f"&current=temperature_2m,apparent_temperature,relative_humidity_2m,"
            f"wind_speed_10m,wind_direction_10m,wind_gusts_10m,weather_code"
        )
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        d = r.json()["current"]

        code = d.get("weather_code", 0)
        desc, icon = self.WMO_WEATHER_MAP.get(code, ("Datos no disponibles", "❓"))

        return {
            "ciudad": "Ubicación Geográfica",
            "descripcion": desc,
            "temperatura_celsius": round(d["temperature_2m"], 1),
            "sensacion_termica": round(d["apparent_temperature"], 1),
            "humedad": d["relative_humidity_2m"],
            "viento_vel_kmh": round(d["wind_speed_10m"], 1),
            "viento_vel_knots": round(d["wind_speed_10m"] * 0.539957, 1),
            "viento_dir": d["wind_direction_10m"],
            "rafaga_kmh": round(d.get("wind_gusts_10m", 0), 1),
            "icono_clima": icon,
        }

    def _get_tomorrowio_data(self, lat, lon):
        """Implementación para Tomorrow.io."""
        url = (
            f"https://api.tomorrow.io/v4/weather/realtime"
            f"?location={lat},{lon}&apikey={self.api_key}&units=metric"
        )
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        vals = r.json()["data"]["values"]

        code = vals.get("weatherCode", 0)
        desc, icon = self.WMO_WEATHER_MAP.get(code, ("Datos no verificados", "❓"))
        city = r.json().get("location", {}).get("name", "Ubicación Geográfica")

        ws_ms = vals["windSpeed"]
        gust_ms = vals.get("windGust", 0)

        return {
            "ciudad": city,
            "descripcion": desc,
            "temperatura_celsius": round(vals["temperature"], 1),
            "sensacion_termica": round(vals["temperatureApparent"], 1),
            "humedad": vals["humidity"],
            "viento_vel_kmh": round(ws_ms * 3.6, 1),
            "viento_vel_knots": round(ws_ms * 1.94384, 1),
            "viento_dir": vals["windDirection"],
            "rafaga_kmh": round(gust_ms * 3.6, 1),
            "icono_clima": icon,
        }

    def _get_accuweather_data(self, lat, lon):
        """Implementación para AccuWeather (Requiere dos llamadas)."""
        
        # 1. Obtener Location Key
        geo = (
            f"http://dataservice.accuweather.com/locations/v1/cities/geoposition/search"
            f"?apikey={self.api_key}&q={lat},{lon}&language=es"
        )
        r_geo = requests.get(geo, timeout=10)
        r_geo.raise_for_status()
        loc = r_geo.json()
        
        if not loc or "Key" not in loc:
            raise Exception("No se encontró la clave de ubicación (Location Key) para esta coordenada.")
            
        key = loc["Key"]
        city = loc.get("LocalizedName", "Ubicación sin nombre")

        # 2. Obtener Current Conditions
        cur = (
            f"http://dataservice.accuweather.com/currentconditions/v1/{key}"
            f"?apikey={self.api_key}&language=es&details=true"
        )
        r = requests.get(cur, timeout=10)
        r.raise_for_status()
        d = r.json()[0]

        return {
            "ciudad": city,
            "descripcion": d["WeatherText"],
            "temperatura_celsius": round(d["Temperature"]["Metric"]["Value"], 1),
            "sensacion_termica": round(d["RealFeelTemperature"]["Metric"]["Value"], 1),
            "humedad": d["RelativeHumidity"],
            "viento_vel_kmh": round(d["Wind"]["Speed"]["Metric"]["Value"], 1),
            "viento_vel_knots": round(d["Wind"]["Speed"]["Metric"]["Value"] * 0.539957, 1),
            "viento_dir": d["Wind"]["Direction"]["Degrees"],
            "rafaga_kmh": round(d["WindGust"]["Speed"]["Metric"]["Value"], 1),
            "icono_clima": f"{d['WeatherIcon']:02d}", 
        }

    def _get_visualcrossing_data(self, lat, lon):
        """Implementación para Visual Crossing."""
        url = (
            f"https://weather.visualcrossing.com/VisualCrossingWebServices/rest/services/timeline/{lat},{lon}"
            f"?key={self.api_key}&unitGroup=metric&include=current"
        )
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        d = r.json()["currentConditions"]

        return {
            "ciudad": "Ubicación Geográfica",
            "descripcion": d["conditions"],
            "temperatura_celsius": round(d["temp"], 1),
            "sensacion_termica": round(d["feelslike"], 1),
            "humedad": d["humidity"],
            "viento_vel_kmh": round(d["windspeed"], 1),
            "viento_vel_knots": round(d["windspeed"] * 0.539957, 1),
            "viento_dir": d["winddir"],
            "rafaga_kmh": round(d.get("windgust", 0), 1),
            "icono_clima": d["icon"], 
        }

    # --------------------------------------------------------
    # Popup de resultados
    # --------------------------------------------------------
    def show_weather_popup(self, data):
        # Mapeo simple de iconos de OpenWeatherMap a emojis
        icon_map = {
            '01d': '☀️', '01n': '🌙',
            '02d': '🌤️', '02n': '🌤️',
            '03d': '🌥️', '03n': '🌥️',
            '04d': '☁️', '04n': '☁️',
            '09d': '🌧️', '09n': '🌧️',
            '10d': '🌦️', '10n': '🌧️',
            '11d': '⛈️', '11n': '⛈️',
            '13d': '❄️', '13n': '❄️',
            '50d': '🌫️', '50n': '🌫️',
        }
        
        # Obtener un emoji amigable o usar el código/string de la API
        if self.api_id == "openweathermap":
            icon_display = icon_map.get(data['icono_clima'], data['icono_clima'])
        elif self.api_id in ["openmeteo", "tomorrowio"]:
            icon_display = data['icono_clima'] 
        elif self.api_id == "accuweather":
            icon_display = f"ID:{data['icono_clima']}"
        elif self.api_id == "visualcrossing":
            icon_display = data['icono_clima']
        else:
            icon_display = "❓"
            
        html = (
            f"<b>{icon_display} {data['ciudad']}</b><br>"
            f"<i>{data['descripcion']} ({self.api_id})</i><hr>"
            f"Temperatura: <b>{data['temperatura_celsius']} °C</b> (Sens. {data['sensacion_termica']} °C)<br>"
            f"Humedad: {data['humedad']} %<br>"
            f"Viento: {data['viento_vel_kmh']} km/h ({data['viento_vel_knots']} nudos)<br>"
            f"Dirección: {data['viento_dir']} °<br>"
            f"Ráfaga: {data['rafaga_kmh']} km/h"
        )
        
        QMessageBox.information(
            self.iface.mainWindow(),
            "Datos del Clima",
            html
        )
