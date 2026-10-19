# backend-django 开发镜像（生产部署走 systemd 裸机，见 spec §九）
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

WORKDIR /app

COPY pyproject.toml ./
RUN pip install --no-cache-dir \
    "django>=5.0,<6.0" "django-ninja>=1.3" "pyjwt>=2.8" "casbin>=1.36" \
    "redis>=5.0" "psycopg[binary]>=3.1" "bcrypt>=4.0" "pyyaml>=6.0" gunicorn \
    "openpyxl>=3.1" "fastapi>=0.110" "uvicorn>=0.27"

COPY . .

EXPOSE 8787

# 启动：migrate（schema 唯一真源）→ 幂等播种 → gunicorn
CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py seed_demo && gunicorn config.wsgi:application -b 0.0.0.0:8787 -w 4 --timeout 60"]
