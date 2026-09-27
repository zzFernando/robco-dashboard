import platform
import time
import psutil

def collect_system():
    memory = psutil.virtual_memory()
    return {
        'hostname': platform.node() or 'UNKNOWN',
        'os': platform.system(),
        'cpu_percent': psutil.cpu_percent(interval=None),
        'memory_percent': memory.percent,
        'memory_used_gb': round(memory.used / 1024**3, 1),
        'memory_total_gb': round(memory.total / 1024**3, 1),
        'timestamp': int(time.time()),
    }
