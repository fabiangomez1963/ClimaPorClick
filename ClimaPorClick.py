# -*- coding: utf-8 -*-
"""
ClimaPorClick - Plugin QGIS para consulta de clima
Compatibilidad: QGIS 3.22 - 3.40, Python 3.12
Versión: 2.0
"""

import os
import sys
import logging
from dataclasses import dataclass, asdict
from typing import Optional, Dict, Tuple
from functools import lru_cache
from datetime import datetime

# Silenciar mensajes de urllib3
logging.getLogger("urllib3").setLevel(logging.CRITICAL)

# Constantes
PLUGIN_NAME = "ClimaPorClick"
SETTINGS_GROUP = "ClimaPorClick"
SETTINGS_API_KEY = "api_key"
TEMP_LAYER_NAME = "Clima por Click (temporal)"

# Constantes de API
API_TIMEOUT = 10
API_BASE_URL = "https://api.openweathermap.org/data/2.5/weather"
MS_TO_KNOTS = 1.94384
MS_TO_KMH = 3.6

# Debug mode
DEBUG_MODE = os.getenv('CLIMAPORCLICK_DEBUG', 'false').lower() == 'true'

# Iconos del clima
ICON_EMOJI = {
    "01d": "☀️", "01n": "🌙", "02d": "⛅", "02n": "☁️",
    "03d": "☁️", "03n": "☁️", "04d": "☁️", "04n": "☁️",
    "09d": "🌧️", "09n": "🌧️", "10d": "🌦️", "10n": "🌧️",
    "11d": "⛈️", "11n": "⛈️", "13d": "❄️", "13n": "❄️",
    "50d": "🌫️", "50n": "🌫️"
}

# Asegurar requests
try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except Exception:
    try:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "requests"])
        import requests
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
    except Exception:
        requests = None

from qgis.PyQt.QtCore import QVariant, Qt, QSettings
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


@dataclass
class WeatherData:
    """Clase de datos para información meteorológica"""
    ciudad: str
    descripcion_clima: str
    icono_clima: str
    temperatura_celsius: float
    sensacion_termica_celsius: Optional[float] = None
    humedad_porcentaje: Optional[float] = None
    velocidad_viento_kmh: float = 0.0
    velocidad_viento_nudos: float = 0.0
    direccion_viento_grados: float = 0.0
    rafaga_viento_kmh: float = 0.0
    rafaga_viento_nudos: float = 0.0
    
    @classmethod
    def from_api_response(cls, data: Dict) -> 'WeatherData':
        """
        Crea una instancia desde la respuesta de la API.
        
        Args:
            data: Respuesta JSON de OpenWeatherMap
            
        Returns:
            WeatherData: Instancia con datos parseados
        """
        main = data.get("main", {})
        wind = data.get("wind", {})
        weather = data.get("weather", [{}])[0]
        
        # Conversión de velocidad del viento
        vel_ms = wind.get("speed", 0.0) or 0.0
        vel_kt = round(vel_ms * MS_TO_KNOTS, 1)
        vel_kmh = round(vel_ms * MS_TO_KMH, 1)
        
        # Conversión de ráfagas
        gust_ms = wind.get("gust", 0.0) or 0.0
        gust_kmh = round(gust_ms * MS_TO_KMH, 1)
        gust_kt = round(gust_ms * MS_TO_KNOTS, 1)
        
        return cls(
            ciudad=data.get("name", "Desconocida"),
            descripcion_clima=weather.get("description", ""),
            icono_clima=ICON_EMOJI.get(weather.get("icon", ""), ""),
            temperatura_celsius=main.get("temp", 0.0),
            sensacion_termica_celsius=main.get("feels_like"),
            humedad_porcentaje=main.get("humidity"),
            velocidad_viento_kmh=vel_kmh,
            velocidad_viento_nudos=vel_kt,
            direccion_viento_grados=wind.get("deg", 0),
            rafaga_viento_kmh=gust_kmh,
            rafaga_viento_nudos=gust_kt
        )
    
    def to_dict(self) -> Dict:
        """Convierte a diccionario para compatibilidad con código legacy"""
        return asdict(self)


