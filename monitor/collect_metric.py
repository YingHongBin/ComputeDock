import subprocess
import logging
import logging.handlers
import os
import time
import argparse

def setup_loggers():
    os.makedirs('logs', exist_ok=True)

    container_logger = logging.getLogger('container_stats')
    container_logger.setLevel(logging.INFO)
    container_logger.handlers.clear()
    container_handler = logging.handlers.TimedRotatingFileHandler(
        filename='logs/container_stats.log',
        when='W6',
        interval=1,
        encoding='utf-8'
    )
    container_handler.suffix = "%Y%m%d"
    formatter = logging.Formatter('%(message)s')
    container_handler.setFormatter(formatter)
    container_logger.addHandler(container_handler)

    gpu_logger = logging.getLogger('gpu_stats')
    gpu_logger.setLevel(logging.INFO)
    gpu_logger.handlers.clear()
    gpu_handler = logging.handlers.TimedRotatingFileHandler(
        filename='logs/gpu_stats.log',
        when='W6',
        interval=1,
        encoding='utf-8',
    )
    gpu_handler.suffix = "%Y%m%d"
    gpu_formatter = logging.Formatter('%(message)s')
    gpu_handler.setFormatter(gpu_formatter)
    gpu_logger.addHandler(gpu_handler)

    return container_logger, gpu_logger

def convert_mem_str(mem_str):
    '''
    Convert memory string like '500.2MiB' or '2GiB' to MB float
    '''
    units = {
        'B': 1 / (1024 * 1024),
        'KB': 1 / 1024,
        'MB': 1,
        'MiB': 1,
        'GB': 1024,
        'GiB': 1024,
        'TB': 1024 * 1024,
        'TiB': 1024 * 1024
    }
    mem = mem_str[:-3]
    unit = mem_str[-3:]
    return float(mem) * units.get(unit, 1)

def count_cpus(cpuset_str):
    '''
    Count number of CPUs from a cpuset string.

    The cpuset string may contain:
      - Continuous ranges, e.g. "0-3"
      - Comma-separated individual CPUs, e.g. "0,1,2,3"
    '''
    if not cpuset_str or not cpuset_str.strip():
        return 0
    cpus = set()
    for part in cpuset_str.split(','):
        part = part.strip()
        if '-' in part:
            start, end = part.split('-')
            cpus.update(range(int(start), int(end) + 1))
        else:
            cpus.add(int(part))
    return len(cpus)

def collect_docker_stats():
    '''
    Collect Docker container statistics using docker stats command
    '''
    
    cmd = [
        'docker', 'stats', '--no-stream', '--format',
        '{{.Container}},{{.Name}},{{.CPUPerc}},{{.MemUsage}}'
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    
    containers = {}
    for line in result.stdout.strip().split('\n'):
        if line:
            parts = line.split(',')
            if len(parts) >= 4:
                containers[parts[0]] = {
                    'name': parts[1],
                    'cpu_usage': float(parts[2][:-1]) / 100.0,
                    'memory_usage': convert_mem_str(parts[3].split(' / ')[0]),  # only take used memory
                    'memory_limit': convert_mem_str(parts[3].split(' / ')[1])  # only take memory limit
                }
    return containers

def collect_nvidia_smi():
    '''
    Collect NVIDIA GPU information using nvidia-smi
    '''
    
    cmd = [
        'nvidia-smi', '--query-gpu=index,name,memory.used,memory.total,utilization.gpu',
        '--format=csv,noheader,nounits'
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    
    gpus = {}
    for line in result.stdout.strip().split('\n'):
        if line:
            parts = [part.strip() for part in line.split(',')]
            if len(parts) >= 5:
                gpus[parts[0]] = {
                    'memory_used': parts[2],
                    'memory_total': parts[3],
                    'utilization': parts[4]
                }
    return gpus

def collect_docker_info(containers):
    '''
    Collect container inspect details to get cpu limit and gpu bindings
    '''
    for container_id in containers:
        inspect_cmd = ['docker', 'inspect', '--format', 
                     '{{.HostConfig.CpusetCpus}}|{{if .HostConfig.DeviceRequests}}{{(index .HostConfig.DeviceRequests 0).DeviceIDs}}{{else}}none{{end}}',
                     container_id]
        result = subprocess.run(inspect_cmd, capture_output=True, text=True, check=True)

        cpuset_info = result.stdout.strip().split('\n')[0].split('|')[0]
        gpus = result.stdout.strip().split('\n')[0].split('|')[1]
        containers[container_id]['cpu_limit'] = count_cpus(cpuset_info)
        containers[container_id]['gpus'] = gpus
    return containers

def log_metrics(logger, mertric_dict, log_time):
    print(time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(logger.handlers[0].rolloverAt)))
    ts = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(log_time))
    for key, metrics in mertric_dict.items():
        log_line = f"{ts},{key}," + ",".join(f"{v}" for k, v in metrics.items())
        logger.info(log_line)

if __name__ == "__main__":

    parser = argparse.ArgumentParser(description="Collect Docker container and GPU metrics.")
    parser.add_argument('--interval', type=int, default=5,
                        help='Interval in seconds between data collections.')

    args = parser.parse_args()

    container_logger, gpu_logger = setup_loggers()

    while True:
        start_time = time.time()
        containers = collect_docker_info(collect_docker_stats())
        log_metrics(container_logger, containers, start_time)
        gpus = collect_nvidia_smi()
        log_metrics(gpu_logger, gpus, start_time)
        execution_time = time.time() - start_time
        print(f"Data collection completed in {execution_time:.2f} seconds.")
        sleep_time = args.interval - execution_time
        if sleep_time > 0:
            time.sleep(sleep_time)