# Deliberately minimal: no ssh client. Everything the dashboard does on a
# real host goes through paramiko as the logged-in operator.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# docker/docker-compose/git are dead weight unless OPS_LOCAL_MODE=1 also
# bind-mounts the host's docker socket + repo in (docker-compose.ops.local.yml)
# — harmless to have them present otherwise, since there's nothing to reach.
RUN apt-get update \
    && apt-get install -y --no-install-recommends docker-cli docker-compose git \
    && rm -rf /var/lib/apt/lists/* \
    # The bind-mounted repo is owned by the host user, not this container's
    # user, which git's dubious-ownership check refuses to touch by default.
    && git config --system --add safe.directory '*'

COPY app ./app
COPY templates ./templates
COPY static ./static

RUN useradd -u 10001 -m ops && mkdir -p /data && chown ops:ops /data
USER ops

EXPOSE 8081

# --workers 1 is NOT a tuning choice: SSH connections and sessions are
# in-process state, so a second worker would randomly invalidate sessions.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8081", "--workers", "1", "--proxy-headers"]