class WeatherDataStore:
    """Maneja la persistencia de datos meteorológicos en GeoPackage"""
    
    def __init__(self, project_instance: QgsProject):
        self.project = project_instance
    
    def get_gpkg_path_and_layer(self) -> Tuple[str, str]:
        """
        Obtiene la ruta del GeoPackage y nombre de capa.
        
        Returns:
            Tuple[str, str]: (ruta_completa_gpkg, nombre_capa)
        """
        proj_file = self.project.fileName()
        folder = os.path.dirname(proj_file) if proj_file else os.path.join(
            os.path.expanduser("~"), "Desktop"
        )
        proj_name = os.path.splitext(os.path.basename(proj_file or "proyecto"))[0]
        gpkg_name = f"{proj_name}_clima.gpkg"
        gpkg_full = os.path.join(folder, gpkg_name)
        layer_name = f"{proj_name}_clima"
        return gpkg_full, layer_name
    
    def ensure_gpkg_layer(self, gpkg_full: str, layer_name: str) -> bool:
        """
        Asegura que existe la capa en el GeoPackage.
        
        Args:
            gpkg_full: Ruta completa al archivo GPKG
            layer_name: Nombre de la capa
            
        Returns:
            bool: True si existe o se creó correctamente
        """
        uri = f"{gpkg_full}|layername={layer_name}"
        layer = QgsVectorLayer(uri, layer_name, "ogr")
        if layer.isValid():
            return True
        
        # Crear nueva capa en memoria
        mem = QgsVectorLayer("Point?crs=EPSG:4326", layer_name, "memory")
        prov = mem.dataProvider()
        prov.addAttributes([
            QgsField("timestamp", QVariant.String),
            QgsField("latitud", QVariant.Double),
            QgsField("longitud", QVariant.Double),
            QgsField("ciudad", QVariant.String),
            QgsField("descripcion_clima", QVariant.String),
            QgsField("temperatura_celsius", QVariant.Double),
            QgsField("sensacion_termica_celsius", QVariant.Double),
            QgsField("humedad_porcentaje", QVariant.Double),
            QgsField("velocidad_viento_kmh", QVariant.Double),
            QgsField("velocidad_viento_nudos", QVariant.Double),
            QgsField("direccion_viento_grados", QVariant.Double),
            QgsField("rafaga_viento_kmh", QVariant.Double),
            QgsField("icono_clima", QVariant.String)
        ])
        mem.updateFields()
        
        # Escribir a GeoPackage
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = layer_name
        options.fileEncoding = "UTF-8"
        
        try:
            QgsVectorFileWriter.writeAsVectorFormatV2(
                mem, gpkg_full, self.project.transformContext(), options
            )
            return True
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error creando GPKG: {e}", PLUGIN_NAME, Qgis.Critical
            )
            return False
    
    def append_feature(self, gpkg_full: str, layer_name: str, feat: QgsFeature) -> bool:
        """
        Añade una feature al GeoPackage.
        
        Args:
            gpkg_full: Ruta completa al archivo GPKG
            layer_name: Nombre de la capa
            feat: Feature a añadir
            
        Returns:
            bool: True si se añadió correctamente
        """
        uri = f"{gpkg_full}|layername={layer_name}"
        layer = QgsVectorLayer(uri, layer_name, "ogr")
        
        if not layer.isValid():
            QgsMessageLog.logMessage(
                "No se pudo abrir capa GPKG para añadir.", 
                PLUGIN_NAME, 
                Qgis.Warning
            )
            return False
        
        dp = layer.dataProvider()
        try:
            dp.addFeatures([feat])
            layer.triggerRepaint()
            return True
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error añadiendo feature a GPKG: {e}", 
                PLUGIN_NAME, 
                Qgis.Critical
            )
            return False
    
    def save_weather(self, lon: float, lat: float, weather: WeatherData) -> bool:
        """
        Guarda datos meteorológicos en el GeoPackage.
        
        Args:
            lon: Longitud
            lat: Latitud
            weather: Datos meteorológicos
            
        Returns:
            bool: True si se guardó correctamente
        """
        gpkg_full, layer_name = self.get_gpkg_path_and_layer()
        
        if not self.ensure_gpkg_layer(gpkg_full, layer_name):
            QgsMessageLog.logMessage(
                "No se pudo crear/asegurar GPKG.", 
                PLUGIN_NAME, 
                Qgis.Critical
            )
            return False
        
        feat = QgsFeature()
        feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(lon, lat)))
        feat.setAttributes([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            lat, lon,
            weather.ciudad,
            weather.descripcion_clima,
            weather.temperatura_celsius,
            weather.sensacion_termica_celsius or 0.0,
            weather.humedad_porcentaje or 0.0,
            weather.velocidad_viento_kmh,
            weather.velocidad_viento_nudos,
            weather.direccion_viento_grados,
            weather.rafaga_viento_kmh,
            weather.icono_clima
        ])
        
        return self.append_feature(gpkg_full, layer_name, feat)


