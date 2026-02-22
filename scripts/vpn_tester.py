#!/usr/bin/env python3
"""
VPN Tester - Инструмент для тестирования VLESS конфигураций
Проверяет работоспособность VPN, измеряет скорость, пинги и генерирует отчёты
"""

import json
import os
import subprocess
import time
import re
import socket
import threading
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse, parse_qs, unquote
import base64

# Пути
# При запуске из Docker: BASE_DIR = /app
# При запуске напрямую: BASE_DIR = /home/matrixhasyou/qwen/vpn-tester
BASE_DIR = Path(__file__).parent.parent
if not (BASE_DIR / "configs").exists():
    # Если запускается из scripts/ напрямую
    BASE_DIR = Path(__file__).parent
CONFIGS_DIR = BASE_DIR / "configs"
REPORTS_DIR = BASE_DIR / "reports"
LOGS_DIR = BASE_DIR / "logs"
XRAY_BIN = BASE_DIR / "xray" / "xray"

# Тестовые сервера для проверки
TEST_SERVERS = [
    # Россия (4)
    ("Yandex RU", "yandex.ru", 443, "RU"),
    ("Mail.ru", "mail.ru", 443, "RU"),
    ("VK.com", "vk.com", 443, "RU"),
    ("Office SMTK", "office.smtk.us", 443, "RU"),
    # Мир (6)
    ("Google DNS", "8.8.8.8", 53, "US"),
    ("Cloudflare", "1.1.1.1", 53, "US"),
    ("GitHub", "github.com", 443, "US"),
    ("Microsoft", "microsoft.com", 443, "US"),
    ("ChatGPT", "chat.openai.com", 443, "US"),
    ("Amazon", "amazon.com", 443, "US"),
]

# URL для проверки скорости (10MB файлы - быстрее для тестов)
SPEEDTEST_URLS = [
    "https://proof.ovh.net/files/10Mb.dat",  # OVH 10MB
    "https://download.oracle.com/otn-pub/java/jdk/10.0.2+13/19aef61b38124481863b1413dce18555/0",  # Oracle
]


class VlessConfig:
    """Класс для работы с VLESS конфигурацией"""
    
    def __init__(self, url: str, name: str = None):
        self.url = url.strip()
        self.name = name or self._parse_name()
        self.parsed = self._parse_url()
        self.config_json = None
        self.test_results = {}
        
    def _parse_url(self) -> dict:
        """Парсинг VLESS URL"""
        try:
            if not self.url.startswith('vless://'):
                return {}
            
            # Удаляем префикс
            url_part = self.url[8:]
            
            # Разделяем на часть до # и после
            if '#' in url_part:
                main_part, fragment = url_part.split('#', 1)
                self.name = unquote(fragment)
            else:
                main_part = url_part
            
            # Парсим основную часть
            # UUID@HOST:PORT?params
            if '@' not in main_part:
                return {}
                
            uuid_part, rest = main_part.split('@', 1)
            uuid = uuid_part
            
            # Хост и порт
            if '?' in rest:
                host_port, params_str = rest.split('?', 1)
            else:
                host_port = rest
                params_str = ""
            
            # Парсим хост:порт (может быть IPv6)
            if host_port.startswith('['):
                # IPv6
                match = re.match(r'\[([^\]]+)\]:(\d+)', host_port)
                if match:
                    host, port = match.groups()
                else:
                    return {}
            else:
                # IPv4 или домен
                if ':' in host_port:
                    host, port = host_port.rsplit(':', 1)
                else:
                    return {}
            
            # Парсим параметры
            params = parse_qs(params_str)
            params = {k: v[0] if v else '' for k, v in params.items()}
            
            return {
                'uuid': uuid,
                'host': host,
                'port': int(port),
                'params': params
            }
        except Exception as e:
            print(f"Error parsing {self.name}: {e}")
            return {}
    
    def _parse_name(self) -> str:
        """Извлечение имени из URL"""
        try:
            if '#' in self.url:
                return unquote(self.url.split('#', 1)[1])
        except:
            pass
        return f"config_{int(time.time())}"
    
    def to_xray_config(self, socks_port: int = 10808, http_port: int = 10809) -> dict:
        """Генерация конфига для Xray"""
        if not self.parsed:
            return {}
        
        p = self.parsed
        params = p.get('params', {})
        
        config = {
            "log": {
                "loglevel": "error",
                "access": str(LOGS_DIR / f"access_{self.name}.log"),
                "error": str(LOGS_DIR / f"error_{self.name}.log")
            },
            "inbounds": [
                {
                    "tag": "socks",
                    "port": socks_port,
                    "listen": "127.0.0.1",
                    "protocol": "socks",
                    "settings": {
                        "auth": "noauth",
                        "udp": True,
                        "address": "127.0.0.1"
                    }
                },
                {
                    "tag": "http",
                    "port": http_port,
                    "listen": "127.0.0.1",
                    "protocol": "http",
                    "settings": {}
                }
            ],
            "outbounds": [
                {
                    "tag": "proxy",
                    "protocol": "vless",
                    "settings": {
                        "vnext": [
                            {
                                "address": p['host'],
                                "port": p['port'],
                                "users": [
                                    {
                                        "id": p['uuid'],
                                        "encryption": "none",
                                        "flow": params.get('flow', '')
                                    }
                                ]
                            }
                        ]
                    },
                    "streamSettings": {
                        "network": params.get('type', 'tcp'),
                        "security": params.get('security', 'none')
                    }
                }
            ]
        }
        
        # Настройка stream settings
        stream = config["outbounds"][0]["streamSettings"]
        
        if params.get('security') == 'reality':
            stream["realitySettings"] = {
                "serverName": params.get('sni', p['host']),
                "publicKey": params.get('pbk', ''),
                "shortId": params.get('sid', ''),
                "spiderX": params.get('spx', '/'),
                "fingerprint": params.get('fp', 'chrome')
            }
        elif params.get('security') == 'tls':
            stream["tlsSettings"] = {
                "serverName": params.get('sni', p['host']),
                "fingerprint": params.get('fp', 'chrome')
            }
        
        if params.get('type') == 'ws':
            stream["wsSettings"] = {
                "path": params.get('path', '/'),
                "headers": {
                    "Host": params.get('host', params.get('sni', p['host']))
                }
            }
        
        # Mux
        config["outbounds"][0]["mux"] = {
            "enabled": False
        }
        
        return config
    
    @property
    def info(self) -> dict:
        """Информация о конфигурации"""
        if not self.parsed:
            return {}
        
        p = self.parsed
        params = p.get('params', {})
        
        return {
            'name': self.name,
            'host': p['host'],
            'port': p['port'],
            'sni': params.get('sni', p['host']),
            'security': params.get('security', 'none'),
            'type': params.get('type', 'tcp'),
            'country': self._guess_country(p['host']),
        }
    
    def _guess_country(self, host: str) -> str:
        """Предположительное определение страны по хосту"""
        # Простая эвристика по домену
        country_map = {
            '.de': 'DE', '.fr': 'FR', '.nl': 'NL', '.uk': 'UK',
            '.us': 'US', '.ca': 'CA', '.sg': 'SG', '.jp': 'JP',
            '.ru': 'RU', '.fi': 'FI', '.se': 'SE', '.no': 'NO',
        }
        for suffix, country in country_map.items():
            if suffix in host:
                return country
        return '??'


