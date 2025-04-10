#!/usr/bin/env python3
"""
Простой тест для проверки обработки Base64 изображений.
"""

import os
import base64
import asyncio
import logging
import sys
import json
from pathlib import Path
from typing import Dict, Any

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger('Base64Test')

# Добавляем путь к корню проекта
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

# Пример небольшого Base64 изображения (1x1 px прозрачный PNG)
SAMPLE_BASE64 = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="

# Более реалистичное изображение участка земли (небольшой JPEG в Base64)
REAL_IMAGE_BASE64 = "data:image/jpeg;base64,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"

async def test_base64_processing():
    """Тестирует сохранение Base64 изображения в файл."""
    logger.info("Запуск теста обработки Base64 изображений")
    
    # Создаем тестовую директорию для изображений
    img_folder = "images"
    os.makedirs(img_folder, exist_ok=True)
    
    # Тестируем разные типы Base64 изображений
    images_to_test = [
        {"name": "sample_png", "data": SAMPLE_BASE64, "expected_type": "png"},
        {"name": "real_image", "data": REAL_IMAGE_BASE64, "expected_type": "jpg"}
    ]
    
    results = []
    
    for img_test in images_to_test:
        logger.info(f"Тестирование изображения: {img_test['name']}")
        try:
            # Извлекаем тип изображения и данные из строки Base64
            if ',' in img_test['data']:
                b64_format, b64_data = img_test['data'].split(',', 1)
                
                # Определяем тип изображения из формата
                img_ext = 'jpg'  # По умолчанию jpg
                if 'image/png' in b64_format:
                    img_ext = 'png'
                elif 'image/jpeg' in b64_format or 'image/jpg' in b64_format:
                    img_ext = 'jpg'
                elif 'image/webp' in b64_format:
                    img_ext = 'webp'
                
                # Проверяем соответствие определенного типа ожидаемому
                if img_ext != img_test['expected_type']:
                    logger.warning(f"Определенный тип {img_ext} не соответствует ожидаемому {img_test['expected_type']}")
                
                # Создаем путь к файлу
                img_path = f"{img_folder}/{img_test['name']}.{img_ext}"
                
                # Декодируем Base64 и записываем в файл
                with open(img_path, "wb") as f:
                    f.write(base64.b64decode(b64_data))
                
                logger.info(f"Base64 изображение успешно сохранено в файл: {img_path}")
                
                # Проверяем размер файла
                file_size = os.path.getsize(img_path)
                logger.info(f"Размер файла: {file_size} байт")
                
                results.append({
                    "name": img_test['name'],
                    "success": True, 
                    "file_path": img_path, 
                    "file_size": file_size
                })
            else:
                logger.error(f"Неверный формат Base64 для {img_test['name']}")
                results.append({
                    "name": img_test['name'],
                    "success": False, 
                    "error": "Invalid Base64 format"
                })
        except Exception as e:
            logger.error(f"Ошибка при обработке изображения {img_test['name']}: {e}", exc_info=True)
            results.append({
                "name": img_test['name'],
                "success": False, 
                "error": str(e)
            })
    
    # Тест отправки в Telegram реального изображения
    if any(r["success"] for r in results):
        # Берем первое успешно сохраненное изображение
        successful_image = next((r for r in results if r["success"]), None)
        if successful_image:
            try:
                from app.telegram_poster import send_telegram_message_async
                
                # Создаем тестовый объект листинга
                test_listing = {
                    "title": "Тестовый участок земли (Base64)",
                    "price": "US$ 50.000",
                    "location": "Maldonado, Uruguay",
                    "area": "5000 m²",
                    "source": "MercadoLibre",
                    "deal_type": "Продажа",
                    "url": "https://example.com/test-land",
                    "image_url": successful_image["file_path"],  # Используем локальный файл
                    "hashtags": ["#TestBase64", "#Uruguay", "#Maldonado", "#TerrenosUY", "#MercadoLibre"]
                }
                
                # Пытаемся отправить
                logger.info("Отправка тестового сообщения с локальным изображением...")
                success = await send_telegram_message_async(test_listing)
                
                if success:
                    logger.info("✅ Тестовое сообщение успешно отправлено!")
                else:
                    logger.error("❌ Ошибка при отправке тестового сообщения")
                    
            except ImportError as e:
                logger.warning(f"Не удалось импортировать модуль telegram_poster: {e}")
            except Exception as e:
                logger.error(f"Ошибка при отправке в Telegram: {e}", exc_info=True)
    
    return {"success": any(r["success"] for r in results), "results": results}

if __name__ == "__main__":
    logger.info("Запуск теста Base64 изображений")
    result = asyncio.run(test_base64_processing())
    print(f"Результат: {json.dumps(result, indent=2)}")
    sys.exit(0 if result.get('success') else 1) 