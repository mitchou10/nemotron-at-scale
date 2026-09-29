# Nemotron Backend

API FastAPI asynchrone pour le projet **nemotron-at-scale**.

## Stack

- **Python 3.12** + **FastAPI** (async natif)
- **SQLAlchemy 2.0** async avec **asyncpg**
- **Alembic** pour les migrations
- **PostgreSQL 16**
- **uv** comme gestionnaire de paquets
- **Docker** / **Docker Compose**

## Structure

```
backend/
├── app/
│   ├── __init__.py
│   ├── main.py            # Factory FastAPI + lifespan async
│   ├── config.py          # Settings (pydantic-settings)
│   ├── db.py              # Engine + session async
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes/
│   │       ├── __init__.py
│   │       ├── health.py  # /health, /health/ready
│   │       └── users.py   # CRUD users
│   ├── core/
│   │   ├── __init__.py
│   │   └── security.py     # Hash/verify password (PBKDF2)
│   ├── crud/
│   │   ├── __init__.py
│   │   └── user.py         # Opérations DB async
│   ├── models/
│   │   ├── __init__.py
│   │   └── user.py         # ORM User (AsyncAttrs)
│   └── schemas/
│       ├── __init__.py
│       └── user.py         # Pydantic schemas
├── alembic/
│   ├── env.py             # Config async
│   ├── script.py.mako
│   └── versions/
│       └── 0001_create_users.py
├── tests/
│   ├── conftest.py        # Fixtures async (DB, client)
│   ├── test_health.py
│   └── test_users.py
├── .env.example
├── .gitignore
├── alembic.ini
├── docker-compose.yml
├── Dockerfile             # Production (multi-stage)
├── Dockerfile.dev         # Dev avec reload
├── pyproject.toml
└── README.md
```

## Démarrage

### Avec Docker (recommandé)

```bash
# Copier la config
cp .env.example .env

# Mode dev (avec hot-reload)
docker compose --profile dev up --build

# Mode production
docker compose up --build
```

L'API est disponible sur http://localhost:8000

- Docs Swagger : http://localhost:8000/api/v1/docs
- ReDoc : http://localhost:8000/api/v1/redoc

### Avec uv (local)

```bash
# Installer uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Sync les dépendances
uv sync

# Lancer les migrations (nécessite PostgreSQL)
alembic upgrade head

# Démarrer le serveur
uv run uvicorn app.main:app --reload
```

## Tests

```bash
uv sync --extra dev
uv run pytest
```

## Migrations Alembic

```bash
# Générer une migration
alembic revision --autogenerate -m "description"

# Appliquer
alembic upgrade head

# Rollback
alembic downgrade -1
```

## Endpoints

| Méthode | Route                    | Description          |
|---------|--------------------------|----------------------|
| GET     | `/api/v1/health`         | Liveness probe       |
| GET     | `/api/v1/health/ready`   | Readiness probe      |
| GET     | `/api/v1/users/`         | Liste des users     |
| POST    | `/api/v1/users/`         | Créer un user        |
| GET     | `/api/v1/users/{id}`     | Détail d'un user     |
| PATCH   | `/api/v1/users/{id}`     | Modifier un user    |
| DELETE  | `/api/v1/users/{id}`     | Supprimer un user    |
