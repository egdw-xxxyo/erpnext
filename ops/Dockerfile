# Deliberately minimal: no ssh client, no docker client. Everything the
# dashboard does on the host goes through paramiko as the logged-in operator.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY templates ./templates
COPY static ./static

RUN useradd -u 10001 -m ops && mkdir -p /data && chown ops:ops /data
USER ops

EXPOSE 8081

# --workers 1 is NOT a tuning choice: SSH connections and sessions are
# in-process state, so a second worker would randomly invalidate sessions.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8081", "--workers", "1", "--proxy-headers"]
