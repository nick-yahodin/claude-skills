#!/usr/bin/env python3
"""
Скрипт для тестирования прямого API-доступа к изображениям MercadoLibre.
Позволяет получать изображения напрямую через API, минуя веб-скрапинг.
"""

import argparse
import asyncio
import aiohttp
import logging
import os
import re
import json
import sys
from datetime import datetime
from typing import List, Dict, Any, Optional, Tuple

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("MercadoLibreImageAPI")

# Схемы доступа к изображениям через API
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

# Расширения для проверки
IMAGE_EXTENSIONS = ["webp", "jpg", "jpeg", "png"]

async def check_image_url(session: aiohttp.ClientSession, url: str) -> Tuple[bool, Optional[str]]:
    """
    Проверяет доступность изображения по URL.
    
    Args:
        session: Сессия aiohttp
        url: URL изображения для проверки
        
    Returns:
        Tuple[bool, Optional[str]]: (Доступно ли изображение, URL если доступно или None)
    """
    try:
        async with session.head(url, allow_redirects=True, timeout=10) as response:
            if response.status == 200:
                content_type = response.headers.get('Content-Type', '')
                if 'image/' in content_type:
                    return True, url
    except Exception as e:
        logger.debug(f"Ошибка при проверке URL {url}: {e}")
    
    return False, None

async def save_image(session: aiohttp.ClientSession, url: str, save_path: str) -> bool:
    """
    Скачивает и сохраняет изображение.
    
    Args:
        session: Сессия aiohttp
        url: URL изображения
        save_path: Путь для сохранения
        
    Returns:
        bool: Успешно ли сохранено изображение
    """
    try:
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

async def get_item_images(item_id: str, save_dir: str = "images") -> List[str]:
    """
    Получает изображения для указанного ID товара MercadoLibre.
    
    Args:
        item_id: ID товара (MLU-XXXXXXX)
        save_dir: Директория для сохранения изображений
        
    Returns:
        List[str]: Список путей к сохраненным изображениям
    """
    saved_images = []
    
    # Генерируем все возможные варианты URL
    all_variants = await generate_image_variants(item_id)
    logger.info(f"Сгенерировано {len(all_variants)} вариантов URL для {item_id}")
    
    # Создаем сессию для HTTP-запросов
    async with aiohttp.ClientSession() as session:
        # Проверяем все варианты URL
        for i, url in enumerate(all_variants):
            if i % 10 == 0:
                logger.info(f"Проверка вариантов {i+1}-{min(i+10, len(all_variants))} из {len(all_variants)}")
            
            is_available, available_url = await check_image_url(session, url)
            
            if is_available:
                logger.info(f"Найдено изображение для {item_id}: {available_url}")
                
                # Сохраняем изображение
                ext = available_url.split('.')[-1]
                save_path = f"{save_dir}/{item_id}_{len(saved_images) + 1}.{ext}"
                if await save_image(session, available_url, save_path):
                    saved_images.append(save_path)
                
                # Если нашли хотя бы одно изображение, пытаемся найти ещё несколько
                # и затем прекращаем поиск остальных вариантов
                if len(saved_images) >= 5:
                    logger.info(f"Найдено достаточно изображений ({len(saved_images)}), прекращаем поиск")
                    break
    
    # Проверяем, нашли ли хоть одно изображение
    if not saved_images:
        logger.warning(f"Не найдено ни одного изображения для {item_id}")
    else:
        logger.info(f"Найдено {len(saved_images)} изображений для {item_id}")
    
    return saved_images

