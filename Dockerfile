# Uma única imagem Python para todos os serviços (simulador, treino, inferência, painel).
# O docker-compose escolhe o comando de cada um.
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/
