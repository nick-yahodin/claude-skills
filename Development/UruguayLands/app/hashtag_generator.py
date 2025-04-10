#!/usr/bin/env python3
"""
Модуль для генерации хэштегов на основе данных объявления.
"""

import logging
import re
from typing import List, Dict, Any, Set

logger = logging.getLogger(__name__)

# --- Словари для генерации хэштегов --- 

# Ключевые слова в тексте -> Хэштег
FEATURE_KEYWORDS = {
    # Особенности
    r'abejas|colmen': '#Пчеловодство',
    r'monte|bosque|árbol|arbol': '#Лес',
    r'agua|arroyo|río|rio|pozo|manantial|cañada|canada|laguna': '#Вода',
    r'electricidad|luz|ute': '#Электричество',
    r'tranquilo|silencio|paz': '#ТихоеМесто',
    r'camino|acceso|ruta': '#УДороги',
    r'sin\s+construcciones|sin\s+vecinos|deshabitado': '#Уединенный',
    r'plantación|plantacion|frutal|cultivo|huerta|olivos': '#ДляПосадок',
    r'cercado|alambrado|perimetral': '#Огорожено',
    r'escritura|título|titulo|registrado|documentación|documentacion': '#ДокументыВПорядке',
    r'vista|panorámica|panoramica': '#СВидом',
    r'costa|playa|mar|arena|balneario': '#Побережье',
    # Тип участка
    r'chacra': '#Чакра',
    r'campo|ganader|agrícola|agricola|forestal|productivo': '#Кампо',
    r'terreno|lote|solar': '#Участок',
    # Строения
    r'casa|rancho|galp[oó]n|caba[ñn]a|tinglado|vivienda|construcci[oó]n|mejoras|container': '#ЕстьСтроения',
    # Сделка
    r'permuta?|permuto': '#Пермута',
    r'financia': '#Финансирование',
    # Удобства
    r'internet|fibra': '#Интернет',
    r'saneamiento': '#Канализация'
}

# Регионы Уругвая -> Хэштег
REGION_HASHTAGS = {
    'artigas': '#Artigas',
    'canelones': '#Canelones',
    'cerro largo': '#CerroLargo',
    'colonia': '#Colonia',
    'durazno': '#Durazno',
    'flores': '#Flores',
    'florida': '#Florida',
    'lavalleja': '#Lavalleja',
    'maldonado': '#Maldonado',
    'montevideo': '#Montevideo',
    'paysandu': '#Paysandu',
    'paysandú': '#Paysandu', # Учет ударения
    'rio negro': '#RioNegro',
    'rivera': '#Rivera',
    'rocha': '#Rocha',
    'salto': '#Salto',
    'san jose': '#SanJose',
    'san josé': '#SanJose', # Учет ударения
    'soriano': '#Soriano',
    'tacuarembo': '#Tacuarembo',
    'tacuarembó': '#Tacuarembo', # Учет ударения
    'treinta y tres': '#TreintaYTres'
}

# --- Основная функция --- 

