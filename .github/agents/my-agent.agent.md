---
# Fill in the fields below to create a basic custom agent for your repository.
# The Copilot CLI can be used for local testing: https://gh.io/customagents/cli
# To make this agent available, merge this file into the default repository branch.
# For format details, see: https://gh.io/customagents/config

name:
description:
---

# My Agent

Describe what your agent does here."""HarborIQ connection repair controller.

Preview:    python agent.py
Repair:     python agent.py --apply
Continuous: python agent.py --apply --loop
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import signal
import tempfile
import threading
from pathlib import Path
from urllib.parse import quote, urlsplit

import httpx

STOP = threading.Event()

HOSTS = {
    "render": "https://api.render.com/v1",
    "vercel": "https://api.vercel.com",
    "cloudflare": "https://api.cloudflare.com/client/v4",
}

TOKENS = {
    "render": "RENDER_API_KEY",
    "vercel": "VERCEL_TOKEN",
    "cloudflare": "CLOUDFLARE_API_TOKEN",
}


class Blocked(RuntimeError):
    """Operator-safe error without credentials or response bodies."""


def emit(event: str, **fields) -> None:
    print(
        json.dumps({"event": event, **fields}, sort_keys=True),
        flush=True,
    )


def resolve(value) -> str:
    if isinstance(value, dict) and set(value) == {"env"}:
        key = value["env"]
        value = os.environ.get(key, "")

        if not value.strip():
            raise Blocked(
                f"Missing configured environment variable: {key}"
            )

    if (
        not isinstance(value, str)
        or not value.strip()
        or "REPLACE_" in value
    ):
        raise Blocked(
            "A required connection setting has not been supplied"
        )

    return value


def fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def segment(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", value):
        raise Blocked("Invalid provider resource identifier")

    return quote(value, safe="")


class API:
    def __init__(self, provider: str, client: httpx.Client):
        self.provider = provider
        self.client = client
        self.token = resolve({"env": TOKENS[provider]})

    def call(
        self,
        method: str,
        path: str,
        *,
        payload=None,
        params=None,
        missing=False,
    ):
        if (
            not path.startswith("/")
            or path.startswith("//")
            or ".." in path
        ):
            raise Blocked("Invalid provider request path")

        url = HOSTS[self.provider] + path

        # Retry reads only. Never blindly repeat a mutation.
        for attempt in range(3 if method == "GET" else 1):
            try:
                response = self.client.request(
                    method,
                    url,
                    headers={
                        "Authorization": f"Bearer {self.token}"
                    },
                    json=payload,
                    params=params,
                )
            except httpx.HTTPError:
                if method == "GET" and attempt < 2:
                    STOP.wait(2 ** attempt)
                    continue

                raise Blocked(
                    f"{self.provider}: request could not be completed"
                ) from None

            if missing and response.status_code == 404:
                return None

            if (
                method == "GET"
                and response.status_code
                in {429, 500, 502, 503, 504}
                and attempt < 2
            ):
                STOP.wait(2 ** attempt)
                continue

            if not 200 <= response.status_code < 300:
                raise Blocked(
                    f"{self.provider}: HTTP {response.status_code}"
                )

            try:
                data = response.json()
            except ValueError:
                raise Blocked(
                    f"{self.provider}: invalid API response"
                ) from None

            if self.provider == "cloudflare":
                if data.get("success") is not True:
                    raise Blocked(
                        "cloudflare: API did not confirm success"
                    )
                return data.get("result")

            return data

        raise Blocked(
            f"{self.provider}: request did not complete"
        )


class Journal:
    """Persist changes and deployment submissions between runs."""

    def __init__(self, path: Path):
        self.path = path
        self.data = (
            json.loads(path.read_text()) if path.exists() else {}
        )

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)

        fd, temporary = tempfile.mkstemp(
            dir=self.path.parent,
            prefix="agent-state-",
        )

        try:
            with os.fdopen(fd, "w") as handle:
                json.dump(self.data, handle)
                handle.flush()
                os.fsync(handle.fileno())

            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def item(self, key: str) -> dict:
        return self.data.setdefault(key, {})


def desired_env(config: dict) -> dict[str, str]:
    values = {}

    for key, source in config.get("env", {}).items():
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            raise Blocked("Invalid environment variable name")

        if (
            key.startswith(("VITE_", "NEXT_PUBLIC_"))
            and isinstance(source, dict)
        ):
            raise Blocked(
                "Public frontend variables cannot reference "
                "a secret environment source"
            )

        values[key] = resolve(source)

    return values


def approved_commit(config: dict) -> str:
    sha = resolve(config["approved_commit"])

    if not re.fullmatch(r"[a-fA-F0-9]{40}", sha):
        raise Blocked(
            "Deployment requires an explicit approved "
            "40-character commit SHA"
        )

    return sha


def inspect_deploy(
    api: API,
    state: dict,
    journal: Journal,
    path: str,
    provider: str,
    params=None,
) -> bool:
    if state.get("submitting"):
        raise Blocked(
            "Deployment submission is uncertain; inspect provider "
            "history before clearing the journal"
        )

    deploy_id = state.get("deploy_id")
    if not deploy_id:
        return False

    data = api.call(
        "GET",
        path + segment(deploy_id),
        params=params,
    )
    data = data.get("deploy", data)

    status = (
        data.get("status")
        if provider == "render"
        else data.get("readyState")
    )

    if status in {"live", "READY"}:
        state.pop("deploy_id", None)
        state["dirty"] = False
        journal.save()

        emit(
            "deployment_verified",
            provider=provider,
            status=status,
        )
        return False

    if status in {
        "build_failed",
        "update_failed",
        "pre_deploy_failed",
        "canceled",
        "deactivated",
        "ERROR",
        "CANCELED",
        "BLOCKED",
    }:
        raise Blocked(
            f"{provider}: deployment failed; "
            "operator review required"
        )

    emit(
        "deployment_pending",
        provider=provider,
        status=status or "unknown",
    )
    return True


def render_service(
    config: dict,
    api: API,
    journal: Journal,
    apply: bool,
):
    service_id = segment(resolve(config["id"]))

    service = api.call("GET", f"/services/{service_id}")
    service = service.get("service", service)

    if (
        service.get("name") != config["name"]
        or service.get("ownerId")
        != resolve(config["workspace_id"])
    ):
        raise Blocked(
            "Render service identity/workspace does not "
            "match the configured target"
        )

    values = desired_env(config)
    sha = approved_commit(config) if values else None
    state = journal.item("render:" + service_id)

    if apply and inspect_deploy(
        api,
        state,
        journal,
        f"/services/{service_id}/deploys/",
        "render",
    ):
        return

    changes = []

    for key, value in values.items():
        current = api.call(
            "GET",
            f"/services/{service_id}/env-vars/{segment(key)}",
            missing=True,
        )

        if current is None or current.get("value") != value:
            changes.append((key, value))

    emit(
        "render_plan",
        service=config["name"],
        keys=[key for key, _ in changes],
        apply=apply,
    )

    if not apply:
        return

    if changes:
        state["dirty"] = True
        journal.save()

        for key, value in changes:
            path = (
                f"/services/{service_id}/env-vars/{segment(key)}"
            )

            api.call("PUT", path, payload={"value": value})
            readback = api.call("GET", path)

            if readback.get("value") != value:
                raise Blocked(
                    "Render environment readback did not "
                    "match the requested value"
                )

    if state.get("dirty"):
        if not sha:
            raise Blocked(
                "An approved commit is required to deploy "
                "pending configuration"
            )

        state["submitting"] = True
        journal.save()

        deployment = api.call(
            "POST",
            f"/services/{service_id}/deploys",
            payload={
                "commitId": sha,
                "clearCache": "do_not_clear",
            },
        )
        deployment = deployment.get("deploy", deployment)

        if not deployment.get("id"):
            raise Blocked(
                "Render did not return a deployment ID"
            )

        state.update(
            submitting=False,
            deploy_id=deployment["id"],
        )
        journal.save()

        emit(
            "deployment_started",
            provider="render",
            service=config["name"],
            commit=sha,
        )


def cloudflare_records(
    config: dict,
    api: API,
    journal: Journal,
    apply: bool,
):
    zone_id = segment(resolve(config["zone_id"]))
    zone = api.call("GET", f"/zones/{zone_id}")

    if (
        zone.get("name") != config["zone_name"]
        or config["zone_name"] != "harboriq.com"
    ):
        raise Blocked(
            "Cloudflare zone identity does not match HarborIQ"
        )

    for spec in config.get("records", []):
        name = spec["name"].rstrip(".")
        kind = spec["type"]
        content = resolve(spec["content"])

        if (
            name != "harboriq.com"
            and not name.endswith(".harboriq.com")
        ):
            raise Blocked(
                "DNS record is outside the HarborIQ zone"
            )

        if kind not in {"A", "AAAA", "CNAME", "TXT"}:
            raise Blocked(
                "This agent manages only A, AAAA, CNAME, "
                "and TXT records"
            )

        params = {
            "name": name,
            "type": kind,
            "per_page": 100,
        }
        path = f"/zones/{zone_id}/dns_records"
        records = api.call("GET", path, params=params)

        def normalized(value):
            if kind == "CNAME":
                return value.rstrip(".").lower()
            return value

        matching = [
            record
            for record in records
            if normalized(record.get("content", ""))
            == normalized(content)
        ]

        label = f"{kind}:{name}:{fingerprint(content)}"
        state = journal.item("dns:" + label)

        if matching:
            if apply and state.get("submitting"):
                state["submitting"] = False
                journal.save()
            continue

        if state.get("submitting"):
            raise Blocked(
                "DNS submission is uncertain; inspect the "
                "record before clearing the journal"
            )

        if kind == "TXT":
            # Add verification TXT without removing other values.
            selected = None
        elif spec.get("id"):
            selected = next(
                (
                    record
                    for record in records
                    if record["id"] == resolve(spec["id"])
                ),
                None,
            )

            if selected is None:
                raise Blocked(
                    "Configured DNS record ID was not found "
                    "for that name/type"
                )
        elif len(records) == 1:
            selected = records[0]
        elif not records:
            selected = None
        else:
            raise Blocked(
                "Multiple DNS records match; "
                "specify the exact record ID"
            )

        emit(
            "dns_plan",
            name=name,
            type=kind,
            action="update" if selected else "add",
            apply=apply,
        )

        if not apply:
            continue

        if selected:
            # Preserve proxy, TTL, and other existing settings.
            api.call(
                "PATCH",
                path + "/" + segment(selected["id"]),
                payload={"content": content},
            )
        else:
            body = {
                "type": kind,
                "name": name,
                "content": content,
                "ttl": 1,
            }

            if kind != "TXT":
                if not isinstance(spec.get("proxied"), bool):
                    raise Blocked(
                        "New address records require "
                        "an explicit proxied setting"
                    )

                body["proxied"] = spec["proxied"]

            state["submitting"] = True
            journal.save()

            api.call("POST", path, payload=body)

            state["submitting"] = False
            journal.save()

        verified = api.call("GET", path, params=params)

        if not any(
            normalized(record.get("content", ""))
            == normalized(content)
            for record in verified
        ):
            raise Blocked(
                "DNS API readback did not confirm "
                "the intended record"
            )

        emit(
            "dns_record_verified",
            name=name,
            type=kind,
        )


def vercel_project(
    config: dict,
    api: API,
    journal: Journal,
    apply: bool,
):
    project_id = segment(resolve(config["id"]))
    team_id = resolve(config["team_id"])
    params = {"teamId": team_id}

    project = api.call(
        "GET",
        f"/v9/projects/{project_id}",
        params=params,
    )

    if (
        project.get("accountId") != team_id
        or project.get("name") != config["name"]
    ):
        raise Blocked(
            "Vercel project/team identity does not "
            "match the configured target"
        )

    values = desired_env(config)
    state = journal.item("vercel:" + project_id)

    if apply and inspect_deploy(
        api,
        state,
        journal,
        "/v13/deployments/",
        "vercel",
        params=params,
    ):
        return

    source = config.get("git_source")

    if values and (
        not source
        or not re.fullmatch(
            r"[a-fA-F0-9]{40}",
            resolve(source["sha"]),
        )
    ):
        raise Blocked(
            "Vercel environment repair requires a source "
            "pinned to an approved commit"
        )

    env_path = f"/v10/projects/{project_id}/env"
    inventory = api.call(
        "GET",
        env_path,
        params=params,
    )["envs"]

    for key, value in values.items():
        matches = [
            entry
            for entry in inventory
            if entry["key"] == key
            and "production" in entry.get("target", [])
        ]

        if len(matches) > 1 or (
            matches
            and set(matches[0]["target"]) != {"production"}
        ):
            raise Blocked(
                "Vercel environment scope is ambiguous or "
                "shared with preview/development"
            )

        current = matches[0] if matches else None
        saved = state.setdefault("env_versions", {}).get(key, {})

        same = current and saved == {
            "id": current["id"],
            "updatedAt": current.get("updatedAt"),
            "digest": fingerprint(value),
        }

        if same:
            continue

        emit("vercel_env_plan", key=key, apply=apply)

        if not apply:
            continue

        state["dirty"] = True
        journal.save()

        body = {
            "key": key,
            "value": value,
            "target": ["production"],
            "type": (
                "plain"
                if key.startswith(("VITE_", "NEXT_PUBLIC_"))
                else "sensitive"
            ),
        }

        api.call(
            "POST",
            env_path,
            params={**params, "upsert": "true"},
            payload=body,
        )

        after = api.call(
            "GET",
            env_path,
            params=params,
        )["envs"]

        entry = next(
            (
                item
                for item in after
                if item["key"] == key
                and item.get("target") == ["production"]
            ),
            None,
        )

        if not entry or entry.get("updatedAt") is None:
            raise Blocked(
                "Vercel did not confirm the production "
                "environment variable metadata"
            )

        state["env_versions"][key] = {
            "id": entry["id"],
            "updatedAt": entry.get("updatedAt"),
            "digest": fingerprint(value),
        }
        journal.save()

    if apply and state.get("dirty"):
        if not source:
            raise Blocked(
                "Vercel has pending configuration "
                "but no approved source"
            )

        state["submitting"] = True
        journal.save()

        git_source = {
            **source,
            "sha": resolve(source["sha"]),
        }

        deployed = api.call(
            "POST",
            "/v13/deployments",
            params=params,
            payload={
                "project": project_id,
                "name": project["name"],
                "target": "production",
                "gitSource": git_source,
            },
        )

        if not deployed.get("id"):
            raise Blocked(
                "Vercel did not return a deployment ID"
            )

        state.update(
            submitting=False,
            deploy_id=deployed["id"],
        )
        journal.save()

        emit(
            "deployment_started",
            provider="vercel",
            commit=git_source["sha"],
        )

    for domain in config.get("domains", []):
        if (
            domain != "harboriq.com"
            and not domain.endswith(".harboriq.com")
        ):
            raise Blocked("Domain is outside HarborIQ")

        domain_path = (
            f"/v9/projects/{project_id}"
            f"/domains/{segment(domain)}"
        )

        details = api.call(
            "GET",
            domain_path,
            params=params,
        )

        if details.get("verified"):
            continue

        emit(
            "domain_verification_plan",
            domain=domain,
            apply=apply,
        )

        if apply:
            details = api.call(
                "POST",
                domain_path + "/verify",
                params=params,
            )

            if not details.get("verified"):
                raise Blocked(
                    "Domain ownership is still unverified; "
                    "check authoritative DNS propagation"
                )

            emit("domain_verified", domain=domain)


def health_checks(
    config: dict,
    client: httpx.Client,
) -> list[dict]:
    outcomes = []

    for item in config.get("checks", []):
        name = item["name"]

        try:
            url = resolve(item["url"])
            parsed = urlsplit(url)

            if (
                parsed.scheme != "https"
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise Blocked(
                    "Health checks require "
                    "credential-free HTTPS URLs"
                )

            response = client.get(url)
            ok = response.status_code == 200
            expected = item.get("json")

            if expected is not None:
                payload = (
                    response.json()
                    if "application/json"
                    in response.headers.get("content-type", "")
                    else None
                )

                ok = (
                    ok
                    and isinstance(payload, dict)
                    and all(
                        payload.get(key) == value
                        for key, value in expected.items()
                    )
                )

            if item.get("contains"):
                ok = (
                    ok
                    and item["contains"].lower()
                    in response.text.lower()
                )

            outcomes.append({
                "check": name,
                "ok": bool(ok),
                "http_status": response.status_code,
            })

        except Blocked as exc:
            outcomes.append({
                "check": name,
                "ok": False,
                "reason": str(exc),
            })
        except (httpx.HTTPError, ValueError):
            outcomes.append({
                "check": name,
                "ok": False,
                "reason": "request_unverified",
            })

    return outcomes


def cycle(
    config: dict,
    journal: Journal,
    apply: bool,
    client: httpx.Client,
) -> bool:
    blocked = []

    handlers = [
        ("cloudflare", cloudflare_records),
        ("render", render_service),
        ("vercel", vercel_project),
    ]

    for provider, handler in handlers:
        targets = config.get(provider, [])

        for index, target in enumerate(targets):
            label = target.get("name", f"{provider}_{index}")

            try:
                handler(
                    target,
                    API(provider, client),
                    journal,
                    apply,
                )
            except Blocked as exc:
                blocked.append({
                    "target": label,
                    "reason": str(exc),
                })
            except Exception:
                blocked.append({
                    "target": label,
                    "reason": (
                        "Unexpected adapter error; "
                        "inspect code/configuration"
                    ),
                })

    checks = health_checks(config, client)

    pending = any(
        state.get("dirty")
        or state.get("deploy_id")
        or state.get("submitting")
        for state in journal.data.values()
    )

    ready = (
        apply
        and not blocked
        and not pending
        and bool(checks)
        and all(item["ok"] for item in checks)
    )

    emit(
        "reconnect_report",
        mode="apply" if apply else "plan",
        configured_targets=sum(
            len(config.get(provider, []))
            for provider, _ in handlers
        ),
        ready=ready,
        pending=bool(pending),
        blocked=blocked,
        checks=checks,
    )

    return ready


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", default="connections.json")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--loop", action="store_true")
    args = parser.parse_args()

    config = json.loads(Path(args.config).read_text())

    interval = max(
        60,
        int(os.environ.get("RECONCILE_INTERVAL_SECONDS", "300")),
    )

    state_path = Path(
        os.environ.get(
            "AGENT_STATE_FILE",
            "state/reconnect.json",
        )
    )
    state_path.parent.mkdir(parents=True, exist_ok=True)

    for sig in (signal.SIGTERM, signal.SIGINT):
        signal.signal(sig, lambda *_: STOP.set())

    with state_path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(
            lock,
            fcntl.LOCK_EX | fcntl.LOCK_NB,
        )

        journal = Journal(state_path)

        with httpx.Client(
            timeout=15,
            follow_redirects=False,
        ) as client:
            while not STOP.is_set():
                try:
                    ready = cycle(
                        config,
                        journal,
                        args.apply,
                        client,
                    )
                except Blocked as exc:
                    emit(
                        "configuration_blocked",
                        reason=str(exc),
                    )
                    ready = False

                if not args.loop:
                    return 0 if ready else 1

                STOP.wait(interval)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
    
