#!/usr/bin/env python3
"""
Скрипт для анализа данных, собранных парсерами UruguayLands
Объединяет и анализирует данные из разных источников
"""

import os
import json
import re
import sys
import glob
import pandas as pd
from datetime import datetime
from pathlib import Path
import argparse

# Определяем корневую директорию проекта относительно текущего файла
# Это нужно, чтобы скрипт работал при запуске из любой директории
PROJECT_ROOT = Path(__file__).parent.parent
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "analysis_results"

def load_data_files(directory=DEFAULT_DATA_DIR, pattern="*.json"):
    """
    Загружает все JSON файлы с данными из указанной директории
    
    Args:
        directory: Путь к директории с данными
        pattern: Шаблон имени файла
        
    Returns:
        Список словарей с данными и метаданными
    """
    data_files = []
    
    # Получаем список файлов по шаблону
    file_paths = glob.glob(os.path.join(directory, pattern))
    
    if not file_paths:
        print(f"Не найдено файлов по шаблону {os.path.join(directory, pattern)}")
        return []
    
    for file_path in file_paths:
        try:
            file_info = {
                "path": file_path,
                "filename": os.path.basename(file_path),
                "size": os.path.getsize(file_path),
                "mtime": datetime.fromtimestamp(os.path.getmtime(file_path)),
                "data": None
            }
            
            # Извлекаем имя парсера из имени файла
            parser_match = re.search(r"(mercadolibre|infocasas|gallito)", file_info["filename"])
            if parser_match:
                file_info["parser"] = parser_match.group(1)
            else:
                file_info["parser"] = "unknown"
            
            # Загружаем данные
            with open(file_path, 'r', encoding='utf-8') as f:
                file_info["data"] = json.load(f)
                file_info["count"] = len(file_info["data"])
            
            data_files.append(file_info)
            print(f"Загружен файл: {file_path} ({file_info['count']} объявлений)")
            
        except Exception as e:
            print(f"Ошибка при загрузке файла {file_path}: {e}")
    
    return data_files

def prepare_dataframe(data_files):
    """
    Подготавливает DataFrame для анализа
    
    Args:
        data_files: Список словарей с данными
        
    Returns:
        pandas.DataFrame с объединенными данными
    """
    all_listings = []
    
    for file_info in data_files:
        parser_name = file_info["parser"]
        
        for listing in file_info["data"]:
            # Добавляем метаданные к каждому объявлению
            listing["_parser"] = parser_name
            listing["_file"] = file_info["filename"]
            listing["_timestamp"] = file_info["mtime"].isoformat()
            
            # Очищаем и нормализуем ключевые поля
            
            # Очистка цены
            if "price" in listing and listing["price"]:
                # Извлекаем числа и валюту
                # Улучшенный regex для разных форматов цен (включая U$S и .) 
                price_str = str(listing["price"]).replace(".", "") # Удаляем точки-разделители тысяч
                price_match = re.search(r"(USD|U\$S|EUR|€)?\s*(\d+[,]?\d*)", price_str, re.IGNORECASE)
                if price_match:
                    currency = price_match.group(1)
                    if currency and ("U$" in currency or "USD" in currency):
                         currency = "USD"
                    elif currency and ("€" in currency or "EUR" in currency):
                         currency = "EUR"
                    else: # Если валюта не указана явно, предполагаем USD
                        currency = "USD" 
                        
                    value_str = price_match.group(2).replace(",", ".") # Заменяем запятую на точку для float
                    try:
                        listing["price_value"] = float(value_str)
                        listing["price_currency"] = currency
                    except ValueError:
                        listing["price_value"] = None
                        listing["price_currency"] = None
                else:
                    listing["price_value"] = None
                    listing["price_currency"] = None
            else:
                 listing["price_value"] = None
                 listing["price_currency"] = None
            
            # Очистка площади
            if "area" in listing and listing["area"]:
                area_str = str(listing["area"])
                # Извлекаем числа и единицы измерения (m², m2, ha, hectáreas/hectarea)
                area_match = re.search(r"(\d+[.,]?\d*)\s*(m²|m2|ha|hectáreas?|hectarea)s?", area_str, re.IGNORECASE)
                if area_match:
                    value_str = area_match.group(1).replace(".", "").replace(",", ".")
                    unit = area_match.group(2).lower()
                    try:
                        listing["area_value"] = float(value_str)
                        listing["area_unit"] = unit
                        
                        # Конвертируем всё в квадратные метры для единообразия
                        if "ha" in unit or "hect" in unit:
                            listing["area_m2"] = float(value_str) * 10000
                        else:
                            listing["area_m2"] = float(value_str)
                    except ValueError:
                        listing["area_value"] = None
                        listing["area_unit"] = None
                        listing["area_m2"] = None
                else:
                    listing["area_value"] = None
                    listing["area_unit"] = None
                    listing["area_m2"] = None
            else:
                listing["area_value"] = None
                listing["area_unit"] = None
                listing["area_m2"] = None
            
            all_listings.append(listing)
    
    # Создаем DataFrame
    if all_listings:
        df = pd.DataFrame(all_listings)
        print(f"Создан DataFrame с {len(df)} объявлениями")
        # Преобразуем типы данных для корректной сортировки и анализа
        df['price_value'] = pd.to_numeric(df['price_value'], errors='coerce')
        df['area_m2'] = pd.to_numeric(df['area_m2'], errors='coerce')
        return df
    else:
        print("Нет данных для анализа")
        return pd.DataFrame()

