#!/usr/bin/env python3
"""
Модели данных Pydantic для проекта UruguayLands.
"""

from typing import Optional, List, Dict, Tuple, Any
from pydantic import BaseModel, HttpUrl, Field, validator
from datetime import datetime
import re

class Listing(BaseModel):
    """Модель данных для одного объявления."""
    id: Optional[str] = None # Уникальный ID объявления (может быть url или специфичный id сайта)
    title: Optional[str] = Field(None, description="Заголовок объявления")
    price: Optional[str] = Field(None, description="Цена (строка, как на сайте, т.к. форматы разные U$S, USD, $)")
    location: Optional[str] = Field(None, description="Местоположение")
    area: Optional[str] = Field(None, description="Площадь (строка, как на сайте, например '5 ha', '2000 m²')")
    url: HttpUrl = Field(..., description="URL объявления")
    source: str = Field(..., description="Источник парсера (например, mercadolibre)")
    image_url: Optional[HttpUrl] = None # URL основного изображения
    description: Optional[str] = None # Описание, если доступно
    date_published: Optional[datetime] = None # Дата публикации, если доступна
    date_scraped: datetime = Field(default_factory=datetime.now, description="Дата и время парсинга")
    
    # Дополнительные необязательные поля, которые могут извлекать парсеры
    attributes: Optional[Dict[str, Any]] = None # Другие атрибуты (удобства, особенности и т.д.)
    coordinates: Optional[Tuple[float, float]] = None # Координаты [широта, долгота]

    # Новые поля для формата поста
    posted_date: Optional[str] = Field(None, description="Дата публикации (строка, как на сайте)")
    deal_type: Optional[str] = Field("Продажа", description="Тип сделки (Продажа, Аренда)") # По умолчанию Продажа
    utilities: Optional[str] = Field("Не указано", description="Наличие коммуникаций (строка)") # По умолчанию не указано

    # Добавляем хештеги сюда же, чтобы они были частью объекта
    hashtags: List[str] = Field([], description="Список сгенерированных хештегов")

    @validator('id', pre=True, always=True)
    def set_id_from_url(cls, v, values):
        """Если ID не предоставлен, использовать URL в качестве ID."""
        if v is None and 'url' in values:
            return str(values['url']) # Преобразуем HttpUrl в строку
        return v

    class Config:
        validate_assignment = True # Проверять типы при присваивании
        anystr_strip_whitespace = True # Удалять пробелы в начале/конце строк
        extra = 'ignore' # Позволяет использовать дополнительные поля, не объявленные в модели 