class WeatherAPIClient:
    """Cliente para la API de OpenWeatherMap"""
    
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.session = self._create_session()
    
    def _create_session(self) -> requests.Session:
        """Crea sesión HTTP con reintentos automáticos"""
        if requests is None:
            return None
        
        session = requests.Session()
        retry = Retry(
            total=3,
            backoff_factor=0.3,
            status_forcelist=[500, 502, 503, 504]
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount('https://', adapter)
        return session
    
    @staticmethod
    def validate_coordinates(lat: float, lon: float) -> bool:
        """
        Valida que las coordenadas estén en rangos válidos.
        
        Args:
            lat: Latitud
            lon: Longitud
            
        Returns:
            bool: True si las coordenadas son válidas
        """
        if not (-90 <= lat <= 90):
            QgsMessageLog.logMessage(
                f"Latitud inválida: {lat}", 
                PLUGIN_NAME, 
                Qgis.Warning
            )
            return False
        if not (-180 <= lon <= 180):
            QgsMessageLog.logMessage(
                f"Longitud inválida: {lon}", 
                PLUGIN_NAME, 
                Qgis.Warning
            )
            return False
        return True
    
    def fetch_weather(self, lat: float, lon: float) -> Optional[WeatherData]:
        """
        Obtiene datos meteorológicos para una ubicación.
        
        Args:
            lat: Latitud en grados decimales (-90 a 90)
            lon: Longitud en grados decimales (-180 a 180)
            
        Returns:
            WeatherData: Datos meteorológicos o None si falla
        """
        if not self.validate_coordinates(lat, lon):
            return None
        
        if not self.api_key:
            QgsMessageLog.logMessage(
                "API key no configurada.", 
                PLUGIN_NAME, 
                Qgis.Warning
            )
            return None
        
        if self.session is None:
            QgsMessageLog.logMessage(
                "Módulo requests no disponible.", 
                PLUGIN_NAME, 
                Qgis.Critical
            )
            return None
        
        url = f"{API_BASE_URL}?lat={lat}&lon={lon}&appid={self.api_key}&units=metric&lang=es"
        
        try:
            r = self.session.get(url, timeout=API_TIMEOUT)
            
            # Validar respuesta JSON
            try:
                data = r.json()
            except ValueError as e:
                QgsMessageLog.logMessage(
                    f"Respuesta inválida de API: {e}", 
                    PLUGIN_NAME, 
                    Qgis.Critical
                )
                return None
            
            if r.status_code != 200:
                QgsMessageLog.logMessage(
                    f"OpenWeather error {r.status_code}: {data.get('message', 'Unknown error')}", 
                    PLUGIN_NAME, 
                    Qgis.Warning
                )
                return None
            
            return WeatherData.from_api_response(data)
            
        except requests.exceptions.Timeout:
            QgsMessageLog.logMessage(
                "Timeout conectando a OpenWeather", 
                PLUGIN_NAME, 
                Qgis.Warning
            )
            return None
        except requests.exceptions.ConnectionError:
            QgsMessageLog.logMessage(
                "Error de conexión a OpenWeather", 
                PLUGIN_NAME, 
                Qgis.Critical
            )
            return None
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error inesperado conectando OpenWeather: {e}", 
                PLUGIN_NAME, 
                Qgis.Critical
            )
            return None


