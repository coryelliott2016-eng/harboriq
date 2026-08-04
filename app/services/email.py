"""Outbound email transport — SMTP when configured, console fallback in dev.

Mirrors the exact graceful-degrade pattern `app/services/stripe_billing.py`
already uses for Stripe: a missing/unset transport is a degraded dev
experience, not a reason to fail the request that queued the email. The
outbox (`app/services/outbox.py`) exists precisely so a transport failure
here never rolls back the business transaction that already committed.
"""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from app.core.config import settings

#: (filename, bytes, mime_subtype) e.g. ("invoice.pdf", b"...", "pdf").
Attachment = tuple[str, bytes, str]

logger = logging.getLogger("harboriq.email")

#: How much of the body to show in the console-fallback / error log line.
_LOG_BODY_TRUNCATE = 200


def send_email(
    to: str,
    subject: str,
    text_body: str,
    html_body: str | None = None,
    attachments: list[Attachment] | None = None,
) -> bool:
    """Send one email. Returns True on success (including console fallback).

    * `smtp_host` empty (the dev default) -> "console transport": log the
      email at INFO level and return True. Nothing is actually sent, which is
      fine for local development — the outbox row still gets marked
      dispatched, and a developer can read the link straight out of the logs.
    * `smtp_host` set -> connect via smtplib and actually send. Any SMTP or
      network failure is caught and logged, never raised — the caller
      (`outbox.dispatch_pending`) decides how to retry; email delivery must
      never raise into a request path that already committed its DB write.

    `attachments` (Phase 8): optional list of `(filename, bytes, mime_subtype)`
    tuples, e.g. `("invoice.pdf", pdf_bytes, "pdf")` for the invoice-send PDF.
    Purely additive — omitted/`None` behaves exactly as before this phase.
    """
    if not settings.smtp_host:
        logger.info(
            "console-transport email to=%s subject=%r body=%r attachments=%s",
            to,
            subject,
            text_body[:_LOG_BODY_TRUNCATE],
            [name for name, _, _ in (attachments or [])],
        )
        return True

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.email_from_address
    message["To"] = to
    message.set_content(text_body)
    if html_body:
        message.add_alternative(html_body, subtype="html")
    for filename, content, mime_subtype in attachments or []:
        message.add_attachment(
            content, maintype="application", subtype=mime_subtype, filename=filename
        )

    try:
        if settings.smtp_port == 465:
            # Implicit TLS from connection open (as opposed to STARTTLS).
            with smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
                _authenticate_and_send(smtp, message)
        else:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as smtp:
                if settings.smtp_use_tls:
                    smtp.starttls()
                _authenticate_and_send(smtp, message)
    except (smtplib.SMTPException, OSError) as exc:
        logger.error(
            "SMTP send failed to=%s subject=%r error=%s", to, subject, exc
        )
        return False

    return True


def _authenticate_and_send(smtp: smtplib.SMTP, message: EmailMessage) -> None:
    if settings.smtp_username:
        smtp.login(settings.smtp_username, settings.smtp_password)
    smtp.send_message(message)
