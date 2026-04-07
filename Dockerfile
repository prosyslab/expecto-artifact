FROM ubuntu:22.04

ARG USERNAME=user
ARG USER_UID=1000
ARG USER_GID=1000

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=America/Los_Angeles
ENV JAVA_HOME=/usr/lib/jvm/java-11-openjdk-amd64
ENV WORKSPACE_DIR=/workspace

# Install shared system dependencies used across the workspace.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    ca-certificates \
    cpanminus \
    git \
    gnupg \
    make \
    openjdk-11-jdk \
    perl \
    software-properties-common \
    subversion \
    sudo \
    tmux \
    unzip \
    wget \
    z3 \
    openssh-client \
    zsh \
    tmux \
    vim \
    wget \
    htop \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime \
    && echo $TZ > /etc/timezone \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install Python 3.12 and make it the default Python interpreter.
RUN add-apt-repository ppa:deadsnakes/ppa \
    && apt-get update \
    && apt-get install -y --no-install-recommends \
    python3.12 \
    python3.12-venv \
    python3.12-dev \
    && curl -sS https://bootstrap.pypa.io/get-pip.py | python3.12 \
    && ln -sf /usr/bin/python3.12 /usr/local/bin/python3 \
    && ln -sf /usr/bin/python3.12 /usr/local/bin/python \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Install merged Python dependencies for the project environment.
COPY requirements.txt /tmp/requirements.txt

RUN python3.12 -m pip install --no-cache-dir --upgrade pip setuptools wheel \
    && python3.12 -m pip install --no-cache-dir -r /tmp/requirements.txt

# Setup defects4j
WORKDIR /opt
RUN git clone https://github.com/rjust/defects4j.git defects4j \
    && cd /opt/defects4j \
    && cpanm --installdeps . \
    && ./init.sh

ENV PATH="/defects4j/framework/bin:${PATH}"

# Setup latex
RUN apt-get update && apt-get install -y texlive-latex-extra texlive-fonts-recommended dvipng cm-super

# Set python3 alias to python3.12.
RUN ln -sf /usr/bin/python3.12 /usr/local/bin/python3
RUN ln -sf /usr/bin/python3.12 /usr/local/bin/python

RUN if ! getent group "${USER_GID}" >/dev/null; then \
    groupadd --gid "${USER_GID}" "${USERNAME}"; \
    fi && \
    useradd --uid "${USER_UID}" --gid "${USER_GID}" --create-home --home-dir "/home/${USERNAME}" "${USERNAME}" && \
    usermod -aG sudo "${USERNAME}" && \
    echo "${USERNAME} ALL=(ALL) NOPASSWD:ALL" >> /etc/sudoers

ENV PATH="/opt/defects4j/framework/bin:/home/user/.local/bin:${PATH}"

RUN sudo chown -R user:user /opt/defects4j

# Set up zsh and oh-my-zsh
USER ${USERNAME}
RUN sudo chsh -s /bin/zsh ${USERNAME}
RUN sh -c "$(curl -fsSL https://raw.githubusercontent.com/ohmyzsh/ohmyzsh/master/tools/install.sh)"

# Activate UTF-8 encoding
ENV LC_ALL=C.UTF-8
ENV LANG=C.UTF-8

# Timezone
ENV TZ=America/Los_Angeles

WORKDIR /workspace

# Clone the artifact repository at the end so dependency layers stay cacheable.
RUN git clone https://github.com/prosyslab/expecto-artifact.git /workspace/expecto-artifact

WORKDIR /workspace/expecto-artifact
