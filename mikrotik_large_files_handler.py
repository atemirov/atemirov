#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import os
import sys
import argparse
from datetime import datetime
import time
import math

# Для SSH подключения
try:
    import paramiko
    SSH_AVAILABLE = True
except ImportError:
    SSH_AVAILABLE = False

def download_ip_list(url):
    """Загружает список IP-адресов из указанного URL"""
    try:
        print(f"Загружаем данные из {url}...")
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        
        ip_list = [line.strip() for line in response.text.split('\n') if line.strip()]
        print(f"Загружено {len(ip_list)} IP-адресов")
        return ip_list
        
    except requests.exceptions.RequestException as e:
        print(f"Ошибка при загрузке данных: {e}")
        return None

def generate_optimized_rsc_file(ip_list, list_name="rkn", output_file=None, clear_existing=False, split_files=False):
    """
    Генерирует оптимизированный .rsc файл для больших списков IP-адресов
    Поддерживает разделение на несколько файлов и оптимизированные команды
    """
    if not ip_list:
        print("Список IP-адресов пуст")
        return False, []
    
    if not output_file:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = f"mikrotik_{list_name}_{timestamp}.rsc"
    
    # Определяем, нужно ли разделение файлов
    max_addresses_per_file = 5000  # Максимум адресов в одном файле
    large_file = len(ip_list) > max_addresses_per_file
    
    if large_file and split_files:
        return generate_split_files(ip_list, list_name, output_file, clear_existing)
    else:
        return generate_single_large_file(ip_list, list_name, output_file, clear_existing)

def generate_single_large_file(ip_list, list_name, output_file, clear_existing):
    """Создает один оптимизированный файл для большого списка"""
    try:
        commands = []
        total_addresses = len(ip_list)
        
        # Заголовок с инструкциями
        commands.extend([
            f"# MikroTik RouterOS script - Optimized for large IP lists",
            f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"# Address list: {list_name}",
            f"# Total addresses: {total_addresses}",
            f"# ",
            f"# ВАЖНО: Для больших файлов используйте:",
            f"# /import file-name={os.path.basename(output_file)} verbose=yes",
            f"# ",
            f"# Процесс может занять несколько минут!",
            f"# Следите за логами: /log print follow where topics~\"system\"",
            f"",
            f"# Отключаем автоматическое обновление интерфейса для ускорения",
            f":global oldverbose [/system logging get [find topics~\"info\"] action]",
            f"/system logging set [find topics~\"info\"] action=memory",
            f""
        ])
        
        # Лог начала импорта
        commands.append(f":log info \"=== Starting import of {total_addresses} IP addresses to list '{list_name}' ===\"")
        commands.append("")
        
        # Очистка существующего списка с подтверждением
        if clear_existing:
            commands.extend([
                f":log info \"Clearing existing address list: {list_name}\"",
                f":local count [/ip firewall address-list print count-only where list=\"{list_name}\"]",
                f":if (\$count > 0) do={{",
                f"  :log info \"Removing \$count existing entries...\"",
                f"  /ip firewall address-list remove [find list=\"{list_name}\"]",
                f"  :log info \"Existing list cleared\"",
                f"}} else={{",
                f"  :log info \"List was empty, nothing to clear\"",
                f"}}",
                ""
            ])
        
        # Оптимизированное добавление IP-адресов
        batch_size = 25  # Меньший размер батча для стабильности
        total_batches = math.ceil(len(ip_list) / batch_size)
        
        commands.append(f":log info \"Adding addresses in {total_batches} batches of {batch_size} each\"")
        commands.append("")
        
        for i in range(0, len(ip_list), batch_size):
            batch = ip_list[i:i + batch_size]
            batch_num = (i // batch_size) + 1
            
            # Прогресс в логах
            if batch_num % 10 == 1 or batch_num == total_batches:
                progress = (batch_num / total_batches) * 100
                commands.append(f":log info \"Processing batch {batch_num}/{total_batches} ({progress:.1f}% complete)\"")
            
            # Создаем блок команд с обработкой ошибок
            commands.extend([
                f"# Batch {batch_num}: addresses {i+1}-{min(i+batch_size, len(ip_list))}",
                f":do {{"
            ])
            
            # Добавляем IP-адреса в батче
            for ip in batch:
                if '/' in ip or '.' in ip:
                    commands.append(f"  /ip firewall address-list add list={list_name} address={ip} comment=\"auto-added\"")
            
            commands.extend([
                f"}} on-error={{",
                f"  :log error \"Error in batch {batch_num}: \$[/system script get \\\"import\\\"]\"",
                f"}}",
                ""
            ])
            
            # Добавляем паузы для очень больших списков
            if len(ip_list) > 10000 and batch_num % 20 == 0:
                commands.extend([
                    f":log info \"Pausing for system stability...\"",
                    f":delay 2s",
                    ""
                ])
        
        # Финальная проверка и восстановление логирования
        commands.extend([
            f"# Проверяем результат",
            f":local final_count [/ip firewall address-list print count-only where list=\"{list_name}\"]",
            f":log info \"=== Import completed. Final count: \$final_count addresses in list '{list_name}' ===\"",
            f"",
            f"# Восстанавливаем логирование",
            f"/system logging set [find topics~\"info\"] action=\$oldverbose",
            f"",
            f":log info \"MikroTik IP list update finished successfully\"",
            ""
        ])
        
        # Записываем в файл
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(commands))
        
        file_size = os.path.getsize(output_file) / 1024 / 1024  # MB
        
        print(f"\n{'='*50}")
        print(f"Файл создан: {output_file}")
        print(f"Размер файла: {file_size:.2f} MB")
        print(f"Адресов: {len(ip_list)}")
        print(f"{'='*50}")
        print(f"\nДля импорта в MikroTik выполните:")
        print(f"/import file-name={os.path.basename(output_file)} verbose=yes")
        print(f"\nИмпорт может занять 5-15 минут в зависимости от размера списка.")
        print(f"Следите за прогрессом: /log print follow where topics~\"info\"")
        
        return True, [output_file]
        
    except Exception as e:
        print(f"Ошибка при создании файла: {e}")
        return False, []

