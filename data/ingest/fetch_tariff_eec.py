#!/usr/bin/env python3
"""
Скрипт для загрузки тарифных данных с сайта ЕЭК
"""
import os
import sys
import hashlib
import yaml
import requests
from pathlib import Path
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup
import time
from datetime import datetime


class TariffEECFetcher:
    def __init__(self, base_url="https://eec.eaeunion.org/comission/department/catr/ett/"):
        self.base_url = base_url
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "tnved-pro/1.0"
        })
        self.version = "2025-01-01"
        self.download_dir = Path("data/raw/tariff_cet") / self.version
        self.sources_file = Path("data/sources.yml")
        
    def setup_directories(self):
        """Создание необходимых каталогов"""
        self.download_dir.mkdir(parents=True, exist_ok=True)
        print(f"📁 Создан каталог: {self.download_dir}")
    
    def get_page_content(self):
        """Получение содержимого страницы"""
        print(f"🌐 Загружаем страницу: {self.base_url}")
        
        try:
            response = self.session.get(self.base_url, timeout=60)
            response.raise_for_status()
            print(f"✅ Страница загружена ({len(response.content)} байт)")
            return response.content
        except requests.exceptions.RequestException as e:
            print(f"❌ Ошибка загрузки страницы: {e}")
            return None
    
    def find_pdf_links(self, html_content):
        """Поиск ссылок на PDF файлы"""
        print("🔍 Ищем ссылки на PDF файлы...")
        
        soup = BeautifulSoup(html_content, 'html.parser')
        pdf_links = []
        
        for link in soup.find_all('a', href=True):
            href = link['href']
            if href.lower().endswith('.pdf'):
                absolute_url = urljoin(self.base_url, href)
                pdf_links.append(absolute_url)
        
        print(f"📄 Найдено {len(pdf_links)} PDF файлов")
        return pdf_links
    
    def calculate_sha256(self, file_path):
        """Расчет SHA256 хеша файла"""
        sha256_hash = hashlib.sha256()
        with open(file_path, "rb") as f:
            for chunk in iter(lambda: f.read(4096), b""):
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest()
    
    def download_file_with_retry(self, url, file_path, max_retries=3):
        """Загрузка файла с повторными попытками"""
        for attempt in range(max_retries):
            try:
                print(f"📥 Загружаем: {url} (попытка {attempt + 1}/{max_retries})")
                
                response = self.session.get(url, timeout=60, stream=True)
                response.raise_for_status()
                
                # Сохраняем файл
                with open(file_path, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)
                
                file_size = file_path.stat().st_size
                sha256 = self.calculate_sha256(file_path)
                
                print(f"✅ [OK] {file_path.name} ({file_size} bytes, {sha256})")
                return True, file_size, sha256
                
            except requests.exceptions.RequestException as e:
                print(f"⚠️ Попытка {attempt + 1} неудачна: {e}")
                if attempt < max_retries - 1:
                    time.sleep(2 ** attempt)  # Экспоненциальная задержка
                else:
                    print(f"❌ Не удалось загрузить {url} после {max_retries} попыток")
                    return False, 0, None
            except Exception as e:
                print(f"❌ Неожиданная ошибка при загрузке {url}: {e}")
                return False, 0, None
        
        return False, 0, None
    
    def download_pdfs(self, pdf_urls):
        """Загрузка всех PDF файлов"""
        print(f"\n📥 Начинаем загрузку {len(pdf_urls)} PDF файлов...")
        
        downloaded_files = []
        total_size = 0
        
        for i, url in enumerate(pdf_urls, 1):
            print(f"\n--- Файл {i}/{len(pdf_urls)} ---")
            
            # Извлекаем имя файла из URL
            parsed_url = urlparse(url)
            filename = os.path.basename(parsed_url.path)
            
            if not filename or not filename.endswith('.pdf'):
                filename = f"document_{i}.pdf"
            
            file_path = self.download_dir / filename
            
            # Проверяем, существует ли файл
            if file_path.exists():
                existing_sha256 = self.calculate_sha256(file_path)
                print(f"📄 Файл уже существует: {filename}")
                
                # Проверяем целостность существующего файла
                try:
                    response = self.session.head(url, timeout=30)
                    if response.status_code == 200:
                        print(f"✅ Файл актуален, пропускаем загрузку")
                        file_size = file_path.stat().st_size
                        downloaded_files.append({
                            'url': url,
                            'filename': filename,
                            'size': file_size,
                            'sha256': existing_sha256
                        })
                        total_size += file_size
                        continue
                except:
                    pass
            
            # Загружаем файл
            success, file_size, sha256 = self.download_file_with_retry(url, file_path)
            
            if success:
                downloaded_files.append({
                    'url': url,
                    'filename': filename,
                    'size': file_size,
                    'sha256': sha256
                })
                total_size += file_size
            else:
                print(f"❌ Пропускаем файл: {filename}")
        
        print(f"\n📊 Итого загружено: {len(downloaded_files)} файлов, {total_size:,} байт")
        return downloaded_files
    
    def load_sources_config(self):
        """Загрузка конфигурации sources.yml"""
        if not self.sources_file.exists():
            print(f"⚠️ Файл {self.sources_file} не найден, создаем новый")
            return {
                'allowed_domains': [
                    'eec.eaeunion.org',
                    'www.eurasiancommission.org',
                    'customs.gov.ru',
                    'data.gov.ru',
                    'minprirody.gov.ru'
                ],
                'datasets': {}
            }
        
        try:
            with open(self.sources_file, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except Exception as e:
            print(f"❌ Ошибка загрузки {self.sources_file}: {e}")
            return None
    
    def save_sources_config(self, config):
        """Сохранение конфигурации sources.yml"""
        try:
            with open(self.sources_file, 'w', encoding='utf-8') as f:
                yaml.safe_dump(config, f, default_flow_style=False, 
                             allow_unicode=True, sort_keys=False)
            print(f"💾 Конфигурация сохранена: {self.sources_file}")
            return True
        except Exception as e:
            print(f"❌ Ошибка сохранения {self.sources_file}: {e}")
            return False
    
    def update_sources_config(self, downloaded_files):
        """Обновление конфигурации sources.yml"""
        print("\n📝 Обновляем конфигурацию sources.yml...")
        
        config = self.load_sources_config()
        if config is None:
            return False
        
        # Подготавливаем данные для tariff_cet
        urls = [file_info['url'] for file_info in downloaded_files]
        filenames = [file_info['filename'] for file_info in downloaded_files]
        checksums = [file_info['sha256'] for file_info in downloaded_files]
        
        # Обновляем или создаем блок tariff_cet
        config['datasets']['tariff_cet'] = {
            'name': 'Единый таможенный тариф (ЕТТ ЕАЭС)',
            'authority': 'ЕЭК',
            'version': self.version,
            'file_type': 'PDF',
            'urls': urls,
            'save_as': filenames,
            'checksum': checksums
        }
        
        # Сохраняем конфигурацию
        return self.save_sources_config(config)
    
    def run(self):
        """Основная функция выполнения"""
        print("🚀 Загрузка тарифных данных с сайта ЕЭК")
        print("=" * 50)
        
        # Создаем каталоги
        self.setup_directories()
        
        # Загружаем страницу
        html_content = self.get_page_content()
        if html_content is None:
            print("❌ Не удалось загрузить страницу")
            return False
        
        # Ищем PDF ссылки
        pdf_urls = self.find_pdf_links(html_content)
        if not pdf_urls:
            print("❌ PDF файлы не найдены")
            return False
        
        # Загружаем PDF файлы
        downloaded_files = self.download_pdfs(pdf_urls)
        if not downloaded_files:
            print("❌ Не удалось загрузить ни одного файла")
            return False
        
        # Обновляем конфигурацию
        if self.update_sources_config(downloaded_files):
            print("✅ Конфигурация обновлена успешно")
        else:
            print("⚠️ Ошибка обновления конфигурации")
        
        # Итоговый отчет
        print("\n" + "=" * 50)
        print("📋 ИТОГОВЫЙ ОТЧЕТ")
        print("=" * 50)
        print(f"🌐 Источник: {self.base_url}")
        print(f"📁 Каталог: {self.download_dir}")
        print(f"📄 Файлов загружено: {len(downloaded_files)}")
        print(f"💾 Общий размер: {sum(f['size'] for f in downloaded_files):,} байт")
        print(f"📝 Конфигурация: {self.sources_file}")
        
        print("\n📄 Загруженные файлы:")
        for file_info in downloaded_files:
            print(f"  ✅ {file_info['filename']} ({file_info['size']:,} bytes)")
        
        return True


def main():
    """Главная функция"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Загрузка тарифных данных с сайта ЕЭК')
    parser.add_argument('--url', default="https://eec.eaeunion.org/comission/department/catr/ett/",
                       help='URL страницы с тарифными данными')
    parser.add_argument('--version', default="2025-01-01",
                       help='Версия данных')
    parser.add_argument('--dry-run', action='store_true',
                       help='Только найти ссылки, не загружать файлы')
    
    args = parser.parse_args()
    
    fetcher = TariffEECFetcher(args.url)
    fetcher.version = args.version
    
    if args.dry_run:
        print("🔍 Режим проверки (dry-run)")
        fetcher.setup_directories()
        html_content = fetcher.get_page_content()
        if html_content:
            pdf_urls = fetcher.find_pdf_links(html_content)
            print(f"\nНайдено {len(pdf_urls)} PDF файлов:")
            for i, url in enumerate(pdf_urls, 1):
                print(f"  {i}. {url}")
    else:
        success = fetcher.run()
        sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
