def analyze_data(df):
    """
    Проводит базовый анализ данных
    
    Args:
        df: pandas.DataFrame с данными
        
    Returns:
        dict с результатами анализа
    """
    if df.empty:
        return {"error": "Нет данных для анализа"}
    
    results = {}
    
    # Общая статистика
    results["total_listings"] = len(df)
    results["unique_urls"] = df["url"].nunique() if "url" in df.columns else 0
    results["sources"] = df["_parser"].value_counts().to_dict() if "_parser" in df.columns else {}
    
    # Статистика по ценам (только USD)
    usd_prices = df[(df["price_value"].notna()) & (df["price_currency"] == "USD")]
    if not usd_prices.empty:
        results["price_usd"] = {
            "count": len(usd_prices),
            "min": usd_prices["price_value"].min(),
            "max": usd_prices["price_value"].max(),
            "mean": usd_prices["price_value"].mean(),
            "median": usd_prices["price_value"].median()
        }
        
        # Распределение по ценовым диапазонам (USD)
        price_bins = [0, 50000, 100000, 200000, 500000, 1000000, float('inf')]
        price_labels = ['0-50k', '50k-100k', '100k-200k', '200k-500k', '500k-1M', '1M+']
        # Добавляем right=False, чтобы включить левую границу (например, 50000 войдет в '50k-100k')
        results["price_usd_distribution"] = pd.cut(usd_prices["price_value"], bins=price_bins, labels=price_labels, right=False).value_counts().sort_index().to_dict()

    # Статистика по площади (в м2)
    area_stats = df[df["area_m2"].notna()]
    if not area_stats.empty:
        results["area_m2"] = {
            "count": len(area_stats),
            "min": area_stats["area_m2"].min(),
            "max": area_stats["area_m2"].max(),
            "mean": area_stats["area_m2"].mean(),
            "median": area_stats["area_m2"].median()
        }
        
        # Распределение по площади (в гектарах)
        area_bins = [0, 10000, 50000, 100000, 500000, 1000000, float('inf')] # 0, 1ha, 5ha, 10ha, 50ha, 100ha, 100ha+
        area_labels = ['< 1ha', '1-5ha', '5-10ha', '10-50ha', '50-100ha', '> 100ha']
        results["area_ha_distribution"] = pd.cut(area_stats["area_m2"], bins=area_bins, labels=area_labels, right=False).value_counts().sort_index().to_dict()
    
    # Статистика по локациям
    if "location" in df.columns:
        # Очищаем локации от лишних пробелов и приводим к нижнему регистру
        cleaned_locations = df["location"].str.strip().str.lower().replace({r'\s*-\s*': ', ', r'\s{2,}': ' '},
                                                                                 regex=True)
        # Извлекаем регионы (первое слово до запятой)
        df["region"] = cleaned_locations.str.extract(r'^([^,]+)').iloc[:, 0].str.strip()
        # Извлекаем город/населенный пункт (второе слово до запятой, если есть)
        df["city"] = cleaned_locations.str.extract(r'^[^,]+,\s*([^,]+)').iloc[:, 0].str.strip()
        
        # Заполняем пропуски в city значением region, если city не извлечен
        df["city"] = df["city"].fillna(df["region"])

        # Топ регионов и городов
        results["top_regions"] = df["region"].value_counts().head(15).to_dict()
        results["top_cities"] = df["city"].value_counts().head(15).to_dict()
    
    # Расчет цены за квадратный метр (только для USD и где есть площадь)
    price_per_m2 = df[(df["price_value"].notna()) &
                      (df["area_m2"].notna()) &
                      (df["price_currency"] == "USD") &
                      (df["area_m2"] > 0)].copy()
                      
    if not price_per_m2.empty:
        price_per_m2["price_per_m2"] = price_per_m2["price_value"] / price_per_m2["area_m2"]
        results["price_per_m2_usd"] = {
            "count": len(price_per_m2),
            "min": price_per_m2["price_per_m2"].min(),
            "max": price_per_m2["price_per_m2"].max(),
            "mean": price_per_m2["price_per_m2"].mean(),
            "median": price_per_m2["price_per_m2"].median()
        }
        
        # Топ предложений с наименьшей ценой за квадратный метр
        best_deals = price_per_m2.sort_values("price_per_m2").head(20)
        results["best_deals_price_per_m2"] = best_deals[["id", "title", "price", "area", "location", "url", "price_per_m2"]].round({'price_per_m2': 2}).to_dict('records')

    # Топ самых дорогих предложений (USD)
    if not usd_prices.empty:
        most_expensive = usd_prices.sort_values("price_value", ascending=False).head(10)
        results["most_expensive_usd"] = most_expensive[["id", "title", "price", "area", "location", "url"]].to_dict('records')

    # Топ самых больших участков (по м2)
    if not area_stats.empty:
        largest_areas = area_stats.sort_values("area_m2", ascending=False).head(10)
        results["largest_areas_m2"] = largest_areas[["id", "title", "price", "area", "location", "url"]].to_dict('records')

    return results

