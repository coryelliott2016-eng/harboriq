"""Tests for the ops-only external-account provisioning scripts under
scripts/ (provision_aws_backup.py, provision_twilio_number.py,
provision_cloudflare.py).

These are ops scripts, not app features -- match the effort to the risk.
No real network/AWS calls are made anywhere in this file (httpx and boto3
are fully mocked/monkeypatched). Coverage focuses on the two things that
actually matter for scripts that can spend money or change live infra:

  1. The dry-run vs. --confirm/--apply gating logic actually gates (no
     purchase/API-mutating call happens without the explicit flag).
  2. The idempotency checks are present and skip already-applied state
     instead of blindly re-creating/re-purchasing/re-configuring.

A full mocked-integration-test suite (every branch, every AWS/Twilio/
Cloudflare error path) is intentionally out of scope here.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


# ---------------------------------------------------------------------------
# provision_twilio_number.py -- dry-run vs. --confirm gating
# ---------------------------------------------------------------------------
provision_twilio_number = importlib.import_module("provision_twilio_number")


class _FakeTwilioResponse:
    def __init__(self, json_data: dict, status_code: int = 200):
        self._json = json_data
        self.status_code = status_code
        self.text = str(json_data)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise __import__("httpx").HTTPStatusError("error", request=None, response=self)

    def json(self):
        return self._json


def test_twilio_dry_run_never_purchases(monkeypatch):
    """Without --confirm, the script must search but never call the
    purchase (IncomingPhoneNumbers POST) endpoint."""
    purchase_calls = []

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get(self, url, params=None, auth=None, timeout=None):
            assert "AvailablePhoneNumbers" in url
            return _FakeTwilioResponse(
                {"available_phone_numbers": [{"phone_number": "+16175551234", "friendly_name": "Boston"}]}
            )

        def post(self, url, data=None, auth=None, timeout=None):
            purchase_calls.append((url, data))
            return _FakeTwilioResponse({"phone_number": "+16175551234"})

    monkeypatch.setattr(provision_twilio_number.httpx, "Client", lambda: FakeClient())

    exit_code = provision_twilio_number.main(
        ["--account-sid", "ACxxx", "--auth-token", "tok", "--area-code", "617"]
    )

    assert exit_code == 0
    assert purchase_calls == [], "dry run (no --confirm) must never call the purchase endpoint"


def test_twilio_confirm_flag_purchases(monkeypatch):
    """With --confirm, the script must call the purchase endpoint exactly once."""
    purchase_calls = []

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get(self, url, params=None, auth=None, timeout=None):
            return _FakeTwilioResponse(
                {"available_phone_numbers": [{"phone_number": "+16175551234", "friendly_name": "Boston"}]}
            )

        def post(self, url, data=None, auth=None, timeout=None):
            purchase_calls.append((url, data))
            return _FakeTwilioResponse({"phone_number": "+16175551234"})

    monkeypatch.setattr(provision_twilio_number.httpx, "Client", lambda: FakeClient())

    exit_code = provision_twilio_number.main(
        ["--account-sid", "ACxxx", "--auth-token", "tok", "--area-code", "617", "--confirm"]
    )

    assert exit_code == 0
    assert len(purchase_calls) == 1, "--confirm must trigger exactly one purchase call"
    assert purchase_calls[0][1] == {"PhoneNumber": "+16175551234"}


def test_twilio_no_numbers_found_is_not_an_error_that_purchases(monkeypatch):
    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get(self, url, params=None, auth=None, timeout=None):
            return _FakeTwilioResponse({"available_phone_numbers": []})

        def post(self, *a, **kw):  # pragma: no cover - must never be called
            raise AssertionError("purchase must not be attempted with zero results")

    monkeypatch.setattr(provision_twilio_number.httpx, "Client", lambda: FakeClient())

    exit_code = provision_twilio_number.main(
        ["--account-sid", "ACxxx", "--auth-token", "tok", "--area-code", "000", "--confirm"]
    )
    assert exit_code == 1


def test_twilio_requires_credentials(capsys):
    with pytest.raises(SystemExit):
        provision_twilio_number.parse_args(["--area-code", "617"])


# ---------------------------------------------------------------------------
# provision_cloudflare.py -- dry-run vs. --apply gating + idempotency
# ---------------------------------------------------------------------------
provision_cloudflare = importlib.import_module("provision_cloudflare")


class _FakeCFResponse:
    def __init__(self, json_data: dict, status_code: int = 200):
        self._json = json_data
        self.status_code = status_code
        self.text = str(json_data)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise __import__("httpx").HTTPStatusError("error", request=None, response=self)

    def json(self):
        return self._json


def _make_fake_cf_client(mutating_calls: list, *, ssl_mode="flexible", ruleset_enabled=False, cache_rule_exists=False):
    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get(self, url, headers=None, timeout=None):
            if "settings/ssl" in url:
                return _FakeCFResponse({"result": {"value": ssl_mode}})
            if "http_request_firewall_managed" in url:
                if not ruleset_enabled:
                    return _FakeCFResponse({}, status_code=404)
                return _FakeCFResponse(
                    {"result": {"rules": [{"action": "execute", "action_parameters": {"id": "abc"}}]}}
                )
            if "http_request_cache_settings" in url:
                if not cache_rule_exists:
                    return _FakeCFResponse({}, status_code=404)
                return _FakeCFResponse(
                    {"result": {"rules": [{"description": provision_cloudflare._CACHE_RULE_DESCRIPTION}]}}
                )
            raise AssertionError(f"unexpected GET {url}")

        def patch(self, url, headers=None, json=None, timeout=None):
            mutating_calls.append(("PATCH", url, json))
            return _FakeCFResponse({"result": {}})

        def put(self, url, headers=None, json=None, timeout=None):
            mutating_calls.append(("PUT", url, json))
            return _FakeCFResponse({"result": {}})

    return FakeClient()


def test_cloudflare_dry_run_makes_no_mutating_calls(monkeypatch):
    """Without --apply, no PATCH/PUT call may ever be made -- only GETs."""
    mutating_calls = []
    monkeypatch.setattr(
        provision_cloudflare.httpx,
        "Client",
        lambda: _make_fake_cf_client(mutating_calls, ssl_mode="flexible", ruleset_enabled=False, cache_rule_exists=False),
    )

    exit_code = provision_cloudflare.main(
        ["--api-token", "tok", "--zone-id", "zone123", "--domain", "example.com"]
    )

    assert exit_code == 0
    assert mutating_calls == [], "dry run (no --apply) must never PATCH or PUT"


def test_cloudflare_apply_flag_makes_mutating_calls_when_needed(monkeypatch):
    """With --apply, and nothing yet configured, all three mutating calls fire."""
    mutating_calls = []
    monkeypatch.setattr(
        provision_cloudflare.httpx,
        "Client",
        lambda: _make_fake_cf_client(mutating_calls, ssl_mode="flexible", ruleset_enabled=False, cache_rule_exists=False),
    )

    exit_code = provision_cloudflare.main(
        ["--api-token", "tok", "--zone-id", "zone123", "--domain", "example.com", "--apply"]
    )

    assert exit_code == 0
    # One PATCH (SSL mode) + two PUTs (managed ruleset, cache rules).
    assert len(mutating_calls) == 3
    methods = [c[0] for c in mutating_calls]
    assert methods.count("PATCH") == 1
    assert methods.count("PUT") == 2


def test_cloudflare_apply_is_idempotent_when_already_configured(monkeypatch):
    """With --apply, but everything already in the desired state, zero
    mutating calls should happen -- idempotency, not blind re-application."""
    mutating_calls = []
    monkeypatch.setattr(
        provision_cloudflare.httpx,
        "Client",
        lambda: _make_fake_cf_client(mutating_calls, ssl_mode="strict", ruleset_enabled=True, cache_rule_exists=True),
    )

    exit_code = provision_cloudflare.main(
        ["--api-token", "tok", "--zone-id", "zone123", "--domain", "example.com", "--apply"]
    )

    assert exit_code == 0
    assert mutating_calls == [], "already-configured zone must result in zero mutating calls (idempotent)"


def test_cloudflare_requires_credentials():
    with pytest.raises(SystemExit):
        provision_cloudflare.parse_args(["--domain", "example.com"])


# ---------------------------------------------------------------------------
# provision_aws_backup.py -- idempotency checks (bucket/policy/user/key)
# ---------------------------------------------------------------------------
boto3 = pytest.importorskip("boto3")
from botocore.exceptions import ClientError  # noqa: E402

provision_aws_backup = importlib.import_module("provision_aws_backup")


def _client_error(code: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": "boom"}}, "SomeOperation")


class _FakeS3Client:
    def __init__(self, *, bucket_exists=False):
        self._bucket_exists = bucket_exists
        self.create_bucket_calls = []
        self.versioning_calls = []
        self.encryption_calls = []
        self.public_access_block_calls = []

    def head_bucket(self, Bucket):
        if not self._bucket_exists:
            raise _client_error("404")

    def create_bucket(self, **kwargs):
        self.create_bucket_calls.append(kwargs)
        self._bucket_exists = True

    def get_bucket_versioning(self, Bucket):
        return {"Status": "Enabled"} if self.versioning_calls else {}

    def put_bucket_versioning(self, **kwargs):
        self.versioning_calls.append(kwargs)

    def get_bucket_encryption(self, Bucket):
        if self.encryption_calls:
            return {
                "ServerSideEncryptionConfiguration": {
                    "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]
                }
            }
        raise _client_error("ServerSideEncryptionConfigurationNotFoundError")

    def put_bucket_encryption(self, **kwargs):
        self.encryption_calls.append(kwargs)

    def get_public_access_block(self, Bucket):
        if self.public_access_block_calls:
            return {
                "PublicAccessBlockConfiguration": {
                    "BlockPublicAcls": True,
                    "IgnorePublicAcls": True,
                    "BlockPublicPolicy": True,
                    "RestrictPublicBuckets": True,
                }
            }
        raise _client_error("NoSuchPublicAccessBlockConfiguration")

    def put_public_access_block(self, **kwargs):
        self.public_access_block_calls.append(kwargs)


def test_aws_bucket_creation_is_idempotent():
    """ensure_bucket must NOT call create_bucket when the bucket already exists."""
    s3 = _FakeS3Client(bucket_exists=True)
    provision_aws_backup.ensure_bucket(s3, "my-bucket", "us-east-1")
    assert s3.create_bucket_calls == []


def test_aws_bucket_creation_happens_when_missing():
    s3 = _FakeS3Client(bucket_exists=False)
    provision_aws_backup.ensure_bucket(s3, "my-bucket", "us-west-2")
    assert len(s3.create_bucket_calls) == 1
    assert s3.create_bucket_calls[0]["CreateBucketConfiguration"] == {"LocationConstraint": "us-west-2"}


def test_aws_bucket_creation_us_east_1_omits_location_constraint():
    """us-east-1 raises InvalidLocationConstraint if a LocationConstraint is
    passed -- ensure_bucket must special-case it and omit the kwarg."""
    s3 = _FakeS3Client(bucket_exists=False)
    provision_aws_backup.ensure_bucket(s3, "my-bucket", "us-east-1")
    assert len(s3.create_bucket_calls) == 1
    assert "CreateBucketConfiguration" not in s3.create_bucket_calls[0]


def test_aws_encryption_is_idempotent_once_enabled():
    s3 = _FakeS3Client(bucket_exists=True)
    provision_aws_backup.ensure_encryption(s3, "my-bucket")
    assert len(s3.encryption_calls) == 1
    # Second call should see it already enabled via get_bucket_encryption and skip.
    provision_aws_backup.ensure_encryption(s3, "my-bucket")
    assert len(s3.encryption_calls) == 1, "must not re-apply encryption once already enabled"


def test_aws_public_access_block_is_idempotent_once_enabled():
    s3 = _FakeS3Client(bucket_exists=True)
    provision_aws_backup.ensure_public_access_block(s3, "my-bucket")
    assert len(s3.public_access_block_calls) == 1
    provision_aws_backup.ensure_public_access_block(s3, "my-bucket")
    assert len(s3.public_access_block_calls) == 1, "must not re-apply once all four settings are on"


def test_aws_least_privilege_policy_scopes_to_single_bucket():
    """The generated IAM policy document must reference only the target
    bucket's ARN -- no wildcards, no other resources, no s3:* action."""
    doc = provision_aws_backup.least_privilege_policy_document("my-bucket")
    resources = []
    actions = []
    for statement in doc["Statement"]:
        actions.extend(statement["Action"])
        res = statement["Resource"]
        resources.extend(res if isinstance(res, list) else [res])

    assert all("my-bucket" in r for r in resources), "every resource ARN must be scoped to the target bucket"
    assert all(r.startswith("arn:aws:s3:::my-bucket") for r in resources)
    assert set(actions) == {"s3:ListBucket", "s3:PutObject", "s3:GetObject"}
    assert "s3:*" not in actions
    assert not any("*" == r for r in resources), "must never grant access to all buckets via a bare wildcard"


