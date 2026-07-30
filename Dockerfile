FROM nvidia/cuda:12.8.1-cudnn-devel-ubuntu24.04 AS runtime-base

RUN sed -i \
        -e 's|http://archive.ubuntu.com/ubuntu/|https://mirrors.zju.edu.cn/ubuntu/|g' \
        -e 's|http://security.ubuntu.com/ubuntu/|https://mirrors.zju.edu.cn/ubuntu/|g' \
        /etc/apt/sources.list.d/ubuntu.sources \
    && rm -f /etc/apt/sources.list

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        git \
        openssh-client \
        openssh-server \
        python3 \
        python3-venv \
        sudo \
        supervisor \
        tmux \
        tzdata \
        vim \
        wget \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/*

# SSH settings.
RUN mkdir -p /run/sshd \
    && sed 's@session\s*required\s*pam_loginuid.so@session optional pam_loginuid.so@g' \
        -i /etc/pam.d/sshd
ENV NOTVISIBLE="in users profile"
RUN echo "export VISIBLE=now" >> /etc/profile
EXPOSE 22

# Install Miniconda for interactive users. The Agent never uses this Python.
RUN wget https://repo.continuum.io/miniconda/Miniconda3-latest-Linux-x86_64.sh -O Miniconda.sh \
    && /bin/bash Miniconda.sh -b -p /opt/conda \
    && rm Miniconda.sh

ENV PATH=/opt/conda/bin:$PATH
RUN printf '%s\n' \
        'channels:' \
        '  - defaults' \
        'show_channel_urls: true' \
        'default_channels:' \
        '  - https://mirrors.zju.edu.cn/anaconda/pkgs/main' \
        '  - https://mirrors.zju.edu.cn/anaconda/pkgs/r' \
        '  - https://mirrors.zju.edu.cn/anaconda/pkgs/msys2' \
        'custom_channels:' \
        '  conda-forge: https://mirrors.zju.edu.cn/anaconda/cloud' \
        '  msys2: https://mirrors.zju.edu.cn/anaconda/cloud' \
        '  bioconda: https://mirrors.zju.edu.cn/anaconda/cloud' \
        '  menpo: https://mirrors.zju.edu.cn/anaconda/cloud' \
        '  pytorch: https://mirrors.zju.edu.cn/anaconda/cloud' \
        '  pytorch-lts: https://mirrors.zju.edu.cn/anaconda/cloud' \
        '  simpleitk: https://mirrors.zju.edu.cn/anaconda/cloud' \
        '  nvidia: https://mirrors.zju.edu.cn/anaconda-r' \
        > /opt/conda/.condarc \
    && conda init bash \
    && conda clean -a -y

RUN printf '%s\n' \
        'if [ -f "$HOME/.bashrc" ]; then' \
        '    source "$HOME/.bashrc"' \
        'fi' \
        > /etc/skel/.bash_profile \
    && printf '%s\n' \
        '' \
        '# Initialize Conda' \
        'source /opt/conda/etc/profile.d/conda.sh' \
        >> /etc/skel/.bashrc

# Build the Agent from the local source without carrying that source into the
# final image.
FROM runtime-base AS agent-builder

COPY agent/ /tmp/computedock-agent/
RUN /usr/bin/python3 -m venv /opt/computedock-agent/venv \
    && /opt/computedock-agent/venv/bin/pip install \
        --no-cache-dir \
        --constraint /tmp/computedock-agent/constraints.txt \
        /tmp/computedock-agent

FROM runtime-base

# Run the Agent as a dedicated unprivileged system user.
RUN { getent group video >/dev/null || groupadd --system video; } \
    && useradd \
        --system \
        --user-group \
        --create-home \
        --home-dir /var/lib/computedock-agent \
        --shell /usr/sbin/nologin \
        computedock-agent \
    && usermod -a -G video computedock-agent \
    && install -d \
        -o computedock-agent \
        -g computedock-agent \
        -m 0750 \
        /run/computedock-agent \
        /var/lib/computedock-agent

COPY --from=agent-builder /opt/computedock-agent/venv /opt/computedock-agent/venv
COPY supervisord.conf /etc/supervisor/supervisord.conf
COPY run_agent_service.sh healthcheck.sh /usr/local/bin/
RUN chown -R root:root /opt/computedock-agent \
    && install \
        -o computedock-agent \
        -g computedock-agent \
        -m 0640 \
        /dev/null \
        /opt/computedock-agent/test-samples.jsonl \
    && chmod 0444 /etc/supervisor/supervisord.conf \
    && chmod 0555 \
        /usr/local/bin/run_agent_service.sh \
        /usr/local/bin/healthcheck.sh

COPY init_container.sh /usr/local/bin/init_container.sh
RUN chmod 0555 /usr/local/bin/init_container.sh

STOPSIGNAL SIGTERM
HEALTHCHECK \
    --interval=5s \
    --timeout=3s \
    --start-period=15s \
    --retries=1 \
    CMD ["/usr/local/bin/healthcheck.sh"]

ENTRYPOINT ["/usr/local/bin/init_container.sh"]
