# Imagem única da plataforma (treino, inferência e painel); o docker-compose
# escolhe o comando de cada serviço. Build context = raiz do repositório,
# porque a plataforma precisa do contrato (contrato/*.schema.json).
FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY plataforma/requirements.txt plataforma/requirements.txt
RUN pip install --no-cache-dir -r plataforma/requirements.txt

COPY contrato/ contrato/
COPY plataforma/ plataforma/
