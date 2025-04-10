"""
Парсеры объявлений о недвижимости в Уругвае.
"""

from app.parsers.base import BaseParser
from app.parsers.mercadolibre import MercadoLibreParser
from app.parsers.infocasas import InfoCasasParser

__all__ = ['BaseParser', 'MercadoLibreParser', 'InfoCasasParser']