def generate_split_files(ip_list, list_name, base_output_file, clear_existing):
    """Создает несколько файлов для очень больших списков"""
    max_per_file = 5000
    total_files = math.ceil(len(ip_list) / max_per_file)
    created_files = []
    
    print(f"Разделяем {len(ip_list)} адресов на {total_files} файлов...")
    
    for file_num in range(total_files):
        start_idx = file_num * max_per_file
        end_idx = min(start_idx + max_per_file, len(ip_list))
        batch_ips = ip_list[start_idx:end_idx]
        
        # Имя файла с номером части
        name_parts = base_output_file.rsplit('.', 1)
        if len(name_parts) == 2:
            split_filename = f"{name_parts[0]}_part{file_num+1:02d}.{name_parts[1]}"
        else:
            split_filename = f"{base_output_file}_part{file_num+1:02d}"
        
        # Очищаем список только в первом файле
        clear_for_this_file = clear_existing and file_num == 0
        
        success, _ = generate_single_large_file(
            batch_ips, 
            list_name, 
            split_filename, 
            clear_for_this_file
        )
        
        if success:
            created_files.append(split_filename)
            print(f"Создан файл {file_num+1}/{total_files}: {split_filename}")
        else:
            print(f"Ошибка создания файла {file_num+1}")
    
    if created_files:
        print(f"\n{'='*50}")
        print("МНОГОФАЙЛОВЫЙ ИМПОРТ - ИНСТРУКЦИИ:")
        print(f"{'='*50}")
        print("Импортируйте файлы ПОСЛЕДОВАТЕЛЬНО:")
        for i, filename in enumerate(created_files, 1):
            print(f"{i}. /import file-name={os.path.basename(filename)} verbose=yes")
        print(f"{'='*50}")
    
    return len(created_files) == total_files, created_files

