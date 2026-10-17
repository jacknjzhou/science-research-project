"""基础配置：环境变量对齐 Go 版 ARK_* 命名。"""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent

SECRET_KEY = os.environ.get("ARK_JWT_SECRET", "dev-secret-change-me-please-use-32-bytes-min!")
DEBUG = False
ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "apps.sysadmin",
    "apps.notify",
    "core",
    "apps.p",
    "apps.project",
    "apps.funding",
    "apps.output",
    "apps.expertreview",
    "apps.activity",
    "apps.archive",
    "apps.performance",
    "apps.dataops",
]

MIDDLEWARE = [
    "django.middleware.common.CommonMiddleware",
    "core.trace.TraceIDMiddleware",
    "core.idempotency.IdempotencyMiddleware",
]

ROOT_URLCONF = "config.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {"context_processors": []},
    },
]

WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

# —— 数据库：DSN 对齐 ARK_DATABASE_URL；测试用 sqlite ——
def _database_from_env() -> dict:
    """解析 postgres://user:pass@host:port/db DSN（不引第三方依赖）。"""
    from urllib.parse import urlparse

    dsn = os.environ.get("ARK_DATABASE_URL", "")
    if not dsn:
        return {}
    u = urlparse(dsn)
    return {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": u.path.lstrip("/"),
        "USER": u.username or "",
        "PASSWORD": u.password or "",
        "HOST": u.hostname or "127.0.0.1",
        "PORT": u.port or 5432,
    }


DATABASES = (
    {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": os.environ.get("ARK_DB_NAME", ":memory:"),
        }
    }
    if os.environ.get("ARK_DB_ENGINE", "") == "sqlite"
    else {
        "default": _database_from_env()
        or {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("PGDATABASE", "ark"),
            "USER": os.environ.get("PGUSER", "ark"),
            "PASSWORD": os.environ.get("PGPASSWORD", "ark"),
            "HOST": os.environ.get("PGHOST", "127.0.0.1"),
            "PORT": os.environ.get("PGPORT", "5432"),
            "OPTIONS": {"connect_timeout": 3},
        }
    }
)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

# —— 时区（PRD 2.2：Asia/Shanghai）——
TIME_ZONE = "Asia/Shanghai"
USE_TZ = True

STATIC_URL = "static/"

# —— Redis（幂等/缓存）——
REDIS_ADDR = os.environ.get("ARK_REDIS_ADDR", "127.0.0.1:6379")

# —— JWT（对齐 Go 版：HS256，claims 含 uid/tenant_id/legal_entity_id/security_level/roles）——
JWT_SECRET = os.environ.get("ARK_JWT_SECRET", "dev-secret-change-me-please-use-32-bytes-min!")
JWT_TTL_SEC = int(os.environ.get("ARK_JWT_TTL_SEC", "7200"))

# —— 两级审核开关（对齐 ARK_APPROVAL_TWOSTEP）——
APPROVAL_TWOSTEP = os.environ.get("ARK_APPROVAL_TWOSTEP", "off") == "on"

# —— casbin：model/policy 从 Go 版零修改复制 ——
CASBIN_MODEL_PATH = str(BASE_DIR / "config" / "casbin" / "model.conf")
CASBIN_POLICY_PATH = str(BASE_DIR / "config" / "casbin" / "policy.csv")

# —— 幂等键 TTL ——
IDEMPOTENCY_TTL_SEC = 24 * 3600

# —— LLM（NewAPI OpenAI 兼容；未配置时 AI 端点自动降级 REVIEW）——
LLM_BASE_URL = os.environ.get("ARK_LLM_BASE_URL", "")
LLM_API_KEY = os.environ.get("ARK_LLM_API_KEY", "")
LLM_MODEL = os.environ.get("ARK_LLM_MODEL", "gpt-4o-mini")
LLM_TIMEOUT_SEC = int(os.environ.get("ARK_LLM_TIMEOUT_SEC", "30"))
