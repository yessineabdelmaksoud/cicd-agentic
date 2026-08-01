FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Dépendances minimales de Zephyr
RUN apt-get update && apt-get install -y --no-install-recommends \
    git cmake ninja-build gperf \
    ccache dfu-util device-tree-compiler wget curl \
    python3-dev python3-pip python3-setuptools python3-tk python3-wheel \
    xz-utils file make gcc gcc-multilib g++-multilib \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Installer west (l'outil de build Zephyr)
RUN pip3 install --no-cache-dir west

# Installer le toolchain cross-compile ARM minimal
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc-arm-none-eabi libnewlib-arm-none-eabi \
    && rm -rf /var/lib/apt/lists/*

# Installer le client MinIO mc (téléchargé au build — jamais committé en binaire)
RUN curl -fsSL https://dl.min.io/client/mc/release/linux-amd64/mc -o /usr/local/bin/mc \
    && chmod +x /usr/local/bin/mc

# Créer un utilisateur non-root
RUN useradd -m -s /bin/bash builder
USER builder
WORKDIR /home/builder