def apply_via_ssh_large(host, username, password, rsc_files, port=22):
    """Применяет большие списки через SSH с оптимизацией"""
    if not SSH_AVAILABLE:
        print("Для SSH подключения установите: pip install paramiko")
        return False
    
    try:
        print(f"Подключаемся к {host}:{port} для импорта больших файлов...")
        
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(host, port=port, username=username, password=password, timeout=15)
        
        for rsc_file in rsc_files:
            print(f"\nЗагружаем файл {os.path.basename(rsc_file)}...")
            
            # Загружаем файл через SFTP
            sftp = ssh.open_sftp()
            remote_filename = f"/{os.path.basename(rsc_file)}"
            sftp.put(rsc_file, remote_filename)
            sftp.close()
            
            print(f"Импортируем {remote_filename}...")
            
            # Импортируем с verbose режимом
            import_command = f"/import file-name={remote_filename} verbose=yes"
            stdin, stdout, stderr = ssh.exec_command(import_command, timeout=1800)  # 30 минут таймаут
            
            # Ждем завершения импорта
            exit_status = stdout.channel.recv_exit_status()
            
            if exit_status == 0:
                print(f"✅ Файл {remote_filename} импортирован успешно")
            else:
                error_msg = stderr.read().decode()
                print(f"❌ Ошибка импорта {remote_filename}: {error_msg}")
                
            # Удаляем временный файл
            try:
                ssh.exec_command(f"/file remove {remote_filename}")
            except:
                pass
        
        ssh.close()
        print("\n✅ Все файлы успешно импортированы через SSH")
        return True
        
    except Exception as e:
        print(f"❌ Ошибка SSH импорта: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description='MikroTik Large IP List Handler')
    parser.add_argument('--list-name', default='rkn', help='Имя address-list в MikroTik')
    parser.add_argument('--output', help='Имя выходного .rsc файла')
    parser.add_argument('--clear-existing', action='store_true', help='Очистить существующий список')
    parser.add_argument('--split-files', action='store_true', help='Разделить на несколько файлов')
    parser.add_argument('--max-size', type=int, default=5000, help='Максимум адресов в одном файле')
    parser.add_argument('--ssh-host', help='IP адрес MikroTik для SSH')
    parser.add_argument('--ssh-user', default='admin', help='SSH пользователь')
    parser.add_argument('--ssh-password', help='SSH пароль')
    parser.add_argument('--ssh-port', type=int, default=22, help='SSH порт')
    parser.add_argument('--url', default='https://raw.githubusercontent.com/lord-alfred/ipranges/main/all/ipv4_merged.txt', 
                       help='URL для загрузки IP списка')
    
    args = parser.parse_args()
    
    print("=== MikroTik Large IP List Handler ===")
    
    # Загружаем IP-адреса
    ip_addresses = download_ip_list(args.url)
    if not ip_addresses:
        print("Не удалось загрузить IP-адреса")
        sys.exit(1)
    
    print(f"\nРазмер списка: {len(ip_addresses)} адресов")
    
    if len(ip_addresses) > 3000:
        print("⚠️  ВНИМАНИЕ: Большой список IP-адресов!")
        print("   Импорт может занять 10-30 минут")
        print("   Рекомендуется использовать SSH для автоматизации")
        
        if not args.ssh_host:
            choice = input("\nПродолжить создание .rsc файла? (y/N): ")
            if choice.lower() != 'y':
                sys.exit(0)
    
    # Генерируем файлы
    success, rsc_files = generate_optimized_rsc_file(
        ip_addresses, 
        args.list_name, 
        args.output, 
        args.clear_existing,
        args.split_files
    )
    
    if not success or not rsc_files:
        print("❌ Ошибка создания файлов")
        sys.exit(1)
    
    # SSH импорт
    if args.ssh_host and args.ssh_password:
        print(f"\n🔄 Применяем через SSH...")
        ssh_success = apply_via_ssh_large(
            args.ssh_host,
            args.ssh_user, 
            args.ssh_password,
            rsc_files,
            args.ssh_port
        )
        
        if ssh_success:
            print("✅ Импорт завершен успешно!")
        else:
            print("❌ Ошибка SSH импорта. Используйте .rsc файлы вручную.")
    
    print(f"\n📄 Создано файлов: {len(rsc_files)}")
    for f in rsc_files:
        file_size = os.path.getsize(f) / 1024
        print(f"   {f} ({file_size:.1f} KB)")

if __name__ == "__main__":
    main()
