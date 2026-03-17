FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bridge.py import_history.py ./

CMD ["python", "-u", "bridge.py"]

LABEL org.opencontainers.image.title="TeslaMate to Traccar Bridge"
LABEL org.opencontainers.image.description="Forwards TeslaMate GPS/telemetry data to Traccar via OsmAnd protocol"
LABEL org.opencontainers.image.authors="Jason Waters"
LABEL org.opencontainers.image.source="https://github.com/jasonwaters/teslamate-to-traccar-bridge"
