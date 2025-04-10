#!/usr/bin/env python3
"""
Модуль для управления списком уже виденных/опубликованных объявлений.
"""

import json
import logging
import os
from pathlib import Path
from typing import Set, Optional, List

logger = logging.getLogger(__name__)

DEFAULT_STATE_FILE = Path("data/seen_listings.json")

class ListingManager:
    """
    Управляет состоянием виденных объявлений (хранит их ID или URL).
    """
    def __init__(self, state_file: Path = DEFAULT_STATE_FILE):
        self.state_file = state_file
        self.seen_ids: Set[str] = self._load_state()

    def _load_state(self) -> Set[str]:
        """Загружает ID виденных объявлений из файла."""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Ожидаем список ID в файле
                    if isinstance(data, list):
                        logger.info(f"Загружено {len(data)} ID виденных объявлений из {self.state_file}")
                        return set(data)
                    else:
                        logger.warning(f"Некорректный формат файла состояния {self.state_file}. Ожидался список.")
            except json.JSONDecodeError:
                logger.error(f"Ошибка декодирования JSON в файле состояния: {self.state_file}")
            except Exception as e:
                logger.error(f"Ошибка загрузки файла состояния {self.state_file}: {e}")
        else:
            logger.info(f"Файл состояния {self.state_file} не найден. Начинаем с пустым списком.")
            
        # Возвращаем пустой set, если файл не найден или произошла ошибка
        return set()

    def _save_state(self):
        """Сохраняет текущий набор ID виденных объявлений в файл."""
        try:
            # Создаем директорию, если она не существует
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            
            with open(self.state_file, 'w', encoding='utf-8') as f:
                # Сохраняем как список для лучшей читаемости JSON
                json.dump(sorted(list(self.seen_ids)), f, indent=2)
            logger.info(f"Сохранено {len(self.seen_ids)} ID виденных объявлений в {self.state_file}")
        except Exception as e:
            logger.error(f"Ошибка сохранения файла состояния {self.state_file}: {e}")

    def is_new(self, listing_identifier: str) -> bool:
        """
        Проверяет, является ли объявление новым (не было видено ранее).
        
        Args:
            listing_identifier: Уникальный идентификатор объявления (URL или ID в виде строки).
            
        Returns:
            True, если объявление новое, иначе False.
        """
        if not listing_identifier:
            logger.warning("Получен пустой идентификатор объявления для проверки новизны.")
            return False # Считаем не новым
            
        return listing_identifier not in self.seen_ids

    def add_seen(self, listing_identifier: str):
        """
        Добавляет идентификатор объявления в список виденных и сохраняет состояние.
        
        Args:
            listing_identifier: Уникальный идентификатор объявления (URL или ID в виде строки).
        """
        if listing_identifier:
            if listing_identifier not in self.seen_ids:
                 self.seen_ids.add(listing_identifier)
                 self._save_state() # Сохраняем после каждого добавления
                 logger.debug(f"Добавлен новый идентификатор в список виденных: {listing_identifier}")
            # else:
                 # Нет смысла логгировать, если уже видели
                 # logger.debug(f"Идентификатор уже был в списке виденных: {listing_identifier}")
        else:
             logger.warning("Попытка добавить пустой идентификатор.")

    # --- Старые методы (оставляем для совместимости, если где-то используются, но они не нужны для main.py) ---
    # def filter_new(self, listings: List[dict]) -> List[dict]: ...
    # def mark_as_seen(self, listings: List[dict]): ...

    # Можно удалить filter_new и mark_as_seen, если они больше нигде не используются.
    # Мы их не будем исправлять, так как основной цикл main.py их не вызывает.

    # def filter_new(self, listings: List[dict]) -> List[dict]:
    #     """
    #     Фильтрует список объявлений, возвращая только новые.
    #     
    #     Args:
    #         listings: Список словарей с данными объявлений.
    #         
    #     Returns:
    #         Список словарей только с новыми объявлениями.
    #     """
    #     new_listings = [lst for lst in listings if self.is_new(lst)]
    #     logger.info(f"Найдено {len(new_listings)} новых объявлений из {len(listings)}.")
    #     return new_listings

    # def mark_as_seen(self, listings: List[dict]):
    #     """
    #     Отмечает все объявления из списка как виденные.
    #     
    #     Args:
    #         listings: Список словарей с данными объявлений.
    #     """
    #     added_count = 0
    #     for listing in listings:
    #         listing_id = listing.get('id') or listing.get('url')
    #         if listing_id and listing_id not in self.seen_ids:
    #             self.seen_ids.add(listing_id)
    #             added_count += 1
    #     
    #     if added_count > 0:
    #         self._save_state()
    #         logger.info(f"Отмечено {added_count} объявлений как виденные.") 