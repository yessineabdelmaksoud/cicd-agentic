FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Outils de compilation standards pour la simulation QNX
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential cmake git file make curl \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Cross-toolchain for bare-metal ARM Cortex-M targets (the real
# QNX-substitute project: cpq/bare-metal-programming-guide, STM32F4,
# Makefile-driven — representative of QNX's failure shapes per the v5 plan).
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc-arm-none-eabi libnewlib-arm-none-eabi \
    && rm -rf /var/lib/apt/lists/*

# Client MinIO mc — needed by pipelines/templates/notify.yml's after_script
# to upload build.log on failure. Downloaded at build time, never committed
# as a binary.
RUN curl -fsSL https://dl.min.io/client/mc/release/linux-amd64/mc -o /usr/local/bin/mc \
    && chmod +x /usr/local/bin/mc

# Créer un utilisateur non-root
RUN useradd -m -s /bin/bash builder
USER builder
WORKDIR /home/builder