def generate_hashtags(listing: Dict[str, Any]) -> List[str]:
    """
    Генерирует список хэштегов для объявления на основе его данных.
    Анализирует заголовок, локацию и описание.
    
    Args:
        listing: Словарь с данными объявления.
        
    Returns:
        Список хэштегов.
    """
    hashtags: Set[str] = set()
    
    # 1. Добавляем источник
    source = listing.get("source")
    if source:
        hashtags.add(f"#{source.capitalize()}")
        
    # 2. Собираем текст для анализа
    title = listing.get('title', '')
    location = listing.get('location', '')
    description = listing.get('description', title) # Используем title, если нет описания
    area = listing.get('area', '')
    # Объединяем все текстовые поля для поиска ключевых слов
    full_text = f"{title} {location} {description} {area}".lower()
    
    # 3. Генерируем хэштеги по ключевым словам
    for pattern, hashtag in FEATURE_KEYWORDS.items():
        if re.search(pattern, full_text, re.IGNORECASE):
            hashtags.add(hashtag)

    # 4. Генерируем хэштеги по локации
    location_lower = location.lower()
    region_found = False
    for region_keyword, region_hashtag in REGION_HASHTAGS.items():
        if region_keyword in location_lower:
            hashtags.add(region_hashtag)
            region_found = True
            # Можно добавить логику для извлечения города/населенного пункта, если нужно
            # Например, извлечь часть строки до названия региона
            try:
                city_part = location_lower.split(region_keyword)[0].strip(' ,-')
                # Убираем общие слова типа "departamento"
                city_part = re.sub(r'departamento\s+de', '', city_part).strip()
                if city_part and len(city_part) > 2: # Простая проверка, что это не просто остатки
                    # Преобразуем в хэштег (убираем пробелы, спецсимволы, делаем CamelCase)
                    city_hashtag = '#' + re.sub(r'[^a-zA-Z0-9]', '', city_part.title().replace(' ', ''))
                    # Добавляем, только если хэштег не слишком короткий и не совпадает с регионом
                    if len(city_hashtag) > 3 and city_hashtag.lower() != region_hashtag.lower():
                       hashtags.add(city_hashtag)
            except Exception as loc_err:
                logger.debug(f"Ошибка при извлечении города из '{location}': {loc_err}")
            break # Нашли регион, дальше не ищем (для предотвращения дублей типа #Rocha #LaPalomaRocha)
            
    # Если регион не найден, добавляем общий тэг
    if not region_found:
        hashtags.add("#UbicacionDesconocida")
        
    # 5. Добавляем хэштег по размеру участка (если указан)
    if area and area != 'N/A':
        area_match_ha = re.search(r'(\d+[.,]?\d*)\s*(ha|hect[áa]reas?)', area, re.IGNORECASE)
        area_match_m2 = re.search(r'(\d+[.,]?\d*)\s*(m²|m2|metros|mts)', area, re.IGNORECASE)
        size_ha = 0
        if area_match_ha:
            try:
                size_ha = float(area_match_ha.group(1).replace(',', '.'))
            except ValueError:
                pass
        elif area_match_m2:
             try:
                size_m2 = float(area_match_m2.group(1).replace(',', '.'))
                size_ha = size_m2 / 10000
             except ValueError:
                 pass
        
        if size_ha > 0:
            if size_ha < 1:
                hashtags.add("#MenosDe1Ha")
            elif size_ha < 5:
                hashtags.add("#De1a5Ha")
            elif size_ha < 10:
                hashtags.add("#De5a10Ha")
            elif size_ha < 50:
                 hashtags.add("#De10a50Ha")
            elif size_ha < 100:
                 hashtags.add("#De50a100Ha")
            else:
                 hashtags.add("#MasDe100Ha")

    # 6. Добавляем общие хэштеги
    hashtags.add("#Uruguay")
    hashtags.add("#TerrenosUY")
    hashtags.add("#InmueblesUY")
    
    logger.debug(f"Сгенерированные хэштеги для ID {listing.get('id', 'N/A')}: {sorted(list(hashtags))}")
    return sorted(list(hashtags)) # Возвращаем отсортированный список

# --- Тестовая функция --- 
if __name__ == "__main__":
    print("Тестирование генератора хэштегов...")
    test_listings = [
        {
            "source": "MercadoLibre",
            "title": "Campo de 12 hectáreas en Colonia con costa de arroyo",
            "location": "Colonia del Sacramento, Colonia",
            "description": "Campo productivo con buena tierra y acceso a agua, ideal para agricultura o ganadería. Casa a reciclar.",
            "area": "12 hectáreas"
        },
        {
            "source": "InfoCasas",
            "title": "Terreno en Piriápolis con vista al mar, 4500 m²",
            "location": "Piriápolis, Maldonado",
            "description": "Hermoso terreno con vista panorámica al mar en Piriápolis, ideal para proyecto turístico. Luz en la puerta.",
            "area": "4500 m²"
        },
        {
             "source": "Gallito",
             "title": "Chacra de 5ha en Minas",
             "location": "Minas, Lavalleja",
             "description": "Hermosa chacra con arroyo, casa principal, galpón y árboles frutales. Ideal para producción y descanso. Permuto.",
             "area": "5 ha"
        },
        {
             "source": "MercadoLibre",
             "title": "Terreno sin mejoras 500m2",
             "location": "Ciudad de la Costa", # Без региона
             "description": "Terreno limpio en zona tranquila",
             "area": "500 m2"
        }
    ]
    
    for i, listing in enumerate(test_listings):
        print(f"\n--- Объявление #{i+1} ---")
        print(f"Входные данные: {listing}")
        generated_tags = generate_hashtags(listing)
        print(f"Сгенерированные хэштеги: {' '.join(generated_tags)}") 