class ClimaPorClick:
    """Plugin principal para consulta de clima en QGIS"""
    
    def __init__(self, iface):
        self.iface = iface
        self.canvas = iface.mapCanvas()
        self.toolbar = None
        self.action = None
        self.map_tool = None
        self.legend_widget = None
        self.checkbox_save = None
        self.save_enabled = True
        self.settings = QSettings()
        self.api_key = self.settings.value(
            f"{SETTINGS_GROUP}/{SETTINGS_API_KEY}", 
            type=str
        ) or ""
        self.api_client = None
        self.data_store = WeatherDataStore(QgsProject.instance())
    
    def log_debug(self, message: str):
        """Log de debug condicional"""
        if DEBUG_MODE:
            QgsMessageLog.logMessage(
                f"[DEBUG] {message}", 
                PLUGIN_NAME, 
                Qgis.Info
            )
    
    def initGui(self):
        """Inicializa la interfaz gráfica del plugin"""
        main = self.iface.mainWindow()
        tb = main.findChild(QToolBar, "ClimaPorClickToolbar")
        
        if not tb:
            tb = QToolBar("Clima por Click")
            tb.setObjectName("ClimaPorClickToolbar")
            main.addToolBar(tb)
        
        self.toolbar = tb
        
        # Verificar si ya existe el botón
        for w in tb.findChildren(QPushButton):
            if w.text().startswith("🌦️"):
                break
        else:
            btn = QPushButton("🌦️ Clima por Click")
            btn.setToolTip("Activar herramienta Clima por Click")
            btn.clicked.connect(self.activate_tool)
            tb.addWidget(btn)
        
        # Menú de configuración
        self.action = QAction("Configurar Clima por Click", main)
        self.action.triggered.connect(self.configure_api_key_dialog)
        self.iface.addPluginToMenu("&Clima por Click", self.action)
    
    def unload(self):
        """Limpia la interfaz al descargar el plugin"""
        try:
            main = self.iface.mainWindow()
            tb = main.findChild(QToolBar, "ClimaPorClickToolbar")
            
            if tb:
                for w in tb.findChildren(QPushButton):
                    if w.text().startswith("🌦️"):
                        tb.removeWidget(w)
                        w.deleteLater()
            
            if self.action:
                self.iface.removePluginMenu("&Clima por Click", self.action)
                
        except Exception as e:
            QgsMessageLog.logMessage(
                f"Error unloading plugin UI: {e}", 
                PLUGIN_NAME, 
                Qgis.Warning
            )
    
    def configure_api_key_dialog(self):
        """Muestra diálogo para configurar la API key"""
        text, ok = QInputDialog.getText(
            self.iface.mainWindow(),
            "Clave API OpenWeatherMap",
            "Ingrese su clave de OpenWeatherMap\n"
            "(puede obtenerla gratis en openweathermap.org):",
            QLineEdit.Normal,
            self.api_key or ""
        )
        
        if ok and text.strip():
            self.api_key = text.strip()
            self.settings.setValue(
                f"{SETTINGS_GROUP}/{SETTINGS_API_KEY}", 
                self.api_key
            )
            self.api_client = WeatherAPIClient(self.api_key)
            
            self.log_debug("API Key guardada en QSettings.")
            QMessageBox.information(
                self.iface.mainWindow(), 
                "Clima por Click", 
                "API Key guardada correctamente."
            )
    
    def ensure_api_key(self):
        """Asegura que hay una API key configurada"""
        if not self.api_key:
            self.configure_api_key_dialog()
        if self.api_key and not self.api_client:
            self.api_client = WeatherAPIClient(self.api_key)
    
    def activate_tool(self):
        """Activa la herramienta de selección de punto"""
        self.ensure_api_key()
        
        if not self.map_tool:
            self.map_tool = self.ClickTool(self)
        
        self.canvas.setMapTool(self.map_tool)
        self.iface.messageBar().pushMessage(
            "Clima por Click", 
            "Haz clic en el mapa para obtener el clima.", 
            level=Qgis.Info, 
            duration=4
        )
    
    def show_legend(self, weather: Optional[WeatherData] = None):
        """
        Muestra o actualiza la leyenda con información meteorológica.
        
        Args:
            weather: Datos meteorológicos a mostrar
        """
        if self.legend_widget is None:
            widget = QWidget()
            layout = QHBoxLayout()
            layout.setContentsMargins(6, 4, 6, 4)
            widget.setLayout(layout)
            
            # Checkbox para guardar
            cb = QCheckBox("Guardar en GeoPackage")
            cb.setChecked(self.save_enabled)
            cb.stateChanged.connect(lambda s: self.set_save_enabled(bool(s)))
            self.checkbox_save = cb
            layout.addWidget(cb)
            
            # Label para información
            lbl = QLabel()
            lbl.setTextFormat(Qt.RichText)
            lbl.setTextInteractionFlags(Qt.NoTextInteraction)
            lbl.setFont(QFont("Arial", 10))
            lbl.setStyleSheet(
                "QLabel { min-width:820px; padding:6px; border-radius:10px; }"
            )
            widget.label = lbl
            layout.addWidget(lbl)
            
            # Sombra
            shadow = QGraphicsDropShadowEffect()
            shadow.setBlurRadius(12)
            shadow.setOffset(0, 2)
            widget.setGraphicsEffect(shadow)
            
            self.legend_widget = widget
            self.iface.messageBar().pushWidget(self.legend_widget, Qgis.Info)
        
        # Actualizar contenido
        if weather:
            sens_txt = ""
            if weather.sensacion_termica_celsius is not None:
                sens_txt = f" (sens. {weather.sensacion_termica_celsius}°C)"
            
            dirg = direccion_viento_desc(weather.direccion_viento_grados)
            
            texto = (
                f"<b>{weather.icono_clima} {weather.ciudad}</b> — "
                f"{weather.temperatura_celsius}°C{sens_txt} — "
                f"{weather.descripcion_clima.capitalize()} — "
                f"Viento: {weather.velocidad_viento_nudos} kt / "
                f"{weather.velocidad_viento_kmh} km/h {dirg}"
            )
            
            if weather.rafaga_viento_nudos > 0:
                texto += f" (ráfaga {weather.rafaga_viento_nudos} kt)"
        else:
            texto = "<i>Haz clic en el mapa para consultar el clima.</i>"
        
        rgba, text_color = color_for_temp(
            weather.temperatura_celsius if weather else None
        )
        self.legend_widget.label.setStyleSheet(
            f"QLabel {{ min-width:820px; padding:6px; border-radius:10px; "
            f"background: {rgba}; color: {text_color}; }}"
        )
        self.legend_widget.label.setText(texto)
    
    def set_save_enabled(self, value: bool):
        """Cambia el estado de guardado automático"""
        self.save_enabled = value
        self.log_debug(f"Guardado automático: {value}")
    
    def ensure_temp_layer(self) -> QgsVectorLayer:
        """
        Asegura que existe la capa temporal en el proyecto.
        
        Returns:
            QgsVectorLayer: Capa temporal
        """
        pr = QgsProject.instance()
        
        # Buscar capa existente
        for lyr in pr.mapLayers().values():
            if lyr.name() == TEMP_LAYER_NAME:
                return lyr
        
        # Crear nueva capa
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
    
    def apply_labeling(self, layer: QgsVectorLayer):
        """
        Aplica etiquetado a la capa.
        
        Args:
            layer: Capa a etiquetar
        """
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
        
        s.fieldName = (
            "format('%1 %2 %3°C\\nV: %4 kt %5', \"icono_clima\", \"ciudad\", "
            "tostring(\"temperatura_celsius\",1), "
            "tostring(\"velocidad_viento_nudos\",1), \"direccion_viento_grados\")"
        )
        
        layer.setLabeling(QgsVectorLayerSimpleLabeling(s))
        layer.setLabelsEnabled(True)
        layer.triggerRepaint()
    
    class ClickTool(QgsMapToolEmitPoint):
        """Herramienta de mapa para capturar clicks"""
        
        def __init__(self, parent):
            super().__init__(parent.iface.mapCanvas())
            self.parent = parent
            self.canvas = parent.iface.mapCanvas()
        
        def canvasReleaseEvent(self, event):
            """Maneja el evento de click en el mapa"""
            pt = self.canvas.getCoordinateTransform().toMapCoordinates(
                event.pos().x(), event.pos().y()
            )
            lon, lat = pt.x(), pt.y()
            
            self.parent.log_debug(f"Click coords {lat:.6f}, {lon:.6f}")
            
            # Mostrar mensaje de carga
            self.parent.iface.messageBar().pushMessage(
                "Clima por Click",
                "Consultando clima...",
                level=Qgis.Info,
                duration=2
            )
            
            # Obtener datos del clima
            if not self.parent.api_client:
                QgsMessageLog.logMessage(
                    "Cliente API no inicializado",
                    PLUGIN_NAME,
                    Qgis.Warning
                )
                return
            
            weather = self.parent.api_client.fetch_weather(lat, lon)
            
            if not weather:
                self.parent.iface.messageBar().pushMessage(
                    "Clima por Click",
                    "No se pudo obtener el clima para esta ubicación.",
                    level=Qgis.Warning,
                    duration=5
                )
                return
            
            # Añadir a capa temporal
            lyr = self.parent.ensure_temp_layer()
            feat = QgsFeature()
            feat.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(lon, lat)))
            feat.setAttributes([
                weather.ciudad,
                weather.descripcion_clima,
                weather.icono_clima,
                weather.temperatura_celsius,
                weather.sensacion_termica_celsius or 0.0,
                weather.humedad_porcentaje or 0.0,
                weather.velocidad_viento_kmh,
                weather.velocidad_viento_nudos,
                weather.direccion_viento_grados,
                weather.rafaga_viento_kmh
            ])
            
            lyr.startEditing()
            lyr.dataProvider().addFeature(feat)
            lyr.commitChanges()
            lyr.triggerRepaint()
            
            # Actualizar leyenda
            self.parent.show_legend(weather)
            
            # Mensaje informativo
            sens = weather.sensacion_termica_celsius
            sens_txt = f" (sens. {sens}°C)" if sens else ""
            dirg = direccion_viento_desc(weather.direccion_viento_grados)
            
            msg = (
                f"<b>{weather.icono_clima} {weather.ciudad}</b><br>"
                f"{weather.temperatura_celsius}°C{sens_txt}<br>"
                f"Viento: {weather.velocidad_viento_nudos} kt / "
                f"{weather.velocidad_viento_kmh} km/h {dirg}<br>"
                f"Humedad: {weather.humedad_porcentaje or '—'}%<br>"
                f"{weather.descripcion_clima.capitalize()}"
            )
            
            self.parent.iface.messageBar().pushMessage(
                "Clima por Click",
                msg,
                level=Qgis.Info,
                duration=6
            )