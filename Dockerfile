# Starling node image — WP-03 Part 5. Makes CLAUDE.md rules 1/2 (one
# process, one replica, no shared filesystem) physical rather than
# conventional: each node runs in its own container, and deploy/
# docker-compose.yml is the thing responsible for making sure no
# container can mount another node's data directory.
FROM python:3.11-slim

# libgl1/libglib2.0-0: OpenCV runtime deps.
# iproute2/iptables: needed by Prompt 4's partition scripts (tc/netem,
# iptables DROP rules between container IPs) — installed now so the image
# doesn't need rebuilding when that lands.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        iproute2 \
        iptables \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml ./
COPY packages/ ./packages/
RUN pip install --no-cache-dir -e .

COPY apps/ ./apps/
COPY configs/ ./configs/

ENV STARLING_CONFIG=/app/configs/nodes/node-00.yaml

CMD ["sh", "-c", "python apps/node.py --config \"$STARLING_CONFIG\""]
