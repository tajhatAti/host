# ============================================================
# Ahad Co — RunSpace + Termux: SINGLE-SERVICE image (web + runner + terminal)
# ------------------------------------------------------------
# One Render web service runs everything as ROOT inside the container:
#   • the site (auth, dashboard, code studio)
#   • the job runner (spawn/auto-install/restart/log streaming) IN-PROCESS
#   • the public /live/{slug}/ gateway (HTTP + WebSocket)
#   • the interactive Termux-style PTY terminal (bash, persistent per-user home)
#
# We run as root because Render free-tier's seccomp/no-new-privileges flag
# blocks sudo/setuid from non-root users — there's no way to gain root from
# an unprivileged account on their free tier. The container is disposable
# (rebuilt from scratch on every deploy), per-user files live in isolated
# /app/data/homes/u<id>/ dirs, and the PTY children get hard RLIMITs
# (mem/CPU/fsize/nofile) + site-wide concurrent-session caps to keep abuse
# bounded.
# ============================================================

# Debian 12 (bookworm) — floating python:3.11-slim currently points at trixie
# which removed openjdk-17-jdk-headless and breaks the build.
FROM python:3.11-slim-bookworm

# Avoid apt interactive prompts during build
ENV DEBIAN_FRONTEND=noninteractive

# System packages + language runtimes + Termux-style CLI tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc g++ openjdk-17-jdk-headless ruby php-cli perl lua5.4 \
    sqlite3 curl ca-certificates git \
    bash-completion nano vim-tiny less file procps psmisc lsof net-tools iproute2 \
    dnsutils iputils-ping wget unzip zip tar xz-utils jq htop tmux screen \
    build-essential pkg-config openssh-client \
    && rm -rf /var/lib/apt/lists/*

# ------------------------------------------------------------
# CURATED MEDIA / FILE TOOLING  (see runner/SYSTEM_TOOLS.md)
#
# Installed at BUILD time, under platform control. Jobs may call these as
# ordinary subprocesses; they can never install system packages themselves.
# That is deliberate: RunSpace is a multi-tenant free platform, so letting
# anonymous user code run apt-get would let one user mutate the shared
# container for everyone.
#
# Kept in its own layer so adding a tool later does not rebuild the whole
# toolchain above it.
#   ffmpeg      audio/video transcoding + trimming; also provides ffprobe
#   imagemagick `convert` / `mogrify` / `identify`
# git, unzip, zip and tar are already installed in the layer above.
# ------------------------------------------------------------
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg imagemagick \
    && rm -rf /var/lib/apt/lists/*

# Node.js (LTS 20) via NodeSource
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && rm -rf /var/lib/apt/lists/*

# Go
RUN curl -fsSL https://go.dev/dl/go1.22.0.linux-amd64.tar.gz \
    | tar -C /usr/local -xz
ENV PATH="/usr/local/go/bin:${PATH}"

# Rust (rustc, minimal profile)
RUN curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y --profile minimal --default-toolchain stable
ENV PATH="/root/.cargo/bin:${PATH}"

WORKDIR /app

# Python deps
COPY requirements.txt /tmp/req-main.txt
COPY runner/requirements.txt /tmp/req-runner.txt
RUN pip install --no-cache-dir -r /tmp/req-main.txt -r /tmp/req-runner.txt

COPY . .

# Per-user terminal homes + job data dirs
RUN mkdir -p /app/data/jobs /app/data/homes && chmod -R 777 /app/data

# Seed skel bashrc/profile at /root (the server's own HOME; PTY children get
# a per-user chdir to /app/data/homes/u<id> which gets its own .bashrc copy)
COPY runner/runner_bashrc   /root/.bashrc
COPY runner/runner_profile  /root/.profile

# Populate apt package lists so `apt install` works out-of-the-box without
# forcing users to run `apt update` on a fresh deploy.
RUN apt-get update && rm -rf /var/lib/apt/lists/partial/* || true

# Run as root (see comment at top). HOME=/root is the default for root and
# keeps uvicorn/cargo/go happy; PTY children cd to their own HOME at spawn.
ENV HOME=/root

EXPOSE 8000

# Render injects $PORT.
CMD uvicorn app:app --app-dir /app --host 0.0.0.0 --port ${PORT:-8000}
