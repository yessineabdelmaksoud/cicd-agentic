FROM ubuntu:22.04

# Éviter les invites interactives pendant l'installation
ENV DEBIAN_FRONTEND=noninteractive

# Installer les dépendances recommandées de Yocto Poky
RUN apt-get update && apt-get install -y --no-install-recommends \
    gawk wget git diffstat unzip texinfo gcc build-essential \
    chrpath socat cpio python3 python3-pip xz-utils debianutils \
    python3-git python3-jinja2 zstd liblz4-tool file locales iproute2 \
    curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Configurer les locales requises par bitbake
RUN locale-gen en_US.UTF-8
ENV LANG=en_US.UTF-8
ENV LANGUAGE=en_US:en
ENV LC_ALL=en_US.UTF-8

# Client MinIO mc — needed by pipelines/templates/notify.yml's after_script
# to upload build.log on failure. Downloaded at build time, never committed
# as a binary.
RUN curl -fsSL https://dl.min.io/client/mc/release/linux-amd64/mc -o /usr/local/bin/mc \
    && chmod +x /usr/local/bin/mc

# Créer un utilisateur builder non-root (obligatoire pour bitbake)
RUN useradd -m -s /bin/bash builder

USER builder
WORKDIR /home/builder