def print_analysis_results(results):
    """
    Выводит результаты анализа в консоль
    
    Args:
        results: Словарь с результатами анализа
    """
    if "error" in results:
        print(f"Ошибка: {results['error']}")
        return
    
    print("\n" + "=" * 60)
    print("                  РЕЗУЛЬТАТЫ АНАЛИЗА")
    print("=" * 60)
    
    print(f"\nОбщая статистика:")
    print(f"  - Всего объявлений загружено: {results.get('total_listings', 0)}")
    print(f"  - Уникальных URL: {results.get('unique_urls', 0)}")
    
    print("\nИсточники данных:")
    sources = results.get("sources", {})
    for source, count in sources.items():
        print(f"  - {source}: {count} объявлений")
    
    if "price_usd" in results:
        p = results["price_usd"]
        print(f"\nСтатистика цен (USD, {p.get('count',0)} объявлений):")
        print(f"  - Минимальная: ${p.get('min', 0):,.0f}")
        print(f"  - Максимальная: ${p.get('max', 0):,.0f}")
        print(f"  - Средняя: ${p.get('mean', 0):,.0f}")
        print(f"  - Медианная: ${p.get('median', 0):,.0f}")
    
    if "price_usd_distribution" in results:
        print("\nРаспределение по ценовым диапазонам (USD):")
        for price_range, count in results["price_usd_distribution"].items():
            print(f"  - {price_range}: {count} объявлений")
    
    if "area_m2" in results:
        a = results["area_m2"]
        print(f"\nСтатистика площади (кв. метры, {a.get('count', 0)} объявлений):")
        print(f"  - Минимальная: {a.get('min', 0):,.0f} м²")
        print(f"  - Максимальная: {a.get('max', 0):,.0f} м²")
        print(f"  - Средняя: {a.get('mean', 0):,.0f} м²")
        print(f"  - Медианная: {a.get('median', 0):,.0f} м²")
    
    if "area_ha_distribution" in results:
        print("\nРаспределение по площади (Гектары):")
        for area_range, count in results["area_ha_distribution"].items():
            print(f"  - {area_range}: {count} объявлений")
    
    if "top_regions" in results:
        print("\nТоп-15 Регионов:")
        for i, (region, count) in enumerate(results["top_regions"].items(), 1):
            if pd.notna(region):
                print(f"  {i:2d}. {region.title()}: {count}")

    if "top_cities" in results:
        print("\nТоп-15 Городов/Населенных пунктов:")
        for i, (city, count) in enumerate(results["top_cities"].items(), 1):
            if pd.notna(city):
                print(f"  {i:2d}. {city.title()}: {count}")
    
    if "price_per_m2_usd" in results:
        ppm = results["price_per_m2_usd"]
        print(f"\nЦена за квадратный метр (USD/м², {ppm.get('count',0)} объявлений):")
        print(f"  - Минимальная: ${ppm.get('min', 0):,.2f}")
        print(f"  - Максимальная: ${ppm.get('max', 0):,.2f}")
        print(f"  - Средняя: ${ppm.get('mean', 0):,.2f}")
        print(f"  - Медианная: ${ppm.get('median', 0):,.2f}")
    
    if "best_deals_price_per_m2" in results:
        print("\nТоп-20 предложений с лучшей ценой за квадратный метр (USD/м²):")
        for i, deal in enumerate(results["best_deals_price_per_m2"], 1):
            print(f"\n  {i}. {deal['title']}")
            print(f"     Цена: {deal['price']} | Площадь: {deal['area']} | Локация: {deal['location']}")
            print(f"     Цена за м²: ${deal['price_per_m2']:.2f} | ID: {deal['id']}")
            print(f"     URL: {deal['url']}")

    print("\n" + "=" * 60)
    print("            АНАЛИЗ ЗАВЕРШЕН")
    print("=" * 60)

