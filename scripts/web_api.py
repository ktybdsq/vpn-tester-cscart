#!/usr/bin/env python3
"""
VPN Tester Web API - Flask приложение для управления тестером
"""

from flask import Flask, request, jsonify, send_from_directory, send_file
import os
import sys
import threading
import subprocess
from pathlib import Path
import time

app = Flask(__name__, static_folder='../web', static_url_path='')

BASE_DIR = Path(__file__).parent.parent
CONFIGS_DIR = BASE_DIR / "configs"
REPORTS_DIR = BASE_DIR / "reports"
SCRIPTS_DIR = BASE_DIR / "scripts"

# Глобальная переменная для статуса тестирования
test_status = {
    'running': False,
    'total': 0,
    'current': 0,
    'current_config': '',
    'completed': False,
    'error': None,
    'start_time': None,
    'end_time': None
}

# Импорт тестера
sys.path.insert(0, str(SCRIPTS_DIR))
from vpn_tester import VpnTester, VlessConfig


@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')


@app.route('/api/configs', methods=['GET'])
def get_configs():
    """Получить список всех конфигураций"""
    tester = VpnTester()
    tester.load_configs()
    
    configs = []
    for config in tester.configs:
        info = config.info
        configs.append({
            'name': info.get('name', 'Unknown'),
            'host': info.get('host', '?'),
            'port': info.get('port', '?'),
            'sni': info.get('sni', 'N/A'),
            'security': info.get('security', 'none'),
            'type': info.get('type', 'tcp'),
            'country': info.get('country', '??')
        })
    
    return jsonify({'configs': configs, 'total': len(configs)})


@app.route('/api/configs', methods=['POST'])
def add_config():
    """Добавить новую конфигурацию"""
    data = request.json
    name = data.get('name')
    url = data.get('url')
    
    if not name or not url:
        return jsonify({'error': 'Name and URL required'}), 400
    
    if not url.startswith('vless://'):
        return jsonify({'error': 'Invalid VLESS URL'}), 400
    
    tester = VpnTester()
    
    # Проверка на дубликат
    config_file = CONFIGS_DIR / f"{name}.txt"
    if config_file.exists():
        return jsonify({'error': 'Config with this name already exists'}), 400
    
    tester.save_config(name, url)
    return jsonify({'success': True, 'message': f'Config {name} added'})


@app.route('/api/configs/<name>', methods=['DELETE'])
def delete_config(name):
    """Удалить конфигурацию"""
    tester = VpnTester()
    tester.delete_config(name)
    return jsonify({'success': True, 'message': f'Config {name} deleted'})


@app.route('/api/test', methods=['POST'])
def run_tests():
    """Запустить тестирование всех конфигураций"""
    global test_status
    
    if test_status['running']:
        return jsonify({'error': 'Tests already running'}), 400
    
    def run_test_thread():
        global test_status
        try:
            test_status = {
                'running': True,
                'total': 0,
                'current': 0,
                'current_config': '',
                'completed': False,
                'error': None,
                'start_time': time.time(),
                'end_time': None
            }
            
            tester = VpnTester()
            tester.load_configs()
            
            test_status['total'] = len(tester.configs)
            all_results = []  # Сохраняем ВСЕ результаты
            
            for i, config in enumerate(tester.configs):
                test_status['current'] = i
                test_status['current_config'] = config.name
                print(f"[{i+1}/{len(tester.configs)}] Testing {config.name}...")
                
                result = tester.test_config(config)
                all_results.append(result)
                
                print(f"[{i+1}/{len(tester.configs)}] {config.name}: {result.get('status', 'unknown')}")
                
                # Пауза между тестами
                time.sleep(1)
            
            # Генерация отчёта со ВСЕМИ результатами
            print("Generating report...")
            test_status['current_config'] = 'Generating report...'
            
            # Создаём новый тестер для отчёта
            report_tester = VpnTester()
            report_tester.results = all_results
            html_file, md_file = report_tester.generate_report()
            
            # Отправка в Telegram (в фоне)
            try:
                import threading
                telegram_thread = threading.Thread(target=send_to_telegram, args=(html_file,))
                telegram_thread.daemon = True
                telegram_thread.start()
                print("📤 Sending report to Telegram...")
            except Exception as e:
                print(f"Telegram send error: {e}")
            
            test_status['running'] = False
            test_status['completed'] = True
            test_status['end_time'] = time.time()
            print(f"✅ Tests completed in {test_status['end_time'] - test_status['start_time']:.1f}s")
            print(f"📊 Generated report with {len(all_results)} configs")
            
        except Exception as e:
            import traceback
            test_status['running'] = False
            test_status['error'] = str(e) + '\n' + traceback.format_exc()
            test_status['end_time'] = time.time()
            print(f"❌ Test error: {e}")

    thread = threading.Thread(target=run_test_thread)
    thread.start()

    return jsonify({
        'success': True,
        'message': 'Tests started',
        'total_configs': len(VpnTester().load_configs() or [])
    })


