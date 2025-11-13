# -*- coding: utf-8 -*-
"""
ClimaPorClick v2.0 - Plugin QGIS
Tiempo actual + Pronósticos (24h, 36h, 48h)
Con barra visible y menú en Complementos
"""

from qgis.PyQt.QtWidgets import (
    QAction, QMessageBox, QDialog, QVBoxLayout, QLabel,
    QComboBox, QLineEdit, QPushButton, QInputDialog, QMenu,
    QTextBrowser
)
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtCore import QSettings
from qgis.core import (
    Qgis, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject
)
from qgis.gui import QgsMapToolEmitPoint
import requests
import logging
import os
from datetime import datetime

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

class ClimaPorClick:
    """
    Plugin QGIS para obtener datos de clima mediante click en el mapa, 
    utilizando diferentes APIs.
    """
    API_OPTIONS = {
        "OpenWeatherMap (Requiere Key)": "openweathermap",
        "Open-Meteo (Sin Key)": "openmeteo",
        "Tomorrow.io (Requiere Key)": "tomorrowio",
        "AccuWeather (Requiere Key)": "accuweather",
        "Visual Crossing (Requiere Key)": "visualcrossing",
    }

    MODOS = ["Tiempo Actual", "Pronóstico 24h", "Pronóstico 36h", "Pronóstico 48h"]

    WMO_WEATHER_MAP = {
        0: ("Cielo despejado", "☀️"), 1: ("Mayormente despejado", "🌤️"), 2: ("Parcialmente nublado", "⛅"),
        3: ("Nublado", "☁️"), 45: ("Niebla", "🌫️"), 48: ("Niebla helada", "🌫️"),
        51: ("Llovizna ligera", "🌦️"), 53: ("Llovizna moderada", "🌦️"), 55: ("Llovizna intensa", "🌧️"),
        61: ("Lluvia ligera", "🌦️"), 63: ("Lluvia moderada", "🌧️"), 65: ("Lluvia intensa", "🌧️"),
        71: ("Nieve ligera", "🌨️"), 73: ("Nieve moderada", "❄️"), 75: ("Nieve intensa", "❄️"),
        95: ("Tormenta", "⛈️"),
    }

    def __init__(self, iface):
        """Inicializa el plugin."""
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.toolbar = self.action = self.config_action = self.tool = None
        self.menu = None
        self.settings = QSettings()
        self.load_settings()

    def initGui(self):
        """Configura la interfaz gráfica (toolbar y menú) con los íconos específicos."""
        plugin_dir = os.path.dirname(os.path.abspath(__file__))
        
        # Uso de los íconos solicitados
        icon_api = QIcon(os.path.join(plugin_dir, 'icon_api.png')) 
        icon_config = QIcon(os.path.join(plugin_dir, 'icon_config.png'))

        self.toolbar = self.iface.addToolBar("Clima por Click")
        self.toolbar.setObjectName("ClimaPorClickToolbar")

        # Acción principal (Clima por Click)
        self.action = QAction(icon_api, "Clima por Click", self.iface.mainWindow())
        self.action.triggered.connect(self.activate)

        # Acción de configuración
        self.config_action = QAction(icon_config, "Configurar API", self.iface.mainWindow())
        self.config_action.triggered.connect(self.show_config_dialog)

        self.toolbar.addAction(self.action)
        self.toolbar.addAction(self.config_action)
        self.toolbar.setVisible(True)

        self.menu = QMenu("Clima por Click", self.iface.mainWindow())
        self.menu.addAction(self.action)
        self.menu.addAction(self.config_action)
        self.iface.pluginMenu().addMenu(self.menu)

    def unload(self):
        """Limpia la interfaz al desactivar el plugin."""
        if self.toolbar:
            self.iface.removeToolBar(self.toolbar)
            self.toolbar.deleteLater()
        if self.menu:
            self.iface.pluginMenu().removeMenu(self.menu)
            self.menu.deleteLater()
        if self.tool and self.canvas.mapTool() == self.tool:
            self.canvas.unsetMapTool(self.tool)

    def load_settings(self):
        """Carga la configuración guardada."""
        self.api_id = self.settings.value("ClimaPorClick/api_id", "openmeteo", type=str)
        self.api_key = self.settings.value(f"ClimaPorClick/api_key_{self.api_id}", "", type=str)
        self.modo = self.settings.value("ClimaPorClick/modo", "Tiempo Actual", type=str)

    def save_settings(self):
        """Guarda la configuración actual."""
        self.settings.setValue("ClimaPorClick/api_id", self.api_id)
        self.settings.setValue(f"ClimaPorClick/api_key_{self.api_id}", self.api_key or "")
        self.settings.setValue("ClimaPorClick/modo", self.modo)

    def show_config_dialog(self, ask_key_only=False):
        """Muestra el diálogo de configuración de API y modo."""
        if ask_key_only:
            name = next(n for n, i in self.API_OPTIONS.items() if i == self.api_id)
            text, ok = QInputDialog.getText(
                self.iface.mainWindow(), f"API Key para {name}",
                "Introduce tu API Key:", QLineEdit.Normal, self.api_key or ""
            )
            if ok and text.strip():
                self.api_key = text.strip()
                self.save_settings()
            return

        dlg = QDialog(self.iface.mainWindow())
        dlg.setWindowTitle("Configuración de Clima")
        dlg.setModal(True)
        layout = QVBoxLayout()

        lbl_api = QLabel("API:")
        combo_api = QComboBox()
        for n in self.API_OPTIONS.keys():
            combo_api.addItem(n)
        try:
            idx = list(self.API_OPTIONS.keys()).index(
                next(n for n, i in self.API_OPTIONS.items() if i == self.api_id)
            )
            combo_api.setCurrentIndex(idx)
        except StopIteration:
            pass
        layout.addWidget(lbl_api)
        layout.addWidget(combo_api)

        lbl_modo = QLabel("Modo:")
        combo_modo = QComboBox()
        combo_modo.addItems(self.MODOS)
        combo_modo.setCurrentText(self.modo)
        layout.addWidget(lbl_modo)
        layout.addWidget(combo_modo)

        lbl_key = QLabel("API Key (si requiere):")
        edit_key = QLineEdit()
        edit_key.setEchoMode(QLineEdit.Password)
        edit_key.setText(self.api_key)
        layout.addWidget(lbl_key)
        layout.addWidget(edit_key)

        btn_ok = QPushButton("Aceptar")
        btn_ok.clicked.connect(dlg.accept)
        layout.addWidget(btn_ok)
        dlg.setLayout(layout)
        
        if dlg.exec_() == QDialog.Accepted:
            new_api_name = combo_api.currentText()
            self.api_id = self.API_OPTIONS[new_api_name]
            self.modo = combo_modo.currentText()

            if "Requiere Key" in new_api_name:
                key = edit_key.text().strip()
                if not key:
                    self.show_config_dialog(ask_key_only=True)
                else:
                    self.api_key = key
            else:
                self.api_key = None

            self.save_settings()
            QMessageBox.information(self.iface.mainWindow(), "Configuración", "Guardada correctamente.")

    def activate(self):
        """Activa la herramienta de mapeo al hacer click."""
        if self._requires_key() and not self.api_key:
            self.show_config_dialog(ask_key_only=True)
            if not self.api_key:
                return

        self.tool = QgsMapToolEmitPoint(self.canvas)
        self.tool.canvasClicked.connect(self.on_map_click)
        self.canvas.setMapTool(self.tool)

        self.iface.messageBar().pushMessage(
            "Clima por Click", f"Modo: {self.modo} | API: {self.api_id}", level=Qgis.Info, duration=5
        )

    def on_map_click(self, point, _):
        """Maneja el evento de click en el mapa."""
        try:
            # Transformar coordenadas a WGS84 (EPSG:4326)
            src_crs = self.canvas.mapSettings().destinationCrs()
            dst_crs = QgsCoordinateReferenceSystem("EPSG:4326")
            xform = QgsCoordinateTransform(src_crs, dst_crs, QgsProject.instance())
            wgs_pt = xform.transform(point)
            lat, lon = wgs_pt.y(), wgs_pt.x()

            horas = 0
            if self.modo.startswith("Pronóstico"):
                horas = int(self.modo.split()[1].replace("h", ""))
            
            data = self.get_weather(lat, lon, horas)
            
            if data:
                self.show_weather_popup(data, horas > 0)
        except Exception as e:
            log.exception("Error en click")
            QMessageBox.critical(self.iface.mainWindow(), "Error", f"Error: {e}")

    def get_weather(self, lat, lon, horas=0):
        """Función genérica para llamar a la API seleccionada."""
        try:
            if self.api_id == "openweathermap":
                return self._openweathermap(lat, lon, horas)
            elif self.api_id == "openmeteo":
                return self._openmeteo(lat, lon, horas)
            elif self.api_id == "tomorrowio":
                return self._tomorrowio(lat, lon, horas)
            elif self.api_id == "accuweather":
                return self._accuweather(lat, lon, horas)
            elif self.api_id == "visualcrossing":
                return self._visualcrossing(lat, lon, horas)
            return None
        except requests.RequestException as e:
            QMessageBox.critical(self.iface.mainWindow(), "Error de red", f"No se pudo conectar: {e}")
            return None
        except Exception as e:
            log.exception("Error API")
            QMessageBox.critical(self.iface.mainWindow(), "Error", f"Error en {self.api_id}: {e}")
            return None

    def _openweathermap(self, lat, lon, horas):
        """Obtiene datos de OpenWeatherMap."""
        if horas == 0:
            url = f"https://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&appid={self.api_key}&units=metric&lang=es"
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            d = r.json()
            return [{
                "hora": "Ahora", "temp": round(d["main"]["temp"], 1), "feels": round(d["main"]["feels_like"], 1),
                "desc": d["weather"][0]["description"].capitalize(), "icon": d["weather"][0]["icon"],
                "hum": d["main"]["humidity"], "viento_kmh": round(d["wind"].get("speed", 0) * 3.6, 1),
                "dir": d["wind"].get("deg", 0), "rafaga": round(d["wind"].get("gust", 0) * 3.6, 1),
                "ciudad": d.get("name", "Ubicación")
            }]
        else:
            url = f"https://api.openweathermap.org/data/3.0/onecall?lat={lat}&lon={lon}&appid={self.api_key}&units=metric&lang=es&exclude=current,minutely,daily,alerts"
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            data = r.json()["hourly"][:horas]
            return [{
                "hora": datetime.fromtimestamp(h["dt"]).strftime("%H:%M"), "temp": round(h["temp"], 1),
                "feels": round(h["feels_like"], 1), "desc": h["weather"][0]["description"].capitalize(),
                "icon": h["weather"][0]["icon"], "hum": h["humidity"],
                "viento_kmh": round(h["wind_speed"] * 3.6, 1), "dir": h["wind_deg"],
                "rafaga": round(h.get("wind_gust", 0) * 3.6, 1), "ciudad": "Pronóstico"
            } for h in data]

    def _openmeteo(self, lat, lon, horas):
        """Obtiene datos de Open-Meteo."""
        if horas == 0:
            url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m,wind_direction_10m,wind_gusts_10m,weather_code"
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            d = r.json()["current"]
            code = d.get("weather_code", 0)
            desc, icon = self.WMO_WEATHER_MAP.get(code, ("Desconocido", "❓"))
            return [{
                "hora": "Ahora", "temp": round(d["temperature_2m"], 1), "feels": round(d["apparent_temperature"], 1),
                "desc": desc, "icon": icon, "hum": d["relative_humidity_2m"],
                "viento_kmh": round(d["wind_speed_10m"], 1), "dir": d["wind_direction_10m"],
                "rafaga": round(d.get("wind_gusts_10m", 0), 1), "ciudad": "Ubicación"
            }]
        else:
            days = (horas // 24) + 1
            url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&hourly=temperature_2m,apparent_temperature,relative_humidity_2m,wind_speed_10m,wind_direction_10m,weather_code&forecast_days={days}"
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            data = r.json()["hourly"]
            result = []
            for i in range(horas):
                code = data["weather_code"][i]
                desc, icon = self.WMO_WEATHER_MAP.get(code, ("Desconocido", "❓"))
                result.append({
                    "hora": datetime.fromisoformat(data["time"][i]).strftime("%H:%M"),
                    "temp": round(data["temperature_2m"][i], 1), "feels": round(data["apparent_temperature"][i], 1),
                    "desc": desc, "icon": icon, "hum": data["relative_humidity_2m"][i],
                    "viento_kmh": round(data["wind_speed_10m"][i], 1), "dir": data["wind_direction_10m"][i],
                    "rafaga": 0, "ciudad": "Pronóstico"
                })
            return result

    def _tomorrowio(self, lat, lon, horas):
        """Obtiene datos de Tomorrow.io."""
        if horas == 0:
            url = f"https://api.tomorrow.io/v4/weather/realtime?location={lat},{lon}&apikey={self.api_key}&units=metric"
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            vals = r.json()["data"]["values"]
            code = vals.get("weatherCode", 0)
            desc, icon = self.WMO_WEATHER_MAP.get(code, ("Desconocido", "❓"))
            return [{
                "hora": "Ahora", "temp": round(vals["temperature"], 1), "feels": round(vals["temperatureApparent"], 1),
                "desc": desc, "icon": icon, "hum": vals["humidity"],
                "viento_kmh": round(vals["windSpeed"] * 3.6, 1), "dir": vals["windDirection"],
                "rafaga": round(vals.get("windGust", 0) * 3.6, 1),
                "ciudad": r.json().get("location", {}).get("name", "Ubicación")
            }]
        else:
            url = f"https://api.tomorrow.io/v4/weather/forecast?location={lat},{lon}&apikey={self.api_key}&units=metric&timesteps=1h&startTime=now&endTime=nowPlus{horas}h"
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            intervals = r.json()["data"]["timelines"][0]["intervals"][:horas]
            return [{
                "hora": datetime.fromisoformat(i["startTime"].replace("Z", "+00:00")).strftime("%H:%M"),
                "temp": round(i["values"]["temperature"], 1), "feels": round(i["values"]["temperatureApparent"], 1),
                "desc": self.WMO_WEATHER_MAP.get(i["values"].get("weatherCode", 0), ("Desconocido", "❓"))[0],
                "icon": self.WMO_WEATHER_MAP.get(i["values"].get("weatherCode", 0), ("", "❓"))[1],
                "hum": i["values"]["humidity"], "viento_kmh": round(i["values"]["windSpeed"] * 3.6, 1),
                "dir": i["values"]["windDirection"], "rafaga": round(i["values"].get("windGust", 0) * 3.6, 1),
                "ciudad": "Pronóstico"
            } for i in intervals]

    def _accuweather(self, lat, lon, horas):
        """Obtiene datos de AccuWeather."""
        geo = f"http://dataservice.accuweather.com/locations/v1/cities/geoposition/search?apikey={self.api_key}&q={lat},{lon}&language=es"
        r_geo = requests.get(geo, timeout=10)
        r_geo.raise_for_status()
        loc = r_geo.json()
        key = loc["Key"]
        ciudad = loc.get("LocalizedName", "Ubicación")

        if horas == 0:
            cur = f"http://dataservice.accuweather.com/currentconditions/v1/{key}?apikey={self.api_key}&language=es&details=true"
            r = requests.get(cur, timeout=10)
            r.raise_for_status()
            d = r.json()[0]
            return [{
                "hora": "Ahora", "temp": round(d["Temperature"]["Metric"]["Value"], 1),
                "feels": round(d["RealFeelTemperature"]["Metric"]["Value"], 1), "desc": d["WeatherText"],
                "icon": f"{d['WeatherIcon']:02d}", "hum": d["RelativeHumidity"],
                "viento_kmh": round(d["Wind"]["Speed"]["Metric"]["Value"], 1), "dir": d["Wind"]["Direction"]["Degrees"],
                "rafaga": round(d["WindGust"]["Speed"]["Metric"]["Value"], 1), "ciudad": ciudad
            }]
        else:
            fc = f"http://dataservice.accuweather.com/forecasts/v1/hourly/{horas}hour/{key}?apikey={self.api_key}&language=es&details=true&metric=true"
            r = requests.get(fc, timeout=10)
            r.raise_for_status()
            data = r.json()[:horas]
            return [{
                "hora": datetime.fromisoformat(h["DateTime"][:-6]).strftime("%H:%M"),
                "temp": round(h["Temperature"]["Value"], 1), "feels": round(h["RealFeelTemperature"]["Value"], 1),
                "desc": h["IconPhrase"], "icon": f"{h['WeatherIcon']:02d}", "hum": h["RelativeHumidity"],
                "viento_kmh": round(h["Wind"]["Speed"]["Value"] * 3.6, 1), "dir": h["Wind"]["Direction"]["Degrees"],
                "rafaga": round(h["WindGust"]["Speed"]["Value"] * 3.6, 1), "ciudad": ciudad
            } for h in data]

    def _visualcrossing(self, lat, lon, horas):
        """Obtiene datos de Visual Crossing."""
        url = f"https://weather.visualcrossing.com/VisualCrossingWebServices/rest/services/timeline/{lat},{lon}?key={self.api_key}&unitGroup=metric&include=current"
        if horas > 0:
            from datetime import timedelta
            now = datetime.now()
            end = now + timedelta(hours=horas)
            url += f"&startDateTime={now.strftime('%Y-%m-%dT%H:00:00')}&endDateTime={end.strftime('%Y-%m-%dT%H:00:00')}"
        r = requests.get(url, timeout=10)
        r.raise_for_status()
        d = r.json()
        
        if horas == 0:
            cur = d["currentConditions"]
            return [{
                "hora": "Ahora", "temp": round(cur["temp"], 1), "feels": round(cur["feelslike"], 1),
                "desc": cur["conditions"], "icon": cur["icon"], "hum": cur["humidity"],
                "viento_kmh": round(cur["windspeed"], 1), "dir": cur["winddir"],
                "rafaga": round(cur.get("windgust", 0), 1), "ciudad": "Ubicación"
            }]
        else:
            result = []
            now = datetime.now()
            end = now + timedelta(hours=horas)
            for day in d["days"]:
                for h in day["hours"]:
                    dt = datetime.fromisoformat(h["datetime"])
                    if now <= dt <= end:
                        result.append({
                            "hora": dt.strftime("%H:%M"), "temp": round(h["temp"], 1), "feels": round(h["feelslike"], 1),
                            "desc": h["conditions"], "icon": h["icon"], "hum": h["humidity"],
                            "viento_kmh": round(h["windspeed"], 1), "dir": h["winddir"],
                            "rafaga": round(h.get("windgust", 0), 1), "ciudad": "Pronóstico"
                        })
                    if len(result) >= horas:
                        return result
            return result[:horas]

    def show_weather_popup(self, datos, es_pronostico):
        """
        Muestra el popup de clima utilizando un QDialog con QTextBrowser 
        para permitir el scroll vertical en pronósticos largos.
        """
        icon_map = {
            '01d': '☀️', '01n': '🌙', '02d': '🌤️', '02n': '🌤️', '03d': '🌥️', '03n': '🌥️',
            '04d': '☁️', '04n': '☁️', '09d': '🌧️', '09n': '🌧️', '10d': '🌦️', '10n': '🌧️',
            '11d': '⛈️', '11n': '⛈️', '13d': '❄️', '13n': '❄️', '50d': '🌫️', '50n': '🌫️',
        }
        
        # 1. Definición del CSS (CORREGIDO Y CERRADO)
        css_style = """
            <style>
                body { font-family: sans-serif; margin: 0; padding: 0; }
                table { border-collapse: collapse; width: 100%; font-size: 10px; margin-top: 10px; }
                th, td { border: 1px solid #ddd; padding: 4px; text-align: center; }
                th { background-color: #f2f2f2; font-weight: bold; }
                .city-header { font-size: 14px; font-weight: bold; margin-bottom: 5px; }
                hr { border: 0; border-top: 1px solid #ccc; margin: 5px 0; }
            </style>
        """ # <-- CIERRE DE LA CADENA DE TEXTO (Línea 278 en el código original)
        
        html = css_style
        html += f"<div class='city-header'>{datos[0]['ciudad']}</div>"

        if es_pronostico:
            # --- FORMATO TABULAR PARA PRONÓSTICO (con scroll) ---
            html += f"<i>Pronóstico {len(datos)}h ({self.api_id})</i><hr>"
            
            # Encabezados de la tabla solicitados
            html += "<table><thead><tr>"
            html += "<th>Hora</th><th>Temp.</th><th>Sens. Térm.</th><th>Estado</th><th>Humedad</th><th>Dir Viento</th><th>Vel Viento</th><th>Ráfaga</th>"
            html += "</tr></thead><tbody>"

            # Filas de datos
            for d in datos:
                icon = icon_map.get(d.get('icon'), d.get('icon', '')) if self.api_id == "openweathermap" else d.get('icon', '')
                
                # Extracción de datos con valor predeterminado '-' para robustez
                temp = d.get('temp', '-')
                feels = d.get('feels', '-')
                desc = d.get('desc', '-')
                hum = d.get('hum', '-')
                dir_grados = d.get('dir', '-')
                viento_kmh = d.get('viento_kmh', '-')
                rafaga = d.get('rafaga', '-')
                
                # Nueva fila
                html += "<tr>"
                html += f"<td><b>{d['hora']}</b></td>"
                html += f"<td>{temp}°C</td>"
                html += f"<td>{feels}°C</td>"
                html += f"<td>{icon} {desc}</td>"
                html += f"<td>{hum}%</td>"
                html += f"<td>{dir_grados}°</td>"
                html += f"<td>{viento_kmh} km/h</td>"
                html += f"<td>{rafaga} km/h</td>"
                html += "</tr>"

            html += "</tbody></table>"
            # ------------------------------------------------
            
            # 2. Uso de QDialog y QTextBrowser para el scroll
            dlg = QDialog(self.iface.mainWindow())
            dlg.setWindowTitle("Pronóstico por Click")
            
            main_layout = QVBoxLayout()
            
            browser = QTextBrowser()
            browser.setHtml(html)
            browser.setMinimumSize(400, 300) 
            browser.setMaximumSize(800, 600)
            
            main_layout.addWidget(browser)
            
            btn_close = QPushButton("Cerrar")
            btn_close.clicked.connect(dlg.accept)
            main_layout.addWidget(btn_close)
            
            dlg.setLayout(main_layout)
            dlg.exec_()
            
        else:
            # --- Formato para "Tiempo Actual" (sin scroll, usa QMessageBox) ---
            d = datos[0]
            icon = icon_map.get(d['icon'], d['icon']) if self.api_id == "openweathermap" else d['icon']
            html += f"<i>{d['desc']} ({self.api_id})</i><hr>"
            html += f"Temperatura: <b>{d['temp']} °C</b> (Sens. {d['feels']} °C)<br>"
            html += f"Humedad: {d['hum']} %<br>"
            html += f"Viento: {d['viento_kmh']} km/h ({d['dir']} °)<br>"
            html += f"Ráfaga: {d['rafaga']} km/h"
            
            self.iface.messageBar().clearWidgets()
            QMessageBox.information(self.iface.mainWindow(), "Clima Actual", html)


    def _requires_key(self):
        """Verifica si la API seleccionada requiere una clave."""
        return any(self.api_id == i and "Requiere Key" in n for n, i in self.API_OPTIONS.items())
