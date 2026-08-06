# Scaling Beyond a Single Host, and Equipment/IoT Integration

These are the two remaining Phase 15/16 deferred items that are **not**
credential-setup gaps like AWS/Twilio/Cloudflare (`docs/EXTERNAL_ACCOUNTS_SETUP.md`)
— they are a capacity-planning decision and a "no vendor chosen yet"
decision, respectively. This document gives Cory an honest assessment and
a concrete path for each, without pretending either is a checkbox that can
be scripted today.

---

## 1. True autoscaling / orchestration (Kubernetes or ECS)

### Honest assessment: this is very likely premature right now

`docs/DEPLOYMENT.md` is explicit that HarborIQ's current deployment target
is **a single host running Docker Compose** — "the honest scope for a
5-shop pilot, not a Kubernetes/multi-region design a pilot does not need
yet." Introducing Kubernetes or AWS ECS before there is a real capacity
problem adds real, ongoing cost and operational complexity (a
control-plane/cluster to run and secure, new failure modes, new things
that can misconfigure) in exchange for solving a problem HarborIQ doesn't
have yet. Zero-Trust/least-complexity is also a security posture — more
moving infrastructure parts is more attack surface, not less, until it
earns its keep.

**Concrete signal to watch for, rather than a calendar date:** revisit
this when any of the following becomes true, not before:

