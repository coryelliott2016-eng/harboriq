"""Customer <-> staff messaging (Phase 9, migration 0008).

One thread per `(company_id, customer_id)`, optionally further split by
`job_id` (a message can be general or job-specific — see
`app.db.models.Message`). Every read/write here is scoped by BOTH
`company_id` (RLS, via `tenant_context`) AND `customer_id` (explicit filter
in the SQL) so that within one tenant, Customer A's thread never leaks into
Customer B's — the same customer-isolation discipline as
`app.services.portal`.

Notifications reuse the existing outbox pattern (`app.services.outbox`) —
no new delivery mechanism. A new customer message enqueues
`message.new_from_customer` (staff gets pinged); a new staff reply enqueues
`message.new_from_staff` (customer gets pinged), best-effort, exactly like
every other outbox email.
"""
from __future__ import annotations

import uuid

from sqlalchemy import Row, text
from sqlalchemy.orm import Session

from app.db.tenant import tenant_context
from app.services import outbox
from app.services.crud import NotFound


def _office_recipients(db: Session, company_id: uuid.UUID) -> list[str]:
    """Owner/admin/office emails — who gets pinged about a new customer
    message. Technicians are excluded; messaging is front-desk work, same
    role split as the rest of the customer book (`UserRole` docstring)."""
    rows = db.execute(
        text(
            """
            SELECT email FROM users
             WHERE company_id = :cid AND is_active = true
               AND role IN ('owner', 'admin', 'office')
            """
        ),
        {"cid": company_id},
    ).all()
    return [r.email for r in rows]


def _customer_row(db: Session, customer_id: uuid.UUID):
    return db.execute(
        text("SELECT * FROM customers WHERE id = :id"), {"id": customer_id}
    ).first()


def send_from_customer(
    db: Session,
    company_id: uuid.UUID,
    customer_id: uuid.UUID,
    body: str,
    job_id: uuid.UUID | None = None,
    channel: str = "portal",
) -> Row:
    """A customer sends a message through their portal session, or (Phase
    11, `channel="sms"`) via a text the inbound SMS webhook matched to them.

    Notifies office staff via the outbox (best-effort — a notification
    failure never blocks the message itself from being stored).
    """
    with tenant_context(db, company_id):
        customer = _customer_row(db, customer_id)
        if customer is None:
            raise NotFound(f"customer {customer_id} not found")

        if job_id is not None:
            job = db.execute(
                text("SELECT id FROM jobs WHERE id = :id AND customer_id = :cid"),
                {"id": job_id, "cid": customer_id},
            ).first()
            if job is None:
                raise NotFound(f"job {job_id} not found for this customer")

        row = db.execute(
            text(
                """
                INSERT INTO messages (company_id, customer_id, job_id, sender_type, body, channel)
                VALUES (:cid, :cust, :job_id, 'customer', :body, :channel)
                RETURNING *
                """
            ),
            {
                "cid": company_id,
                "cust": customer_id,
                "job_id": job_id,
                "body": body,
                "channel": channel,
            },
        ).first()

        recipients = _office_recipients(db, company_id)
        customer_label = (
            customer.company_name
            or " ".join(filter(None, [customer.first_name, customer.last_name]))
            or "A customer"
        )
        for to in recipients:
            outbox.enqueue(
                db,
                company_id,
                "message.new_from_customer",
                {
                    "to": to,
                    "customer_id": str(customer_id),
                    "customer_label": customer_label,
                    "job_id": str(job_id) if job_id else None,
                    "body": body,
                },
            )
        db.commit()
    return row