@app.route('/api/test/status', methods=['GET'])
def get_test_status():
    """Получить статус текущего тестирования"""
    global test_status
    
    status = test_status.copy()
    
    # Рассчитываем прогресс в процентах
    if status['total'] > 0:
        # Каждый конфиг = (100 / total)%, генерация отчёта = ещё ~10%
        if status['completed']:
            status['progress'] = 100
        else:
            # Прогресс = (текущий / всего) * 90% + немного за текущий
            base_progress = (status['current'] / status['total']) * 90
            status['progress'] = min(99, int(base_progress))
    else:
        status['progress'] = 0
    
    # Добавляем время выполнения
    if status['start_time']:
        if status['end_time']:
            status['elapsed'] = round(status['end_time'] - status['start_time'], 1)
        else:
            status['elapsed'] = round(time.time() - status['start_time'], 1)
    
    return jsonify(status)


@app.route('/api/test/single', methods=['POST'])
def test_single():
    """Протестировать одну конфигурацию с созданием отчёта и отправкой в Telegram"""
    data = request.json
    name = data.get('name')

    if not name:
        return jsonify({'error': 'Name required'}), 400

    tester = VpnTester()
    tester.load_configs()

    config = None
    for c in tester.configs:
        if c.name == name:
            config = c
            break

    if not config:
        return jsonify({'error': 'Config not found'}), 404

    print(f"🔍 Testing single config: {name}...")
    start_time = time.time()
    
    # Тестируем конфиг
    result = tester.test_config(config)
    elapsed = time.time() - start_time
    result['test_duration'] = round(elapsed, 2)
    
    tester.results = [result]  # Сохраняем результат
    
    # Генерируем отчёт
    print(f"📊 Generating report for {name}...")
    try:
        html_file, md_file = tester.generate_report()
        print(f"✅ Report generated: {html_file}")
        
        # Отправляем в Telegram
        print(f"📤 Sending report to Telegram...")
        try:
            import threading
            telegram_thread = threading.Thread(target=send_to_telegram, args=(html_file, elapsed))
            telegram_thread.daemon = True
            telegram_thread.start()
        except Exception as e:
            print(f"Telegram send error: {e}")
    except Exception as e:
        print(f"❌ Report generation error: {e}")
        import traceback
        traceback.print_exc()
    
    print(f"✅ Test completed for {name}: {result.get('status', 'unknown')} ({elapsed:.1f}s)")
    
    return jsonify(result)


@app.route('/api/reports', methods=['GET'])
def get_reports():
    """Получить список отчётов"""
    reports = []
    for f in sorted(REPORTS_DIR.glob("report_*.html"), reverse=True):
        reports.append({
            'name': f.stem,
            'file': f.name,
            'created': f.stat().st_mtime
        })
    return jsonify({'reports': reports})


@app.route('/api/reports/latest', methods=['GET'])
def get_latest_report():
    """Получить последний отчёт"""
    latest = REPORTS_DIR / "latest.html"
    if latest.exists():
        return send_file(latest)
    return jsonify({'error': 'No reports yet'}), 404


@app.route('/api/reports/<filename>', methods=['GET'])
def get_report(filename):
    """Получить конкретный отчёт"""
    report = REPORTS_DIR / filename
    if report.exists():
        return send_file(report)
    return jsonify({'error': 'Report not found'}), 404


@app.route('/api/reports/<filename>', methods=['DELETE'])
def delete_report(filename):
    """Удалить отчёт"""
    try:
        report_html = REPORTS_DIR / filename
        report_md = REPORTS_DIR / filename.replace('.html', '.md')
        
        deleted = []
        if report_html.exists():
            report_html.unlink()
            deleted.append(filename)
        if report_md.exists():
            report_md.unlink()
            deleted.append(report_md.name)
        
        return jsonify({'success': True, 'deleted': deleted})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/api/status', methods=['GET'])
def get_status():
    """Получить статус системы"""
    # Проверка наличия Xray
    xray_bin = BASE_DIR / "xray" / "xray"
    xray_exists = xray_bin.exists()

    # Количество конфигов
    config_count = len(list(CONFIGS_DIR.glob("*.txt")))

    # Количество отчётов
    report_count = len(list(REPORTS_DIR.glob("report_*.html")))

    return jsonify({
        'xray_installed': xray_exists,
        'configs_count': config_count,
        'reports_count': report_count
    })


# Telegram Bot Integration
# Token and Chat ID are loaded from environment variables or .env file
# Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in your environment
TELEGRAM_BOT_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN', '')
TELEGRAM_CHAT_ID = os.environ.get('TELEGRAM_CHAT_ID', '')

