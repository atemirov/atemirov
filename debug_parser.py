#!/usr/bin/env python3
import requests
import re

def test_parse():
    url = "https://gist.githubusercontent.com/iamwildtuna/7772b7c84a11bf6e1385f23096a73a15/raw"
    
    print("Загружаю данные...")
    response = requests.get(url)
    content = response.text
    
    lines = content.strip().split('\n')
    print(f"Всего строк: {len(lines)}")
    
    # Тестовые строки из логов
    test_lines = [
        "157.240.253.174, 157.240.253.172, 157.240.253.167, 157.240.253.63, 157.240.253.32",
        "94.237.43.28 - API",
        "157.240.253.0/24",
        "162.159.140.0/24"
    ]
    
    ip_pattern = r'\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)(?:/[0-9]{1,2})?\b'
    
    print("\n=== ТЕСТ ПАРСИНГА ===")
    for test_line in test_lines:
        print(f"\nОбрабатываю: '{test_line}'")
        
        # Находим все IP в строке
        found_ips = re.findall(ip_pattern, test_line)
        print(f"  Найдено regex: {found_ips}")
        
        # Тест для запятых
        if ',' in test_line:
            parts = [part.strip() for part in test_line.split(',')]
            print(f"  Разделение запятыми: {parts}")
    
    print(f"\n=== ПОИСК В ФАЙЛЕ ===")
    target_patterns = ["157.240.253.0", "162.159.140.0"]
    
    for pattern in target_patterns:
        found_lines = []
        for i, line in enumerate(lines, 1):
            if pattern in line:
                found_lines.append(f"Строка {i}: {line.strip()}")
        
        if found_lines:
            print(f"\nНайдено '{pattern}':")
            for found_line in found_lines:
                print(f"  {found_line}")
        else:
            print(f"\n'{pattern}' НЕ НАЙДЕН")
    
    print(f"\n=== ОБРАБОТКА ВСЕХ СТРОК ===")
    all_ips = []
    
    for i, line in enumerate(lines[:50], 1):  # Первые 50 строк для теста
        line = line.strip()
        if not line:
            continue
            
        print(f"\nСтрока {i}: '{line}'")
        
        # Пропускаем route команды
        if 'route ADD' in line.upper():
            print("  -> Пропускаю: route команда")
            continue
            
        # Находим IP
        found_ips = re.findall(ip_pattern, line)
        
        if found_ips:
            print(f"  -> Найдено: {found_ips}")
            all_ips.extend(found_ips)
        else:
            # Ручная обработка
            clean_line = line
            
            # Удаляем комментарии
            for separator in [' - ', ' (', ' //']:
                if separator in clean_line:
                    clean_line = clean_line.split(separator)[0].strip()
            
            if ',' in clean_line:
                parts = [part.strip() for part in clean_line.split(',')]
                for part in parts:
                    if re.match(ip_pattern, part):
                        print(f"  -> Найден через запятую: {part}")
                        all_ips.append(part)
            elif re.match(ip_pattern, clean_line):
                print(f"  -> Найден после очистки: {clean_line}")
                all_ips.append(clean_line)
            else:
                print(f"  -> Не найдено IP")
    
    print(f"\nВсего найдено IP: {len(all_ips)}")
    print("Первые 10:", all_ips[:10])

if __name__ == "__main__":
    test_parse()