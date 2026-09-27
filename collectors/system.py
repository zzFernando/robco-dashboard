import ipaddress
import platform
import time
from pathlib import Path

import psutil


def network_available():
    """An up interface with a usable IP; not a claim of Internet reachability."""
    stats = psutil.net_if_stats()
    for name, addresses in psutil.net_if_addrs().items():
        if name not in stats or not stats[name].isup:
            continue
        for address in addresses:
            try:
                ip = ipaddress.ip_address(address.address.split('%')[0])
                if not (ip.is_loopback or ip.is_link_local or ip.is_unspecified):
                    return True
            except ValueError:
                continue
    return False


def collect_system(root=None):
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage(str(Path(root or Path.cwd()).anchor))
    try:
        network = network_available()
    except (psutil.Error, OSError):
        network = None
    temperature = None
    try:
        readings = psutil.sensors_temperatures(fahrenheit=False)
        values = [reading.current for group in readings.values() for reading in group if reading.current is not None]
        if values:
            temperature = round(sum(values) / len(values), 1)
    except (AttributeError, psutil.Error, OSError):
        pass
    return {
        'hostname': platform.node() or 'UNKNOWN',
        'os': platform.system(),
        'cpu_percent': psutil.cpu_percent(interval=None),
        'memory_percent': memory.percent,
        'memory_used_gb': round(memory.used / 1024**3, 1),
        'memory_total_gb': round(memory.total / 1024**3, 1),
        'disk_percent': disk.percent,
        'disk_used_gb': round(disk.used / 1024**3, 1),
        'disk_total_gb': round(disk.total / 1024**3, 1),
        'disk_path': str(Path(root or Path.cwd()).anchor),
        'uptime_seconds': max(0, int(time.time() - psutil.boot_time())),
        'network_available': network,
        'temperature_c': temperature,
        'media': {'available': False, 'title': None, 'artist': None, 'status': 'UNKNOWN'},
    }