def get_system_info():
    """Собрать информацию о системе"""
    import platform
    import subprocess
    import socket
    
    info = {
        'hostname': socket.gethostname(),
        'local_ip': socket.gethostbyname(socket.gethostname()),
        'os': f"{platform.system()} {platform.release()}",
        'python_version': platform.python_version(),
        'cpu_count': os.cpu_count(),
    }
    
    # Получить версию Docker
    try:
        result = subprocess.run(['docker', '--version'], capture_output=True, text=True, timeout=5)
        info['docker_version'] = result.stdout.strip()
    except:
        info['docker_version'] = 'Unknown'
    
    # Получить объем RAM
    try:
        with open('/proc/meminfo', 'r') as f:
            for line in f:
                if line.startswith('MemTotal:'):
                    mem_kb = int(line.split()[1])
                    info['ram_gb'] = round(mem_kb / 1024 / 1024, 2)
                    break
    except:
        info['ram_gb'] = 'Unknown'
    
    # Проверить белый IP - через curl с хоста
    try:
        # Пробуем получить публичный IP
        result = subprocess.run(
            ['curl', '-s', '--connect-timeout', '5', 'https://api.ipify.org?format=json'],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            import json
            public_ip = json.loads(result.stdout).get('ip', 'Unknown')
            info['public_ip'] = public_ip
            # Сравниваем с локальным - если отличаются, значит есть NAT
            info['has_static_ip'] = True  # Считаем что статический если получили ответ
        else:
            info['public_ip'] = 'Unknown'
            info['has_static_ip'] = False
    except:
        info['public_ip'] = 'Unknown'
        info['has_static_ip'] = False
    
    # Получить DNS серверы
    dns_servers = []
    try:
        with open('/etc/resolv.conf', 'r') as f:
            for line in f:
                if line.strip().startswith('nameserver'):
                    dns_servers.append(line.split()[1])
        info['dns_servers'] = ', '.join(dns_servers) if dns_servers else 'Unknown'
    except:
        info['dns_servers'] = 'Unknown'
    
    return info


def send_to_telegram(report_file: Path, test_duration: float = 0, working_config=None):
    """
    Отправить отчет в Telegram бот через встроенный VPN прокси.
    
    Автономная функция - НЕ зависит от внешнего прокси.
    Использует Xray для поднятия SOCKS5 прокси внутри контейнера.
    """
    import requests
    import subprocess
    import time
    import json
    import socket

    # Импортируем LOGS_DIR локально
    from pathlib import Path as P
    _base_dir = P(__file__).parent.parent
    if not (_base_dir / "configs").exists():
        _base_dir = P(__file__).parent
    _logs_dir = _base_dir / "logs"

    proxies = None
    xray_proc = None
    xray_config_file = None

    # Проверяем, есть ли токен и chat_id
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("⚠️ Telegram bot token or chat ID not configured. Skipping Telegram send.")
        print("   Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID environment variables.")
        return False

    try:
        # === ШАГ 1: Пробуем найти внешний прокси (быстрая проверка) ===
        # Это может помочь, если у сотрудника уже есть VPN
        external_hosts = ['127.0.0.1', 'host.docker.internal', '172.17.0.1', '172.22.0.1']
        external_ports = [10808, 10828, 8080, 3128]

        for host in external_hosts:
            for port in external_ports:
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(1)
                    result = sock.connect_ex((host, port))
                    sock.close()
                    if result == 0:
                        proxies = {
                            'http': f'socks5h://{host}:{port}',
                            'https': f'socks5h://{host}:{port}'
                        }
                        print(f"✅ Found external proxy at {host}:{port}")
                        break
                except:
                    pass
            if proxies:
                break

        # === ШАГ 2: Если нет внешнего прокси - запускаем свой Xray ===
        if not proxies:
            print("🔑 No external proxy found - starting internal Xray proxy...")

            # Если не передали рабочий конфиг - ищем его
            if working_config is None:
                tester = VpnTester()
                tester.load_configs()
                # Берём первый доступный конфиг
                if len(tester.configs) > 0:
                    working_config = tester.configs[0]
                    print(f"   Using config '{working_config.name}' for proxy")

            # Запускаем Xray с конфигом как SOCKS прокси
            if working_config:
                try:
                    print(f"🔑 Starting Xray proxy with config: {working_config.name}...")

                    # Генерируем конфиг для Xray (SOCKS порт 11080)
                    xray_config = working_config.to_xray_config(11080, 11081)
                    xray_config_file = _logs_dir / f"xray_telegram_proxy_{int(time.time())}.json"

                    with open(xray_config_file, 'w') as f:
                        json.dump(xray_config, f, indent=2)

                    # Запускаем Xray
                    xray_bin = _base_dir / "xray" / "xray"
                    if not xray_bin.exists():
                        print(f"⚠️ Xray binary not found at {xray_bin}")
                    else:
                        xray_proc = subprocess.Popen(
                            [str(xray_bin), 'run', '-c', str(xray_config_file)],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE
                        )

                        # Ждём запуска (даём больше времени)
                        for _ in range(10):
                            time.sleep(0.5)
                            if xray_proc.poll() is not None:
                                # Процесс умер
                                stderr_output = xray_proc.stderr.read().decode() if xray_proc.stderr else 'unknown'
                                print(f"⚠️ Xray proxy failed to start: {stderr_output}")
                                break

                        # Проверяем, работает ли прокси
                        if xray_proc.poll() is None:
                            # Проверяем доступность порта
                            for _ in range(5):
                                try:
                                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                                    sock.settimeout(1)
                                    result = sock.connect_ex(('127.0.0.1', 11080))
                                    sock.close()
                                    if result == 0:
                                        proxies = {
                                            'http': 'socks5h://127.0.0.1:11080',
                                            'https': 'socks5h://127.0.0.1:11080'
                                        }
                                        print(f"✅ Internal Xray proxy started on port 11080")
                                        break
                                except:
                                    pass
                                time.sleep(1)

                except Exception as e:
                    print(f"⚠️ Failed to start Xray proxy: {e}")

        # === ШАГ 3: Проверяем доступность Telegram ===
        if proxies:
            try:
                test_resp = requests.get('https://api.telegram.org', timeout=15, proxies=proxies)
                if test_resp.status_code == 200:
                    print(f"✅ Telegram API accessible via proxy")
                else:
                    print(f"⚠️ Telegram API returned status {test_resp.status_code}")
            except Exception as e:
                print(f"⚠️ Telegram API check failed: {e}")
        else:
            print("⚠️ No proxy available - will try direct connection (may fail in Russia)")

        # === ШАГ 4: Отправляем сообщение ===
        system_info = get_system_info()

        message = f"""
🔐 <b>VPN TESTER CS-CART - TEST REPORT</b>

⏱️ <b>Test Duration:</b> <code>{test_duration:.1f} seconds</code>

🖥️ <b>SYSTEM INFO:</b>
• Hostname: <code>{system_info['hostname']}</code>
• Local IP: <code>{system_info['local_ip']}</code>
• Public IP: <code>{system_info['public_ip']}</code>
• Static IP: {'✅ Yes' if system_info['has_static_ip'] else '❌ No'}
• OS: <code>{system_info['os']}</code>
• RAM: <code>{system_info['ram_gb']} GB</code>
• CPU Cores: <code>{system_info['cpu_count']}</code>
• Docker: <code>{system_info['docker_version']}</code>
• Python: <code>{system_info['python_version']}</code>
• DNS: <code>{system_info.get('dns_servers', 'Unknown')}</code>

📊 <b>HTML Report file attached below.</b>

━━━━━━━━━━━━━━━━━━━━
<b>by MatrixHasYou</b>
"""

        # Отправляем текстовое сообщение
        msg_sent = False
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
            data = {
                'chat_id': TELEGRAM_CHAT_ID,
                'text': message,
                'parse_mode': 'HTML'
            }
            resp = requests.post(url, json=data, timeout=30, proxies=proxies)
            if resp.status_code == 200:
                print(f"✅ Telegram message sent successfully!")
                msg_sent = True
            else:
                print(f"Telegram message error ({resp.status_code}): {resp.text}")
        except Exception as msg_error:
            print(f"Message send error: {msg_error}")

        # Отправляем файл отчёта
        doc_sent = False
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
            with open(report_file, 'rb') as f:
                files = {'document': f}
                data = {'chat_id': TELEGRAM_CHAT_ID}
                resp = requests.post(url, files=files, data=data, timeout=120, proxies=proxies)
                if resp.status_code == 200:
                    print(f"✅ Telegram document sent successfully!")
                    doc_sent = True
                else:
                    print(f"Telegram document error ({resp.status_code}): {resp.text}")
        except Exception as doc_error:
            print(f"Document send error: {doc_error}")

        if msg_sent or doc_sent:
            print(f"✅ Report sent to Telegram: {report_file.name}")
            return True
        else:
            print(f"❌ Failed to send report to Telegram")
            return False

    except Exception as e:
        print(f"❌ Telegram error: {e}")
        import traceback
        traceback.print_exc()
        return False

    finally:
        # === ШАГ 5: Останавливаем Xray прокси ===
        if xray_proc:
            try:
                xray_proc.terminate()
                xray_proc.wait(timeout=5)
                print(f"🛑 Internal Xray proxy stopped")
            except:
                xray_proc.kill()

        # Удаляем временный конфиг
        if xray_config_file and xray_config_file.exists():
            try:
                xray_config_file.unlink()
            except:
                pass


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
