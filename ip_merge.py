#!/usr/bin/env python3
"""
Скрипт для объединения IP-адресов из нескольких источников,
устранения пересечений и создания .rsc файла для MikroTik RouterOS.
"""

import ipaddress
import requests
import sys
import re
from typing import Set, List
import logging

import argparse
import time
import os

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Попытка импорта paramiko для SSH
try:
    import paramiko
    SSH_AVAILABLE = True
except ImportError:
    SSH_AVAILABLE = False
    logger.warning("Paramiko не установлен. SSH функции будут недоступны.")

class IPMerger:
    def __init__(self):
        self.ip_networks: Set[ipaddress.IPv4Network] = set()
        
    def fetch_url_content(self, url: str) -> str:
        """Загружает содержимое URL"""
        try:
            logger.info(f"Загружаю данные из: {url}")
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            logger.error(f"Ошибка при загрузке {url}: {e}")
            return ""
    
    def extract_ips_from_content(self, content: str) -> List[str]:
        """Извлекает все IP-адреса из содержимого"""
        ip_list = []
        lines = content.strip().split('\n')
        
        # Регулярное выражение для поиска IP-адресов
        ip_pattern = r'\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)(?:/[0-9]{1,2})?\b'
        
        for line_num, line in enumerate(lines, 1):
            original_line = line.strip()
            
            # Пропускаем пустые строки
            if not original_line:
                continue
            
            # Пропускаем явные заголовки без IP
            if original_line in ['Meta (Instagram, Facebook)', 'Telegram', 'Discord', 
                               'ChatGPT', 'GitHub Copilot', 'Twitter', '// Узлы', 
                               '// Подсети', '// Узлы и подсети']:
                continue
            
            # Специальная обработка для строк с route ADD
            if 'route ADD' in original_line.upper() and 'MASK' in original_line.upper():
                # Извлекаем пары IP MASK
                matches = re.findall(r'(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}) MASK (\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})', original_line)
                for ip, mask in matches:
                    try:
                        network = ipaddress.IPv4Network(f"{ip}/{mask}", strict=False)
                        ip_str = str(network)
                        ip_list.append(ip_str)
                        logger.debug(f"Строка {line_num}: найдена сеть из route: {ip_str}")
                    except Exception as e:
                        logger.warning(f"Ошибка при парсинге route в строке {line_num}: {e}")
                continue  # Пропускаем дальнейшую обработку этой строки
            
            # Ищем все IP-адреса в строке для остальных строк
            found_ips = re.findall(ip_pattern, original_line)
            
            if found_ips:
                logger.debug(f"Строка {line_num}: найдено {len(found_ips)} IP: {found_ips}")
                ip_list.extend(found_ips)
        
        # Удаляем дубликаты, сохраняя порядок
        seen = set()
        unique_ips = []
        for ip in ip_list:
            if ip not in seen:
                seen.add(ip)
                unique_ips.append(ip)
        
        logger.info(f"Извлечено {len(unique_ips)} уникальных IP-адресов")
        return unique_ips
    
    def add_ip_range(self, ip_str: str):
        """Добавляет IP-адрес или диапазон в набор сетей"""
        try:
            # Попробуем распарсить как сеть (с маской)
            if '/' in ip_str:
                network = ipaddress.IPv4Network(ip_str, strict=False)
            else:
                # Если это отдельный IP, создаем сеть /32
                network = ipaddress.IPv4Network(f"{ip_str}/32", strict=False)
            
            self.ip_networks.add(network)
            logger.debug(f"Добавлена сеть: {network}")
            
        except ipaddress.AddressValueError as e:
            logger.warning(f"Невалидный IP-адрес: {ip_str} - {e}")
        except Exception as e:
            logger.warning(f"Ошибка при обработке IP: {ip_str} - {e}")
    
    def collapse_networks(self):
        """Объединяет перекрывающиеся сети и подсети"""
        logger.info("Объединяю перекрывающиеся сети...")
        original_count = len(self.ip_networks)
        
        # Используем встроенную функцию collapse_addresses для оптимизации
        collapsed = list(ipaddress.collapse_addresses(self.ip_networks))
        self.ip_networks = set(collapsed)
        
        logger.info(f"Сетей до объединения: {original_count}")
        logger.info(f"Сетей после объединения: {len(self.ip_networks)}")
    
    def load_from_urls(self, urls: List[str]):
        """Загружает и обрабатывает IP-адреса из списка URLs"""
        for url in urls:
            content = self.fetch_url_content(url)
            if content:
                # Извлекаем IP-адреса из содержимого
                ip_list = self.extract_ips_from_content(content)
                
                if ip_list:
                    logger.info(f"Примеры найденных IP: {ip_list[:5]}")
                    
                    # Проверяем наличие целевых IP в извлеченном списке
                    target_ips = ['157.240.253.0/24', '162.159.140.0/24', '157.240.253.174', '162.159.140.4']
                    found_targets = []
                    for target in target_ips:
                        target_base = target.split('/')[0]  # Убираем маску для проверки
                        for ip in ip_list:
                            if target == ip or target_base in ip:
                                found_targets.append(ip)
                    
                    if found_targets:
                        logger.info(f"Найдены целевые IP в {url}: {found_targets[:10]}")
                
                # Добавляем каждый IP-адрес в набор сетей
                added_count = 0
                for ip_str in ip_list:
                    old_count = len(self.ip_networks)
                    self.add_ip_range(ip_str)
                    if len(self.ip_networks) > old_count:
                        added_count += 1
                
                logger.info(f"Добавлено {added_count} уникальных сетей из {url}")
                
                # Проверяем, что целевые сети добавлены
                target_networks = ['157.240.253.0/24', '162.159.140.0/24']
                for target in target_networks:
                    try:
                        target_net = ipaddress.IPv4Network(target)
                        if target_net in self.ip_networks:
                            logger.info(f"✓ {target} успешно добавлена из {url}")
                        else:
                            # Проверяем отдельные IP из этой подсети
                            subnet_ips = [net for net in self.ip_networks if net.network_address.exploded.startswith(target.split('.')[0] + '.' + target.split('.')[1])]
                            if subnet_ips:
                                logger.info(f"ℹ Из подсети {target} добавлено {len(subnet_ips)} IP")
                    except:
                        pass
        
        logger.info(f"Всего загружено уникальных сетей: {len(self.ip_networks)}")

    def filter_private_networks(self):
        """Удаляет частные, локальные и зарезервированные сети"""
        logger.info("Фильтрация частных и служебных сетей...")
        
        # Список сетей для удаления (RFC 1918, Loopback, Multicast, Reserved)
        private_ranges = [
            ipaddress.IPv4Network("10.0.0.0/8"),
            ipaddress.IPv4Network("172.16.0.0/12"),
            ipaddress.IPv4Network("192.168.0.0/16"),
            ipaddress.IPv4Network("127.0.0.0/8"),
            ipaddress.IPv4Network("169.254.0.0/16"), # Link-local
            ipaddress.IPv4Network("224.0.0.0/4"),    # Multicast
            ipaddress.IPv4Network("240.0.0.0/4")     # Reserved
        ]
        
        to_remove = set()
        for net in self.ip_networks:
            for private in private_ranges:
                # Если сеть пересекается с частным диапазоном
                if net.overlaps(private):
                    # Если (внезапно) частный диапазон шире или равен нашей сети - удаляем нашу
                    # Если наша сеть шире private (например 0.0.0.0/0) - это тоже плохо
                    logger.warning(f"Удалена сеть {net}, так как пересекается с {private}")
                    to_remove.add(net)
                    break
        
        self.ip_networks -= to_remove
        logger.info(f"Удалено {len(to_remove)} некорректных сетей")

    def apply_whitelist(self, whitelist_file="whitelist.txt"):
        """Удаляет сети, находящиеся в белом списке"""
        whitelist_nets = set()
        
        # 1. Загрузка из файла
        if os.path.exists(whitelist_file):
            logger.info(f"Загружаю белый список из {whitelist_file}...")
            try:
                with open(whitelist_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            try:
                                # Поддержка IP/mask или просто IP
                                if '/' not in line: 
                                    line += '/32'
                                whitelist_nets.add(ipaddress.IPv4Network(line, strict=False))
                            except ValueError:
                                logger.warning(f"Ошибка в белом списке: {line}")
            except Exception as e:
                logger.error(f"Ошибка чтения whitelist: {e}")
        
        if not whitelist_nets:
            logger.info("Белый список пуст.")
            return

        logger.info(f"В белом списке {len(whitelist_nets)} сетей")
        
        to_remove = set()
        for net in self.ip_networks:
            for white in whitelist_nets:
                # Если наша "плохая" сеть пересекается с белой
                # ВАЖНО: Мы удаляем "плохую" сеть, если она полностью входит в белую
                # ИЛИ если белая входит в плохую (тогда нужно разбить плохую, но это сложно, проще удалить)
                if net.overlaps(white):
                    logger.warning(f"Сеть {net} удалена по белому списку ({white})")
                    to_remove.add(net)
                    break
        
        self.ip_networks -= to_remove

    def check_large_networks(self, max_prefix=12):
        """Проверяет наличие слишком больших сетей"""
        for net in self.ip_networks:
            if net.prefixlen < max_prefix:
                logger.warning(f"⚠️ ОБНАРУЖЕНА ОЧЕНЬ БОЛЬШАЯ СЕТЬ: {net} (/{net.prefixlen})")
                logger.warning("Возможно, стоит добавить её в исключения или проверить источник.")
    
    def final_check(self):
        target_networks = ['157.240.253.0/24', '162.159.140.0/24']
        logger.info("=== ФИНАЛЬНАЯ ПРОВЕРКА ПОСЛЕ ОБЪЕДИНЕНИЯ ===")
        for target in target_networks:
            try:
                target_net = ipaddress.IPv4Network(target)
                covered = False
                covering_net = None
                for net in self.ip_networks:
                    if net.supernet_of(target_net):
                        covered = True
                        covering_net = net
                        break
                if covered:
                    if covering_net == target_net:
                        logger.info(f"✓ {target} присутствует в финальном наборе")
                    else:
                        logger.info(f"✓ {target} покрыта более крупной сетью {covering_net}")
                else:
                    # Ищем похожие сети
                    similar = [str(net) for net in self.ip_networks if target.split('.')[0] + '.' + target.split('.')[1] in str(net)][:5]
                    if similar:
                        logger.info(f"⚠ {target} не найдена как отдельная, но есть похожие: {similar}")
                    else:
                        logger.warning(f"❌ {target} отсутствует в финальном наборе")
            except:
                pass
    
    def generate_rsc_file(self, filename: str = "rkn_ips.rsc", list_name: str = "rkn"):
        """Создает .rsc файл для MikroTik RouterOS"""
        logger.info(f"Создаю файл {filename}...")
        
        # Сортируем сети для удобства
        sorted_networks = sorted(self.ip_networks)
        
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                # Добавляем заголовок
                f.write(f"# MikroTik RouterOS script\n")
                f.write(f"# Список IP-адресов для firewall\n")
                f.write(f"# Сгенерировано автоматически\n")
                f.write(f"# Всего записей: {len(sorted_networks)}\n\n")
                
                # Удаляем существующий список (если есть)
                f.write(f"/ip firewall address-list remove [find list=\"{list_name}\"]\n\n")
                
                # Добавляем все IP-адреса
                for network in sorted_networks:
                    # Для сетей /32 можем записывать просто IP без маски
                    if network.prefixlen == 32:
                        address = str(network.network_address)
                    else:
                        address = str(network)
                    
                    f.write(f"/ip firewall address-list add list=\"{list_name}\" address=\"{address}\"\n")
            
            logger.info(f"Файл {filename} создан успешно!")
            logger.info(f"Записей в файле: {len(sorted_networks)}")
            
        except IOError as e:
            logger.error(f"Ошибка при создании файла: {e}")
    
    def save_text_list(self, filename: str = "ip_list.txt"):
        """Сохраняет список IP в текстовый файл для проверки"""
        logger.info(f"Сохраняю список в {filename}...")
        
        sorted_networks = sorted(self.ip_networks)
        
        try:
            with open(filename, 'w', encoding='utf-8') as f:
                for network in sorted_networks:
                    f.write(f"{network}\n")
            
            logger.info(f"Текстовый список сохранен в {filename}")
            
        except IOError as e:
            logger.error(f"Ошибка при сохранении файла: {e}")

class SSHManager:
    def __init__(self, host, user, password, port=22):
        self.host = host
        self.user = user
        self.password = password
        self.port = port
        self.client = None
        
    def connect(self):
        if not SSH_AVAILABLE:
            raise ImportError("Paramiko library is not available")
            
        try:
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            # Mikrotik часто конфликтует с попытками использовать ключи если нужен пароль
            # Ошибка "expected msg: 50 got: 5" обычно лечится отключением поиска ключей
            self.client.connect(
                self.host, 
                port=self.port, 
                username=self.user, 
                password=self.password, 
                timeout=10,
                look_for_keys=False,
                allow_agent=False
            )
            logger.info(f"SSH соединение установлено с {self.host}")
            return True
        except Exception as e:
            logger.error(f"Ошибка SSH подключения: {e}")
            return False
            
    def close(self):
        if self.client:
            self.client.close()
            
    def execute_command(self, command):
        if not self.client:
            return None, "Not connected", -1
            
        try:
            stdin, stdout, stderr = self.client.exec_command(command)
            exit_status = stdout.channel.recv_exit_status()
            out = stdout.read().decode().strip()
            err = stderr.read().decode().strip()
            return out, err, exit_status
        except Exception as e:
            return None, str(e), -1

    def fetch_address_list(self, list_name):
        """Получает текущий список адресов с микротика с их ID"""
        logger.info(f"Получаю текущий список '{list_name}' с роутера...")
        
        # Запрашиваем .id явно, хотя в terse он обычно есть
        cmd = f"/ip/firewall/address-list/print terse where list={list_name}"
        out, err, code = self.execute_command(cmd)
        
        if code != 0:
            logger.error(f"Ошибка получения списка: {err}")
            return {}
            
        current_ips = {}
        lines = out.split('\n')
        
        # DEBUG: Если включен debug или если не найдено записей, выводим первые строки
        if len(lines) > 0:
            logger.debug(f"Row output sample: {lines[:3]}")
            
        for line in lines:
            # Пример строки: 0   list=rkn address=1.1.1.1 .id=*123
            # Или (без .id): 0   list=rkn address=1.1.1.1 ...
            if f"list={list_name}" in line:
                # Ищем IP
                ip_match = re.search(r'address=([0-9./]+)', line)
                
                # Ищем ID (сначала пробуем найти внутренний ID вида *1A)
                id_match = re.search(r'\.id=(\*[0-9A-Fa-f]+)', line)
                
                # Если внутреннего ID нет, ищем порядковый номер (индекс) в начале строки
                index_match = re.match(r'^\s*(\d+)\s+', line)
                
                mikrotik_id = None
                if id_match:
                    mikrotik_id = id_match.group(1)
                elif index_match:
                    mikrotik_id = index_match.group(1)
                
                if ip_match and mikrotik_id:
                    try:
                        network = ipaddress.IPv4Network(ip_match.group(1), strict=False)
                        current_ips[network] = mikrotik_id
                    except ValueError:
                        pass
        
        logger.info(f"Получено {len(current_ips)} записей с роутера")
        if len(current_ips) == 0 and len(lines) > 5:
            logger.warning("Не удалось распарсить записи, хотя вывод не пустой!")
            logger.warning(f"Пример строки: {lines[0] if lines else 'NONE'}")
            
        return current_ips

    def apply_diff(self, to_add: Set[ipaddress.IPv4Network], to_remove_ids: List[str], list_name: str, dry_run=False):
        """Применяет изменения (добавление и удаление)"""
        logger.info(f"Применяю изменения: +{len(to_add)} / -{len(to_remove_ids)}")
        
        if dry_run:
            logger.info("[DRY RUN] Изменения не будут применены")
            return

        # Удаление (теперь быстрое, по ID)
        if to_remove_ids:
            logger.info(f"Удаляю {len(to_remove_ids)} адресов...")
            
            # Разбиваем на батчи
            batch_size = 100 # Можно удалять помногу за раз
            for i in range(0, len(to_remove_ids), batch_size):
                batch = to_remove_ids[i:i + batch_size]
                # Формат: /ip/firewall/address-list/remove numbers=*1,*2,*3
                ids_str = ",".join(batch)
                cmd = f"/ip/firewall/address-list/remove numbers={ids_str}"
                self.execute_command(cmd)
        
        # Добавление
        if to_add:
            logger.info(f"Добавляю {len(to_add)} адресов...")
            batch_size = 50
            add_list = list(to_add)
            for i in range(0, len(add_list), batch_size):
                batch = add_list[i:i + batch_size]
                cmds = []
                for net in batch:
                    addr = str(net.network_address) if net.prefixlen == 32 else str(net)
                    # Используем безопасное добавление: игнорируем ошибки, если запись уже есть
                    # do { ... } on-error={}
                    cmd = f"/ip/firewall/address-list/add list={list_name} address={addr}"
                    safe_cmd = f"do {{ {cmd} }} on-error={{}}"
                    cmds.append(safe_cmd)
                
                full_cmd = "; ".join(cmds)
                self.execute_command(full_cmd)
        
        logger.info("Синхронизация завершена")

def test_parsing():
    """Тестовая функция для проверки парсинга проблематичного файла"""
    test_url = "https://gist.githubusercontent.com/iamwildtuna/7772b7c84a11bf6e1385f23096a73a15/raw"
    
    merger = IPMerger()
    content = merger.fetch_url_content(test_url)
    
    if content:
        print("Тестирую извлечение IP-адресов...")
        
        # Ищем конкретные IP, которые должны быть
        target_ips = ['157.240.253.0/24', '162.159.140.0/24', '157.240.252.0/24', '162.159.152.4']
        for target_ip in target_ips:
            if target_ip in content:
                print(f"✓ Найден {target_ip} в исходном файле")
            else:
                print(f"✗ НЕ найден {target_ip} в исходном файле")
        
        print("\n" + "="*50 + "\n")
        
        ip_list = merger.extract_ips_from_content(content)
        print(f"Извлечено IP-адресов: {len(ip_list)}")
        
        # Проверяем, есть ли целевые IP в результатах
        found_targets = []
        for target_ip in target_ips:
            for parsed_ip in ip_list:
                if target_ip == parsed_ip or target_ip.split('/')[0] in parsed_ip:
                    found_targets.append(parsed_ip)
        
        if found_targets:
            print(f"\n✓ Найденные целевые IP:")
            for found in set(found_targets):
                print(f"  {found}")
        else:
            print(f"\n❌ Целевые IP НЕ найдены в результатах извлечения!")
        
        print(f"\nПримеры IP с подсетью 157.240:")
        matching_ips = [ip for ip in ip_list if '157.240' in ip][:10]
        for ip in matching_ips:
            print(f"  {ip}")
        
        print(f"\nПримеры IP с подсетью 162.159:")
        matching_ips = [ip for ip in ip_list if '162.159' in ip][:10]
        for ip in matching_ips:
            print(f"  {ip}")

def main():
    
    # Argument Parser
    parser = argparse.ArgumentParser(description="MikroTik IP List Merger & Updater")
    parser.add_argument("--test", action="store_true", help="Запустить тесты парсинга")
    parser.add_argument("--debug", action="store_true", help="Включить отладку")
    parser.add_argument("--ssh-host", default="192.168.1.1", help="IP адрес MikroTik для SSH")
    parser.add_argument("--ssh-user", default="atemirov", help="SSH пользователь")
    # Пароль содержит спецсимволы, в коде Python экранирование {} не требуется для обычных строк
    parser.add_argument("--ssh-password", default="Djqnb{jxe_2021", help="SSH пароль")
    parser.add_argument("--ssh-port", type=int, default=22, help="SSH порт")
    parser.add_argument("--list-name", default="rkn", help="Имя списка адресов (address-list)")
    parser.add_argument("--dry-run", action="store_true", help="Не применять изменения, только показать")
    parser.add_argument("--no-ssh", action="store_true", help="Не использовать SSH даже если параметры указаны (только генерация файлов)")

    args = parser.parse_args()

    # Обработка аргументов
    if args.test:
        test_parsing()
        return
    
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # Config
    list_name = args.list_name
    
    # URLs репозиториев
    urls = [
        "https://gist.githubusercontent.com/iamwildtuna/7772b7c84a11bf6e1385f23096a73a15/raw",
        "https://raw.githubusercontent.com/touhidurrr/iplist-youtube/main/lists/ipv4.txt",
        "https://raw.githubusercontent.com/lord-alfred/ipranges/main/all/ipv4_merged.txt"
    ]
    
    # Создаем экземпляр класса
    merger = IPMerger()
    
    try:
        # Загружаем данные из всех источников
        merger.load_from_urls(urls)
        
        # Объединяем перекрывающиеся сети
        merger.collapse_networks()
        
        # === NEW: Filtering & Quality Control ===
        merger.filter_private_networks()
        merger.apply_whitelist("whitelist.txt")
        merger.check_large_networks()
        # ========================================
        
        # Финальная проверка после объединения
        merger.final_check()
        
        # Создаем .rsc файл
        merger.generate_rsc_file("rkn_ips.rsc", "rkn")
        
        # Также сохраняем текстовый список для проверки
        merger.save_text_list("merged_ips.txt")

        # === CORE LOGIC for DIFF ===
        server_ips_map = {} # Dict[IPv4Network, str_id]
        ssh_manager = None
        use_ssh = args.ssh_host and not args.no_ssh

        if use_ssh:
            if not SSH_AVAILABLE:
                logger.error("SSH недоступен (нет paramiko). Пропускаем sync.")
            else:
                ssh_manager = SSHManager(args.ssh_host, args.ssh_user, args.ssh_password, args.ssh_port)
                if ssh_manager.connect():
                    server_ips_map = ssh_manager.fetch_address_list(list_name)
                    server_ips_set = set(server_ips_map.keys())
                    
                    # Расчет разницы
                    desired_ips = merger.ip_networks
                    
                    to_add = desired_ips - server_ips_set
                    to_remove_nets = server_ips_set - desired_ips
                    
                    # Получаем ID для удаления
                    to_remove_ids = []
                    for net in to_remove_nets:
                        if net in server_ips_map:
                            to_remove_ids.append(server_ips_map[net])
                    
                    logger.info(f"Сводка изменений: Добавить {len(to_add)}, Удалить {len(to_remove_ids)}")
                    
                    if to_add or to_remove_ids:
                        ssh_manager.apply_diff(to_add, to_remove_ids, list_name, dry_run=args.dry_run)
                    else:
                        logger.info("Изменений не требуется.")

                    ssh_manager.close()
                else:
                    logger.error("Не удалось подключиться по SSH. Пропускаем sync.")
        
        logger.info("Обработка завершена успешно!")
        
    except KeyboardInterrupt:
        logger.info("Операция прервана пользователем")
        sys.exit(1)
    except Exception as e:
        logger.error(f"Произошла ошибка: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()