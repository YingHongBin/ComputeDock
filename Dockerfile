FROM nvidia/cuda:12.8.1-cudnn-devel-ubuntu24.04

# Ubuntu 24.04
RUN sed -i s@/archive.ubuntu.com/@/mirrors.zju.edu.cn/@g /etc/apt/sources.list.d/ubuntu.sources
# Ubuntu 20.04
RUN echo "deb https://mirrors.zju.edu.cn/ubuntu/ focal main restricted universe multiverse" > /etc/apt/sources.list && \
    echo "deb https://mirrors.zju.edu.cn/ubuntu/ focal-updates main restricted universe multiverse" >> /etc/apt/sources.list && \
    echo "deb https://mirrors.zju.edu.cn/ubuntu/ focal-backports main restricted universe multiverse" >> /etc/apt/sources.list && \
    echo "deb https://mirrors.zju.edu.cn/ubuntu/ focal-security main restricted universe multiverse" >> /etc/apt/sources.list

RUN apt-get clean

ENV DEBIAN_FRONTEND=noninteractive

# Install some essential tools
RUN apt update && apt install -y \
    tzdata \
    sudo \
    wget \
    curl \
    vim \
    git \  
    openssh-server \
    openssh-client \
    tmux

# SSH settings
RUN mkdir /var/run/sshd
# Replace the "session required pam_loginuid.so" in /etc/pam.d/sshd with "session optional pam_loginuid.so"
# But it seems that this is not needed in the new versions of docker. See https://gitlab.com/gitlab-org/gitlab-foss/-/issues/3027
# SSH login fix. Otherwise user is kicked off after login
RUN sed 's@session\s*required\s*pam_loginuid.so@session optional pam_loginuid.so@g' -i /etc/pam.d/sshd
ENV NOTVISIBLE="in users profile"
RUN echo "export VISIBLE=now" >> /etc/profile
EXPOSE 22

# Install Miniconda
RUN wget https://repo.continuum.io/miniconda/Miniconda3-latest-Linux-x86_64.sh -O Miniconda.sh && \
    /bin/bash Miniconda.sh -b -p /opt/conda && \
    rm Miniconda.sh

# Add cuda and conda paths
RUN echo "export PATH=/usr/local/cuda/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin:/opt/conda/bin" >> /etc/profile
RUN echo "export LD_LIBRARY_PATH=/usr/local/cuda/lib64:/usr/lib64:/usr/local/lib:/usr/lib:/usr/lib/x86_64-linux-gnu" >> /etc/profile

# initial conda
ENV PATH=/opt/conda/bin:$PATH
RUN echo -e "channels:\n  - defaults\nshow_channel_urls: true\ndefault_channels:\n  - https://mirrors.zju.edu.cn/anaconda/pkgs/main\n  - https://mirrors.zju.edu.cn/anaconda/pkgs/r\n  - https://mirrors.zju.edu.cn/anaconda/pkgs/msys2\ncustom_channels:\n  conda-forge: https://mirrors.zju.edu.cn/anaconda/cloud\n  msys2: https://mirrors.zju.edu.cn/anaconda/cloud\n  bioconda: https://mirrors.zju.edu.cn/anaconda/cloud\n  menpo: https://mirrors.zju.edu.cn/anaconda/cloud\n  pytorch: https://mirrors.zju.edu.cn/anaconda/cloud\n  pytorch-lts: https://mirrors.zju.edu.cn/anaconda/cloud\n  simpleitk: https://mirrors.zju.edu.cn/anaconda/cloud\n  nvidia: https://mirrors.zju.edu.cn/anaconda-r" > /opt/conda/.condarc

RUN conda init bash

# Clean up all temp files
RUN apt clean && rm -rf /tmp/* /var/tmp/* /var/lib/apt/lists/* /var/cache/apt/*
RUN conda clean -a -y

RUN printf '%s\n' \
    'if [ -f "$HOME/.bashrc" ]; then' \
    '    source "$HOME/.bashrc"' \
    'fi' \
    > /etc/skel/.bash_profile
RUN echo '' >> /etc/skel/.bashrc && \
    echo '# Initialize Conda' >> /etc/skel/.bashrc && \
    echo 'source /opt/conda/etc/profile.d/conda.sh' >> /etc/skel/.bashrc

# Set the entrypoint
COPY ./init_container.sh /usr/local/bin/init_container.sh
RUN chmod +x /usr/local/bin/init_container.sh
ENTRYPOINT ["/usr/local/bin/init_container.sh"]