class _FakeIAMClient:
    def __init__(self, *, has_existing_key=False):
        self._has_existing_key = has_existing_key
        self.create_access_key_calls = []

    def list_access_keys(self, UserName):
        if self._has_existing_key:
            return {"AccessKeyMetadata": [{"AccessKeyId": "AKIAEXISTING"}]}
        return {"AccessKeyMetadata": []}

    def create_access_key(self, UserName):
        self.create_access_key_calls.append(UserName)
        return {"AccessKey": {"AccessKeyId": "AKIANEW", "SecretAccessKey": "supersecret"}}


def test_aws_access_key_not_recreated_when_one_already_exists():
    """AWS never re-shows a secret -- creating a second key when one exists
    would silently orphan the first without ever being able to display it
    again in a useful way, so ensure_access_key must skip and return None."""
    iam = _FakeIAMClient(has_existing_key=True)
    result = provision_aws_backup.ensure_access_key(iam)
    assert result is None
    assert iam.create_access_key_calls == []


def test_aws_access_key_created_when_none_exists():
    iam = _FakeIAMClient(has_existing_key=False)
    result = provision_aws_backup.ensure_access_key(iam)
    assert result == ("AKIANEW", "supersecret")
    assert iam.create_access_key_calls == ["harboriq-backup"]
