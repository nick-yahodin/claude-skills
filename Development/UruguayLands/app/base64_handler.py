#!/usr/bin/env python3
"""
Модуль для обработки и сохранения Base64-изображений.
Предоставляет надежные функции для:
1. Декодирования Base64-строк в различных форматах
2. Определения типа изображения
3. Сохранения изображений на диск с валидацией
4. Обработки изображений (изменение размера, оптимизация)
"""

import os
import re
import base64
import logging
import hashlib
from typing import Dict, Optional, Tuple, Union
from datetime import datetime
from pathlib import Path
import aiohttp
import asyncio

# Устанавливаем logger для модуля
logger = logging.getLogger(__name__)

# Каталог для сохранения изображений
DEFAULT_IMAGE_DIR = "images"

# Поддерживаемые типы изображений и их расширения
IMAGE_TYPES = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif",
    "image/bmp": "bmp",
    "image/svg+xml": "svg"
}

# Шаблоны доступа к изображениям через API
IMAGE_API_TEMPLATES = [
    # Основной формат (2X - высокое разрешение)
    "https://http2.mlstatic.com/D_NQ_NP_2X_{item_id}-F.webp",
    # Второй формат (нумерованный)
    "https://http2.mlstatic.com/D_NQ_NP_2X_{item_id}-{number}.webp",
    # Стандартное разрешение
    "https://http2.mlstatic.com/D_NQ_NP_{item_id}-F.webp",
    # Стандартное разрешение с номером 
    "https://http2.mlstatic.com/D_NQ_NP_{item_id}-{number}.webp",
    # Альтернативные форматы (старые)
    "https://http2.mlstatic.com/D_NQ_NP_{item_id}-O.webp",
    "https://http2.mlstatic.com/D_NQ_NP_{item_id}-V.webp",
    # Форматы с дополнительными суффиксами
    "https://http2.mlstatic.com/D_NQ_NP_2X_{item_id}-MLA{item_id}-F.webp",
    "https://http2.mlstatic.com/D_NQ_NP_2X_{item_id}-MLU{item_id}-F.webp"
]

def is_base64_image(data_url: str) -> bool:
    """
    Проверяет, является ли строка корректным Base64-изображением.
    
    Args:
        data_url: строка с потенциальным Base64-изображением
        
    Returns:
        bool: True если строка похожа на Base64-изображение
    """
    if not data_url:
        return False
    
    # Проверка формата data:image/xxx;base64,
    if not data_url.startswith('data:image/'):
        return False
    
    # Проверка наличия маркера base64
    if ';base64,' not in data_url:
        return False
    
    return True

def get_image_format_from_data_url(data_url: str) -> Tuple[str, str, str]:
    """
    Извлекает тип изображения и данные из Base64 строки.
    
    Args:
        data_url: строка с Base64-изображением
        
    Returns:
        Tuple[str, str, str]: (mime_type, расширение, base64_data)
    """
    if not is_base64_image(data_url):
        raise ValueError("Переданная строка не является корректным Base64-изображением")
    
    # Разделяем на метаданные и данные
    header, b64_data = data_url.split(';base64,', 1)
    
    # Извлекаем тип изображения
    mime_match = re.match(r'data:([^;]+)', header)
    if not mime_match:
        # Если не найден тип, используем значение по умолчанию
        mime_type = "image/jpeg"
    else:
        mime_type = mime_match.group(1).lower()
    
    # Определяем расширение файла по MIME-типу
    extension = IMAGE_TYPES.get(mime_type, "jpg")  # По умолчанию jpg
    
    return mime_type, extension, b64_data

def decode_base64_image(b64_data: str) -> Optional[bytes]:
    """
    Декодирует Base64-данные в бинарный формат с валидацией.
    
    Args:
        b64_data: данные в формате Base64 (без префикса)
        
    Returns:
        Optional[bytes]: бинарные данные изображения или None при ошибке
    """
    try:
        # Удаляем все пробелы и переносы строк для улучшения совместимости
        cleaned_data = re.sub(r'\s+', '', b64_data)
        
        # Добавляем отсутствующие символы заполнения, если необходимо
        padding = 4 - (len(cleaned_data) % 4)
        if padding < 4:
            cleaned_data += "=" * padding
        
        # Декодируем с обработкой ошибок
        img_data = base64.b64decode(cleaned_data)
        return img_data
    except Exception as e:
        logger.error(f"Ошибка при декодировании Base64-данных: {e}")
        return None

