#!/usr/bin/env python3
"""
Скрипт для запуска тестов TN VED Pro Backend
"""
import subprocess
import sys
import os


def run_tests():
    """Запуск всех тестов"""
    print("🧪 Запуск тестов TN VED Pro Backend...")
    
    # Устанавливаем переменные окружения для тестов
    os.environ["DB_URL"] = "sqlite:///./test.db"
    os.environ["AI_OFFLINE_MODE"] = "false"
    os.environ["ALLOW_EXTERNAL_AI"] = "true"
    os.environ["AUDIT_LOGGING"] = "false"
    os.environ["ADMIN_API_KEY"] = "test-admin-key"
    
    try:
        # Запускаем pytest
        result = subprocess.run([
            "python", "-m", "pytest", 
            "tests/",
            "-v",
            "--tb=short",
            "--color=yes"
        ], check=True)
        
        print("✅ Все тесты прошли успешно!")
        return 0
        
    except subprocess.CalledProcessError as e:
        print(f"❌ Тесты завершились с ошибкой: {e}")
        return e.returncode
    except FileNotFoundError:
        print("❌ pytest не найден. Установите зависимости:")
        print("pip install -r requirements.txt")
        return 1


def run_specific_test(test_file):
    """Запуск конкретного теста"""
    print(f"🧪 Запуск теста: {test_file}")
    
    try:
        result = subprocess.run([
            "python", "-m", "pytest", 
            f"tests/{test_file}",
            "-v",
            "--tb=short",
            "--color=yes"
        ], check=True)
        
        print(f"✅ Тест {test_file} прошел успешно!")
        return 0
        
    except subprocess.CalledProcessError as e:
        print(f"❌ Тест {test_file} завершился с ошибкой: {e}")
        return e.returncode


def run_coverage():
    """Запуск тестов с покрытием кода"""
    print("🧪 Запуск тестов с покрытием кода...")
    
    try:
        result = subprocess.run([
            "python", "-m", "pytest", 
            "tests/",
            "--cov=app",
            "--cov-report=html",
            "--cov-report=term",
            "-v"
        ], check=True)
        
        print("✅ Тесты с покрытием завершены!")
        print("📊 Отчет о покрытии сохранен в htmlcov/")
        return 0
        
    except subprocess.CalledProcessError as e:
        print(f"❌ Тесты с покрытием завершились с ошибкой: {e}")
        return e.returncode


if __name__ == "__main__":
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == "coverage":
            exit_code = run_coverage()
        elif command.endswith(".py"):
            exit_code = run_specific_test(command)
        else:
            print("❌ Неизвестная команда. Использование:")
            print("python run_tests.py              # Все тесты")
            print("python run_tests.py coverage     # С покрытием")
            print("python run_tests.py test_file.py # Конкретный тест")
            exit_code = 1
    else:
        exit_code = run_tests()
    
    sys.exit(exit_code)
















