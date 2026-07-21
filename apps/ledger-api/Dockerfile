# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm@sha256:d50fb7611f86d04a3b0471b46d7557818d88983fc3136726336b2a4c657aa30b AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

FROM python:3.12-slim-bookworm@sha256:d50fb7611f86d04a3b0471b46d7557818d88983fc3136726336b2a4c657aa30b
RUN groupadd -g 10001 appgroup && useradd -u 10001 -g appgroup -M -s /usr/sbin/nologin appuser
WORKDIR /app
COPY --from=builder /root/.local /home/appuser/.local
COPY app.py .
RUN chown -R appuser:appgroup /app
ENV PATH=/home/appuser/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
USER 10001
EXPOSE 8080
ENTRYPOINT ["python", "app.py"]