class VpnTester:
    """Основной класс тестировщика"""
    
    def __init__(self):
        self.configs = []
        self.results = []
        self.xray_processes = {}
        
    def load_configs(self):
        """Загрузка конфигураций из файлов"""
        self.configs = []
        for config_file in CONFIGS_DIR.glob("*.txt"):
            with open(config_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('vless://'):
                        config = VlessConfig(line)
                        self.configs.append(config)
        print(f"Loaded {len(self.configs)} configs")
    
    def save_config(self, name: str, url: str):
        """Сохранение новой конфигурации"""
        config = VlessConfig(url, name)
        config_file = CONFIGS_DIR / f"{name}.txt"
        with open(config_file, 'w') as f:
            f.write(url + '\n')
        self.configs.append(config)
    
    def delete_config(self, name: str):
        """Удаление конфигурации"""
        config_file = CONFIGS_DIR / f"{name}.txt"
        if config_file.exists():
            config_file.unlink()
        self.configs = [c for c in self.configs if c.name != name]
    
    def start_xray(self, config: VlessConfig, socks_port: int, http_port: int) -> subprocess.Popen:
        """Запуск Xray с конфигурацией"""
        xray_config = config.to_xray_config(socks_port, http_port)
        config_file = LOGS_DIR / f"xray_config_{config.name}.json"
        
        with open(config_file, 'w') as f:
            json.dump(xray_config, f, indent=2)
        
        proc = subprocess.Popen(
            [str(XRAY_BIN), 'run', '-c', str(config_file)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        time.sleep(2)  # Ждём запуска
        return proc
    
    def stop_xray(self, proc: subprocess.Popen):
        """Остановка Xray"""
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except:
            proc.kill()
    
    def test_ping(self, http_port: int) -> dict:
        """Тест пинга до тестовых серверов"""
        results = {}
        proxy = f"http://127.0.0.1:{http_port}"

        for name, host, port, region in TEST_SERVERS:
            try:
                start = time.time()
                result = subprocess.run(
                    ['curl', '-s', '-o', '/dev/null', '-w', '%{http_code},%{time_total}',
                     '--proxy', proxy, '--connect-timeout', '8', '--max-time', '15',
                     f'https://{host}:{port}' if port == 443 else f'http://{host}:{port}'],
                    capture_output=True, timeout=20
                )
                elapsed = time.time() - start
                
                if result.returncode == 0:
                    resp = result.stdout.decode().strip().split(',')
                    http_code = resp[0] if len(resp) > 0 else '000'
                    curl_time = float(resp[1]) if len(resp) > 1 else elapsed
                    results[name] = {
                        'status': 'ok',
                        'time_ms': round(curl_time * 1000, 2),
                        'http_code': http_code,
                        'region': region
                    }
                else:
                    results[name] = {
                        'status': 'fail',
                        'time_ms': round(elapsed * 1000, 2),
                        'http_code': '000',
                        'region': region,
                        'error': 'Connection failed'
                    }
            except subprocess.TimeoutExpired:
                results[name] = {
                    'status': 'timeout',
                    'time_ms': 15000,
                    'http_code': '000',
                    'region': region,
                    'error': 'Timeout'
                }
            except Exception as e:
                results[name] = {
                    'status': 'error',
                    'time_ms': 0,
                    'http_code': '000',
                    'region': region,
                    'error': str(e)
                }

        return results

    def test_traceroute(self, http_port: int) -> dict:
        """Тест трассировки до ключевых серверов (выборочно) - БЕЗ прокси"""
        results = {}
        
        # Выбираем 4 сервера для трассировки
        targets = [
            ("Yandex RU", "yandex.ru"),
            ("Office SMTK", "office.smtk.us"),
            ("Google", "8.8.8.8"),
            ("GitHub", "github.com"),
        ]
        
        for name, host in targets:
            try:
                # Запускаем traceroute с таймаутом
                result = subprocess.run(
                    ['traceroute', '-m', '20', '-w', '2', '-q', '1', host],
                    capture_output=True,
                    text=True,
                    timeout=45
                )
                
                # Парсим вывод traceroute
                hops = []
                reached_destination = False
                
                for line in result.stdout.split('\n')[1:]:
                    if line.strip() and not line.startswith('traceroute'):
                        parts = line.split()
                        if len(parts) >= 2:
                            host_str = parts[-1] if len(parts) > 2 else '*'
                            time_str = parts[1].rstrip('ms') if len(parts) > 1 else '*'
                            
                            # Проверяем, дошли ли до цели
                            if host in host_str or host_str == host:
                                reached_destination = True
                            
                            hop_info = {
                                'hop': parts[0].rstrip('*'),
                                'host': host_str,
                                'time': time_str
                            }
                            hops.append(hop_info)
                
                # Определяем статус
                if reached_destination:
                    status = 'ok'
                    status_text = '✅ REACHED'
                elif len(hops) >= 3:
                    status = 'partial'
                    status_text = '⚠️ PARTIAL'
                else:
                    status = 'fail'
                    status_text = '❌ FAILED'
                
                results[name] = {
                    'status': status,
                    'status_text': status_text,
                    'reached': reached_destination,
                    'hops_count': len(hops),
                    'target': host,
                    'hops': hops[:5] if reached_destination else hops  # Только первые 5 хопов для отчёта
                }
            except subprocess.TimeoutExpired:
                results[name] = {'status': 'timeout', 'status_text': '⏱️ TIMEOUT', 'reached': False, 'hops': [], 'hops_count': 0, 'target': host}
            except FileNotFoundError:
                results[name] = {'status': 'error', 'status_text': '❌ NO TRACEROUTE', 'reached': False, 'hops': [], 'hops_count': 0, 'target': host}
            except Exception as e:
                results[name] = {'status': 'error', 'status_text': f'❌ ERROR', 'reached': False, 'error': str(e), 'hops': [], 'hops_count': 0, 'target': host}

        return results

    def test_speed(self, http_port: int) -> dict:
        """Тест скорости скачивания (10MB файл)"""
        proxy = f"http://127.0.0.1:{http_port}"
        results = {}

        # Используем первый доступный URL для скорости
        for url in SPEEDTEST_URLS[:1]:
            try:
                start = time.time()
                # Скачиваем с прогрессом
                result = subprocess.run(
                    ['curl', '-s', '-L', '-o', '/dev/null', 
                     '-w', '%{size_download},%{speed_download},%{time_total},%{http_code}',
                     '--proxy', proxy, 
                     '--connect-timeout', '15', 
                     '--speed-time', '20',  # Если скорость 0 более 20 сек - прервать
                     '--speed-limit', '1000',  # Минимум 1KB/s
                     '--max-time', '60',  # Максимум 1 минута для 10MB
                     url],
                    capture_output=True, 
                    timeout=90
                )
                elapsed = time.time() - start

                if result.returncode == 0:
                    resp = result.stdout.decode().strip().split(',')
                    size = float(resp[0]) if len(resp) > 0 else 0
                    speed_bps = float(resp[1]) if len(resp) > 1 else 0
                    total_time = float(resp[2]) if len(resp) > 2 else elapsed
                    http_code = resp[3] if len(resp) > 3 else '000'
                    
                    # Только если скачали больше 1MB считаем успешным
                    if size > 1_000_000:
                        results[url] = {
                            'status': 'ok',
                            'size_bytes': int(size),
                            'size_mb': round(size / 1_000_000, 2),
                            'speed_bps': speed_bps,
                            'speed_mbps': round(speed_bps * 8 / 1_000_000, 2),
                            'time_sec': round(total_time, 2),
                            'http_code': http_code
                        }
                    else:
                        results[url] = {
                            'status': 'fail',
                            'error': f'Download incomplete ({int(size/1000)}KB)',
                            'blocked': True,  # Возможно блокировка РКН
                            'size_bytes': int(size),
                            'http_code': http_code
                        }
                else:
                    results[url] = {
                        'status': 'fail', 
                        'error': f'Download failed (curl={result.returncode})',
                        'http_code': '000'
                    }
            except subprocess.TimeoutExpired:
                results[url] = {'status': 'timeout', 'error': 'Timeout after 60s'}
            except Exception as e:
                results[url] = {'status': 'error', 'error': str(e)}

        return results
    
    def test_ip(self, http_port: int) -> dict:
        """Проверка IP и страны"""
        proxy = f"http://127.0.0.1:{http_port}"
        try:
            result = subprocess.run(
                ['curl', '-s', '--proxy', proxy, '--connect-timeout', '5',
                 'https://api.ipify.org?format=json'],
                capture_output=True, timeout=10
            )
            if result.returncode == 0:
                ip_data = json.loads(result.stdout)
                return {'status': 'ok', 'ip': ip_data.get('ip', 'unknown')}
            return {'status': 'fail'}
        except Exception as e:
            return {'status': 'error', 'error': str(e)}

    def test_dns(self) -> dict:
        """Проверка DNS серверов - определяет использует ли провайдер свои DNS"""
        results = {
            'local_dns': [],
            'uses_provider_dns': False,
            'recommendation': ''
        }
        
        try:
            # Получаем текущие DNS через nmcli (если есть)
            try:
                result = subprocess.run(
                    ['nmcli', 'dev', 'show'],
                    capture_output=True, text=True, timeout=10
                )
                if result.returncode == 0:
                    for line in result.stdout.split('\n'):
                        if 'IP4.DNS' in line:
                            dns = line.split(':')[1].strip()
                            if dns and dns not in results['local_dns']:
                                results['local_dns'].append(dns)
            except:
                pass
            
            # Если не нашли через nmcli, пробуем через resolvectl
            if not results['local_dns']:
                try:
                    result = subprocess.run(
                        ['resolvectl', 'status'],
                        capture_output=True, text=True, timeout=10
                    )
                    if result.returncode == 0:
                        for line in result.stdout.split('\n'):
                            if 'DNS Servers:' in line:
                                dns_list = line.split(':')[1].strip().split()
                                results['local_dns'].extend(dns_list)
                except:
                    pass
            
            # Если всё ещё не нашли, пробуем /etc/resolv.conf
            if not results['local_dns']:
                try:
                    with open('/etc/resolv.conf', 'r') as f:
                        for line in f:
                            if line.strip().startswith('nameserver'):
                                dns = line.split()[1]
                                results['local_dns'].append(dns)
                except:
                    pass
            
            # Проверяем, являются ли DNS публичными
            public_dns = ['8.8.8.8', '8.8.4.4', '1.1.1.1', '1.0.0.1', '9.9.9.9', '208.67.222.222']
            provider_dns_patterns = ['192.168.', '10.', '172.16.', '172.17.', '172.18.', '172.19.', 
                                     '172.20.', '172.21.', '172.22.', '172.23.', '172.24.', '172.25.',
                                     '172.26.', '172.27.', '172.28.', '172.29.', '172.30.', '172.31.']
            
            uses_public = False
            uses_provider = False
            
            for dns in results['local_dns']:
                if any(public in dns for public in public_dns):
                    uses_public = True
                if any(pattern in dns for pattern in provider_dns_patterns):
                    uses_provider = True
            
            results['uses_provider_dns'] = uses_provider and not uses_public
            results['uses_public_dns'] = uses_public
            
            # Формируем рекомендацию
            if results['uses_provider_dns']:
                results['recommendation'] = '⚠️ WARNING: Using provider DNS (possible censorship). Recommend changing to 8.8.8.8 or 1.1.1.1'
            elif uses_public:
                results['recommendation'] = '✅ OK: Using public DNS (Google/Cloudflare)'
            else:
                results['recommendation'] = 'ℹ️ INFO: Using local/network DNS'
                
        except Exception as e:
            results['error'] = str(e)
            results['recommendation'] = '❌ ERROR: Could not detect DNS'
        
        return results
    
    def test_config(self, config: VlessConfig) -> dict:
        """Полное тестирование конфигурации"""
        print(f"Testing {config.name}...")

        socks_port = 10808
        http_port = 10809

        # Запускаем Xray
        proc = self.start_xray(config, socks_port, http_port)

        if proc.poll() is not None:
            # Не запустился
            return {
                'name': config.name,
                'info': config.info,
                'status': 'failed_to_start',
                'timestamp': datetime.now().isoformat()
            }

        result = {
            'name': config.name,
            'info': config.info,
            'timestamp': datetime.now().isoformat()
        }

        try:
            # Тест IP
            result['ip_check'] = self.test_ip(http_port)

            # Проверка DNS (без прокси - локальные DNS)
            result['dns_check'] = self.test_dns()

            # Тест пингов (10 серверов)
            result['ping'] = self.test_ping(http_port)

            # Тест скорости (100MB)
            result['speed'] = self.test_speed(http_port)

            # Трассировка (выборочно, 4 цели)
            result['traceroute'] = self.test_traceroute(http_port)

            # Определяем общий статус
            if result['ip_check'].get('status') == 'ok':
                result['status'] = 'working'
            else:
                result['status'] = 'not_working'

        finally:
            self.stop_xray(proc)

        return result
    
    def run_all_tests(self):
        """Запуск тестов для всех конфигураций"""
        self.load_configs()
        self.results = []
        
        for config in self.configs:
            result = self.test_config(config)
            self.results.append(result)
            
            # Пауза между тестами
            time.sleep(1)
        
        return self.results
    
    def generate_report(self) -> tuple:
        """Генерация отчётов (HTML и MD)"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # HTML отчёт
        html_content = self._generate_html()
        html_file = REPORTS_DIR / f"report_{timestamp}.html"
        with open(html_file, 'w') as f:
            f.write(html_content)
        
        # MD отчёт
        md_content = self._generate_md()
        md_file = REPORTS_DIR / f"report_{timestamp}.md"
        with open(md_file, 'w') as f:
            f.write(md_content)
        
        # Копия последнего отчёта
        with open(REPORTS_DIR / "latest.html", 'w') as f:
            f.write(html_content)
        with open(REPORTS_DIR / "latest.md", 'w') as f:
            f.write(md_content)
        
        return html_file, md_file
    
    def _generate_html(self) -> str:
        """Генерация HTML отчёта в стиле Матрицы"""
        working = [r for r in self.results if r.get('status') == 'working']
        not_working = [r for r in self.results if r.get('status') != 'working']

        html = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>VPN Tester CS-CART Report</title>
    <style>
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        body {{ font-family: 'Courier New', monospace; background: #000; color: #0f0; padding: 20px; }}
        .container {{ max-width: 1600px; margin: 0 auto; }}
        h1 {{ color: #0f0; margin-bottom: 10px; text-shadow: 0 0 10px #0f0; }}
        h2 {{ color: #0f0; margin: 30px 0 15px; border-bottom: 2px solid #0f0; padding-bottom: 10px; text-shadow: 0 0 10px #0f0; }}
        h3 {{ color: #0f0; margin: 20px 0 10px; font-size: 1.1em; text-shadow: 0 0 5px #0f0; }}
        .summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; margin: 20px 0; }}
        .card {{ background: #001100; border: 2px solid #0f0; padding: 20px; box-shadow: 0 0 20px #0f0; }}
        .card h3 {{ font-size: 2.5em; margin-bottom: 5px; color: #0f0; text-shadow: 0 0 10px #0f0; }}
        .card.working h3 {{ color: #0f0; }}
        .card.not-working h3 {{ color: #f00; text-shadow: 0 0 10px #f00; }}
        .card.total h3 {{ color: #0f0; }}
        .card p {{ color: #0f0; font-size: 0.9em; opacity: 0.8; }}
        table {{ width: 100%; border-collapse: collapse; margin: 15px 0; border: 1px solid #0f0; font-size: 0.85em; }}
        th, td {{ padding: 10px 12px; text-align: left; border: 1px solid #003300; color: #0f0; }}
        th {{ background: #001100; color: #0f0; font-weight: 600; text-shadow: 0 0 5px #0f0; }}
        tr:hover {{ background: #002200; }}
        .status {{ padding: 4px 12px; border: 1px solid; font-size: 0.85em; font-weight: bold; display: inline-block; }}
        .status.working {{ border-color: #0f0; color: #0f0; background: #001100; }}
        .status.not-working {{ border-color: #f00; color: #f00; background: #110000; }}
        .status.failed_to_start {{ border-color: #f00; color: #f00; }}
        .status.timeout {{ border-color: #ff0; color: #ff0; }}
        .config-name {{ font-weight: bold; color: #0ff; text-shadow: 0 0 5px #0ff; }}
        .ping-good {{ color: #0f0; }}
        .ping-avg {{ color: #ff0; }}
        .ping-bad {{ color: #f00; }}
        .speed {{ color: #0ff; font-weight: bold; text-shadow: 0 0 5px #0ff; }}
        .speed-slow {{ color: #ff0; }}
        .timestamp {{ color: #0f0; font-size: 0.8em; margin-top: 20px; opacity: 0.7; }}
        .region-header {{ background: #001100; border: 1px solid #0f0; padding: 8px 15px; font-weight: bold; color: #0f0; }}
        .ping-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 10px; margin: 15px 0; }}
        .ping-item {{ background: #000; border: 1px solid #003300; padding: 10px; }}
        .ping-item .name {{ font-size: 0.8em; color: #0f0; opacity: 0.8; margin-bottom: 5px; }}
        .ping-item .value {{ font-size: 1.2em; font-weight: bold; }}
        .traceroute {{ background: #000; border: 1px solid #003300; padding: 12px; font-family: 'Courier New', monospace; font-size: 0.8em; overflow-x: auto; }}
        .traceroute-hop {{ margin: 3px 0; color: #0f0; }}
        .traceroute-hop.success {{ color: #0f0; text-shadow: 0 0 3px #0f0; }}
        .traceroute-hop.fail {{ color: #f00; opacity: 0.7; }}
        .blocked-warning {{ background: #110000; border: 1px solid #f00; padding: 8px; color: #f00; }}
        .scroll-table {{ max-height: 400px; overflow-y: auto; }}
        .scroll-table::-webkit-scrollbar {{ width: 8px; }}
        .scroll-table::-webkit-scrollbar-track {{ background: #000; }}
        .scroll-table::-webkit-scrollbar-thumb {{ background: #0f0; }}
        .signature {{ text-align: right; color: #0f0; font-size: 0.8em; margin-top: 30px; opacity: 0.7; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🔐 VPN TESTER CS-CART REPORT</h1>
        <p class="timestamp">Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>

        <div class="summary">
            <div class="card total">
                <h3>{len(self.results)}</h3>
                <p>Total Configs</p>
            </div>
            <div class="card working">
                <h3>{len(working)}</h3>
                <p>Working ✅</p>
            </div>
            <div class="card not-working">
                <h3>{len(not_working)}</h3>
                <p>Not Working ❌</p>
            </div>
        </div>
"""

        # Working configs table
        if working:
            html += """
        <h2>✅ WORKING CONFIGS</h2>
        <div class="scroll-table">
        <table>
            <thead>
                <tr>
                    <th>Name</th>
                    <th>Host:Port</th>
                    <th>SNI</th>
                    <th>Security</th>
                    <th>IP</th>
                    <th>Avg Ping</th>
                    <th>Speed (100MB)</th>
                </tr>
            </thead>
            <tbody>
"""
            for r in sorted(working, key=lambda x: self._get_avg_ping(x)):
                info = r.get('info', {})
                avg_ping = self._get_avg_ping(r)
                ping_class = 'ping-good' if avg_ping < 150 else ('ping-avg' if avg_ping < 400 else 'ping-bad')
                speed = r.get('speed', {})
                speed_str = 'N/A'
                speed_class = ''
                for url, data in speed.items():
                    if data.get('status') == 'ok':
                        speed_mbps = data.get('speed_mbps', 0)
                        speed_str = f"{speed_mbps:.2f} Mbps ({data.get('size_mb', 0):.1f}MB/{data.get('time_sec', 0):.1f}s)"
                        speed_class = 'speed' if speed_mbps > 5 else 'speed-slow'
                        break
                    elif data.get('blocked'):
                        speed_str = '⚠️ BLOCKED?'
                        speed_class = 'speed-slow'

                html += f"""                <tr>
                    <td class="config-name">{r.get('name', 'Unknown')}</td>
                    <td>{info.get('host', '?')}:{info.get('port', '?')}</td>
                    <td>{info.get('sni', 'N/A')}</td>
                    <td>{info.get('security', 'none')}</td>
                    <td>{r.get('ip_check', {}).get('ip', 'N/A')}</td>
                    <td class="{ping_class}">{avg_ping:.0f} ms</td>
                    <td class="{speed_class}">{speed_str}</td>
                </tr>
"""
            html += """            </tbody>
        </table>
        </div>
"""

        # Ping details by region
        if working:
            html += """
        <h2>📍 PING DETAILS BY REGION</h2>
"""
            for r in working:
                html += f"""
        <h3>{r.get('name', 'Unknown')}</h3>
        <div class="ping-grid">
"""
                ping = r.get('ping', {})
                regions = {}
                for server, data in ping.items():
                    region = data.get('region', 'XX')
                    if region not in regions:
                        regions[region] = []
                    regions[region].append((server, data))
                
                for region, servers in sorted(regions.items()):
                    region_name = '🇷🇺 Russia' if region == 'RU' else '🌍 International'
                    html += f"""
            <div>
                <div class="region-header">{region_name} ({region})</div>
"""
                    for server, data in servers:
                        status = data.get('status', 'unknown')
                        time_ms = data.get('time_ms', 0)
                        ping_class = 'ping-good' if time_ms < 150 else ('ping-avg' if time_ms < 400 else 'ping-bad')
                        status_icon = '✅' if status == 'ok' else ('⏱️' if status == 'timeout' else '❌')
                        html += f"""
                <div class="ping-item">
                    <div class="name">{status_icon} {server}</div>
                    <div class="value {ping_class}">{time_ms:.0f} ms</div>
"""
                        if data.get('http_code') and data['http_code'] != '000':
                            html += f"""                    <div style="font-size: 0.75em; opacity: 0.7;">HTTP: {data['http_code']}</div>
"""
                        html += """                </div>
"""
                    html += """
            </div>
"""
                html += """
        </div>
"""

        # Traceroute details - упрощённо
        if working:
            html += """
        <h2>🛤️ TRACEROUTE STATUS</h2>
        <div class="scroll-table">
        <table>
            <thead>
                <tr>
                    <th>Config</th>
                    <th>Yandex RU</th>
                    <th>Office SMTK</th>
                    <th>Google</th>
                    <th>GitHub</th>
                </tr>
            </thead>
            <tbody>
"""
            for r in working:
                trace = r.get('traceroute', {})
                if trace:
                    yandex = trace.get('Yandex RU', {}).get('status_text', '❓')
                    office = trace.get('Office SMTK', {}).get('status_text', '❓')
                    google = trace.get('Google', {}).get('status_text', '❓')
                    github = trace.get('GitHub', {}).get('status_text', '❓')
                    
                    html += f"""                <tr>
                    <td class="config-name">{r.get('name', 'Unknown')}</td>
                    <td>{yandex}</td>
                    <td>{office}</td>
                    <td>{google}</td>
                    <td>{github}</td>
                </tr>
"""
            html += """            </tbody>
        </table>
        </div>
"""

        # DNS Check details
        if working:
            html += """
        <h2>🌐 DNS CHECK</h2>
        <div class="scroll-table">
        <table>
            <thead>
                <tr>
                    <th>Config</th>
                    <th>Local DNS</th>
                    <th>Status</th>
                    <th>Recommendation</th>
                </tr>
            </thead>
            <tbody>
"""
            for r in working:
                dns = r.get('dns_check', {})
                dns_servers = ', '.join(dns.get('local_dns', ['Unknown']))
                status = '⚠️ PROVIDER DNS' if dns.get('uses_provider_dns') else ('✅ PUBLIC DNS' if dns.get('uses_public_dns') else 'ℹ️ LOCAL DNS')
                status_class = 'speed-slow' if dns.get('uses_provider_dns') else 'speed'
                recommendation = dns.get('recommendation', '')
                
                html += f"""                <tr>
                    <td class="config-name">{r.get('name', 'Unknown')}</td>
                    <td>{dns_servers}</td>
                    <td class="{status_class}">{status}</td>
                    <td style="font-size: 0.8em; opacity: 0.9;">{recommendation}</td>
                </tr>
"""
            html += """            </tbody>
        </table>
        </div>
"""

        # Speed test details
        if working:
            html += """
        <h2>🚀 SPEED TEST (100MB DOWNLOAD)</h2>
        <div class="scroll-table">
        <table>
            <thead>
                <tr>
                    <th>Config</th>
                    <th>Size</th>
                    <th>Speed</th>
                    <th>Time</th>
                    <th>Status</th>
                </tr>
            </thead>
            <tbody>
"""
            for r in working:
                speed = r.get('speed', {})
                for url, data in speed.items():
                    if data.get('status') == 'ok':
                        html += f"""                <tr>
                    <td class="config-name">{r.get('name', 'Unknown')}</td>
                    <td>{data.get('size_mb', 0):.1f} MB</td>
                    <td class="speed">{data.get('speed_mbps', 0):.2f} Mbps</td>
                    <td>{data.get('time_sec', 0):.1f}s</td>
                    <td><span class="status working">OK</span></td>
                </tr>
"""
                    elif data.get('blocked'):
                        html += f"""                <tr>
                    <td class="config-name">{r.get('name', 'Unknown')}</td>
                    <td>{data.get('size_bytes', 0) / 1000:.0f} KB</td>
                    <td class="speed-slow">N/A</td>
                    <td>-</td>
                    <td><div class="blocked-warning">⚠️ BLOCKED?</div></td>
                </tr>
"""
            html += """            </tbody>
        </table>
        </div>
"""

        # Not working configs
        if not_working:
            html += """
        <h2>❌ NOT WORKING CONFIGS</h2>
        <table>
            <thead>
                <tr>
                    <th>Name</th>
                    <th>Host:Port</th>
                    <th>Status</th>
                    <th>Details</th>
                </tr>
            </thead>
            <tbody>
"""
            for r in not_working:
                info = r.get('info', {})
                details = r.get('ip_check', {}).get('error', r.get('status', 'unknown'))
                html += f"""                <tr>
                    <td class="config-name">{r.get('name', 'Unknown')}</td>
                    <td>{info.get('host', '?')}:{info.get('port', '?')}</td>
                    <td><span class="status {r.get('status', 'not_working')}">{r.get('status', 'not_working')}</span></td>
                    <td style="opacity: 0.8;">{details}</td>
                </tr>
"""
            html += """            </tbody>
        </table>
"""

        html += f"""
        <div class="signature">
            <p>━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━</p>
            <p>VPN TESTER CS-CART | by MatrixHasYou</p>
        </div>
    </div>
</body>
</html>
"""
        return html
    
    def _get_avg_ping(self, result: dict) -> float:
        """Средний пинг"""
        ping = result.get('ping', {})
        times = []
        for server, data in ping.items():
            if data.get('status') == 'ok':
                times.append(data.get('time_ms', 0))
        return sum(times) / len(times) if times else float('inf')
    
    def _generate_md(self) -> str:
        """Генерация MD отчёта"""
        working = [r for r in self.results if r.get('status') == 'working']
        not_working = [r for r in self.results if r.get('status') != 'working']
        
        md = f"""# 🔐 VPN Tester Report

**Generated:** {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

## 📊 Summary

| Metric | Value |
|--------|-------|
| Total Configs | {len(self.results)} |
| Working | {len(working)} |
| Not Working | {len(not_working)} |

---

## ✅ Working Configs ({len(working)})

| Name | Host:Port | SNI | Security | IP | Avg Ping | Speed |
|------|-----------|-----|----------|-----|----------|-------|
"""
        
        for r in sorted(working, key=lambda x: self._get_avg_ping(x)):
            info = r.get('info', {})
            avg_ping = self._get_avg_ping(r)
            speed = r.get('speed', {})
            speed_str = 'N/A'
            for url, data in speed.items():
                if data.get('status') == 'ok':
                    speed_str = f"{data.get('speed_mbps', 0):.2f} Mbps"
                    break
            
            md += f"| {r.get('name', 'Unknown')} | {info.get('host', '?')}:{info.get('port', '?')} | {info.get('sni', 'N/A')} | {info.get('security', 'none')} | {r.get('ip_check', {}).get('ip', 'N/A')} | {avg_ping:.0f}ms | {speed_str} |\n"
        
        md += f"\n---\n\n## ❌ Not Working Configs ({len(not_working)})\n\n"
        
        if not_working:
            md += "| Name | Host:Port | Status | Details |\n"
            md += "|------|-----------|--------|---------|\n"
            for r in not_working:
                info = r.get('info', {})
                details = r.get('ip_check', {}).get('error', r.get('status', 'unknown'))
                md += f"| {r.get('name', 'Unknown')} | {info.get('host', '?')}:{info.get('port', '?')} | {r.get('status', 'not_working')} | {details} |\n"
        
        md += f"\n---\n\n*Report generated by VPN Tester*\n"
        return md


if __name__ == "__main__":
    import sys
    
    tester = VpnTester()
    
    if len(sys.argv) > 1:
        command = sys.argv[1]
        
        if command == "test":
            tester.run_all_tests()
            html_file, md_file = tester.generate_report()
            print(f"Reports generated:")
            print(f"  HTML: {html_file}")
            print(f"  MD: {md_file}")
            
        elif command == "add":
            if len(sys.argv) >= 4:
                name = sys.argv[2]
                url = sys.argv[3]
                tester.save_config(name, url)
                print(f"Config '{name}' added")
            else:
                print("Usage: vpn_tester.py add <name> <vless_url>")
                
        elif command == "delete":
            if len(sys.argv) >= 3:
                name = sys.argv[2]
                tester.delete_config(name)
                print(f"Config '{name}' deleted")
            else:
                print("Usage: vpn_tester.py delete <name>")
                
        elif command == "list":
            tester.load_configs()
            for config in tester.configs:
                info = config.info
                print(f"{info.get('name', 'Unknown'):30} {info.get('host', '?'):30}:{info.get('port', '?')} {info.get('sni', 'N/A'):20} {info.get('security', 'none')}")
    else:
        print("VPN Tester - Test VLESS configurations")
        print("Usage:")
        print("  vpn_tester.py test     - Run all tests and generate reports")
        print("  vpn_tester.py add <name> <url> - Add new config")
        print("  vpn_tester.py delete <name> - Delete config")
        print("  vpn_tester.py list     - List all configs")
