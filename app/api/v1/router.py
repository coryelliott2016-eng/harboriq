from fastapi import APIRouter

from app.api.v1.routes import (
    auth,
    billing,
    customers,
    dispatch,
    geocode_admin,
    health,
    inventory,
    invoices,
    jobs,
    messages,
    portal,
    public,
    reports,
    sms_webhooks,
    stripe_webhooks,
    users,
    vessels,
)

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(health.router, tags=["health"])
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(customers.router)
api_router.include_router(vessels.router)
api_router.include_router(jobs.router)
api_router.include_router(dispatch.router)
api_router.include_router(inventory.router, tags=["inventory"])
api_router.include_router(invoices.router)
api_router.include_router(billing.router)
api_router.include_router(reports.router)
api_router.include_router(public.router, tags=["public"])
api_router.include_router(portal.router)
api_router.include_router(messages.router)
api_router.include_router(stripe_webhooks.router, tags=["webhooks"])
api_router.include_router(sms_webhooks.router, tags=["webhooks"])
api_router.include_router(geocode_admin.router)
