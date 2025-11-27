import math
from datetime import datetime, timedelta

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt    
import matplotlib.dates as mdates
import pandas as pd

def get_last_monday():
    today = datetime.now()
    # 直接计算上周一
    last_monday = today - timedelta(days=today.weekday() + 7)
    return last_monday.strftime('%Y%m%d')

def aggreget(df, groupby_cols, numeric_cols):
    df_copy = df.copy()
    df_copy['hour'] = df_copy.index.floor('h')
    agg_dict = {}
    for col in df_copy.columns:
        if col in numeric_cols:
            agg_dict[col] = 'mean'
        else:
            agg_dict[col] = 'first'
    aggregated = df_copy.groupby(['hour'] + groupby_cols).agg(agg_dict)
    aggregated = aggregated.set_index('hour').sort_index()
    return aggregated

containers_data = pd.read_csv(f'monitor/logs/container_stats.log.{get_last_monday()}', header=None, names=['time', 'container_id', 'name', 'cpu_usage', 'memory_usage', 'memory_limit', 'cpu_limit', 'gpus'])
containers_data['time'] = pd.to_datetime(containers_data['time'], utc=True).dt.tz_convert('Asia/Shanghai')
containers_data = containers_data.set_index('time').sort_index()

containers_data = aggreget(containers_data, ['container_id', 'name', 'cpu_limit', 'memory_limit', 'gpus'], ['cpu_usage', 'memory_usage'])

gpus_data = pd.read_csv(f'monitor/logs/gpu_stats.log.{get_last_monday()}', header=None, names=['time', 'gpu_id', 'memory_usage', 'memory_limit', 'utilization'])
gpus_data['time'] = pd.to_datetime(gpus_data['time'], utc=True).dt.tz_convert('Asia/Shanghai')
gpus_data = gpus_data.set_index('time').sort_index()

gpus_data = aggreget(gpus_data, ['gpu_id', 'memory_limit'], ['memory_usage', 'utilization'])

container_ids = containers_data['container_id'].unique()
for id in container_ids:
    container_data = containers_data[containers_data['container_id'] == id]
    name = container_data['name'].iloc[0]
    gpus = list(set(map(int, container_data['gpus'].iloc[0].strip('[]').split())))
    cpu_limit = container_data['cpu_limit'].iloc[0]
    mem_limit = container_data['memory_limit'].iloc[0]
    container_data = container_data.drop(['container_id', 'name', 'gpus'], axis=1)

    print(f'Container: {name}')

    columns = math.ceil(1 + len(gpus) / 2)

    plt.figure(figsize=(12, 8))
    plt.suptitle(f'Container: {name} (ID: {id}, CPU: {cpu_limit} Core, Mem: {mem_limit / 1024} G, GPUs: {gpus})', fontsize=14)

    plt.subplot(columns, 2, 1)
    plt.title('CPU Usage')
    plt.axhline(y=cpu_limit, color='r', linestyle='--', label='CPU Limit')
    plt.plot(container_data.index, container_data['cpu_usage'], label='CPU Usage (%)', color='blue')
    plt.ylabel('CPU Usage (%)')
    plt.legend()
    # 设置X轴只在每天0点0分显示刻度
    ax = plt.gca()
    ax.xaxis.set_major_locator(mdates.DayLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')

    plt.subplot(columns, 2, 2)
    plt.title('Memory Usage')
    plt.axhline(y=mem_limit, color='r', linestyle='--', label='Memory Limit')
    plt.plot(container_data.index, container_data['memory_usage'], label='Memory Usage (MB)', color='blue')
    plt.ylabel('Memory Usage (MB)')
    plt.legend()
    # 设置X轴只在每天0点0分显示刻度
    ax = plt.gca()
    ax.xaxis.set_major_locator(mdates.DayLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
    plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha='right')

    for i in range(len(gpus)):
        gpu = gpus[i]
        print(f'GPU: {gpu}')
        gpu_data = gpus_data[gpus_data['gpu_id'] == gpu]
        print('Mem usage: ', len(gpu_data[gpu_data['memory_usage'] > 0]) / len(gpu_data), ' Max mem usage: ', gpu_data['memory_usage'].max())
        print('Utilization: ', len(gpu_data[gpu_data['utilization'] > 0]) / len(gpu_data), ' Max utilization: ', gpu_data['utilization'].max())
        gpu_mem_limit = gpu_data['memory_limit'].iloc[0]
        plt.subplot(columns, 2, 3 + i)
        plt.title(f'GPU {gpu} Usage')
        # 创建第一个Y轴 - GPU内存使用量
        ax1 = plt.gca()
        ax1.axhline(y=gpu_mem_limit, color='r', linestyle='--', alpha=0.7, label='Memory Limit')
        line1 = ax1.plot(gpu_data.index, gpu_data['memory_usage'], label='GPU Memory Usage (MB)', color='blue')
        ax1.set_ylabel('Memory Usage (MB)', color='blue')
        ax1.tick_params(axis='y', labelcolor='blue')
        
        # 创建第二个Y轴 - GPU利用率
        ax2 = ax1.twinx()
        line2 = ax2.plot(gpu_data.index, gpu_data['utilization'], label='GPU Utilization (%)', color='green', alpha=0.5)
        ax2.set_ylabel('Utilization (%)', color='green')
        ax2.tick_params(axis='y', labelcolor='green')
        
        # 对齐双Y轴的0刻度
        ax1.set_ylim(bottom=0, top=gpu_mem_limit * 1.1)
        ax2.set_ylim(bottom=0, top=100)
        
        # 确保两个Y轴的刻度数量相同，进一步保证对齐
        ax1.locator_params(axis='y', nbins=6)
        ax2.locator_params(axis='y', nbins=6)
        
        # 合并图例
        lines = line1 + line2
        labels = [l.get_label() for l in lines]
        ax1.legend(lines, labels, loc='upper left')
        # 设置X轴只在每天0点0分显示刻度
        ax1.xaxis.set_major_locator(mdates.DayLocator())
        ax1.xaxis.set_major_formatter(mdates.DateFormatter('%Y-%m-%d'))
        plt.setp(ax1.xaxis.get_majorticklabels(), rotation=45, ha='right')
    plt.tight_layout()
    plt.savefig(f'container_{name}_stats-{get_last_monday()}.png', dpi=300, bbox_inches='tight')