async def get_image_from_url(url: str, save_dir: str = "images") -> Optional[str]:
    """
    Извлекает ID товара из URL и получает изображения.
    
    Args:
        url: URL страницы товара MercadoLibre
        save_dir: Директория для сохранения изображений
        
    Returns:
        Optional[str]: Путь к основному изображению или None
    """
    # Извлекаем ID товара из URL
    item_id_match = re.search(r'MLU-?(\d+)', url)
    if not item_id_match:
        logger.error(f"Не удалось извлечь ID товара из URL: {url}")
        return None
    
    item_id = item_id_match.group(0)
    logger.info(f"Извлечен ID товара: {item_id}")
    
    # Получаем изображения
    saved_images = await get_item_images(item_id, save_dir)
    
    # Возвращаем путь к основному изображению, если есть
    return saved_images[0] if saved_images else None

async def fetch_product_data_api(item_id: str) -> Dict[str, Any]:
    """
    Пытается получить данные о товаре через API MercadoLibre.
    
    Args:
        item_id: ID товара (MLU-XXXXXXX)
        
    Returns:
        Dict[str, Any]: Данные о товаре или пустой словарь
    """
    # Нормализуем ID (удаляем дефис, если есть)
    normalized_id = item_id.replace("-", "")
    
    # Формируем URL API для получения данных о товаре
    api_url = f"https://api.mercadolibre.com/items/{normalized_id}"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(api_url, timeout=30) as response:
                if response.status == 200:
                    data = await response.json()
                    logger.info(f"Получены данные через API для {item_id}")
                    return data
                else:
                    status = response.status
                    text = await response.text()
                    logger.warning(f"API вернул статус {status}: {text[:100]}")
    except Exception as e:
        logger.error(f"Ошибка при запросе к API для {item_id}: {e}")
    
    return {}

async def extract_image_id_from_page(url: str) -> Optional[str]:
    """
    Извлекает ID изображения напрямую со страницы объявления.
    
    Args:
        url: URL страницы товара MercadoLibre
        
    Returns:
        Optional[str]: ID изображения или None, если не удалось извлечь
    """
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
                    
                    for pattern in patterns:
                        matches = re.findall(pattern, html)
                        if matches:
                            image_id = matches[0]
                            logger.info(f"Извлечен ID изображения из страницы: {image_id}")
                            return image_id
                    
                    logger.warning(f"Не удалось извлечь ID изображения из страницы. Ищем полные URL изображений...")
                    
                    # Если не нашли ID, ищем полные URL изображений
                    img_url_patterns = [
                        r'(https://http2\.mlstatic\.com/D_NQ_NP_[^"]+\.webp)"',
                        r'(https://http2\.mlstatic\.com/D_NQ_NP_[^"]+\.jpg)"',
                        r'content="(https://http2\.mlstatic\.com/D_NQ_NP_[^"]+\.(webp|jpg))"'
                    ]
                    
                    all_img_urls = []
                    for pattern in img_url_patterns:
                        img_matches = re.findall(pattern, html)
                        if img_matches:
                            for img_match in img_matches:
                                if isinstance(img_match, tuple):
                                    img_url = img_match[0]
                                else:
                                    img_url = img_match
                                if img_url.startswith('http') and 'http2.mlstatic.com' in img_url:
                                    all_img_urls.append(img_url)
                    
                    if all_img_urls:
                        logger.info(f"Найдено {len(all_img_urls)} прямых URL изображений на странице")
                        return "|".join(all_img_urls)  # Возвращаем URL, объединенные разделителем
                    
                    logger.warning("Не удалось найти прямые URL изображений на странице")
                else:
                    logger.warning(f"Ошибка при получении страницы: статус {response.status}")
    except Exception as e:
        logger.error(f"Ошибка при извлечении ID изображения из страницы: {e}")
    
    return None

