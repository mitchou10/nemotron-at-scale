"""Routes package."""
from app.api.routes.health import router as health_router
from app.api.routes.users import router as users_router

__all__ = ["health_router", "users_router"]
