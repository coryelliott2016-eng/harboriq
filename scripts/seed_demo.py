#!/usr/bin/env python3
"""Seed the canned Gulf Coast Marine Service sales-demo tenant.

Run from the repository root:

    APP_ENV=development .venv/bin/python scripts/seed_demo.py --reset

The script intentionally uses the service database role.  Seed data spans the
full tenant graph and is only appropriate for the disposable demo environment;
the environment guard below prevents an accidental production run.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.engine import Connection

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.core.security import hash_password  # noqa: E402

DEMO_SLUG = "gulf-coast-marine-service-demo"
DEMO_COMPANY_NAME = "Gulf Coast Marine Service"
DEMO_PASSWORD = "HarborDemo!2026"  # noqa: S105 - documented local demo credential
DEMO_URL = "http://localhost:5173"
NAMESPACE = uuid.UUID("a53724c4-90d3-4690-ae69-caddb24ed55d")

EXPECTED_COUNTS = {
    "users": 4,
    "customers": 10,
    "vessels": 13,
    "jobs": 16,
    "job_line_items": 32,
    "estimates": 4,
    "invoices": 8,
    "payments": 3,
    "inventory_items": 12,
    "vendors": 2,
    "purchase_orders": 2,
    "purchase_order_line_items": 4,
    "slips": 10,
    "slip_reservations": 4,
    "messages": 3,
}


def demo_id(key: str) -> uuid.UUID:
    """Return a stable UUID, making repeated seed runs naturally idempotent."""
    return uuid.uuid5(NAMESPACE, key)


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def ensure_safe_environment(override: bool) -> None:
    """Refuse non-demo environments unless the caller explicitly overrides."""
    app_env = os.environ.get("APP_ENV", "development").strip().lower()
    if app_env not in {"development", "staging"} and not override:
        raise SystemExit(
            "Refusing to seed because APP_ENV must be development or staging. "
            "Pass --i-know-what-im-doing to override."
        )


def service_engine() -> Engine:
    """Build an isolated service-role engine without relying on a dotenv file."""
    database_url = os.environ.get("SERVICE_DATABASE_URL")
    if not database_url:
        raise SystemExit("SERVICE_DATABASE_URL must be set for the demo seed.")
    return create_engine(database_url, future=True, pool_pre_ping=True)


def upsert(
    connection: Connection,
    table: str,
    values: Mapping[str, Any],
    *,
    conflict_columns: Sequence[str] = ("id",),
    update_columns: Sequence[str] | None = None,
) -> None:
    """Insert one static seed row or update it in place by its stable key."""
    columns = tuple(values)
    mutable_columns = tuple(update_columns or (column for column in columns if column not in conflict_columns))
    statement = text(
        f"""
        INSERT INTO {table} ({", ".join(columns)})
        VALUES ({", ".join(f":{column}" for column in columns)})
        ON CONFLICT ({", ".join(conflict_columns)}) DO UPDATE
        SET {", ".join(f"{column} = EXCLUDED.{column}" for column in mutable_columns)}
        """
    )
    parameters = {
        column: json.dumps(value) if isinstance(value, dict) else value
        for column, value in values.items()
    }
    connection.execute(statement, parameters)


def delete_demo_tenant(connection: Connection, company_id: uuid.UUID) -> None:
    """Delete mutable demo rows in dependency order before a clean re-seed."""
    company_tables = (
        "token_ledger_entries",
        "asset_tokens",
        "crypto_payments",
        "crypto_processed_events",
        "job_attachments",
        "job_time_entries",
        "messages",
        "dry_stack_launch_requests",
        "slip_reservations",
        "job_line_items",
        "purchase_order_line_items",
        "purchase_orders",
        "payments",
        "refunds",
        "invoices",
        "estimate_line_items",
        "estimates",
        "slips",
        "jobs",
        "inventory_items",
        "vendors",
        "vessels",
        "customers",
        "public_tokens",
        "password_reset_tokens",
        "mfa_backup_codes",
        "user_sessions",
        "outbox_events",
        "stripe_processed_events",
        "subscriptions",
    )
    for table in company_tables:
        if table == "token_ledger_entries":
            connection.execute(
                text(
                    """
                    DELETE FROM token_ledger_entries
                    WHERE asset_token_id IN (
                        SELECT id FROM asset_tokens WHERE company_id = :company_id
                    )
                    """
                ),
                {"company_id": company_id},
            )
        elif table == "estimate_line_items":
            connection.execute(
                text(
                    """
                    DELETE FROM estimate_line_items
                    WHERE estimate_id IN (
                        SELECT id FROM estimates WHERE company_id = :company_id
                    )
                    """
                ),
                {"company_id": company_id},
            )
        else:
            connection.execute(
                text(f"DELETE FROM {table} WHERE company_id = :company_id"),
                {"company_id": company_id},
            )

    # audit_log deliberately rejects DELETE through a database rule. It has no
    # FK to companies, so historical rows cannot block a demo tenant reset.
    connection.execute(
        text("DELETE FROM users WHERE company_id = :company_id"),
        {"company_id": company_id},
    )
    connection.execute(
        text("DELETE FROM companies WHERE id = :company_id"),
        {"company_id": company_id},
    )


def reset_if_requested(connection: Connection, reset: bool) -> None:
    """Locate the current demo tenant by slug and remove it only when asked."""
    if not reset:
        return
    company_id = connection.execute(
        text("SELECT id FROM companies WHERE slug = :slug"),
        {"slug": DEMO_SLUG},
    ).scalar_one_or_none()
    if company_id is not None:
        delete_demo_tenant(connection, company_id)


def seed_company_and_users(connection: Connection, now: datetime) -> dict[str, uuid.UUID]:
    """Create the demo company and its owner, office, and technician accounts."""
    company_id = demo_id("company")
    upsert(
        connection,
        "companies",
        {
            "id": company_id,
            "slug": DEMO_SLUG,
            "name": DEMO_COMPANY_NAME,
            "latitude": Decimal("27.336434"),
            "longitude": Decimal("-82.530653"),
            "mfa_required": False,
            "created_at": now - timedelta(days=60),
            "updated_at": now,
        },
    )

    users = (
        (
            "owner",
            "demo@harboriq.app",
            "Cory Elliott",
            "owner",
            ["operations", "customer-service", "sales"],
            "1200 1st Avenue W, Bradenton, FL 34205",
            Decimal("27.498928"),
            Decimal("-82.574819"),
            Decimal("0.00"),
        ),
        (
            "office",
            "office@gulfcoastmarine.demo",
            "Maya Torres",
            "office",
            ["scheduling", "billing", "customer-service"],
            "1600 Ken Thompson Parkway, Sarasota, FL 34236",
            Decimal("27.328657"),
            Decimal("-82.573722"),
            Decimal("31.00"),
        ),
        (
            "tech-1",
            "tech1@gulfcoastmarine.demo",
            "Luis Navarro",
            "technician",
            ["outboard", "yamaha", "mercury", "electronics"],
            "4900 14th Street W, Bradenton, FL 34207",
            Decimal("27.454670"),
            Decimal("-82.574056"),
            Decimal("42.00"),
        ),
        (
            "tech-2",
            "tech2@gulfcoastmarine.demo",
            "Dana Price",
            "technician",
            ["diesel", "bottom-paint", "fiberglass", "electrical"],
            "6700 Cortez Road W, Bradenton, FL 34210",
            Decimal("27.461907"),
            Decimal("-82.633597"),
            Decimal("44.00"),
        ),
    )
    ids: dict[str, uuid.UUID] = {}
    for key, email, full_name, role, skills, address, lat, lng, hourly_rate in users:
        user_id = demo_id(f"user:{key}")
        ids[key] = user_id
        upsert(
            connection,
            "users",
            {
                "id": user_id,
                "company_id": company_id,
                "email": email,
                "password_hash": hash_password(DEMO_PASSWORD),
                "full_name": full_name,
                "role": role,
                "is_active": True,
                "email_verified_at": now - timedelta(days=59),
                "failed_login_attempts": 0,
                "locked_until": None,
                "mfa_enabled_at": None,
                "skills": skills,
                "address_text": address,
                "home_latitude": lat,
                "home_longitude": lng,
                "current_latitude": lat,
                "current_longitude": lng,
                "location_updated_at": now - timedelta(minutes=12),
                "hourly_rate": hourly_rate,
                "created_at": now - timedelta(days=59),
            },
        )
    ids["company"] = company_id
    return ids


def seed_customers_and_vessels(
    connection: Connection, ids: Mapping[str, uuid.UUID], now: datetime
) -> tuple[dict[str, uuid.UUID], dict[str, uuid.UUID]]:
    """Seed fictional Gulf Coast customers and a varied local vessel roster."""
    company_id = ids["company"]
    customers = (
        ("ava-merrin", "Ava", "Merrin", None, "ava.merrin@example.demo", "941-555-0101",
         "2419 Bay Street", "Sarasota", "34237", "27.336715", "-82.534212"),
        ("noah-caldwell", "Noah", "Caldwell", None, "noah.caldwell@example.demo", "941-555-0102",
         "512 Harbor Drive", "Sarasota", "34236", "27.321473", "-82.576864"),
        ("elise-rowan", "Elise", "Rowan", None, "elise.rowan@example.demo", "941-555-0103",
         "1804 5th Street W", "Palmetto", "34221", "27.521304", "-82.574936"),
        ("marcus-vail", "Marcus", "Vail", None, "marcus.vail@example.demo", "941-555-0104",
         "7604 16th Avenue NW", "Bradenton", "34209", "27.505624", "-82.625159"),
        ("sienna-holt", "Sienna", "Holt", None, "sienna.holt@example.demo", "941-555-0105",
         "1150 John Ringling Boulevard", "Sarasota", "34236", "27.328908", "-82.574305"),
        ("owen-pike", "Owen", "Pike", None, "owen.pike@example.demo", "941-555-0106",
         "4410 75th Street W", "Bradenton", "34210", "27.452312", "-82.626010"),
        ("leah-barnett", "Leah", "Barnett", None, "leah.barnett@example.demo", "941-555-0107",
         "2990 53rd Avenue E", "Bradenton", "34203", "27.445049", "-82.531087"),
        ("gideon-lane", "Gideon", "Lane", None, "gideon.lane@example.demo", "941-555-0108",
         "1044 Gulf of Mexico Drive", "Longboat Key", "34228", "27.394407", "-82.644681"),
        ("pelican-cove", None, None, "Pelican Cove Marina", "dockmaster@pelicancove.example.demo",
         "941-555-0109", "8200 Midnight Pass Road", "Sarasota", "34242", "27.240341", "-82.530181"),
        ("cortez-charters", None, None, "Cortez Bay Charters", "ops@cortezbay.example.demo",
         "941-555-0110", "12307 46th Avenue W", "Cortez", "34215", "27.470006", "-82.683742"),
    )
    customer_ids: dict[str, uuid.UUID] = {}
    for index, row in enumerate(customers):
        key, first, last, company_name, email, phone, address, city, postal, lat, lng = row
        customer_id = demo_id(f"customer:{key}")
        customer_ids[key] = customer_id
        upsert(
            connection,
            "customers",
            {
                "id": customer_id,
                "company_id": company_id,
                "first_name": first,
                "last_name": last,
                "company_name": company_name,
                "email": email,
                "phone": phone,
                "sms_consent_at": now - timedelta(days=55 - index),
                "sms_opted_out": False,
                "address_line1": address,
                "city": city,
                "state": "FL",
                "postal_code": postal,
                "country": "US",
                "notes": "Demo account — fictional contact information only.",
                "latitude": Decimal(lat),
                "longitude": Decimal(lng),
                "created_at": now - timedelta(days=58 - index * 3),
                "updated_at": now - timedelta(days=index),
            },
        )

    vessels = (
        ("reel-therapy", "ava-merrin", "Reel Therapy", "Boston Whaler", "280 Outrage", 2021,
         "BWHTY280DEMO001", "FL-DM-201", "28.00", "9.50", "1.75", "Mercury", "Verado 300",
         412, 2, "Rack C-14", None),
        ("salt-life", "noah-caldwell", "Salt Life", "Contender", "25T", 2019,
         "CNT250DEMO0002", "FL-DM-202", "25.00", "8.50", "1.67", "Yamaha", "F200",
         688, 2, "Wet slip A-03", "A-03"),
        ("blue-hour", "elise-rowan", "Blue Hour", "Sea Ray", "Sundancer 320", 2017,
         "SRY320DEMO0003", "FL-DM-203", "32.00", "10.75", "2.58", "MerCruiser", "6.2L DTS",
         535, 2, "Wet slip B-02", "B-02"),
        ("running-tide", "marcus-vail", "Running Tide", "Grady-White", "Canyon 306", 2020,
         "GW306DEMO00004", "FL-DM-204", "30.50", "10.75", "1.83", "Yamaha", "F300",
         276, 2, "Service yard", None),
        ("second-wind", "sienna-holt", "Second Wind", "Pursuit", "S 328", 2022,
         "PUR328DEMO0005", "FL-DM-205", "34.50", "10.83", "2.08", "Yamaha", "F300",
         189, 2, "Dry stack DS-1-02", "DS-1-02"),
        ("tide-line", "owen-pike", "Tide Line", "Key West", "263 FS", 2018,
         "KWE263DEMO0006", "FL-DM-206", "26.25", "9.25", "1.58", "Yamaha", "F200",
         804, 2, "Rack B-07", None),
        ("easy-days", "leah-barnett", "Easy Days", "Regulator", "31", 2016,
         "REG310DEMO0007", "FL-DM-207", "31.00", "10.33", "2.08", "Yamaha", "F300",
         912, 2, "Wet slip A-07", "A-07"),
        ("sea-keeper", "gideon-lane", "Sea Keeper", "Tiara", "31 Open", 2014,
         "TIA310DEMO0008", "FL-DM-208", "31.00", "12.00", "3.00", "Volvo Penta", "D6",
         1246, 2, "Wet slip B-05", "B-05"),
        ("dockside-one", "pelican-cove", "Dockside One", "Boston Whaler", "250 Dauntless", 2020,
         "BWH250DEMO0009", "FL-DM-209", "24.75", "8.50", "1.42", "Mercury", "Verado 250",
         366, 1, "Pelican Cove transient dock", None),
        ("marina-runner", "pelican-cove", "Marina Runner", "Parker", "2520 XLD", 2015,
         "PAR252DEMO0010", "FL-DM-210", "25.92", "9.50", "2.33", "Yamaha", "F250",
         1104, 1, "Wet slip C-01", "C-01"),
        ("gulf-stream", "cortez-charters", "Gulf Stream", "Contender", "39 ST", 2021,
         "CNT390DEMO0011", "FL-DM-211", "39.00", "10.83", "2.00", "Yamaha", "F425",
         721, 3, "Charter dock", None),
        ("sunset-cruise", "cortez-charters", "Sunset Cruise", "Sea Ray", "SLX 350", 2019,
         "SRY350DEMO0012", "FL-DM-212", "34.75", "11.33", "2.75", "MerCruiser", "8.2L",
         640, 2, "Charter dock", None),
        ("watermark", "ava-merrin", "Watermark", "Grady-White", "Freedom 285", 2023,
         "GW285DEMO0013", "FL-DM-213", "28.00", "9.50", "1.83", "Yamaha", "F300",
         94, 2, "Dry stack DS-2-01", "DS-2-01"),
    )
    vessel_ids: dict[str, uuid.UUID] = {}
    for index, row in enumerate(vessels):
        (
            key,
            customer_key,
            name,
            make,
            model,
            year,
            hull_id,
            registration,
            length,
            beam,
            draft,
            engine_make,
            engine_model,
            hours,
            engine_count,
            storage,
            slip_number,
        ) = row
        vessel_id = demo_id(f"vessel:{key}")
        vessel_ids[key] = vessel_id
        upsert(
            connection,
            "vessels",
            {
                "id": vessel_id,
                "company_id": company_id,
                "customer_id": customer_ids[customer_key],
                "name": name,
                "make": make,
                "model": model,
                "year": year,
                "hull_id": hull_id,
                "registration": registration,
                "length_ft": Decimal(length),
                "beam_ft": Decimal(beam),
                "draft_ft": Decimal(draft),
                "engine_make": engine_make,
                "engine_model": engine_model,
                "engine_hours": hours,
                "engine_count": engine_count,
                "storage_location": storage,
                "slip_number": slip_number,
                "notes": "Fictional demo vessel.",
                "created_at": now - timedelta(days=57 - index * 2),
                "updated_at": now - timedelta(days=index),
            },
        )
    return customer_ids, vessel_ids


def seed_vendors_and_inventory(
    connection: Connection, ids: Mapping[str, uuid.UUID], now: datetime
) -> dict[str, uuid.UUID]:
    """Seed local-looking suppliers and marine parts with two low-stock alerts."""
    company_id = ids["company"]
    vendors = (
        ("suncoast", "Suncoast Marine Supply", "orders@suncoast.example.demo", "941-555-0140"),
        ("gulf-engine", "Gulf Engine & Rigging", "parts@gulfengine.example.demo", "941-555-0141"),
    )
    vendor_ids: dict[str, uuid.UUID] = {}
    for index, (key, name, email, phone) in enumerate(vendors):
        vendor_id = demo_id(f"vendor:{key}")
        vendor_ids[key] = vendor_id
        upsert(
            connection,
            "vendors",
            {
                "id": vendor_id,
                "company_id": company_id,
                "name": name,
                "contact_email": email,
                "contact_phone": phone,
                "notes": "Fictional demo supplier.",
                "is_active": True,
                "created_at": now - timedelta(days=56 - index),
                "updated_at": now,
            },
        )

    inventory = (
        ("yam-10w30", "YAM-10W30-GAL", "Yamalube 10W-30 4-Stroke Oil, Gallon", "31.50", "49.95", 18, 8, "gulf-engine"),
        ("merc-25w40", "MER-25W40-GAL", "Mercury 25W-40 Synthetic Blend Oil, Gallon", "34.00", "54.95", 14, 8, "gulf-engine"),
        ("impeller-yamaha", "YAM-6E5-44352", "Yamaha Water Pump Impeller Kit", "42.00", "78.50", 2, 6, "gulf-engine"),
        ("impeller-mercury", "MER-47-89984", "Mercury Water Pump Impeller", "35.25", "69.95", 9, 5, "gulf-engine"),
        ("zinc-kit", "ZINC-TRI-KIT", "Triple Engine Zinc Kit", "28.00", "59.95", 3, 10, "suncoast"),
        ("fuel-filter", "RACOR-S3213", "Racor 10-Micron Fuel Filter", "16.75", "32.95", 24, 10, "suncoast"),
        ("oil-filter", "YAM-5GH-13440", "Yamaha Oil Filter", "11.50", "24.95", 21, 10, "gulf-engine"),
        ("alternator-belt", "BELT-ALT-90", "Marine Alternator Belt", "18.25", "39.95", 12, 5, "suncoast"),
        ("steering-fluid", "SEA-STAR-HF", "SeaStar Hydraulic Steering Fluid", "14.00", "29.95", 16, 6, "suncoast"),
        ("bilge-pump", "RULE-1100", "Rule 1100 GPH Bilge Pump", "46.00", "89.95", 7, 4, "suncoast"),
        ("battery", "DUR-G27M", "Group 27 Marine AGM Battery", "174.00", "259.95", 6, 3, "gulf-engine"),
        ("bottom-paint", "PETTIT-VIVID-BL", "Pettit Vivid Bottom Paint, Gallon", "138.00", "219.95", 8, 4, "suncoast"),
    )
    inventory_ids: dict[str, uuid.UUID] = {}
    for index, (key, sku, name, cost, retail, quantity, reorder, vendor_key) in enumerate(inventory):
        item_id = demo_id(f"inventory:{key}")
        inventory_ids[key] = item_id
        upsert(
            connection,
            "inventory_items",
            {
                "id": item_id,
                "company_id": company_id,
                "sku": sku,
                "name": name,
                "unit_cost": Decimal(cost),
                "retail_price": Decimal(retail),
                "quantity_on_hand": quantity,
                "reorder_point": reorder,
                "low_stock_alerted": quantity <= reorder,
                "default_vendor_id": vendor_ids[vendor_key],
                "created_at": now - timedelta(days=54 - index),
            },
        )
    inventory_ids.update({f"vendor:{key}": value for key, value in vendor_ids.items()})
    return inventory_ids


def seed_jobs(
    connection: Connection,
    ids: Mapping[str, uuid.UUID],
    customer_ids: Mapping[str, uuid.UUID],
    vessel_ids: Mapping[str, uuid.UUID],
    inventory_ids: Mapping[str, uuid.UUID],
    now: datetime,
) -> dict[str, uuid.UUID]:
    """Seed a dispatch-ready work order board and labor-plus-parts detail."""
    company_id = ids["company"]
    jobs = (
        ("j01", "ava-merrin", "reel-therapy", "100-hour service", "scheduled", "high", 3, "tech-1", ["outboard", "yamaha"], "oil-filter", "Yamaha 100-hour service"),
        ("j02", "noah-caldwell", "salt-life", "Impeller swap and cooling-system inspection", "in_progress", "urgent", 0, "tech-1", ["outboard", "yamaha"], "impeller-yamaha", "Water pump impeller replacement"),
        ("j03", "elise-rowan", "blue-hour", "Bottom paint touch-up", "completed", "normal", -42, "tech-2", ["bottom-paint"], "bottom-paint", "Bottom paint materials"),
        ("j04", "marcus-vail", "running-tide", "Garmin chartplotter installation", "scheduled", "high", 5, "tech-1", ["electronics", "electrical"], "battery", "Electronics house battery"),
        ("j05", "sienna-holt", "second-wind", "Pre-season systems check", "scheduled", "normal", 9, "tech-2", ["electrical", "outboard"], "fuel-filter", "Fuel system filter"),
        ("j06", "owen-pike", "tide-line", "Annual engine service", "scheduled", "normal", 2, None, ["outboard", "yamaha"], "merc-25w40", "Engine oil and inspection supplies"),
        ("j07", "leah-barnett", "easy-days", "Replace sacrificial zincs", "completed", "normal", -33, "tech-2", ["outboard"], "zinc-kit", "Triple engine zinc kit"),
        ("j08", "gideon-lane", "sea-keeper", "Diesel generator diagnostics", "in_progress", "high", -1, "tech-2", ["diesel", "electrical"], "alternator-belt", "Generator drive belt"),
        ("j09", "pelican-cove", "dockside-one", "Bilge pump replacement", "completed", "high", -27, "tech-1", ["electrical"], "bilge-pump", "Rule bilge pump"),
        ("j10", "cortez-charters", "gulf-stream", "Triple outboard 300-hour service", "scheduled", "urgent", 6, "tech-1", ["outboard", "yamaha"], "yam-10w30", "Yamalube service oil"),
        ("j11", "ava-merrin", "watermark", "New boat commissioning", "scheduled", "normal", 12, None, ["electronics", "outboard"], "steering-fluid", "Hydraulic steering fluid"),
        ("j12", "noah-caldwell", "salt-life", "Trailer light and brake inspection", "in_progress", "normal", -2, "tech-2", ["electrical"], "alternator-belt", "Trailer electrical supplies"),
        ("j13", "elise-rowan", "blue-hour", "Cabin AC sea strainer service", "completed", "normal", -51, "tech-2", ["diesel"], "impeller-mercury", "AC circulation impeller"),
        ("j14", "marcus-vail", "running-tide", "VHF antenna and radio check", "scheduled", "low", 15, None, ["electronics"], "fuel-filter", "Antenna mounting hardware"),
        ("j15", "sienna-holt", "second-wind", "Propeller vibration diagnosis", "in_progress", "high", -3, "tech-1", ["outboard"], "zinc-kit", "Propeller hardware and zincs"),
        ("j16", "cortez-charters", "sunset-cruise", "Oil and filter change", "completed", "normal", -17, "tech-1", ["outboard"], "oil-filter", "Oil filter"),
    )
    job_ids: dict[str, uuid.UUID] = {}
    completed_keys = {"j03", "j07", "j09", "j13", "j16"}
    for index, row in enumerate(jobs):
        (
            key,
            customer_key,
            vessel_key,
            title,
            status,
            priority,
            day_offset,
            technician_key,
            skills,
            part_key,
            part_description,
        ) = row
        job_id = demo_id(f"job:{key}")
        job_ids[key] = job_id
        scheduled_at = now + timedelta(days=day_offset, hours=(8 + index % 5))
        started_at = scheduled_at if status in {"in_progress", "completed"} else None
        completed_at = scheduled_at + timedelta(hours=3) if key in completed_keys else None
        upsert(
            connection,
            "jobs",
            {
                "id": job_id,
                "company_id": company_id,
                "customer_id": customer_ids[customer_key],
                "vessel_id": vessel_ids[vessel_key],
                "title": title,
                "description": f"{title}. Confirm condition, document findings, and notify the owner.",
                "status": status,
                "priority": priority,
                "scheduled_at": scheduled_at,
                "scheduled_end_at": scheduled_at + timedelta(hours=3),
                "technician_id": ids[technician_key] if technician_key else None,
                "started_at": started_at,
                "completed_at": completed_at,
                "notes": "Fictional sales-demo work order.",
                "required_skills": skills,
                "dispatch_score": Decimal(str(62 + (index * 2) % 31)),
                "dispatch_score_breakdown": {
                    "urgency": 30 if priority == "urgent" else 18,
                    "revenue": 24,
                    "customer_value": 20,
                },
                "dispatch_scored_at": now - timedelta(hours=index),
                "created_at": now - timedelta(days=58 - index * 3),
                "updated_at": now - timedelta(hours=index),
            },
        )
        labor_id = demo_id(f"job-line:{key}:labor")
        part_id = demo_id(f"job-line:{key}:part")
        labor_hours = Decimal("2.50") if priority in {"high", "urgent"} else Decimal("1.50")
        upsert(
            connection,
            "job_line_items",
            {
                "id": labor_id,
                "company_id": company_id,
                "job_id": job_id,
                "slip_reservation_id": None,
                "kind": "labor",
                "description": "Marine technician labor",
                "inventory_item_id": None,
                "quantity": labor_hours,
                "unit_price": Decimal("145.00"),
                "taxable": False,
                "inventory_committed": False,
                "invoice_id": None,
                "invoiced_at": None,
                "created_at": now - timedelta(days=57 - index * 3),
                "updated_at": now,
            },
        )
        upsert(
            connection,
            "job_line_items",
            {
                "id": part_id,
                "company_id": company_id,
                "job_id": job_id,
                "slip_reservation_id": None,
                "kind": "part",
                "description": part_description,
                "inventory_item_id": inventory_ids[part_key],
                "quantity": Decimal("1.00"),
                "unit_price": (
                    Decimal("219.95") if part_key == "bottom-paint" else Decimal("59.95")
                ),
                "taxable": True,
                "inventory_committed": key in completed_keys,
                "invoice_id": None,
                "invoiced_at": None,
                "created_at": now - timedelta(days=57 - index * 3),
                "updated_at": now,
            },
        )
    return job_ids


def seed_estimates_and_invoices(
    connection: Connection,
    ids: Mapping[str, uuid.UUID],
    customer_ids: Mapping[str, uuid.UUID],
    job_ids: Mapping[str, uuid.UUID],
    now: datetime,
) -> dict[str, uuid.UUID]:
    """Seed estimates and an AR-aging mix of draft, sent, paid, and overdue invoices."""
    company_id = ids["company"]
    estimates = (
        ("e01", "j04", "marcus-vail", "sent", "1125.00", "78.75", "1203.75", None),
        ("e02", "j11", "ava-merrin", "viewed", "785.00", "54.95", "839.95", None),
        ("e03", "j10", "cortez-charters", "approved", "1840.00", "128.80", "1968.80", now - timedelta(days=4)),
        ("e04", "j14", "marcus-vail", "draft", "425.00", "29.75", "454.75", None),
    )
    estimate_ids: dict[str, uuid.UUID] = {}
    for index, (key, job_key, customer_key, status, subtotal, tax, total, approved_at) in enumerate(estimates):
        estimate_id = demo_id(f"estimate:{key}")
        estimate_ids[key] = estimate_id
        upsert(
            connection,
            "estimates",
            {
                "id": estimate_id,
                "company_id": company_id,
                "job_id": job_ids[job_key],
                "customer_id": customer_ids[customer_key],
                "status": status,
                "subtotal": Decimal(subtotal),
                "tax_total": Decimal(tax),
                "total": Decimal(total),
                "balance_due": Decimal("0.00") if status == "approved" else Decimal(total),
                "approved_at": approved_at,
                "created_at": now - timedelta(days=42 - index * 6),
            },
        )
        upsert(
            connection,
            "estimate_line_items",
            {
                "id": demo_id(f"estimate-line:{key}:labor"),
                "estimate_id": estimate_id,
                "inventory_item_id": None,
                "description": "Estimated technician labor and shop supplies",
                "quantity": 1,
                "unit_price": Decimal(subtotal),
            },
        )

    invoices = (
        ("i01", "j03", "elise-rowan", "e01", "paid", "582.50", "40.78", "623.28", -39, -24),
        ("i02", "j07", "leah-barnett", None, "paid", "422.45", "29.57", "452.02", -31, -16),
        ("i03", "j09", "pelican-cove", None, "paid", "478.25", "33.48", "511.73", -24, -10),
        ("i04", "j13", "elise-rowan", None, "sent", "675.00", "47.25", "722.25", -35, -21),
        ("i05", "j16", "cortez-charters", "e03", "sent", "1012.50", "70.88", "1083.38", -14, 1),
        ("i06", "j02", "noah-caldwell", None, "draft", "511.00", "35.77", "546.77", -3, 11),
        ("i07", "j08", "gideon-lane", None, "draft", "790.00", "55.30", "845.30", -1, 13),
        ("i08", "j12", "noah-caldwell", None, "sent", "365.00", "25.55", "390.55", -8, 6),
    )
    invoice_ids: dict[str, uuid.UUID] = {}
    paid_keys = {"i01", "i02", "i03"}
    for index, (
        key,
        job_key,
        customer_key,
        estimate_key,
        status,
        subtotal,
        tax,
        total,
        created_days,
        due_days,
    ) in enumerate(invoices):
        invoice_id = demo_id(f"invoice:{key}")
        invoice_ids[key] = invoice_id
        is_paid = key in paid_keys
        sent_at = now + timedelta(days=created_days + 1) if status in {"sent", "paid"} else None
        paid_at = now + timedelta(days=due_days + 1) if is_paid else None
        upsert(
            connection,
            "invoices",
            {
                "id": invoice_id,
                "company_id": company_id,
                "estimate_id": estimate_ids[estimate_key] if estimate_key else None,
                "customer_id": customer_ids[customer_key],
                "status": status,
                "subtotal": Decimal(subtotal),
                "tax_total": Decimal(tax),
                "total": Decimal(total),
                "amount_paid": Decimal(total) if is_paid else Decimal("0.00"),
                "balance_due": Decimal("0.00") if is_paid else Decimal(total),
                "tax_rate": Decimal("0.0700"),
                "due_date": now + timedelta(days=due_days),
                "sent_at": sent_at,
                "paid_at": paid_at,
                "created_at": now + timedelta(days=created_days),
                "updated_at": now - timedelta(hours=index),
            },
        )
        if is_paid:
            upsert(
                connection,
                "payments",
                {
                    "id": demo_id(f"payment:{key}"),
                    "company_id": company_id,
                    "invoice_id": invoice_id,
                    "status": "succeeded",
                    "amount": Decimal(total),
                    "stripe_charge_id": f"demo_ch_{key}",
                    "stripe_fee": (Decimal(total) * Decimal("0.029")).quantize(Decimal("0.01")),
                    "created_at": paid_at,
                },
            )
        connection.execute(
            text(
                """
                UPDATE job_line_items
                   SET invoice_id = :invoice_id,
                       invoiced_at = :invoiced_at,
                       updated_at = :updated_at
                 WHERE company_id = :company_id
                   AND job_id = :job_id
                """
            ),
            {
                "invoice_id": invoice_id,
                "invoiced_at": sent_at or now,
                "updated_at": now,
                "company_id": company_id,
                "job_id": job_ids[job_key],
            },
        )
    return invoice_ids


def seed_purchase_orders(
    connection: Connection,
    ids: Mapping[str, uuid.UUID],
    inventory_ids: Mapping[str, uuid.UUID],
    now: datetime,
) -> None:
    """Seed a submitted restock PO and a draft purchase order."""
    company_id = ids["company"]
    purchase_orders = (
        ("po01", "vendor:gulf-engine", "submitted", now - timedelta(days=1), None, "Restock low Yamaha service items."),
        ("po02", "vendor:suncoast", "draft", None, None, "Prepare bottom-paint and zinc replenishment."),
    )
    po_ids: dict[str, uuid.UUID] = {}
    for index, (key, vendor_key, status, submitted_at, received_at, notes) in enumerate(purchase_orders):
        po_id = demo_id(f"purchase-order:{key}")
        po_ids[key] = po_id
        upsert(
            connection,
            "purchase_orders",
            {
                "id": po_id,
                "company_id": company_id,
                "vendor_id": inventory_ids[vendor_key],
                "status": status,
                "created_by": ids["owner"],
                "submitted_at": submitted_at,
                "received_at": received_at,
                "notes": notes,
                "created_at": now - timedelta(days=4 - index),
                "updated_at": now,
            },
        )
    lines = (
        ("po01", "impeller-yamaha", 12, 0, "42.00"),
        ("po01", "oil-filter", 24, 0, "11.50"),
        ("po02", "zinc-kit", 20, 0, "28.00"),
        ("po02", "bottom-paint", 8, 0, "138.00"),
    )
    for po_key, item_key, ordered, received, cost in lines:
        upsert(
            connection,
            "purchase_order_line_items",
            {
                "id": demo_id(f"purchase-order-line:{po_key}:{item_key}"),
                "company_id": company_id,
                "purchase_order_id": po_ids[po_key],
                "inventory_item_id": inventory_ids[item_key],
                "quantity_ordered": ordered,
                "quantity_received": received,
                "unit_cost": Decimal(cost),
                "created_at": now - timedelta(days=3),
            },
        )


def seed_slips_and_reservations(
    connection: Connection,
    ids: Mapping[str, uuid.UUID],
    customer_ids: Mapping[str, uuid.UUID],
    vessel_ids: Mapping[str, uuid.UUID],
    now: datetime,
) -> None:
    """Seed a lively wet-slip and dry-stack map with non-overlapping reservations."""
    company_id = ids["company"]
    slips = (
        ("a01", "A-01", "wet_slip", "available", "30.00", "11.00", "6.00", None, None, "950.00", "75.00"),
        ("a03", "A-03", "wet_slip", "occupied", "35.00", "12.00", "7.00", None, None, "1125.00", "90.00"),
        ("a07", "A-07", "wet_slip", "available", "40.00", "13.00", "8.00", None, None, "1350.00", "105.00"),
        ("b02", "B-02", "wet_slip", "reserved", "35.00", "12.00", "7.00", None, None, "1175.00", "95.00"),
        ("b05", "B-05", "wet_slip", "available", "40.00", "14.00", "8.00", None, None, "1450.00", "115.00"),
        ("c01", "C-01", "wet_slip", "maintenance", "30.00", "11.00", "6.00", None, None, "925.00", "72.00"),
        ("ds102", "DS-1-02", "dry_stack", "occupied", "30.00", "10.00", None, 1, "Bay 02", "625.00", "48.00"),
        ("ds201", "DS-2-01", "dry_stack", "reserved", "30.00", "10.00", None, 2, "Bay 01", "650.00", "50.00"),
        ("ds307", "DS-3-07", "dry_stack", "available", "28.00", "9.00", None, 3, "Bay 07", "575.00", "45.00"),
        ("m01", "M-01", "mooring", "available", "45.00", None, "10.00", None, None, "700.00", "55.00"),
    )
    slip_ids: dict[str, uuid.UUID] = {}
    for index, row in enumerate(slips):
        (
            key,
            identifier,
            slip_type,
            status,
            length,
            width,
            depth,
            rack_level,
            rack_position,
            monthly_rate,
            daily_rate,
        ) = row
        slip_id = demo_id(f"slip:{key}")
        slip_ids[key] = slip_id
        upsert(
            connection,
            "slips",
            {
                "id": slip_id,
                "company_id": company_id,
                "identifier": identifier,
                "slip_type": slip_type,
                "status": status,
                "length_ft": Decimal(length),
                "width_ft": Decimal(width) if width else None,
                "depth_ft": Decimal(depth) if depth else None,
                "rack_level": rack_level,
                "rack_position": rack_position,
                "latitude": Decimal("27.336400") + Decimal(index) / Decimal("100000"),
                "longitude": Decimal("-82.530650") - Decimal(index) / Decimal("100000"),
                "monthly_rate": Decimal(monthly_rate),
                "daily_rate": Decimal(daily_rate),
                "notes": "Fictional demo marina inventory.",
                "created_at": now - timedelta(days=50),
                "updated_at": now,
            },
        )
    today = now.date()
    reservations = (
        ("r01", "a03", "noah-caldwell", "salt-life", "checked_in", today - timedelta(days=2), today + timedelta(days=5), now - timedelta(days=2), None, None),
        ("r02", "b02", "elise-rowan", "blue-hour", "confirmed", today + timedelta(days=7), today + timedelta(days=14), None, None, None),
        ("r03", "ds102", "sienna-holt", "second-wind", "checked_out", today - timedelta(days=16), today - timedelta(days=4), now - timedelta(days=16), now - timedelta(days=4), None),
        ("r04", "ds201", "ava-merrin", "watermark", "pending", today + timedelta(days=20), today + timedelta(days=50), None, None, None),
    )
    for key, slip_key, customer_key, vessel_key, status, start, end, checked_in, checked_out, cancelled in reservations:
        upsert(
            connection,
            "slip_reservations",
            {
                "id": demo_id(f"reservation:{key}"),
                "company_id": company_id,
                "slip_id": slip_ids[slip_key],
                "customer_id": customer_ids[customer_key],
                "vessel_id": vessel_ids[vessel_key],
                "status": status,
                "start_date": start,
                "end_date": end,
                "checked_in_at": checked_in,
                "checked_out_at": checked_out,
                "cancelled_at": cancelled,
                "notes": "Fictional demo reservation.",
                "created_at": now - timedelta(days=18),
                "updated_at": now,
            },
        )


def seed_messages(
    connection: Connection,
    ids: Mapping[str, uuid.UUID],
    customer_ids: Mapping[str, uuid.UUID],
    job_ids: Mapping[str, uuid.UUID],
    now: datetime,
) -> None:
    """Put a customer conversation in the portal inbox."""
    company_id = ids["company"]
    messages = (
        ("m01", "noah-caldwell", "j02", "customer", None, "Hi team — is Salt Life still on track for pickup Friday?", now - timedelta(hours=20), None),
        ("m02", "noah-caldwell", "j02", "staff", "office", "Yes. Luis is finishing the cooling-system inspection this afternoon.", now - timedelta(hours=18), now - timedelta(hours=17)),
        ("m03", "noah-caldwell", "j02", "customer", None, "Perfect, thank you. Please text me when she is ready.", now - timedelta(hours=17), None),
    )
    for key, customer_key, job_key, sender_type, sender_key, body, created_at, read_at in messages:
        upsert(
            connection,
            "messages",
            {
                "id": demo_id(f"message:{key}"),
                "company_id": company_id,
                "customer_id": customer_ids[customer_key],
                "job_id": job_ids[job_key],
                "sender_type": sender_type,
                "sender_user_id": ids[sender_key] if sender_key else None,
                "body": body,
                "channel": "portal",
                "created_at": created_at,
                "read_at": read_at,
            },
        )


def count_rows(connection: Connection, company_id: uuid.UUID) -> dict[str, int]:
    """Return the seeded entity counts, including estimate lines via their parent."""
    counts: dict[str, int] = {}
    for table in EXPECTED_COUNTS:
        if table == "estimate_line_items":
            continue
        counts[table] = int(
            connection.execute(
                text(f"SELECT count(*) FROM {table} WHERE company_id = :company_id"),
                {"company_id": company_id},
            ).scalar_one()
        )
    return counts


def assert_expected_counts(counts: Mapping[str, int]) -> None:
    """Fail visibly if a partial seed silently produced the wrong demo shape."""
    mismatches = {
        table: (EXPECTED_COUNTS[table], actual)
        for table, actual in counts.items()
        if actual != EXPECTED_COUNTS[table]
    }
    if mismatches:
        raise RuntimeError(f"Demo seed count mismatch: {mismatches}")


def print_credentials() -> None:
    """Print the exact logins promised in the demo brief."""
    print("\nHarborIQ demo seed completed.")
    print(f"Demo URL: {DEMO_URL}")
    print(f"Company: {DEMO_COMPANY_NAME}")
    print(f"Shared password: {DEMO_PASSWORD}")
    print("Logins:")
    print("  Owner/admin: demo@harboriq.app")
    print("  Office:      office@gulfcoastmarine.demo")
    print("  Tech:        tech1@gulfcoastmarine.demo")
    print("  Tech:        tech2@gulfcoastmarine.demo")


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reset", action="store_true", help="wipe and recreate the demo tenant")
    parser.add_argument(
        "--i-know-what-im-doing",
        action="store_true",
        help="override the APP_ENV development/staging safety guard",
    )
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> None:
    args = parse_args(argv)
    ensure_safe_environment(args.i_know_what_im_doing)
    now = utc_now()
    engine = service_engine()
    try:
        with engine.begin() as connection:
            reset_if_requested(connection, args.reset)
            ids = seed_company_and_users(connection, now)
            customer_ids, vessel_ids = seed_customers_and_vessels(connection, ids, now)
            inventory_ids = seed_vendors_and_inventory(connection, ids, now)
            job_ids = seed_jobs(connection, ids, customer_ids, vessel_ids, inventory_ids, now)
            seed_estimates_and_invoices(connection, ids, customer_ids, job_ids, now)
            seed_purchase_orders(connection, ids, inventory_ids, now)
            seed_slips_and_reservations(connection, ids, customer_ids, vessel_ids, now)
            seed_messages(connection, ids, customer_ids, job_ids, now)
            counts = count_rows(connection, ids["company"])
            assert_expected_counts(counts)
    finally:
        engine.dispose()
    print("Seeded counts: " + ", ".join(f"{table}={count}" for table, count in counts.items()))
    print_credentials()


if __name__ == "__main__":
    main()
