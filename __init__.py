# -*- coding: utf-8 -*-
from .ClimaPorClick import ClimaPorClick

def classFactory(iface):
    """QGIS exige esta función."""
    return ClimaPorClick(iface)