def generate_image_filename(url: str, extension: str, img_id: Optional[str] = None) -> str:
    """
    Генерирует имя файла для изображения на основе URL и ID.
    
    Args:
        url: URL объявления или источник данных
        extension: расширение файла (без точки)
        img_id: опциональный ID изображения
        
    Returns:
        str: Уникальное имя файла
    """
    if img_id:
        # Если есть ID изображения, используем его
        return f"{img_id}.{extension}"
    
    # Создаем хеш от URL для уникального имени файла
    url_hash = hashlib.md5(url.encode()).hexdigest()[:10]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    return f"{url_hash}_{timestamp}.{extension}"

def save_base64_image(data_url: str, url: str, img_id: Optional[str] = None, directory: str = DEFAULT_IMAGE_DIR) -> Optional[str]:
    """
    Сохраняет Base64-изображение в файл.
    
    Args:
        data_url: строка с Base64-изображением
        url: URL объявления для генерации имени файла
        img_id: опциональный ID изображения
        directory: директория для сохранения
        
    Returns:
        Optional[str]: путь к сохраненному файлу или None при ошибке
    """
    if not is_base64_image(data_url):
        logger.warning(f"Переданная строка не является Base64-изображением: {data_url[:30]}...")
        return None
    
    try:
        # Получаем информацию о формате изображения
        mime_type, extension, b64_data = get_image_format_from_data_url(data_url)
        
        # Декодируем Base64-данные
        img_data = decode_base64_image(b64_data)
        if not img_data:
            logger.error("Не удалось декодировать Base64-данные")
            return None
        
        # Проверяем минимальный размер изображения
        if len(img_data) < 100:  # Вероятно, это не настоящее изображение
            logger.warning(f"Слишком маленький размер изображения: {len(img_data)} байт")
            return None
        
        # Создаем директорию, если она не существует
        os.makedirs(directory, exist_ok=True)
        
        # Генерируем имя файла
        filename = generate_image_filename(url, extension, img_id)
        file_path = os.path.join(directory, filename)
        
        # Сохраняем изображение
        with open(file_path, "wb") as f:
            f.write(img_data)
            
        logger.info(f"Base64-изображение успешно сохранено в файл: {file_path} ({len(img_data)} байт)")
        return file_path
        
    except Exception as e:
        logger.error(f"Ошибка при сохранении Base64-изображения: {e}")
        return None

def process_and_save_base64_image(data_url: str, url: str, img_id: Optional[str] = None) -> Optional[str]:
    """
    Обрабатывает Base64-изображение и сохраняет его с дополнительной валидацией.
    
    Args:
        data_url: строка с Base64-изображением
        url: URL объявления
        img_id: опциональный ID изображения
        
    Returns:
        Optional[str]: путь к сохраненному файлу или None при ошибке
    """
    # Проверка и сохранение изображения
    file_path = save_base64_image(data_url, url, img_id)
    if not file_path:
        return None
        
    # Здесь можно добавить дополнительную обработку изображения, если нужно
    # Например, проверка формата, изменение размера, оптимизация
    
    return file_path

def extract_base64_images_from_html(html: str, url: str, min_width: int = 200) -> Dict[str, str]:
    """
    Извлекает все Base64-изображения из HTML-страницы.
    
    Args:
        html: HTML-код страницы
        url: URL страницы для генерации имени файла
        min_width: минимальная ширина изображения в пикселях
        
    Returns:
        Dict[str, str]: словарь {имя_файла: путь_к_файлу}
    """
    saved_images = {}
    
    # Поиск всех Base64-изображений с атрибутом width
    pattern = r'<img[^>]+src="(data:image/[^;]+;base64,[^"]+)"[^>]+width="([^"]+)"'
    matches = re.findall(pattern, html)
    
    if not matches:
        logger.info(f"В HTML не найдено Base64-изображений")
        return saved_images
    
    logger.info(f"Найдено {len(matches)} Base64-изображений в HTML")
    
    # Сортируем изображения по размеру (от большего к меньшему)
    matches.sort(key=lambda x: int(x[1]) if x[1].isdigit() else 0, reverse=True)
    
    # Обрабатываем найденные изображения
    for i, (base64_img, width_str) in enumerate(matches):
        try:
            width = int(width_str) if width_str.isdigit() else 0
            
            # Пропускаем маленькие изображения
            if width < min_width:
                continue
                
            # Сохраняем изображение
            img_id = f"{hashlib.md5(url.encode()).hexdigest()[:6]}_{i+1}"
            file_path = process_and_save_base64_image(base64_img, url, img_id)
            
            if file_path:
                saved_images[f"image_{i+1}"] = file_path
                
        except Exception as e:
            logger.error(f"Ошибка при обработке Base64-изображения {i+1}: {e}")
    
    return saved_images

