# -*- coding: utf-8 -*-
from .ClimaPorClick import ClimaPorClickPlugin

def classFactory(iface):
    """Carga el complemento ClimaPorClick."""
    return ClimaPorClickPlugin(iface)
