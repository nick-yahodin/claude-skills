#!/usr/bin/env python3
"""
Скрипт для быстрого запуска парсеров UruguayLands.
"""

import asyncio
import argparse
import sys
from app.main import main, run_mercadolibre_parser, run_infocasas_parser, save_listings

async def run_with_args():
    """Запускает парсеры с аргументами командной строки."""
    parser = argparse.ArgumentParser(description="Запуск парсеров UruguayLands")
    parser.add_argument("--parser", "-p", choices=["mercadolibre", "infocasas", "all"], 
                        default="all", help="Какой парсер запустить")
    parser.add_argument("--pages", "-n", type=int, default=1, 
                        help="Количество страниц для обработки")
    parser.add_argument("--details", "-d", action="store_true", 
                        help="Обрабатывать детали объявлений")
    parser.add_argument("--headless", action="store_true", 
                        help="Запустить браузер в фоновом режиме")
    
    args = parser.parse_args()
    listings = []
    
    print(f"Запуск парсера: {args.parser}")
    print(f"Количество страниц: {args.pages}")
    print(f"Обрабатывать детали: {args.details}")
    print(f"Фоновый режим: {args.headless}")
    
    if args.parser == "mercadolibre" or args.parser == "all":
        ml_listings = await run_mercadolibre_parser(
            max_pages=args.pages,
            headless=args.headless,
            with_details=args.details
        )
        print(f"MercadoLibre: найдено {len(ml_listings)} объявлений")
        listings.extend(ml_listings)
    
    if args.parser == "infocasas" or args.parser == "all":
        ic_listings = await run_infocasas_parser(
            max_pages=args.pages,
            headless=args.headless,
            with_details=args.details
        )
        print(f"InfoCasas: найдено {len(ic_listings)} объявлений")
        listings.extend(ic_listings)
    
    print(f"Всего найдено: {len(listings)} объявлений")
    
    if listings:
        save_listings(listings)
        print("Результаты сохранены в папку data/")

if __name__ == "__main__":
    try:
        asyncio.run(run_with_args())
    except KeyboardInterrupt:
        print("\nПрограмма остановлена пользователем.")
        sys.exit(0)
    except Exception as e:
        print(f"Ошибка: {e}")
        sys.exit(1) 