def export_results(df, results, output_dir=DEFAULT_OUTPUT_DIR):
    """
    Экспортирует результаты анализа в файлы
    
    Args:
        df: pandas.DataFrame с данными
        results: Словарь с результатами анализа
        output_dir: Директория для сохранения результатов
    """
    # Создаем директорию для результатов
    os.makedirs(output_dir, exist_ok=True)
    
    # Текущая дата и время для имени файла
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # --- Экспорт в Excel --- 
    if not df.empty:
        excel_path = os.path.join(output_dir, f"listings_analysis_{timestamp}.xlsx")
        try:
            with pd.ExcelWriter(excel_path, engine='xlsxwriter') as writer:
                
                # Лист с полными данными (выбираем нужные колонки)
                export_cols = ['id', 'title', 'price', 'price_value', 'price_currency', 
                               'area', 'area_value', 'area_unit', 'area_m2', 
                               'location', 'region', 'city', 'url', '_parser', '_timestamp']
                df_export = df[[col for col in export_cols if col in df.columns]]
                df_export.to_excel(writer, sheet_name='All Listings', index=False)
                
                # Лист с лучшими предложениями по цене за м2
                if "best_deals_price_per_m2" in results:
                    best_deals_df = pd.DataFrame(results["best_deals_price_per_m2"])
                    best_deals_df.to_excel(writer, sheet_name='Best Deals (Price per m2)', index=False)
                
                # Лист с самыми дорогими
                if "most_expensive_usd" in results:
                    most_exp_df = pd.DataFrame(results["most_expensive_usd"])
                    most_exp_df.to_excel(writer, sheet_name='Most Expensive (USD)', index=False)
                
                # Лист с самыми большими
                if "largest_areas_m2" in results:
                    largest_df = pd.DataFrame(results["largest_areas_m2"])
                    largest_df.to_excel(writer, sheet_name='Largest Areas (m2)', index=False)

                # Лист со сводной статистикой
                summary_data = {
                    'Metric': [],
                    'Value': []
                }
                summary_data['Metric'].append('Total Listings'); summary_data['Value'].append(results.get('total_listings', 0))
                summary_data['Metric'].append('Unique URLs'); summary_data['Value'].append(results.get('unique_urls', 0))
                if 'price_usd' in results: 
                    p = results['price_usd']
                    summary_data['Metric'].append('Price USD Count'); summary_data['Value'].append(p.get('count', 0))
                    summary_data['Metric'].append('Price USD Min'); summary_data['Value'].append(p.get('min', 0))
                    summary_data['Metric'].append('Price USD Max'); summary_data['Value'].append(p.get('max', 0))
                    summary_data['Metric'].append('Price USD Mean'); summary_data['Value'].append(p.get('mean', 0))
                    summary_data['Metric'].append('Price USD Median'); summary_data['Value'].append(p.get('median', 0))
                if 'area_m2' in results:
                    a = results['area_m2']
                    summary_data['Metric'].append('Area m2 Count'); summary_data['Value'].append(a.get('count', 0))
                    summary_data['Metric'].append('Area m2 Min'); summary_data['Value'].append(a.get('min', 0))
                    summary_data['Metric'].append('Area m2 Max'); summary_data['Value'].append(a.get('max', 0))
                    summary_data['Metric'].append('Area m2 Mean'); summary_data['Value'].append(a.get('mean', 0))
                    summary_data['Metric'].append('Area m2 Median'); summary_data['Value'].append(a.get('median', 0))
                if 'price_per_m2_usd' in results:
                     ppm = results["price_per_m2_usd"]
                     summary_data['Metric'].append('Price/m2 USD Count'); summary_data['Value'].append(ppm.get('count', 0))
                     summary_data['Metric'].append('Price/m2 USD Min'); summary_data['Value'].append(ppm.get('min', 0))
                     summary_data['Metric'].append('Price/m2 USD Max'); summary_data['Value'].append(ppm.get('max', 0))
                     summary_data['Metric'].append('Price/m2 USD Mean'); summary_data['Value'].append(ppm.get('mean', 0))
                     summary_data['Metric'].append('Price/m2 USD Median'); summary_data['Value'].append(ppm.get('median', 0))
                
                summary_df = pd.DataFrame(summary_data)
                summary_df.to_excel(writer, sheet_name='Summary Statistics', index=False)

                # Форматирование чисел в Excel
                workbook = writer.book
                currency_format = workbook.add_format({'num_format': '$#,##0'})
                float_format = workbook.add_format({'num_format': '#,##0.00'})
                integer_format = workbook.add_format({'num_format': '#,##0'})
                
                # Применение форматов (пример для листа All Listings)
                worksheet_all = writer.sheets['All Listings']
                # Найти колонки по имени
                col_idx_price = df_export.columns.get_loc('price_value')
                col_idx_area = df_export.columns.get_loc('area_m2')
                worksheet_all.set_column(col_idx_price, col_idx_price, 12, currency_format)
                worksheet_all.set_column(col_idx_area, col_idx_area, 12, integer_format)
                # TODO: Применить форматы к другим листам по аналогии
                
            print(f"\nДанные экспортированы в Excel: {excel_path}")
        except Exception as e:
             print(f"\nОшибка при экспорте в Excel: {e}")
             traceback.print_exc()
    
    # --- Экспорт результатов в JSON --- 
    json_path = os.path.join(output_dir, f"analysis_summary_{timestamp}.json")
    try:
        # Конвертируем объекты pandas Series в словари для JSON
        results_for_json = results.copy()
        for key, value in results_for_json.items():
            if isinstance(value, pd.Series):
                results_for_json[key] = value.to_dict()
            elif isinstance(value, dict):
                 for sub_key, sub_value in value.items():
                     if isinstance(sub_value, pd.Series):
                         value[sub_key] = sub_value.to_dict()
        
        with open(json_path, 'w', encoding='utf-8') as f:
            # Используем json.dumps для обработки NaN и Inf
            json_output = json.dumps(results_for_json, 
                                     ensure_ascii=False, 
                                     indent=2, 
                                     default=lambda x: None if pd.isna(x) else x, # Заменяем NaN на null
                                     allow_nan=False) # Запрещаем NaN/Inf напрямую
            f.write(json_output)
        print(f"Результаты анализа сохранены в JSON: {json_path}")
    except Exception as e:
        print(f"\nОшибка при экспорте в JSON: {e}")
        traceback.print_exc()

