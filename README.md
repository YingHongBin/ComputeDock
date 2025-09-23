# 基于 Docker 与 NVIDIA Container Toolkit 的算力隔离容器

为提升算力服务器的资源利用率与多用户使用效率，本文设计并实现了一套基于 Docker 与 NVIDIA Container Toolkit 的容器化算力隔离方案。该方案可实现 GPU 资源的按需分配、用户任务之间的算力隔离，并通过统一的基础镜像环境，保障了深度学习任务在共享服务器环境下的可复现性与稳定性。

## 基础镜像环境介绍
镜像构建基底：
```
FROM nvidia/cuda:12.8.1-cudnn-devel-ubuntu24.04
```

镜像预安装组件如下：

- CUDA工具链（CUDA Toolkit/cuDNN），nvidia cuda镜像提供

- 包管理工具（conda），已换源ZJU mirror

> 推荐维护conda环境文件，新建容器后可以一键导入conda环境

- 系统工具（sudo/wget/curl/vim/git/openssh-server/openssh-client/tmux），apt安装，apt已换源ZJU mirror

## 容器构建

- 使用--gpus参数指定容器使用的具体GPU卡

- 使用--cpuset-cpus参数指定容器使用的特定cpu核

- 使用-m参数指定容器使用的内存限制

- 使用--shm-size参数指定容器共享内存大小，通常为内存的一半

> DataLoader设置--num_workers大于1时会启用多进程并行加载数据，加速训练数据的加载过程，提高 GPU 利用率。\
> 当使用多进程加载数据时，每个 worker 都可能：
> 1. 将数据缓存到 /dev/shm（共享内存）中；
> 2. 使用 multiprocessing 通信（也依赖 shared memory）；
> 3. PyTorch 的 tensor 默认支持共享内存以加速通信（pin_memory=True 时尤为明显）；<br>
>
> 因此，过小的共享内存配置可能导致Unexpected bus error encountered in worker. This might be caused by insufficient shared memory异常
- 通过-v $(pwd)/$USERNAME:/data将容器内的/data挂载至宿主机持久化

# 潜在问题

构建的容器在执行systemctl daemon-reload之后会出现显卡丢失的问题

```
(container) $ nvidia-smi -L
Failed to initialize NVML: Unknown Error
```

这是一个已知的问题，据称将在[nvidia-container-toolkit v1.18.0](https://github.com/NVIDIA/nvidia-container-toolkit/issues/1227)版本解决，目前可考虑[临时解决方案](https://github.com/NVIDIA/nvidia-container-toolkit/discussions/1133)。