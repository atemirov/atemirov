#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import requests
import os
import sys
import argparse
from datetime import datetime
import time

# Для SSH подключения (установите: pip install paramiko)
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

def generate_rsc_file(ip_list, list_name="rkn", output_file=None, clear_existing=False):
    """Генерирует .rsc файл с командами для MikroTik"""
    if not ip_list:
        print("Список IP-адресов пуст")
        return False, None
    
    if not output_file:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = f"mikrotik_{list_name}_{timestamp}.rsc"
    
    try:
        commands = []
        
        # Заголовок
        commands.append(f"# MikroTik RouterOS script")
        commands.append(f"# Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        commands.append(f"# Address list: {list_name}")
        commands.append(f"# Total addresses: {len(ip_list)}")
        commands.append(f"# For large files use: /import file-name={os.path.basename(output_file)} verbose=yes")
        commands.append("")
        
        # Включаем verbose mode для больших файлов
        if len(ip_list) > 1000:
            commands.append(":log info \"Starting import of large IP list - this may take several minutes\"")
            commands.append("")
        
        # Очистка существующего списка
        if clear_existing:
            commands.append(f":log info \"Clearing existing address list: {list_name}\"")
            commands.append(f"/ip firewall address-list remove [find list=\"{list_name}\"]")
            commands.append(f":log info \"Existing list cleared\"")
            commands.append("")
        
        # Добавление IP-адресов оптимизированными батчами
        batch_size = 50  # Уменьшаем размер батча для стабильности
        total_batches = (len(ip_list) + batch_size - 1) // batch_size
        
        commands.append(f":log info \"Adding {len(ip_list)} addresses in {total_batches} batches\"")
        commands.append("")
        
        for i in range(0, len(ip_list), batch_size):
            batch = ip_list[i:i + batch_size]
            batch_num = i // batch_size + 1
            
            commands.append(f"# Batch {batch_num}/{total_batches} ({len(batch)} addresses)")
            commands.append(f":log info \"Processing batch {batch_num}/{total_batches}\"")
            
            # Группируем команды add в один блок для ускорения
            commands.append("{")
            for ip in batch:
                if '/' in ip or '.' in ip:
                    commands.append(f"  /ip firewall address-list add list={list_name} address={ip}")
            commands.append("}")
            
            # Добавляем паузы для больших списков
            if len(ip_list) > 5000 and batch_num % 10 == 0:
                commands.append(":delay 1s")
            
            commands.append("")
        
        commands.append(f":log info \"Import completed. Added {len(ip_list)} addresses to list '{list_name}'\"")
        
        # Записываем в файл
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(commands))
        
        print(f"Файл {output_file} успешно создан")
        print(f"Для импорта используйте: /import file-name={os.path.basename(output_file)} verbose=yes")
        return True, output_file
        
    except Exception as e:
        print(f"Ошибка при создании файла: {e}")
        return False, None

def apply_via_ssh(host, username, password, rsc_file, port=22):
    """Применяет настройки через SSH (требует paramiko)"""
    if not SSH_AVAILABLE:
        print("Для SSH подключения установите: pip install paramiko")
        return False
    
    try:
        print(f"Подключаемся к {host}:{port}...")
        
        # Создаем SSH клиент
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        ssh.connect(host, port=port, username=username, password=password, timeout=10)
        
        # Читаем команды из файла
        with open(rsc_file, 'r', encoding='utf-8') as f:
            commands = f.readlines()
        
        # Фильтруем только команды (без комментариев и пустых строк)
        exec_commands = []
        for line in commands:
            line = line.strip()
            if line and not line.startswith('#'):
                exec_commands.append(line)
        
        print(f"Выполняем {len(exec_commands)} команд...")
        
        # Выполняем команды батчами
        batch_size = 50
        for i in range(0, len(exec_commands), batch_size):
            batch = exec_commands[i:i + batch_size]
            batch_command = '\n'.join(batch)
            
            print(f"Выполняем батч {i//batch_size + 1}/{(len(exec_commands)-1)//batch_size + 1}...")
            
            stdin, stdout, stderr = ssh.exec_command(batch_command)
            
            # Ждем завершения
            exit_status = stdout.channel.recv_exit_status()
            
            if exit_status != 0:
                error = stderr.read().decode()
                print(f"Ошибка при выполнении батча: {error}")
            
            # Небольшая пауза между батчами
            time.sleep(0.5)
        
        ssh.close()
        print("Настройки успешно применены через SSH")
        return True
        
    except Exception as e:
        print(f"Ошибка SSH подключения: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description='MikroTik IP Address List Manager')
    parser.add_argument('--list-name', default='rkn', help='Имя address-list в MikroTik')
    parser.add_argument('--output', help='Имя выходного .rsc файла')
    parser.add_argument('--clear-existing', action='store_true', help='Очистить существующий список')
    parser.add_argument('--ssh-host', help='IP адрес MikroTik для SSH')
    parser.add_argument('--ssh-user', default='admin', help='SSH пользователь')
    parser.add_argument('--ssh-password', help='SSH пароль')
    parser.add_argument('--ssh-port', type=int, default=22, help='SSH порт')
    parser.add_argument('--url', default='https://raw.githubusercontent.com/lord-alfred/ipranges/main/all/ipv4_merged.txt', 
                       help='URL для загрузки IP списка')
    
    args = parser.parse_args()
    
    print("=== MikroTik Advanced IP Address List Manager ===")
    
    # Загружаем IP-адреса
    ip_addresses = download_ip_list(args.url)
    if not ip_addresses:
        print("Не удалось загрузить IP-адреса")
        sys.exit(1)
    
    # Генерируем .rsc файл
    success, rsc_file = generate_rsc_file(
        ip_addresses, 
        args.list_name, 
        args.output, 
        args.clear_existing
    )
    
    if not success:
        print("Ошибка создания .rsc файла")
        sys.exit(1)
    
    # Применяем через SSH если указаны параметры
    if args.ssh_host and args.ssh_password:
        print("\nПрименяем настройки через SSH...")
        ssh_success = apply_via_ssh(
            args.ssh_host,
            args.ssh_user, 
            args.ssh_password,
            rsc_file,
            args.ssh_port
        )
        
        if ssh_success:
            print("Настройки успешно применены!")
        else:
            print("Ошибка применения через SSH. Используйте .rsc файл вручную.")
    
    else:
        print(f"\n=== .rsc файл готов: {rsc_file} ===")
        print("Для ручного применения:")
        print("1. Скопируйте файл на MikroTik")
        print("2. Выполните: /import file-name=" + os.path.basename(rsc_file))
        print("\nИли используйте SSH опции для автоматического применения:")
        print("python script.py --ssh-host 192.168.1.1 --ssh-password your_password")

if __name__ == "__main__":
    main()
