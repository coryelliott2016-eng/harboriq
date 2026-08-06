#!/usr/bin/env python3
"""provision_aws_backup.py -- one-time AWS setup for off-host DB backups.

Creates (idempotently) everything `scripts/backup_db_s3.sh` needs on the AWS
side: an S3 bucket with versioning + default encryption + all four
public-access-block settings on, a least-privilege IAM policy scoped to only
that bucket, an IAM user for the backup script, and an access key for that
user. It does NOT create the AWS account itself -- that requires Cory's own
identity and payment method in a browser (see
docs/EXTERNAL_ACCOUNTS_SETUP.md). This script is the step that runs *after*
the account exists and you have a temporary admin credential (or AWS
CloudShell) to run it with.

Zero-Trust / least-privilege (per this project's security standard, see
project knowledge on `harboriq-security-standard`): the IAM policy this
script creates grants exactly `s3:PutObject`, `s3:GetObject`, and
`s3:ListBucket` on the ONE target bucket's ARN (and that bucket's `/*`
object ARN where applicable) -- nothing account-wide, nothing on any other
bucket, no `s3:*`, no `iam:*`. The IAM user has no console password and no
MFA device (it is a machine identity for one cron job, not a human login).

Dependency note: this is an ops script, not application code -- boto3 is
deliberately NOT added to pyproject.toml's main dependency list (the FastAPI
app itself has no AWS dependency; only this one-off provisioning script
does). One-time setup:

    pip install boto3

Usage:
    export AWS_ACCESS_KEY_ID=<temporary admin/CloudShell credential>
    export AWS_SECRET_ACCESS_KEY=<...>
    export AWS_DEFAULT_REGION=us-east-1

    python scripts/provision_aws_backup.py --bucket my-company-harboriq-backups --region us-east-1

    # or via env vars instead of flags:
    BACKUP_S3_BUCKET=my-company-harboriq-backups AWS_DEFAULT_REGION=us-east-1 \\
        python scripts/provision_aws_backup.py

Idempotent: safe to re-run. Bucket creation, policy creation, user creation
are all skipped if they already exist. An access key is only ever created
if the IAM user does not already have one (AWS allows at most 2 active keys
per user) -- re-running this script will NOT print a new secret if a key
already exists, since AWS never allows retrieving an existing secret again;
in that case, delete the old key manually and re-run to rotate it.

The final access key secret is shown exactly ONCE, immediately after
creation -- AWS itself never shows it again after this. Save it before
closing the terminal.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

try:
    import boto3
    from botocore.exceptions import ClientError
except ImportError:  # pragma: no cover - exercised only when boto3 missing
    print(
        "provision_aws_backup.py: boto3 is not installed.\n"
        "This is a one-time ops-script dependency, not part of the main "
        "app -- install it with:\n\n    pip install boto3\n",
        file=sys.stderr,
    )
    raise SystemExit(1)

IAM_USER_NAME = "harboriq-backup"
IAM_POLICY_NAME = "harboriq-backup-s3-least-privilege"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--bucket",
        default=os.environ.get("BACKUP_S3_BUCKET", ""),
        help="S3 bucket name to create/use (default: $BACKUP_S3_BUCKET).",
    )
    parser.add_argument(
        "--region",
        default=os.environ.get("AWS_DEFAULT_REGION", os.environ.get("AWS_REGION", "")),
        help="AWS region for the bucket (default: $AWS_DEFAULT_REGION / $AWS_REGION).",
    )
    args = parser.parse_args(argv)
    if not args.bucket:
        parser.error("--bucket is required (or set BACKUP_S3_BUCKET)")
    if not args.region:
        parser.error("--region is required (or set AWS_DEFAULT_REGION)")
    return args


def bucket_exists(s3_client, bucket: str) -> bool:
    try:
        s3_client.head_bucket(Bucket=bucket)
        return True
    except ClientError as exc:
        error_code = exc.response.get("Error", {}).get("Code", "")
        if error_code in ("404", "NoSuchBucket"):
            return False
        # 403 means it exists but is owned by someone else -- surface that
        # distinctly rather than silently trying (and failing) to create it.
        if error_code == "403":
            raise RuntimeError(
                f"Bucket {bucket!r} already exists and is owned by a "
                "different AWS account -- choose a different (globally "
                "unique) bucket name."
            ) from exc
        raise


def ensure_bucket(s3_client, bucket: str, region: str) -> None:
    if bucket_exists(s3_client, bucket):
        print(f"[ok] bucket {bucket!r} already exists, skipping creation")
        return

    print(f"[create] bucket {bucket!r} in {region}")
    if region == "us-east-1":
        # us-east-1 is the one region where passing a LocationConstraint
        # raises InvalidLocationConstraint -- it must be omitted entirely.
        s3_client.create_bucket(Bucket=bucket)
    else:
        s3_client.create_bucket(
            Bucket=bucket,
            CreateBucketConfiguration={"LocationConstraint": region},
        )


def ensure_versioning(s3_client, bucket: str) -> None:
    current = s3_client.get_bucket_versioning(Bucket=bucket)
    if current.get("Status") == "Enabled":
        print(f"[ok] versioning already enabled on {bucket!r}")
        return
    print(f"[apply] enabling versioning on {bucket!r}")
    s3_client.put_bucket_versioning(
        Bucket=bucket, VersioningConfiguration={"Status": "Enabled"}
    )


def ensure_encryption(s3_client, bucket: str) -> None:
    try:
        current = s3_client.get_bucket_encryption(Bucket=bucket)
        rules = current.get("ServerSideEncryptionConfiguration", {}).get("Rules", [])
        if any(
            r.get("ApplyServerSideEncryptionByDefault", {}).get("SSEAlgorithm") == "AES256"
            for r in rules
        ):
            print(f"[ok] default SSE-S3 encryption already enabled on {bucket!r}")
            return
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "ServerSideEncryptionConfigurationNotFoundError":
            raise

    print(f"[apply] enabling default SSE-S3 (AES256) encryption on {bucket!r}")
    s3_client.put_bucket_encryption(
        Bucket=bucket,
        ServerSideEncryptionConfiguration={
            "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]
        },
    )


def ensure_public_access_block(s3_client, bucket: str) -> None:
    desired = {
        "BlockPublicAcls": True,
        "IgnorePublicAcls": True,
        "BlockPublicPolicy": True,
        "RestrictPublicBuckets": True,
    }
    try:
        current = s3_client.get_public_access_block(Bucket=bucket)
        config = current.get("PublicAccessBlockConfiguration", {})
        if all(config.get(k) is True for k in desired):
            print(f"[ok] public-access-block already fully enabled on {bucket!r}")
            return
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "NoSuchPublicAccessBlockConfiguration":
            raise

    print(f"[apply] enabling all four public-access-block settings on {bucket!r}")
    s3_client.put_public_access_block(
        Bucket=bucket, PublicAccessBlockConfiguration=desired
    )


def least_privilege_policy_document(bucket: str) -> dict:
    """Scoped to exactly this bucket -- no wildcard bucket ARNs, no s3:*."""
    bucket_arn = f"arn:aws:s3:::{bucket}"
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "ListOnlyThisBucket",
                "Effect": "Allow",
                "Action": ["s3:ListBucket"],
                "Resource": bucket_arn,
            },
            {
                "Sid": "ReadWriteOnlyThisBucketsObjects",
                "Effect": "Allow",
                "Action": ["s3:PutObject", "s3:GetObject"],
                "Resource": f"{bucket_arn}/*",
            },
        ],
    }


def ensure_policy(iam_client, bucket: str) -> str:
    """Returns the policy ARN, creating it (or a new version) if needed."""
    account_id = boto3.client("sts").get_caller_identity()["Account"]
    policy_arn = f"arn:aws:iam::{account_id}:policy/{IAM_POLICY_NAME}"
    document = least_privilege_policy_document(bucket)

    try:
        iam_client.get_policy(PolicyArn=policy_arn)
        print(f"[ok] IAM policy {IAM_POLICY_NAME!r} already exists")
        return policy_arn
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "NoSuchEntity":
            raise

    print(f"[create] IAM policy {IAM_POLICY_NAME!r} scoped to bucket {bucket!r} only")
    response = iam_client.create_policy(
        PolicyName=IAM_POLICY_NAME,
        PolicyDocument=json.dumps(document),
        Description=(
            f"Least-privilege access for the HarborIQ backup script: "
            f"PutObject/GetObject/ListBucket on {bucket} only."
        ),
    )
    return response["Policy"]["Arn"]


def ensure_user(iam_client) -> None:
    try:
        iam_client.get_user(UserName=IAM_USER_NAME)
        print(f"[ok] IAM user {IAM_USER_NAME!r} already exists")
        return
    except ClientError as exc:
        if exc.response.get("Error", {}).get("Code") != "NoSuchEntity":
            raise

    print(f"[create] IAM user {IAM_USER_NAME!r} (machine identity, no console access)")
    iam_client.create_user(
        UserName=IAM_USER_NAME,
        Tags=[{"Key": "purpose", "Value": "harboriq-db-backup"}],
    )


def ensure_policy_attached(iam_client, policy_arn: str) -> None:
    attached = iam_client.list_attached_user_policies(UserName=IAM_USER_NAME)
    if any(p["PolicyArn"] == policy_arn for p in attached.get("AttachedPolicies", [])):
        print(f"[ok] policy already attached to {IAM_USER_NAME!r}")
        return
    print(f"[apply] attaching policy to {IAM_USER_NAME!r}")
    iam_client.attach_user_policy(UserName=IAM_USER_NAME, PolicyArn=policy_arn)


def ensure_access_key(iam_client) -> tuple[str, str] | None:
    """Returns (access_key_id, secret) only if a NEW key was just created.

    AWS allows at most 2 active access keys per user and never re-exposes a
    secret after creation -- if a key already exists, this function returns
    None rather than fabricating a "success" that can't actually deliver a
    usable secret. Delete the old key by hand and re-run to rotate.
    """
    existing = iam_client.list_access_keys(UserName=IAM_USER_NAME)
    if existing.get("AccessKeyMetadata"):
        print(
            f"[skip] {IAM_USER_NAME!r} already has an access key "
            f"({existing['AccessKeyMetadata'][0]['AccessKeyId']}). "
            "AWS cannot re-display an existing secret -- delete the old key "
            "in IAM and re-run this script to rotate it."
        )
        return None

    print(f"[create] new access key for {IAM_USER_NAME!r}")
    response = iam_client.create_access_key(UserName=IAM_USER_NAME)
    key = response["AccessKey"]
    return key["AccessKeyId"], key["SecretAccessKey"]


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    session = boto3.Session(region_name=args.region)
    s3 = session.client("s3")
    iam = session.client("iam")

    print(f"== HarborIQ AWS backup provisioning: bucket={args.bucket!r} region={args.region!r} ==")

    ensure_bucket(s3, args.bucket, args.region)
    ensure_versioning(s3, args.bucket)
    ensure_encryption(s3, args.bucket)
    ensure_public_access_block(s3, args.bucket)

    policy_arn = ensure_policy(iam, args.bucket)
    ensure_user(iam)
    ensure_policy_attached(iam, policy_arn)
    new_key = ensure_access_key(iam)

    print()
    print("== Done ==")
    print(f"Bucket:      {args.bucket}")
    print(f"Region:      {args.region}")
    print(f"IAM user:    {IAM_USER_NAME}")
    print(f"IAM policy:  {policy_arn}")

    if new_key:
        access_key_id, secret_access_key = new_key
        print()
        print("!" * 78)
        print("!! SAVE THIS NOW -- AWS will NEVER show this secret access key again. !!")
        print("!" * 78)
        print(f"AWS_ACCESS_KEY_ID={access_key_id}")
        print(f"AWS_SECRET_ACCESS_KEY={secret_access_key}")
        print()
        print("Add these to your .env (do not commit .env):")
        print(f"  AWS_ACCESS_KEY_ID={access_key_id}")
        print(f"  AWS_SECRET_ACCESS_KEY={secret_access_key}")
        print(f"  AWS_DEFAULT_REGION={args.region}")
        print(f"  BACKUP_S3_BUCKET={args.bucket}")
        print("  BACKUP_S3_PREFIX=harboriq-backups")
    else:
        print()
        print("No new access key was created (see [skip] note above). Existing")
        print(".env credentials for this user, if any, remain valid and unchanged.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
