from fastapi import APIRouter

from app.api.v1.routes import (
    auth,
    customers,
    health,
    inventory,
    jobs,
    public,
    stripe_webhooks,
    vessels,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router)
api_router.include_router(customers.router)
api_router.include_router(vessels.router)
api_router.include_router(jobs.router)
api_router.include_router(inventory.router, tags=["inventory"])
api_router.include_router(public.router, tags=["public"])
api_router.include_router(stripe_webhooks.router, tags=["webhooks"])