- A single host's CPU/RAM is consistently pegged during business hours
  even after right-sizing the instance (check via the Prometheus
  `http_requests_total` / `http_request_duration_seconds` metrics and the
  Grafana dashboards `docs/DEPLOYMENT.md`'s "Metrics"/"Observability"
  sections already wire up — this repo can tell you the honest answer once
  it's running against real traffic).
- A single-host outage (hardware failure, host reboot for patching) is no
  longer an acceptable amount of downtime for the business — i.e. you need
  the app to survive one machine dying, not just recover quickly after.
- You're running enough marina/shop tenants that Celery worker queue depth
  (dunning, geocode-backfill, storage-billing sweeps — see README, "Async
  jobs (Phase 6)") is visibly backing up rather than draining between
  scheduled runs.

### Interim step that needs zero new infrastructure

Before reaching for an orchestrator at all, Docker Compose already
supports running more than one `app`/worker replica on the **same** host,
behind the reverse proxy from `docs/DEPLOYMENT.md`'s "Reverse proxy and
TLS" section:

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  up -d --build --scale app=3 --scale worker=2
```

Caddy/nginx round-robins to the `app` service's replicas automatically
(Docker Compose's internal DNS resolves the service name to all healthy
replica IPs). This buys real headroom — more CPU cores serving requests,
more Celery workers draining queues — without provisioning a second host
or a cluster, and it's already fully supported by the existing compose
files with no code changes. This is the right next step long before ECS
or Kubernetes, and may be sufficient for a long time at pilot/early-growth
scale.

### When the signal above is real: ECS Fargate, not raw Kubernetes

If/when a second host (or true autoscaling that reacts to load
automatically) is actually needed, **AWS ECS on Fargate** is the
recommended path over self-managed Kubernetes for a small team, because:

- No cluster nodes to patch, size, or secure — Fargate is serverless
  container hosting; you define a task (already close to what
  `docker-compose.prod.yml` describes) and AWS runs it.
- An **Application Load Balancer + ECS Service auto scaling policy**
  (target-tracking on CPU or on `ALBRequestCountPerTarget`) is a
  console/Terraform-level concept, not new application code — the
  `app`/`frontend`/`worker` containers themselves need no changes to run
  under ECS; only the deployment target changes.
- Kubernetes (EKS or self-hosted) is the right call later if/when multi-
  cloud portability or a large, sophisticated platform-engineering
  practice actually needs it — for a single-cloud, small-team deployment,
  it's meaningfully more operational surface than ECS/Fargate for the same
  outcome.

**What this would concretely involve, at a high level** (do not build any
of this until the signal above is real — this is a reference outline, not
a task list to execute today):

1. Push the existing `Dockerfile` / `frontend/Dockerfile` images to a
   registry (Amazon ECR) — this repo does not push tagged images to any
   registry yet (see README's deferred-items list), so that would be a
   prerequisite either way, independent of ECS vs. Kubernetes.
2. Define an ECS **Task Definition** per service (`app`, `worker`,
   `worker-beat`) translating `docker-compose.prod.yml`'s env vars,
   resource limits, and health check into Fargate's equivalent fields.
3. Move Postgres and Redis to managed services (RDS for Postgres,
   ElastiCache for Redis) rather than running them as containers —
   `DATABASE_URL`/`SERVICE_DATABASE_URL`/`REDIS_URL` already externalize
   this cleanly; only the connection strings in `.env` change, not the
   application code.
4. Put an Application Load Balancer in front of the `app` and `frontend`
   ECS services, and either keep Cloudflare in front of the ALB (once
   provisioned per `docs/EXTERNAL_ACCOUNTS_SETUP.md`) or terminate TLS at
   the ALB directly via an ACM certificate.
5. Configure ECS Service auto scaling (target-tracking policy on CPU
   utilization or request count) for the `app` service, and a separate
   policy or a fixed larger worker count for `worker` based on Celery
   queue depth.

This is deliberately not built out further here — actually provisioning
AWS infrastructure (VPC, ALB, ECS cluster, RDS/ElastiCache instances) is a
real spend decision requiring an AWS account and is not something to
script speculatively before the scaling signal above is real.

---

## 2. Crane / forklift / boat-lift equipment (IoT) integration

**Current status: no equipment exists yet.** Cory confirmed the business
does not currently operate a crane, forklift, or boat-lift system. There
is genuinely no code to write for this today — any integration would be
built against a specific vendor's API/protocol, and there is no universal
"marine equipment" standard to build against speculatively. Building
against a guessed API shape would very likely need to be thrown away once
real equipment is chosen anyway.

### What HarborIQ already supports without any equipment integration

`dry_stack_launch_requests` (Phase 15) already lets staff log and schedule
dry-stack launch/retrieval requests — this is the operational workflow a
boatyard needs day one, independent of whether any physical lift reports
telemetry back. Equipment integration would **add** automatic status
updates and utilization data on top of this workflow; it does not block
using the workflow today.

### What exists in the market, for when equipment is chosen

A quick survey of what's actually available (verify current
features/pricing directly with each vendor before committing — this list
is not exhaustive and vendor offerings change):

| Vendor / product | Relevance | Notes |
|---|---|---|
| [Radian IoT — Boat Lift Monitoring](https://www.marinadockage.com/radian-boat-lift-sensor/) | Purpose-built for **boat lift** (dry-stack rack/lift) monitoring — battery, lift-cycle counts, usage patterns | Closest match to a marina-specific "boat lift" telemetry product found; confirm current API/webhook availability directly with Radian before assuming one exists |
| Marine Travelift (mobile boat hoists) | The most common **travel lift** manufacturer in US boatyards | No public REST API found as of this writing — if Cory's business uses or plans to use a Travelift-brand hoist, ask their sales/service contact directly whether a telemetry/API add-on exists |
| Wiggins Lift Co. (marina forklifts) | Common marina/boatyard forklift manufacturer | No public REST API found as of this writing — same recommendation: ask directly |
| Generic industrial fleet telematics (Samsara, Verizon Connect, and similar) | If the equipment is a standard forklift/vehicle rather than marine-specific gear, a generic fleet telematics platform's REST API/webhooks may be usable regardless of the equipment brand | These are built for trucking/warehouse fleets, not boatyards specifically — evaluate whether their GPS/engine-hour/utilization data model actually maps to a marina's dry-stack workflow before committing |

### Recommended next step, when equipment is actually being purchased or already owned

1. Tell me (or note in the project) the specific make/model and whether it
   ships with, or offers as an add-on, any telemetry/IoT reporting
   capability — that answer determines whether there is an API to build
   against at all, versus needing a third-party retrofit sensor (like
   Radian's product above).
2. If a REST API or webhook exists, request that vendor's API
   documentation and I can scope a real integration (a new `app/services/`
   module + Celery task ingesting webhook/poll data, following the same
   pattern as the existing Stripe/Twilio integrations) against the actual
   contract instead of a guess.
3. If no API exists (common for older or purely mechanical equipment),
   the realistic path is a retrofit IoT sensor product (Radian-style) that
   publishes its own API/webhook independent of the lift manufacturer —
   evaluate those against the same "does it have a documented API" bar.

Revisit this section once there is a specific vendor to integrate with —
speculative code against no real target would not be a genuine capability,
just the appearance of one.
