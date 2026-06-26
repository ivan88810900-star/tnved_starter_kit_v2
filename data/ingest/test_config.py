#!/usr/bin/env python3
"""
Тестовый скрипт для проверки конфигурации
"""
import yaml
import os

def test_config():
    """Тест загрузки конфигурации"""
    config_path = "../sources_updated.yml"
    
    print(f"Проверяем конфигурацию: {config_path}")
    print(f"Файл существует: {os.path.exists(config_path)}")
    
    if os.path.exists(config_path):
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        
        print(f"Конфигурация загружена: {config is not None}")
        print(f"Ключи: {list(config.keys())}")
        
        if 'datasets' in config:
            print(f"Наборы данных: {list(config['datasets'].keys())}")
            
            if 'tariff_cet' in config['datasets']:
                tariff_config = config['datasets']['tariff_cet']
                print(f"Конфигурация tariff_cet:")
                print(f"  name: {tariff_config.get('name')}")
                print(f"  authority: {tariff_config.get('authority')}")
                print(f"  version: {tariff_config.get('version')}")
                print(f"  file_type: {tariff_config.get('file_type')}")
                print(f"  local_path: {tariff_config.get('local_path')}")
                print(f"  urls: {len(tariff_config.get('urls', []))}")
                print(f"  save_as: {len(tariff_config.get('save_as', []))}")
                print(f"  checksum: {len(tariff_config.get('checksum', []))}")
                
                # Проверяем существование файлов
                local_path = tariff_config.get('local_path', '')
                if local_path:
                    print(f"\nПроверяем директорию: {local_path}")
                    print(f"Директория существует: {os.path.exists(local_path)}")
                    
                    if os.path.exists(local_path):
                        files = os.listdir(local_path)
                        print(f"Файлов в директории: {len(files)}")
                        print(f"Первые 5 файлов: {files[:5]}")
            else:
                print("❌ tariff_cet не найден в datasets")
        else:
            print("❌ datasets не найден в конфигурации")
    else:
        print("❌ Файл конфигурации не найден")

if __name__ == "__main__":
    test_config()
















