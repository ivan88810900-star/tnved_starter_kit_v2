#!/usr/bin/env python3
"""
Скрипт для загрузки источников данных TN VED Pro
"""
import os
import sys
import yaml
import hashlib
import requests
from urllib.parse import urlparse
from pathlib import Path


class DataDownloader:
    def __init__(self, config_path="sources.yml"):
        self.config_path = config_path
        self.config = self.load_config()
        self.download_dir = Path("raw")
        self.download_dir.mkdir(exist_ok=True)
    
    def load_config(self):
        """Загрузка конфигурации из YAML файла"""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except FileNotFoundError:
            print(f"❌ Файл конфигурации {self.config_path} не найден")
            sys.exit(1)
        except yaml.YAMLError as e:
            print(f"❌ Ошибка парсинга YAML: {e}")
            sys.exit(1)
    
    def is_domain_allowed(self, url):
        """Проверка разрешенных доменов"""
        parsed_url = urlparse(url)
        domain = parsed_url.netloc.lower()
        
        allowed_domains = self.config.get('allowed_domains', [])
        return any(domain.endswith(allowed) for allowed in allowed_domains)
    
    def calculate_checksum(self, file_path):
        """Расчет SHA256 хеша файла"""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest()
    
    def download_file(self, url, save_path):
        """Загрузка файла с проверками"""
        print(f"📥 Загружаем: {url}")
        
        # Проверяем домен
        if not self.is_domain_allowed(url):
            print(f"❌ Домен {urlparse(url).netloc} не разрешен")
            return False
        
        try:
            # Заголовки для имитации браузера
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            response = requests.get(url, headers=headers, timeout=30, stream=True)
            response.raise_for_status()
            
            # Сохраняем файл
            with open(save_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            print(f"✅ Загружено: {save_path}")
            return True
            
        except requests.exceptions.RequestException as e:
            print(f"❌ Ошибка загрузки {url}: {e}")
            return False
        except Exception as e:
            print(f"❌ Неожиданная ошибка: {e}")
            return False
    
    def update_checksum(self, dataset_key, file_path):
        """Обновление checksum в конфигурации"""
        if file_path.exists():
            checksum = self.calculate_checksum(file_path)
            self.config['datasets'][dataset_key]['checksum'] = checksum
            print(f"🔐 SHA256: {checksum}")
            return checksum
        return None
    
    def save_updated_config(self):
        """Сохранение обновленной конфигурации"""
        try:
            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.dump(self.config, f, default_flow_style=False, allow_unicode=True, sort_keys=False)
            print("💾 Конфигурация обновлена")
        except Exception as e:
            print(f"❌ Ошибка сохранения конфигурации: {e}")
    
    def download_dataset(self, dataset_key, dataset_config):
        """Загрузка одного набора данных"""
        print(f"\n📦 {dataset_config['name']} ({dataset_config['authority']})")
        print(f"   Версия: {dataset_config['version']}")
        print(f"   Тип файла: {dataset_config['file_type']}")
        
        save_path = self.download_dir / dataset_config['save_as']
        
        # Проверяем, существует ли файл
        if save_path.exists():
            print(f"⚠️  Файл уже существует: {save_path}")
            response = input("Перезаписать? (y/N): ").strip().lower()
            if response != 'y':
                print("⏭️  Пропускаем")
                return True
        
        # Загружаем файлы
        success = True
        for url in dataset_config['urls']:
            if not self.download_file(url, save_path):
                success = False
        
        if success:
            # Обновляем checksum
            self.update_checksum(dataset_key, save_path)
        
        return success
    
    def download_all(self):
        """Загрузка всех наборов данных"""
        print("🚀 Загрузка источников данных TN VED Pro")
        print(f"📁 Папка загрузки: {self.download_dir.absolute()}")
        
        datasets = self.config.get('datasets', {})
        if not datasets:
            print("❌ Наборы данных не найдены в конфигурации")
            return False
        
        success_count = 0
        total_count = len(datasets)
        
        for dataset_key, dataset_config in datasets.items():
            try:
                if self.download_dataset(dataset_key, dataset_config):
                    success_count += 1
            except Exception as e:
                print(f"❌ Ошибка обработки {dataset_key}: {e}")
        
        # Сохраняем обновленную конфигурацию
        self.save_updated_config()
        
        print(f"\n📊 Результат: {success_count}/{total_count} наборов загружено")
        
        if success_count == total_count:
            print("✅ Все данные загружены успешно!")
            return True
        else:
            print("⚠️  Некоторые данные не удалось загрузить")
            return False
    
    def list_datasets(self):
        """Список доступных наборов данных"""
        print("📋 Доступные наборы данных:")
        
        datasets = self.config.get('datasets', {})
        for key, config in datasets.items():
            print(f"\n🔹 {key}")
            print(f"   Название: {config['name']}")
            print(f"   Орган: {config['authority']}")
            print(f"   Версия: {config['version']}")
            print(f"   Тип: {config['file_type']}")
            print(f"   Файл: {config['save_as']}")
            if config.get('checksum'):
                print(f"   SHA256: {config['checksum'][:16]}...")
    
    def verify_checksums(self):
        """Проверка целостности загруженных файлов"""
        print("🔍 Проверка целостности файлов...")
        
        datasets = self.config.get('datasets', {})
        for key, config in datasets.items():
            file_path = self.download_dir / config['save_as']
            expected_checksum = config.get('checksum', '')
            
            if not file_path.exists():
                print(f"❌ {key}: файл не найден")
                continue
            
            if not expected_checksum:
                print(f"⚠️  {key}: checksum не указан")
                continue
            
            actual_checksum = self.calculate_checksum(file_path)
            if actual_checksum == expected_checksum:
                print(f"✅ {key}: целостность подтверждена")
            else:
                print(f"❌ {key}: checksum не совпадает")
                print(f"   Ожидался: {expected_checksum}")
                print(f"   Получен:  {actual_checksum}")


def main():
    """Главная функция"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Загрузка источников данных TN VED Pro')
    parser.add_argument('--list', action='store_true', help='Показать список наборов данных')
    parser.add_argument('--verify', action='store_true', help='Проверить целостность файлов')
    parser.add_argument('--config', default='sources.yml', help='Путь к файлу конфигурации')
    parser.add_argument('--dataset', help='Загрузить конкретный набор данных')
    
    args = parser.parse_args()
    
    downloader = DataDownloader(args.config)
    
    if args.list:
        downloader.list_datasets()
    elif args.verify:
        downloader.verify_checksums()
    elif args.dataset:
        datasets = downloader.config.get('datasets', {})
        if args.dataset in datasets:
            downloader.download_dataset(args.dataset, datasets[args.dataset])
            downloader.save_updated_config()
        else:
            print(f"❌ Набор данных '{args.dataset}' не найден")
            sys.exit(1)
    else:
        downloader.download_all()


if __name__ == "__main__":
    main()
