def main():
    parser = argparse.ArgumentParser(description="Анализ данных UruguayLands")
    parser.add_argument('--dir', type=str, default=str(DEFAULT_DATA_DIR), 
                        help=f'Директория с JSON-файлами данных (по умолчанию: {DEFAULT_DATA_DIR})')
    parser.add_argument('--output', type=str, default=str(DEFAULT_OUTPUT_DIR), 
                        help=f'Директория для сохранения результатов (по умолчанию: {DEFAULT_OUTPUT_DIR})')
    args = parser.parse_args()
    
    print("\n" + "=" * 60)
    print("       АНАЛИЗ ДАННЫХ О ЗЕМЕЛЬНЫХ УЧАСТКАХ В УРУГВАЕ")
    print("=" * 60)
    
    # Загружаем данные
    data_files = load_data_files(directory=args.dir)
    
    if not data_files:
        print(f"В директории \'{args.dir}\' не найдены файлы с данными (*.json). Убедитесь, что вы запустили парсеры.")
        sys.exit(1)
    
    # Подготавливаем данные для анализа
    df = prepare_dataframe(data_files)
    
    if df.empty:
        print("Нет данных для анализа.")
        sys.exit(1)
    
    # Проводим анализ
    results = analyze_data(df)
    
    # Выводим результаты
    print_analysis_results(results)
    
    # Экспортируем результаты
    export_results(df, results, output_dir=args.output)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"Критическая ошибка при выполнении анализа: {e}")
        import traceback
        traceback.print_exc() 