def send_from_staff(
    db: Session,
    company_id: uuid.UUID,
    customer_id: uuid.UUID,
    sender_user_id: uuid.UUID,
    body: str,
    job_id: uuid.UUID | None = None,
) -> Row:
    """Office staff reply to a customer's thread.

    Notification channel (Phase 11): SMS if the customer's most recent
    inbound message arrived via SMS and they have a phone number on file
    (they clearly prefer texting, and the reply belongs in the same
    conversation they are already having with the shop) and they have not
    opted out (`sms_opted_out`); otherwise email if they have one on file,
    matching the pre-Phase-11 behavior exactly."""
    with tenant_context(db, company_id):
        customer = _customer_row(db, customer_id)
        if customer is None:
            raise NotFound(f"customer {customer_id} not found")

        if job_id is not None:
            job = db.execute(
                text("SELECT id FROM jobs WHERE id = :id AND customer_id = :cid"),
                {"id": job_id, "cid": customer_id},
            ).first()
            if job is None:
                raise NotFound(f"job {job_id} not found for this customer")

        # Last inbound channel decides where this reply's notification
        # goes — checked BEFORE inserting this new (staff/outbound) row so
        # it reflects the customer's most recent message to US, not this
        # one we are about to write.
        last_inbound = db.execute(
            text(
                """
                SELECT channel FROM messages
                 WHERE customer_id = :cid AND sender_type = 'customer'
                 ORDER BY created_at DESC
                 LIMIT 1
                """
            ),
            {"cid": customer_id},
        ).first()
        prefers_sms = bool(
            last_inbound
            and last_inbound.channel == "sms"
            and customer.phone
            and not customer.sms_opted_out
        )

        row = db.execute(
            text(
                """
                INSERT INTO messages
                    (company_id, customer_id, job_id, sender_type, sender_user_id, body, channel)
                VALUES (:cid, :cust, :job_id, 'staff', :uid, :body, :channel)
                RETURNING *
                """
            ),
            {
                "cid": company_id,
                "cust": customer_id,
                "job_id": job_id,
                "uid": sender_user_id,
                "body": body,
                "channel": "sms" if prefers_sms else "portal",
            },
        ).first()

        if prefers_sms:
            outbox.enqueue(
                db,
                company_id,
                "sms.send",
                {"to": customer.phone, "body": body},
            )
        elif customer.email:
            outbox.enqueue(
                db,
                company_id,
                "message.new_from_staff",
                {
                    "to": customer.email,
                    "job_id": str(job_id) if job_id else None,
                    "body": body,
                },
            )
        db.commit()
    return row


def list_for_customer(
    db: Session,
    company_id: uuid.UUID,
    customer_id: uuid.UUID,
    job_id: uuid.UUID | None = None,
) -> list[Row]:
    """A single customer's own thread (portal view), oldest first."""
    clause = "AND job_id = :job_id" if job_id is not None else ""
    with tenant_context(db, company_id):
        return list(
            db.execute(
                text(
                    f"""
                    SELECT * FROM messages
                     WHERE customer_id = :cid {clause}
                     ORDER BY created_at ASC
                    """
                ),
                {"cid": customer_id, "job_id": job_id},
            ).all()
        )


def list_for_job(db: Session, company_id: uuid.UUID, job_id: uuid.UUID) -> list[Row]:
    """Staff view: every message on one job, across customer/staff senders."""
    with tenant_context(db, company_id):
        job = db.execute(text("SELECT id FROM jobs WHERE id = :id"), {"id": job_id}).first()
        if job is None:
            raise NotFound(f"job {job_id} not found")
        return list(
            db.execute(
                text(
                    """
                    SELECT * FROM messages WHERE job_id = :job_id ORDER BY created_at ASC
                    """
                ),
                {"job_id": job_id},
            ).all()
        )


def list_all_for_company(
    db: Session, company_id: uuid.UUID, unread_only: bool = False
) -> list[Row]:
    """Staff inbox: every thread in the tenant, newest first. `unread_only`
    narrows to customer-authored messages no staff member has read yet."""
    clause = "AND read_at IS NULL AND sender_type = 'customer'" if unread_only else ""
    with tenant_context(db, company_id):
        return list(
            db.execute(
                text(
                    f"""
                    SELECT m.*, c.first_name, c.last_name, c.company_name
                      FROM messages m
                      JOIN customers c ON c.id = m.customer_id
                     WHERE true {clause}
                     ORDER BY m.created_at DESC
                    """
                ),
                {},
            ).all()
        )


def mark_read(db: Session, company_id: uuid.UUID, message_id: uuid.UUID) -> Row:
    """Staff has viewed a customer message."""
    with tenant_context(db, company_id):
        row = db.execute(
            text(
                """
                UPDATE messages SET read_at = now()
                 WHERE id = :id AND read_at IS NULL
                RETURNING *
                """
            ),
            {"id": message_id},
        ).first()
        if row is None:
            row = db.execute(
                text("SELECT * FROM messages WHERE id = :id"), {"id": message_id}
            ).first()
            if row is None:
                db.rollback()
                raise NotFound(f"message {message_id} not found")
        db.commit()
    return row