async def generate_image_variants(item_id: str) -> List[str]:
    """
    Генерирует все возможные варианты URL изображений для указанного ID.
    
    Args:
        item_id: ID товара (MLU-XXXXXXX)
        
    Returns:
        List[str]: Список всех возможных URL изображений
    """
    # Нормализуем ID (удаляем дефис, если есть)
    normalized_id = item_id.replace("-", "")
    pure_id = re.sub(r'^MLU', '', normalized_id)
    
    variants = []
    
    # Генерируем URL из шаблонов
    for template in IMAGE_API_TEMPLATES:
        if "{number}" in template:
            # Для шаблонов с номерами добавляем варианты без номера и с номерами от 2 до 10
            variants.append(template.format(item_id=normalized_id, number=""))
            for i in range(2, 11):
                variants.append(template.format(item_id=normalized_id, number=i))
        else:
            # Для шаблонов без номеров просто форматируем
            variants.append(template.format(item_id=normalized_id))
    
    # Добавляем дополнительные варианты с датами в ID
    date_patterns = ["", "637399", "683091", "820071", "941697", "994265"]
    for pattern in date_patterns:
        variants.append(f"https://http2.mlstatic.com/D_NQ_NP_2X_{pattern}{pure_id}-F.webp")
        variants.append(f"https://http2.mlstatic.com/D_NQ_NP_{pattern}{pure_id}-F.webp")
    
    return list(set(variants))  # Убираем дубликаты

async def check_image_url(url: str) -> bool:
    """
    Проверяет доступность изображения по URL.
    
    Args:
        url: URL изображения для проверки
        
    Returns:
        bool: Доступно ли изображение
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.head(url, allow_redirects=True, timeout=10) as response:
                if response.status == 200:
                    content_type = response.headers.get('Content-Type', '')
                    if 'image/' in content_type:
                        return True
    except Exception as e:
        logger.debug(f"Ошибка при проверке URL {url}: {e}")
    
    return False

async def save_image_from_url(url: str, save_path: str) -> bool:
    """
    Скачивает и сохраняет изображение.
    
    Args:
        url: URL изображения
        save_path: Путь для сохранения
        
    Returns:
        bool: Успешно ли сохранено изображение
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=30) as response:
                if response.status == 200:
                    os.makedirs(os.path.dirname(save_path), exist_ok=True)
                    with open(save_path, 'wb') as f:
                        f.write(await response.read())
                    logger.info(f"Изображение сохранено: {save_path}")
                    return True
    except Exception as e:
        logger.error(f"Ошибка при сохранении изображения {url}: {e}")
    
    return False