async def get_all_product_data(url: str, save_dir: str = "images", save_json: bool = True) -> Dict[str, Any]:
    """
    Получает все данные о товаре, включая изображения.
    
    Args:
        url: URL страницы товара MercadoLibre
        save_dir: Директория для сохранения изображений
        save_json: Сохранять ли результаты в JSON
        
    Returns:
        Dict[str, Any]: Все данные о товаре
    """
    # Извлекаем ID товара из URL
    item_id_match = re.search(r'MLU-?(\d+)', url)
    if not item_id_match:
        logger.error(f"Не удалось извлечь ID товара из URL: {url}")
        return {"success": False, "error": "Не удалось извлечь ID товара"}
    
    item_id = item_id_match.group(0)
    normalized_id = item_id.replace("-", "")
    logger.info(f"Извлечен ID товара: {item_id}")
    
    # Создаем результирующий словарь
    result = {
        "item_id": item_id,
        "url": url,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "api_data": {},
        "images": []
    }
    
    # Получаем данные через API
    api_data = await fetch_product_data_api(item_id)
    if api_data:
        result["api_data"] = api_data
        result["success"] = True
        
        # Извлекаем важные данные из API
        if "title" in api_data:
            result["title"] = api_data["title"]
        if "price" in api_data:
            result["price"] = api_data["price"]
            result["currency_id"] = api_data.get("currency_id", "UYU")
        if "location" in api_data:
            result["location"] = api_data["location"]
        if "seller_address" in api_data:
            address = api_data["seller_address"]
            location_parts = []
            if "city" in address and address["city"]:
                location_parts.append(address["city"]["name"])
            if "state" in address and address["state"]:
                location_parts.append(address["state"]["name"])
            if location_parts:
                result["location_text"] = ", ".join(location_parts)
    
    # Получаем изображения через генерацию URL по шаблонам
    os.makedirs(save_dir, exist_ok=True)
    images = await get_item_images(item_id, save_dir)
    
    # Если не удалось получить изображения через шаблоны, пробуем извлечь прямо со страницы
    if not images:
        logger.info("Не удалось получить изображения через шаблоны. Пытаемся извлечь со страницы...")
        image_data = await extract_image_id_from_page(url)
        
        if image_data:
            if "|" in image_data:  # Если получили URL изображений, а не ID
                # Обрабатываем случай, когда вернулись URL изображений
                img_urls = image_data.split("|")
                logger.info(f"Получены прямые URL изображений со страницы: {len(img_urls)}")
                
                # Скачиваем каждое изображение
                async with aiohttp.ClientSession() as session:
                    for i, img_url in enumerate(img_urls):
                        ext = img_url.split('.')[-1]
                        save_path = f"{save_dir}/{item_id}_{i+1}.{ext}"
                        if await save_image(session, img_url, save_path):
                            images.append(save_path)
            else:
                # Обрабатываем случай, когда вернулся ID изображения
                logger.info(f"Получен ID изображения: {image_data}, генерируем URL...")
                img_templates = [
                    f"https://http2.mlstatic.com/D_NQ_NP_2X_{image_data}-F.webp",
                    f"https://http2.mlstatic.com/D_NQ_NP_{image_data}-F.webp",
                    f"https://http2.mlstatic.com/D_NQ_NP_2X_{image_data}-O.webp"
                ]
                
                async with aiohttp.ClientSession() as session:
                    for i, img_url in enumerate(img_templates):
                        is_available, available_url = await check_image_url(session, img_url)
                        if is_available:
                            ext = available_url.split('.')[-1]
                            save_path = f"{save_dir}/{item_id}_{i+1}.{ext}"
                            if await save_image(session, available_url, save_path):
                                images.append(save_path)
    
    if images:
        result["images"] = images
        result["main_image"] = images[0]
        result["success"] = True
    
    # Сохраняем результаты в JSON, если запрошено
    if save_json:
        try:
            json_dir = "api_results"
            os.makedirs(json_dir, exist_ok=True)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            json_path = f"{json_dir}/{item_id}_{timestamp}.json"
            
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            
            logger.info(f"Данные сохранены в {json_path}")
        except Exception as e:
            logger.error(f"Ошибка при сохранении JSON: {e}")
    
    return result

