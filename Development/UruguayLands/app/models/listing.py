#!/usr/bin/env python3
"""
Модель данных для объявлений о недвижимости.
"""

from typing import Optional, List, Dict, Tuple, Any
from pydantic import BaseModel, HttpUrl, Field, validator
from datetime import datetime

class Listing(BaseModel):
    """Модель данных для объявления о недвижимости."""
    id: Optional[str] = None  # Уникальный ID объявления
    title: Optional[str] = Field(None, description="Заголовок объявления")
    price: Optional[str] = Field(None, description="Цена (в формате источника)")
    location: Optional[str] = Field(None, description="Местоположение")
    area: Optional[str] = Field(None, description="Площадь (например '5 ha', '2000 m²')")
    url: HttpUrl = Field(..., description="URL объявления")
    source: str = Field(..., description="Источник (mercadolibre, infocasas)")
    image_url: Optional[HttpUrl] = None  # URL основного изображения
    description: Optional[str] = None  # Описание объявления
    
    # Метаданные
    date_published: Optional[datetime] = None # Дата публикации, если доступна
    date_scraped: datetime = Field(default_factory=datetime.now)
    
    # Дополнительные данные
    attributes: Optional[Dict[str, Any]] = None # Другие атрибуты
    coordinates: Optional[Tuple[float, float]] = None # Координаты [широта, долгота]
    
    # Данные для форматирования сообщений
    posted_date: Optional[str] = Field(None, description="Дата публикации (строка)")
    deal_type: Optional[str] = Field("Продажа", description="Тип сделки")
    utilities: Optional[str] = Field("Не указано", description="Коммуникации")
    
    # Хештеги и теги
    hashtags: List[str] = Field(default_factory=list, description="Хештеги")

    @validator('id', pre=True, always=True)
    def set_id_from_url(cls, v, values):
        """Если ID не предоставлен, использовать URL в качестве ID."""
        if v is None and 'url' in values:
            return str(values['url'])
        return v

    class Config:
        validate_assignment = True
        anystr_strip_whitespace = True
        extra = 'ignore' 