async def get_image_for_listing(url: str, item_id: str = None) -> Optional[str]:
    """
    Получает изображение для указанного URL листинга.
    Интегрирует все методы для максимальной надежности.
    
    Args:
        url: URL страницы товара
        item_id: ID товара (опционально, будет извлечен из URL если не указан)
        
    Returns:
        Optional[str]: Путь к сохраненному изображению или None
    """
    # Если ID не указан, извлекаем из URL
    if not item_id:
        id_match = re.search(r'MLU-?(\d+)', url)
        if id_match:
            item_id = id_match.group(0)
        else:
            logger.error(f"Не удалось извлечь ID товара из URL: {url}")
            return None
    
    logger.info(f"Получение изображения для {item_id}")
    
    # Создаем директорию для изображений
    img_dir = 'images'
    os.makedirs(img_dir, exist_ok=True)
    
    # 1. Пробуем прямые URL по шаблонам
    variants = await generate_image_variants(item_id)
    logger.info(f"Сгенерировано {len(variants)} вариантов URL для {item_id}")
    
    for i, img_url in enumerate(variants):
        if i % 10 == 0:
            logger.debug(f"Проверка вариантов {i+1}-{min(i+10, len(variants))} из {len(variants)}")
        
        is_available = await check_image_url(img_url)
        if is_available:
            logger.info(f"Найдено изображение для {item_id}: {img_url}")
            # Сохраняем изображение
            ext = img_url.split('.')[-1]
            save_path = f"{img_dir}/{item_id}.{ext}"
            if await save_image_from_url(img_url, save_path):
                return save_path
    
    # 2. Если не нашли по шаблонам, пробуем извлечь из HTML
    logger.info(f"Не удалось найти изображение по шаблонам для {item_id}. Пытаемся извлечь из HTML...")
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=30) as response:
                if response.status == 200:
                    html = await response.text()
                    
                    # Ищем ID изображения в HTML
                    patterns = [
                        r'"picture_id":"([^"]+)"',
                        r'"image_id":"([^"]+)"',
                        r'data-zoom="https://http2\.mlstatic\.com/D_NQ_NP_\d*_?([^"\.]+)',
                        r'https://http2\.mlstatic\.com/D_NQ_NP_\d*_?([^"\.]+)\.webp',
                        r'<img[^>]+src="https://http2\.mlstatic\.com/D_NQ_NP_[^"]*?(\d+)-[^"]*\.webp"',
                        r'content="https://http2\.mlstatic\.com/D_NQ_NP_[^"]*?(\d+)-[^"]*\.webp"'
                    ]
                    
                    image_id = None
                    for pattern in patterns:
                        matches = re.findall(pattern, html)
                        if matches:
                            image_id = matches[0]
                            logger.info(f"Извлечен ID изображения из страницы: {image_id}")
                            break
                    
                    if image_id:
                        # Формируем URL на основе найденного ID
                        img_urls = [
                            f"https://http2.mlstatic.com/D_NQ_NP_2X_{image_id}.webp",
                            f"https://http2.mlstatic.com/D_NQ_NP_{image_id}.webp"
                        ]
                        
                        # Проверяем каждый URL
                        for img_url in img_urls:
                            if await check_image_url(img_url):
                                # Сохраняем изображение
                                ext = img_url.split('.')[-1]
                                save_path = f"{img_dir}/{item_id}.{ext}"
                                if await save_image_from_url(img_url, save_path):
                                    return save_path
                    
                    # 3. Если не нашли ID, ищем готовые URL в HTML
                    img_url_patterns = [
                        r'(https://http2\.mlstatic\.com/D_NQ_NP_[^"]+\.webp)"',
                        r'(https://http2\.mlstatic\.com/D_NQ_NP_[^"]+\.jpg)"',
                        r'content="(https://http2\.mlstatic\.com/D_NQ_NP_[^"]+\.(webp|jpg))"'
                    ]
                    
                    for pattern in img_url_patterns:
                        img_matches = re.findall(pattern, html)
                        if img_matches:
                            for img_match in img_matches:
                                img_url = img_match[0] if isinstance(img_match, tuple) else img_match
                                if img_url.startswith('http') and 'http2.mlstatic.com' in img_url:
                                    # Проверяем, что это не заглушка
                                    if not any(x in img_url for x in ['mercadolibre.com/homes', 'placeholder', 'org-img']):
                                        # Проверяем доступность
                                        if await check_image_url(img_url):
                                            # Сохраняем изображение
                                            ext = img_url.split('.')[-1]
                                            save_path = f"{img_dir}/{item_id}.{ext}"
                                            if await save_image_from_url(img_url, save_path):
                                                return save_path
                    
                    # 4. Ищем Base64 изображения
                    base64_images = extract_base64_images_from_html(html, url, min_width=300)
                    if base64_images:
                        return list(base64_images.values())[0]  # Возвращаем первое найденное
    except Exception as e:
        logger.error(f"Ошибка при извлечении изображения из HTML: {e}")
    
    logger.warning(f"Не удалось найти изображение для {item_id}")
    return None

if __name__ == "__main__":
    # Простой тест для проверки работы модуля
    logging.basicConfig(level=logging.INFO)
    
    # Тестовое Base64-изображение (1x1 px прозрачный PNG)
    test_image = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
    
    # Проверка декодирования и сохранения
    file_path = process_and_save_base64_image(test_image, "https://test.com/example", "test_image")
    
    if file_path:
        print(f"Тест успешно пройден: {file_path}")
    else:
        print("Тест не пройден") 