"""
Django settings for manpower_forecasting.
Environment variables override development defaults for production.
"""
import os
from pathlib import Path

from django.contrib.messages import constants as message_constants

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-insecure-key-change-in-production-9f3k2l1m0n")
DEBUG = os.environ.get("DJANGO_DEBUG", "True").lower() in ("1", "true", "yes")
ALLOWED_HOSTS = [h.strip() for h in os.environ.get("DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost").split(",") if h.strip()]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.humanize",
    "forecasting.apps.ForecastingConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "manpower_forecasting.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "forecasting.context_processors.user_roles",
            ],
        },
    },
]

WSGI_APPLICATION = "manpower_forecasting.wsgi.application"

# SQLite for development; set DB_ENGINE=postgresql (and DB_* variables) for PostgreSQL.
if os.environ.get("DB_ENGINE", "sqlite") == "postgresql":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.environ.get("DB_NAME", "manpower_forecasting"),
            "USER": os.environ.get("DB_USER", "postgres"),
            "PASSWORD": os.environ.get("DB_PASSWORD", ""),
            "HOST": os.environ.get("DB_HOST", "localhost"),
            "PORT": os.environ.get("DB_PORT", "5432"),
        }
    }
else:
    DATABASES = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": BASE_DIR / "db.sqlite3"}}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Kolkata"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "forecasting:dashboard"
LOGOUT_REDIRECT_URL = "login"

MESSAGE_TAGS = {message_constants.ERROR: "danger"}

FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

# Business thresholds - configurable, never hard-coded in services
FORECASTING = {
    "SUFFICIENCY_THRESHOLD": 80,   # minimum Monte Carlo sufficiency probability (%)
    "UTILIZATION_LOWER": 70,       # below this => Higher Manpower
    "UTILIZATION_UPPER": 90,       # above this => High Utilization Risk
    "SIMULATION_MIN": 1000,
    "SIMULATION_MAX": 100000,
    "SCENARIO_MAX": 4,
    "MONTE_CARLO_DEFAULT": True,   # default state of the "Run Monte Carlo" switch
    "HORIZON_DEFAULT": 12,         # default growth projection horizon (months)
    "HORIZON_MAX": 60,             # maximum growth projection horizon (months)
    "GROWTH_MAX_FACTOR": 1000,     # max volume multiplier allowed at the end of the horizon
    # ---- Executive dashboard ----
    "EXEC_COST_PER_FTE": 600000,   # default fully loaded annual cost per FTE (editable on the page)
    "EXEC_CURRENCY": "₹",          # currency symbol shown on the executive dashboard
    "EXEC_HORIZON_MONTHS": 12,     # outlook window for the executive headcount trajectory
    "EXEC_TARGET_UTILIZATION": 80, # organisation-level target utilization (%)
}

if not DEBUG:
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    X_FRAME_OPTIONS = "DENY"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"console": {"class": "logging.StreamHandler"}},
    "loggers": {"forecasting": {"handlers": ["console"], "level": "INFO"}},
}
