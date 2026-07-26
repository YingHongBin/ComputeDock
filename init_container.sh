#!/bin/bash

# Fail if NEW_USER or NEW_PWD is not given
if [ -z "$NEW_USER" ]; then
    echo 'ERROR: Missing -e NEW_USER="username" in docker run command.'
    exit 1
fi
if [ -z "$NEW_PWD" ]; then
    echo 'ERROR: Missing -e NEW_PWD="password" in docker run command.'
    exit 1
fi

# Create a sudo user account with a password and a /bin/bash shell
useradd -m -G sudo -s /bin/bash $NEW_USER &>/dev/null
echo "$NEW_USER:$NEW_PWD" | chpasswd

# 复制 /etc/skel 中缺失的初始化文件
if [[ ! -f "/home/${NEW_USER}/.bashrc" ]]; then
    cp /etc/skel/.bashrc "/home/${NEW_USER}/.bashrc"
fi

if [[ ! -f "/home/${NEW_USER}/.bash_profile" ]]; then
    cp /etc/skel/.bash_profile "/home/${NEW_USER}/.bash_profile"
fi

mkdir -p /run/sshd
exec /usr/sbin/sshd -D -e
