FROM python:3.12.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY telemetry/ telemetry/
COPY sops/ sops/
COPY static/ static/
USER 10001:10001
CMD ["python", "-m", "telemetry.simulator"]
