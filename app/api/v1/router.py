from fastapi import APIRouter

from app.api.v1.routes import auth, health, inventory, public, stripe_webhooks

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router)
api_router.include_router(inventory.router, tags=["inventory"])
api_router.include_router(public.router, tags=["public"])
api_router.include_router(stripe_webhooks.router, tags=["webhooks"])
