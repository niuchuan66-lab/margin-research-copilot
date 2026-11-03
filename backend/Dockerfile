FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System packages kept minimal; OCR/parsing extras can be added with
# `docker build --build-arg EXTRAS=".[parsing,rag,agent]"`.
COPY pyproject.toml ./
COPY app ./app
RUN pip install --upgrade pip && pip install -e .

ARG EXTRAS=""
RUN if [ -n "$EXTRAS" ]; then pip install -e "$EXTRAS"; fi

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
