#!/usr/bin/env python3
"""
Скрипт для настройки среды разработки UruguayLands
Проверяет и устанавливает все необходимые зависимости
"""
import os
import sys
import subprocess
import platform
from pathlib import Path

# Определяем корневую директорию проекта относительно текущего файла
PROJECT_ROOT = Path(__file__).parent.parent
REQUIREMENTS_FILE = PROJECT_ROOT / "requirements.txt"

def run_command(command):
    """
    Запускает команду и возвращает её вывод
    """
    print(f"Выполняем: {command}")
    try:
        result = subprocess.run(command, shell=True, check=True, 
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        print(result.stdout.decode('utf-8', errors='ignore'))
        return True
    except subprocess.CalledProcessError as e:
        print(f"Ошибка выполнения команды:")
        print(f"Команда: {command}")
        print(f"Код ошибки: {e.returncode}")
        print(f"STDOUT: {e.stdout.decode('utf-8', errors='ignore')}")
        print(f"STDERR: {e.stderr.decode('utf-8', errors='ignore')}")
        return False
    except Exception as e:
        print(f"Непредвиденная ошибка при выполнении команды '{command}': {e}")
        return False

def check_pip() -> Optional[str]:
    """Проверяет наличие и работоспособность pip, возвращает команду для запуска pip"""
    try:
        import pip
        print("✓ pip найден")
        return "pip" # Возвращаем просто 'pip', система найдет его в PATH
    except ImportError:
        print("✗ pip не установлен или не доступен в PYTHONPATH")
        
        # Проверяем, используется ли виртуальное окружение
        venv_path = None
        if hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix):
            print("ⓘ Активировано виртуальное окружение")
            venv_path = sys.prefix
        elif 'VIRTUAL_ENV' in os.environ:
             print("ⓘ Активировано виртуальное окружение (через VIRTUAL_ENV)")
             venv_path = os.environ['VIRTUAL_ENV']
        
        if venv_path:
            # Определяем путь к python и pip внутри venv
            if platform.system() == "Windows":
                python_exe = Path(venv_path) / "Scripts" / "python.exe"
                pip_exe = Path(venv_path) / "Scripts" / "pip.exe"
            else:
                python_exe = Path(venv_path) / "bin" / "python"
                pip_exe = Path(venv_path) / "bin" / "pip"
                
            # Проверяем существование pip
            if pip_exe.exists():
                print(f"✓ Найден pip в venv: {pip_exe}")
                return str(pip_exe)
            
            # Пробуем установить pip, если есть python
            if python_exe.exists():
                print("ⓘ Попытка установить pip в виртуальное окружение...")
                if run_command(f'"{python_exe}" -m ensurepip --upgrade'):
                    if pip_exe.exists():
                        print(f"✓ pip успешно установлен в venv: {pip_exe}")
                        return str(pip_exe)
                    else:
                        print("✗ Не удалось найти pip после установки.")
                else:
                     print("✗ Ошибка при выполнении ensurepip.")
            else:
                 print(f"✗ Не найден python в {venv_path} для установки pip.")
        
        print("✗ Не удалось найти или установить pip. Пожалуйста, установите pip вручную.")
        return None

def install_requirements():
    """Устанавливает необходимые зависимости из requirements.txt"""
    pip_cmd = check_pip()
    if not pip_cmd:
        print("✗ Установка зависимостей невозможна без pip.")
        return False
        
    if not REQUIREMENTS_FILE.exists():
        print(f"✗ Файл зависимостей не найден: {REQUIREMENTS_FILE}")
        return False
        
    print(f"Установка зависимостей из {REQUIREMENTS_FILE}...")
    if run_command(f'{pip_cmd} install -r "{REQUIREMENTS_FILE}"'):
        print("✓ Зависимости успешно установлены/обновлены.")
        
        # Отдельно устанавливаем браузеры для Playwright
        print("Установка браузеров для Playwright (может занять некоторое время)...")
        if run_command("playwright install firefox"):
             print("✓ Браузеры Playwright установлены.")
             return True
        else:
            print("✗ Ошибка при установке браузеров Playwright.")
            return False
    else:
        print("✗ Ошибка при установке зависимостей.")
        return False

def setup_directories():
    """Создает необходимые директории проекта"""
    print("Создание необходимых директорий...")
    directories = [
        PROJECT_ROOT / "data",
        PROJECT_ROOT / "logs",
        PROJECT_ROOT / "analysis_results" # Добавлено из analyze_data.py
        # PROJECT_ROOT / "test_results" # Папка test_results больше не используется напрямую
    ]
    
    all_created = True
    for directory in directories:
        try:
            directory.mkdir(parents=True, exist_ok=True)
            print(f"✓ Директория создана/существует: {directory.relative_to(PROJECT_ROOT)}")
        except Exception as e:
            print(f"✗ Ошибка при создании директории {directory}: {e}")
            all_created = False
    return all_created

def main():
    """Основная функция настройки"""
    print("=" * 60)
    print("       Настройка среды разработки UruguayLands")
    print("=" * 60)
    
    # Проверяем версию Python
    python_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    print(f"Версия Python: {python_version}")
    
    if sys.version_info < (3, 8):
        print("✗ Требуется Python 3.8 или выше")
        sys.exit(1)
    else:
        print("✓ Версия Python подходит.")
    
    # Создаем необходимые директории
    if not setup_directories():
        print("✗ Не удалось создать все необходимые директории. Установка прервана.")
        sys.exit(1)
    
    # Устанавливаем зависимости
    if not install_requirements():
         print("✗ Не удалось установить все зависимости. Проверьте ошибки выше.")
         sys.exit(1)
    
    print("=" * 60)
    print("✓ Настройка успешно завершена!")
    print("=" * 60)
    print("Теперь вы можете:")
    print(f"  - Запустить автоматический мониторинг: python {(PROJECT_ROOT / 'app' / 'main.py').relative_to(PROJECT_ROOT)}")
    print(f"  - Запустить парсер вручную: python {(PROJECT_ROOT / 'run_manual.py').relative_to(PROJECT_ROOT)}")
    print(f"  - Проанализировать данные: python {(PROJECT_ROOT / 'utils' / 'analyze_data.py').relative_to(PROJECT_ROOT)}")
    print(f"  - Проверить прокси: python {(PROJECT_ROOT / 'utils' / 'create_proxy_list.py').relative_to(PROJECT_ROOT)} --file <your_proxy_file>")
    print("Не забудьте настроить файл config/.env перед запуском основного скрипта!")
    
if __name__ == "__main__":
    # Переходим в корневую директорию проекта для корректной работы путей
    os.chdir(PROJECT_ROOT)
    main() 