FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /srv

COPY requirements.txt requirements-dev.txt ./
RUN pip install --no-cache-dir -r requirements-dev.txt

COPY app ./app
COPY tests ./tests
COPY pytest.ini ./

# Usuário sem privilégios (segurança)
RUN useradd --create-home appuser && chown -R appuser /srv
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.api:app_factory", "--factory", "--host", "0.0.0.0", "--port", "8000"]
