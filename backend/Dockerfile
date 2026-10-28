# syntax=docker/dockerfile:1
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# GeoDjango runtime libraries (GeoDjango/PostGIS support from Django 5).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgeos-c1v5 gdal-bin \
    && rm -rf /var/lib/apt/lists/*

ARG REQUIREMENTS_FILE=development.txt
COPY requirements/ requirements/
RUN pip install -r requirements/${REQUIREMENTS_FILE}

COPY . .
RUN chmod +x docker-entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["./docker-entrypoint.sh"]
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]