async def process_urls(urls: List[str], save_dir: str = "images", save_json: bool = True) -> Dict[str, Any]:
    """
    Обрабатывает список URL и получает данные для каждого.
    
    Args:
        urls: Список URL для обработки
        save_dir: Директория для сохранения изображений
        save_json: Сохранять ли результаты в JSON
        
    Returns:
        Dict[str, Any]: Результаты обработки всех URL
    """
    results = {
        "total": len(urls),
        "success": 0,
        "failed": 0,
        "items": []
    }
    
    for i, url in enumerate(urls):
        logger.info(f"Обработка URL {i+1}/{len(urls)}: {url}")
        
        try:
            # Получаем данные для URL
            item_data = await get_all_product_data(url, save_dir, False)  # Не сохраняем отдельные JSON
            
            # Добавляем результат в общий список
            results["items"].append(item_data)
            
            # Обновляем счетчики
            if item_data.get("success", False):
                results["success"] += 1
            else:
                results["failed"] += 1
        except Exception as e:
            logger.error(f"Ошибка при обработке URL {url}: {e}")
            results["failed"] += 1
            results["items"].append({
                "url": url,
                "success": False,
                "error": str(e)
            })
    
    # Сохраняем общие результаты в JSON
    if save_json:
        try:
            json_dir = "api_results"
            os.makedirs(json_dir, exist_ok=True)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            json_path = f"{json_dir}/batch_results_{timestamp}.json"
            
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(results, f, ensure_ascii=False, indent=2)
            
            logger.info(f"Общие результаты сохранены в {json_path}")
        except Exception as e:
            logger.error(f"Ошибка при сохранении общих результатов в JSON: {e}")
    
    logger.info(f"Всего URL: {results['total']}, Успешно: {results['success']}, Ошибок: {results['failed']}")
    
    return results

def parse_args():
    """Разбор аргументов командной строки."""
    parser = argparse.ArgumentParser(description="Получение изображений и данных товаров MercadoLibre через API")
    parser.add_argument("--urls", nargs="+", help="Список URL для обработки")
    parser.add_argument("--url-file", help="Файл со списком URL (по одному на строку)")
    parser.add_argument("--save-dir", default="images", help="Директория для сохранения изображений")
    parser.add_argument("--no-json", action="store_true", help="Не сохранять результаты в JSON")
    
    return parser.parse_args()

async def main():
    """Основная функция для запуска обработки."""
    args = parse_args()
    
    urls = []
    
    # Получаем список URL из аргументов или файла
    if args.urls:
        urls = args.urls
    elif args.url_file:
        try:
            with open(args.url_file, "r", encoding="utf-8") as f:
                urls = [line.strip() for line in f if line.strip()]
        except Exception as e:
            logger.error(f"Ошибка при чтении файла URL: {e}")
            return
    else:
        # Предопределенные URL для тестирования
        urls = [
            "https://terreno.mercadolibre.com.uy/MLU-712986794-venta-terreno-loteo-barrio-privado-la-arbolada-fraccionamiento-costa-de-oro-_JM",
            "https://terreno.mercadolibre.com.uy/MLU-704632172-lotes-entre-el-campo-y-el-bosque-a-un-minuto-del-mar-_JM",
            "https://terreno.mercadolibre.com.uy/MLU-706539090-barrio-semi-privado-colonia-del-sacramento-_JM",
            "https://terreno.mercadolibre.com.uy/MLU-639860029-terreno-en-barrio-privado-verde-mora-_JM",
            "https://terreno.mercadolibre.com.uy/MLU-711738830-se-vende-terreno-220m2-con-casa-construida-y-espacio-para-auto-en-piedra-blancas-_JM"
        ]
    
    if not urls:
        logger.error("Не указаны URL для обработки")
        return
    
    # Если указан только один URL, обрабатываем его отдельно
    if len(urls) == 1:
        await get_all_product_data(urls[0], args.save_dir, not args.no_json)
    else:
        # Обрабатываем несколько URL
        await process_urls(urls, args.save_dir, not args.no_json)

if __name__ == "__main__":
    asyncio.run(main()) 