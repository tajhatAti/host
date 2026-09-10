# ============================================================
# Code Execution Runner — Dockerfile (standalone service #2, optional)
# ------------------------------------------------------------
# This is kept around for future horizontal scaling. The default deployment
# uses the single-service root Dockerfile where everything runs in-process.
# Same design: runs as ROOT because free-tier containers block sudo/setuid.
# ============================================================

FROM python:3.11-slim-bookworm
ENV DEBIAN_FRONTEND=noninteractive

# System + language runtimes + Termux CLI tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ openjdk-17-jdk-headless ruby php-cli perl lua5.4 \
    sqlite3 curl ca-certificates git \
    bash-completion nano vim-tiny less file procps psmisc lsof net-tools iproute2 \
    dnsutils iputils-ping wget unzip zip tar xz-utils jq htop tmux screen \
    build-essential pkg-config openssh-client \
    && rm -rf /var/lib/apt/lists/*

# ------------------------------------------------------------
# CURATED MEDIA / FILE TOOLING  (see SYSTEM_TOOLS.md)
# Must stay in lockstep with the root Dockerfile: a job that works in the
# single-service deployment has to work identically here, or the two-service
# layout silently becomes a different platform.
# ------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg imagemagick \
    && rm -rf /var/lib/apt/lists/*

# Node 20
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Go
RUN curl -fsSL https://go.dev/dl/go1.22.0.linux-amd64.tar.gz \
    | tar -C /usr/local -xz
ENV PATH="/usr/local/go/bin:${PATH}"

# Rust
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal --default-toolchain stable
ENV PATH="/root/.cargo/bin:${PATH}"

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /app/data/jobs /app/data/homes && chmod -R 777 /app/data
COPY runner_bashrc  /root/.bashrc
COPY runner_profile /root/.profile
RUN apt-get update && rm -rf /var/lib/apt/lists/partial/* || true

ENV HOME=/root
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000"]
