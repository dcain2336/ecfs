FROM python:3.12-slim

WORKDIR /app
COPY . .

# Python already required packages are minimal – no extra deps
RUN python3 -m pip install -r requirements.txt || true

ENV PYTHONUNBUFFERED=1
ENV PORT=7700

CMD ["python", "-m", "ecfs.ecfs-lite"]
