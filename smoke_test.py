"""Manual smoke test exercising the exact API sequence the Phase 4 frontend
uses: signup -> customer -> vessel -> job -> line items -> status transition
-> invoice -> send -> public pay page.

Not part of the automated test suite -- a throwaway script to validate the
frontend's integration assumptions against the real running API before
declaring Phase 4 done. Safe to delete after review.
"""
import sys
import time
import httpx

BASE = "http://localhost:8000/api/v1"
c = httpx.Client(base_url=BASE, timeout=10)


def step(name):
    print(f"\n=== {name} ===")


def check(resp, expected=range(200, 300)):
    ok = resp.status_code in expected if not isinstance(expected, int) else resp.status_code == expected
    print(resp.status_code, resp.request.method, resp.request.url)
    if not ok:
        print("BODY:", resp.text[:2000])
        sys.exit(1)
    return resp


email = f"smoketest+{int(time.time())}@example.com"

step("CORS preflight (mirrors what the browser does before any real request)")
r = c.options(
    "/customers",
    headers={
        "Origin": "http://localhost:5173",
        "Access-Control-Request-Method": "GET",
    },
)
print(r.status_code, dict(r.headers))
assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"

step("Signup")
r = check(c.post("/auth/signup", json={
    "company_name": "Smoke Test Marine LLC",
    "email": email,
    "password": "correct-horse-battery-staple",
    "full_name": "Smoke Tester",
}))
body = r.json()
access = body["tokens"]["access_token"]
refresh = body["tokens"]["refresh_token"]
c.headers["Authorization"] = f"Bearer {access}"
print("user:", body["user"]["email"], body["user"]["role"])

step("GET /auth/me (hydration on load)")
check(c.get("/auth/me"))

step("Create customer")
r = check(c.post("/customers", json={
    "first_name": "Jane",
    "last_name": "Boater",
    "email": "jane@example.com",
    "phone": "941-555-0100",
}))
customer = r.json()
print("customer id:", customer["id"])

step("Create vessel")
r = check(c.post("/vessels", json={
    "customer_id": customer["id"],
    "name": "Reel Deal",
    "make": "Boston Whaler",
    "model": "Outrage 250",
    "year": 2019,
}))
vessel = r.json()
print("vessel id:", vessel["id"])

step("Get customer's vessels (nested list)")
r = check(c.get(f"/customers/{customer['id']}/vessels"))
print(len(r.json()), "vessel(s) found via nested list")

step("Create job")
r = check(c.post("/jobs", json={
    "customer_id": customer["id"],
    "vessel_id": vessel["id"],
    "title": "Engine won't start",
    "description": "No crank, no click.",
    "priority": "high",
}))
job = r.json()
print("job id:", job["id"], "status:", job["status"])

step("Add line items")
r = check(c.post(f"/jobs/{job['id']}/line-items", json={
    "kind": "labor",
    "description": "Diagnostics",
    "quantity": "1",
    "unit_price": "150.00",
}))
li1 = r.json()
r = check(c.post(f"/jobs/{job['id']}/line-items", json={
    "kind": "part",
    "description": "Starter motor",
    "quantity": "1",
    "unit_price": "320.00",
}))
li2 = r.json()
print("line items:", li1["id"], li2["id"])

step("Get job detail (line items + status)")
r = check(c.get(f"/jobs/{job['id']}"))
print(r.json()["status"], len(r.json()["line_items"]), "line items")

step("Status transition: scheduled -> in_progress")
r = check(c.post(f"/jobs/{job['id']}/status", json={"status": "in_progress"}))
print("new status:", r.json()["status"])

step("Status transition: in_progress -> completed")
r = c.post(f"/jobs/{job['id']}/status", json={"status": "completed"})
check(r)
print("new status:", r.json()["status"])

step("Illegal transition should be rejected: completed is terminal, cannot go back to scheduled")
r = c.post(f"/jobs/{job['id']}/status", json={"status": "scheduled"})
print("status code (expect 409):", r.status_code, r.text[:300])
assert r.status_code == 409, f"expected 409, got {r.status_code}: {r.text}"

step("Create invoice from job")
r = check(c.post("/invoices", json={"job_id": job["id"], "tax_rate": "0.07"}))
invoice = r.json()
print("invoice id:", invoice["id"], "status:", invoice["status"], "total:", invoice.get("total"))

step("Get invoice detail")
r = check(c.get(f"/invoices/{invoice['id']}"))
inv_detail = r.json()
print("subtotal:", inv_detail["subtotal"], "total:", inv_detail["total"], "balance_due:", inv_detail.get("balance_due"))

step("Send invoice")
r = check(c.post(f"/invoices/{invoice['id']}/send"))
send_body = r.json()
print("send response keys:", list(send_body.keys()))
pay_token = send_body["pay_token"]
print("pay_token:", pay_token, "pay_url:", send_body["pay_url"])

step("Get invoice again (status should now be sent)")
r = check(c.get(f"/invoices/{invoice['id']}"))
print("status now:", r.json()["status"])

step(f"Public pay page lookup for token {pay_token}")
pub = httpx.Client(base_url=BASE, timeout=10)
r = check(pub.get(f"/public/invoice/{pay_token}"))
pub_invoice = r.json()
print("public invoice status:", pub_invoice["status"], "total:", pub_invoice["total"], "checkout_url:", pub_invoice.get("checkout_url"))

step("Refresh token flow")
r2 = httpx.Client(base_url=BASE, timeout=10)
r = check(r2.post("/auth/refresh", json={"refresh_token": refresh}))
print("refreshed access token acquired:", bool(r.json()["tokens"]["access_token"]))

print("\nSMOKE TEST COMPLETE")
