# syntax=docker/dockerfile:1
ARG BASE_IMAGE=node:22-bookworm-slim
FROM ${BASE_IMAGE}

ARG GH_VERSION=2.101.0
ARG BRIDGE_REPO=https://github.com/inkbox-ai/claude-code-plugin
ARG BRIDGE_REF=a02722d42bbdc40e8a6944fccf4118c594dd5661
ARG TARGETARCH

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates curl git openssh-client python3 python3-venv \
    && rm -rf /var/lib/apt/lists/*

RUN arch="${TARGETARCH:-$(dpkg --print-architecture)}" \
    && cd /tmp \
    && curl -fsSLO "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_linux_${arch}.tar.gz" \
    && curl -fsSLO "https://github.com/cli/cli/releases/download/v${GH_VERSION}/gh_${GH_VERSION}_checksums.txt" \
    && grep " gh_${GH_VERSION}_linux_${arch}.tar.gz\$" "gh_${GH_VERSION}_checksums.txt" | sha256sum -c - \
    && tar -xzf "gh_${GH_VERSION}_linux_${arch}.tar.gz" \
    && install -m 0755 "gh_${GH_VERSION}_linux_${arch}/bin/gh" /usr/local/bin/gh \
    && rm -rf /tmp/gh_*

COPY docker/constraints.txt /opt/iclaude/constraints.txt
RUN python3 -m venv /opt/inkbox-claude \
    && /opt/inkbox-claude/bin/pip install --upgrade pip \
    && /opt/inkbox-claude/bin/pip install \
        --constraint /opt/iclaude/constraints.txt \
        "claude-code-plugin @ git+${BRIDGE_REPO}@${BRIDGE_REF}" \
    && ln -s "$(/opt/inkbox-claude/bin/python -c 'import claude_agent_sdk, pathlib; print(pathlib.Path(claude_agent_sdk.__file__).parent / "_bundled" / "claude")')" /usr/local/bin/claude \
    && claude --version \
    && /opt/inkbox-claude/bin/inkbox-claude --help > /dev/null

COPY runtime/iclaude_runtime /opt/iclaude/iclaude_runtime
COPY runtime/defaults /opt/iclaude/defaults
COPY runtime/bin/iclaude-container /usr/local/bin/iclaude-container

RUN groupmod --new-name iclaude node \
    && usermod --login iclaude --home /home/iclaude --move-home node \
    && mkdir -p /home/iclaude/.claude /home/iclaude/.inkbox-claude /workspace \
    && chown -R iclaude:iclaude /home/iclaude /workspace \
    && chmod 0700 /home/iclaude/.claude /home/iclaude/.inkbox-claude

ENV PATH="/opt/inkbox-claude/bin:${PATH}" \
    PYTHONPATH=/opt/iclaude \
    HOME=/home/iclaude \
    INKBOX_CLAUDE_HOME=/home/iclaude/.inkbox-claude \
    INKBOX_CLAUDE_ENV_FILE=/home/iclaude/.inkbox-claude/.env \
    CLAUDE_PROJECT_DIR=/workspace \
    DISABLE_AUTOUPDATER=1 \
    ICLAUDE_BRIDGE_REF=${BRIDGE_REF}

USER iclaude
WORKDIR /workspace

HEALTHCHECK --interval=30s --timeout=10s --start-period=90s --retries=3 \
    CMD ["iclaude-container", "healthcheck"]

ENTRYPOINT ["iclaude-container"]
CMD ["run"]
