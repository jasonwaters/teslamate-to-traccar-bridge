FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY bridge.py import_history.py ./

CMD ["python", "-u", "bridge.py"]
