// # ---------------------------------------------------------------------------
// # Copy to `.env` and fill in. `.env` is gitignored and NEVER committed.
// # Every value here maps 1:1 to a field on app/core/config.py::Settings.
// # ---------------------------------------------------------------------------

// # --- Application ---
// APP_NAME="School Management System"
// ENVIRONMENT=local                     # local | test | staging | production
// DEBUG=true
// LOG_LEVEL=INFO
// LOG_JSON=false                        # false = pretty console logs, true = JSON for log aggregators

// # --- API ---
// API_V1_PREFIX=/api/v1
// CORS_ORIGINS=["http://localhost:3000"]   # Next.js dev server

// # --- Security ---
// # Generate with: python -c "import secrets; print(secrets.token_urlsafe(64))"
// SECRET_KEY=local-dev-only-not-a-real-secret-abcdefghijklmnop
// JWT_ALGORITHM=HS256
// ACCESS_TOKEN_EXPIRE_MINUTES=30
// REFRESH_TOKEN_EXPIRE_DAYS=7

// # --- Database ---
// # Leave DB_ENABLED=false until the PostgreSQL integration phase.
// # The app boots and serves /health without a database when this is false.
// DB_ENABLED=true
// POSTGRES_HOST=localhost
// POSTGRES_PORT=5432
// POSTGRES_USER=sms_app
// POSTGRES_PASSWORD=sms_app_password
// POSTGRES_DB=school_manage_db
// DB_ECHO=false                         # true logs every SQL statement (dev only)
// DB_POOL_SIZE=10
// DB_MAX_OVERFLOW=5

// # Alembic connects as the schema owner. Required: scripts/init-db.sql revokes
// # CREATE on public from sms_app, so migrations cannot run as the app role.
// MIGRATION_USER=postgres
// MIGRATION_PASSWORD=postgres

// # --- Email / OTP ---
// EMAIL_BACKEND=smtp
// SMTP_HOST=smtp.gmail.com
// SMTP_PORT=587
// SMTP_START_TLS=true
// SMTP_USE_TLS=false
// SMTP_USER=sajidhgn1@gmail.com
// # ==> PASTE YOUR **NEW** APP PASSWORD HERE AFTER REVOKING THE OLD ONE <==
// # The password shared in chat (aezrs...) must be revoked at
// # https://myaccount.google.com/apppasswords -- treat it as compromised.
// SMTP_PASSWORD=aezrsihhulyytajr
// SMTP_TIMEOUT_SECONDS=15
// EMAIL_FROM_ADDRESS=sajidhgn1@gmail.com
// EMAIL_FROM_NAME=School Manage
// FRONTEND_URL=http://localhost:3000
// EMAIL_LOGO_URL=

// SUPERADMIN_EMAIL=vulcantech709@gmail.com
// SUPERADMIN_PASSWORD=3648Cultas@

// BOOKS_SCAN_PROVIDER=kie
// BOOKS_SCAN_MODEL=gpt-6-luna