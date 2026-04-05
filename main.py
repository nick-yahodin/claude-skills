#!/usr/bin/env python3
"""
UruguayLands — парсер земельных участков в Уругвае.

Использование:
    python main.py                    # Полный цикл: поиск → обогащение → Telegram
    python main.py --no-send          # Только парсинг, без отправки
    python main.py --max 20           # Максимум 20 объявлений
    python main.py --min-price 5000   # Фильтр по мин. цене
    python main.py --export data/results.json  # Экспорт в JSON
"""

import asyncio
import argparse
import json
import logging
import sys
from datetime import datetime

from config import setup_logging, MAX_LISTINGS, TELEGRAM_BOT_TOKEN, DATA_DIR
from scraper import MercadoLibreScraper
from duplicate_checker import DuplicateChecker
from telegram_bot import TelegramSender

logger = logging.getLogger("main")


async def main():
    parser = argparse.ArgumentParser(description="UruguayLands Scraper")
    parser.add_argument("--max", type=int, default=MAX_LISTINGS, help="Max listings")
    parser.add_argument("--no-send", action="store_true", help="Skip Telegram")
    parser.add_argument("--no-enrich", action="store_true", help="Skip details API")
    parser.add_argument("--min-price", type=int, help="Min price USD")
    parser.add_argument("--max-price", type=int, help="Max price USD")
    parser.add_argument("--export", type=str, help="Export results to JSON file")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    setup_logging("DEBUG" if args.debug else "INFO")
    logger.info("=== UruguayLands Scraper ===")

    scraper = MercadoLibreScraper()

    try:
        # 1. Scrape
        listings = await scraper.scrape(
            max_results=args.max,
            enrich=not args.no_enrich,
            price_min=args.min_price,
            price_max=args.max_price,
        )

        if not listings:
            logger.warning("No listings found")
            return 1

        logger.info(f"Found {len(listings)} listings")

        # 2. Filter duplicates
        checker = DuplicateChecker()
        new_listings = checker.filter_new(listings)

        if not new_listings:
            logger.info("No new listings (all duplicates)")
            return 0

        logger.info(f"New listings: {len(new_listings)}")

        # 3. Export
        if args.export:
            _export(new_listings, args.export)

        # Auto-save raw results
        _export(
            new_listings,
            f"{DATA_DIR}/listings_{datetime.now():%Y%m%d_%H%M%S}.json",
        )

        # 4. Stats
        _print_stats(new_listings)

        # 5. Telegram
        if not args.no_send:
            if not TELEGRAM_BOT_TOKEN:
                logger.warning("TELEGRAM_BOT_TOKEN not set, skipping send")
                return 0

            sender = TelegramSender()
            sent = await sender.send_batch(new_listings)
            logger.info(f"Sent {sent} listings to Telegram")

        return 0

    except Exception as e:
        logger.error(f"Fatal error: {e}", exc_info=True)
        return 1

    finally:
        await scraper.close()


def _export(listings, path: str):
    """Сохраняет листинги в JSON."""
    import os
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

    data = [lst.model_dump(mode="json") for lst in listings]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    logger.info(f"Exported {len(listings)} listings to {path}")


def _print_stats(listings):
    """Печатает краткую статистику."""
    prices = [l.price_usd for l in listings if l.price_usd]
    areas = [l.area_m2 for l in listings if l.area_m2]
    with_coords = sum(1 for l in listings if l.latitude)
    with_utils = sum(1 for l in listings if l.utilities)
    with_images = sum(1 for l in listings if l.image_urls)
    recent = sum(1 for l in listings if l.is_recent)

    logger.info("── Statistics ──")
    logger.info(f"  Total: {len(listings)}")
    if prices:
        logger.info(
            f"  Price: ${min(prices):,.0f} – ${max(prices):,.0f} "
            f"(avg ${sum(prices)/len(prices):,.0f})"
        )
    if areas:
        logger.info(
            f"  Area: {min(areas):,.0f} – {max(areas):,.0f} m² "
            f"(avg {sum(areas)/len(areas):,.0f} m²)"
        )
    logger.info(f"  With coordinates: {with_coords}")
    logger.info(f"  With utilities info: {with_utils}")
    logger.info(f"  With images: {with_images}")
    logger.info(f"  Recent (<24h): {recent}")


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
