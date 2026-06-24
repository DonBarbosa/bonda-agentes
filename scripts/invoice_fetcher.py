"""
BONDA OS — Invoice Fetcher
==========================

Pulls invoice emails from rogeradrian@gmail.com and forwards them to
facturacion@steviabonda.com.mx with the BONDA fiscal data block, so the
counterpart can issue the CFDI.

Run:
    # Dry run first — see what would happen, no emails sent
    python scripts/invoice_fetcher.py --since 2026-06-01 --dry-run

    # Live run — full month of June
    python scripts/invoice_fetcher.py --since 2026-06-01

    # Anthropic only (most conservative)
    python scripts/invoice_fetcher.py --since 2026-06-01 --senders anthropic

Required environment variables (in .env or shell):
    BONDA_GMAIL_USER             rogeradrian@gmail.com
    BONDA_GMAIL_APP_PASSWORD     16-char Gmail App Password
    BONDA_FACTURACION_EMAIL      facturacion@steviabonda.com.mx  (default)

Optional fiscal data overrides (defaults below):
    BONDA_FISCAL_NAME            BONDA ALIMENTOS SANOS
    BONDA_FISCAL_RFC             BAS2112142V6
    BONDA_FISCAL_ADDRESS         Encino #1385-A, Col. del Fresno, Guadalajara...
    BONDA_FISCAL_CP              (empty — Roger should fill)
    BONDA_FISCAL_REGIME          (empty — Roger should fill)
    BONDA_FISCAL_CFDI_USE        G03

Idempotency: processed emails get the Gmail label "📄 Facturas/Procesado"
and are skipped on subsequent runs.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path

# Allow running as a script from the project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.integrations.gmail_invoice_client import (  # noqa: E402
    GmailInvoiceClient,
    extract_attachments,
    extract_body_text,
)

# ---------------------------------------------------------------------- #
# Configuration from environment
# ---------------------------------------------------------------------- #


def _required(name: str) -> str:
    val = os.environ.get(name)
    if not val:
        print(f"ERROR: env var {name} is not set", file=sys.stderr)
        sys.exit(2)
    return val


GMAIL_USER = _required("BONDA_GMAIL_USER")
GMAIL_APP_PASSWORD = _required("BONDA_GMAIL_APP_PASSWORD")
FACTURACION_EMAIL = os.environ.get(
    "BONDA_FACTURACION_EMAIL", "facturacion@steviabonda.com.mx"
)

FISCAL_NAME = os.environ.get("BONDA_FISCAL_NAME", "BONDA ALIMENTOS SANOS")
FISCAL_RFC = os.environ.get("BONDA_FISCAL_RFC", "BAS2112142V6")
FISCAL_ADDRESS = os.environ.get(
    "BONDA_FISCAL_ADDRESS",
    "Encino #1385-A, Col. del Fresno, Guadalajara, Jalisco, México",
)
FISCAL_CP = os.environ.get("BONDA_FISCAL_CP", "")  # Roger to confirm
FISCAL_REGIME = os.environ.get("BONDA_FISCAL_REGIME", "")  # Roger to confirm
FISCAL_CFDI_USE = os.environ.get("BONDA_FISCAL_CFDI_USE", "G03")

# ---------------------------------------------------------------------- #
# Sender lists
# ---------------------------------------------------------------------- #

SENDERS_ALL = [
    "invoice+statements@mail.anthropic.com",
    "billing@openai.com",
    "receipts@perplexity.ai",
    "noreply@semrush.com",
]
SENDERS_ANTHROPIC_ONLY = ["invoice+statements@mail.anthropic.com"]

# ---------------------------------------------------------------------- #
# Logging
# ---------------------------------------------------------------------- #

LOG_DIR = Path(os.environ.get("BONDA_LOG_DIR", str(Path.home() / ".bonda" / "logs")))
LOG_DIR.mkdir(parents=True, exist_ok=True)
RUN_TS = datetime.now().strftime("%Y%m%d_%H%M%S")
LOG_FILE = LOG_DIR / f"invoice_fetcher_{RUN_TS}.log"
SUMMARY_FILE = LOG_DIR / f"invoice_summary_{RUN_TS}.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s | %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("invoice_fetcher")


# ---------------------------------------------------------------------- #
# Email composition
# ---------------------------------------------------------------------- #


def build_fiscal_block() -> str:
    cp_line = f"Código Postal:    {FISCAL_CP}" if FISCAL_CP else "Código Postal:    (pendiente confirmar)"
    regime_line = (
        f"Régimen Fiscal:   {FISCAL_REGIME}"
        if FISCAL_REGIME
        else "Régimen Fiscal:   (pendiente confirmar)"
    )
    return f"""
══════════════════════════════════════════════════
DATOS FISCALES — SOLICITUD DE CFDI
══════════════════════════════════════════════════

Razón Social:     {FISCAL_NAME}
RFC:              {FISCAL_RFC}
Domicilio Fiscal: {FISCAL_ADDRESS}
{cp_line}
{regime_line}
Uso CFDI:         {FISCAL_CFDI_USE}
Email para CFDI:  {FACTURACION_EMAIL}

══════════════════════════════════════════════════

Por favor emitir CFDI con los datos arriba indicados y enviarlo a
{FACTURACION_EMAIL}.

Recibo/factura original adjunto en este correo.

— Generado por BONDA OS · Invoice Fetcher
"""


def build_forward_subject(original_subject: str) -> str:
    prefix = "[BONDA CFDI]"
    if original_subject.startswith(prefix):
        return original_subject
    return f"{prefix} {original_subject}"


def build_forward_body(original_msg, original_body_text: str) -> str:
    from_h = original_msg.get("From", "(unknown)")
    date_h = original_msg.get("Date", "(unknown)")
    subj_h = original_msg.get("Subject", "(unknown)")
    return f"""{build_fiscal_block()}

──────────────────────────────────────────────────
ORIGINAL EMAIL FORWARDED
──────────────────────────────────────────────────
From:    {from_h}
Date:    {date_h}
Subject: {subj_h}
──────────────────────────────────────────────────

{original_body_text}
"""


# ---------------------------------------------------------------------- #
# Main
# ---------------------------------------------------------------------- #


def main() -> int:
    parser = argparse.ArgumentParser(
        description="BONDA Invoice Fetcher — forwards invoices to facturacion@",
    )
    parser.add_argument(
        "--since",
        type=str,
        required=True,
        help="ISO date YYYY-MM-DD: search for messages received after this date",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't actually send emails or label. Logs what would happen.",
    )
    parser.add_argument(
        "--senders",
        choices=["all", "anthropic"],
        default="all",
        help="all = anthropic+openai+perplexity+semrush · anthropic = only Anthropic",
    )
    args = parser.parse_args()

    try:
        since_date = date.fromisoformat(args.since)
    except ValueError:
        print(f"ERROR: --since must be ISO date YYYY-MM-DD, got {args.since!r}",
              file=sys.stderr)
        return 2

    senders = SENDERS_ANTHROPIC_ONLY if args.senders == "anthropic" else SENDERS_ALL

    logger.info("=" * 70)
    logger.info("BONDA OS — Invoice Fetcher")
    logger.info("=" * 70)
    logger.info(f"User:         {GMAIL_USER}")
    logger.info(f"Since:        {since_date.isoformat()}")
    logger.info(f"Senders:      {senders}")
    logger.info(f"Forward to:   {FACTURACION_EMAIL}")
    logger.info(f"Fiscal RFC:   {FISCAL_RFC}")
    logger.info(f"Dry run:      {args.dry_run}")
    logger.info(f"Log file:     {LOG_FILE}")
    logger.info(f"Summary file: {SUMMARY_FILE}")
    logger.info("=" * 70)

    processed_count = 0
    skipped_no_pdf = 0
    errors = 0
    summary: list[dict] = []
    uids: list[bytes] = []

    try:
        with GmailInvoiceClient(GMAIL_USER, GMAIL_APP_PASSWORD) as client:
            if not args.dry_run:
                client.ensure_processed_label()

            uids = client.search_invoices(senders, since_date)
            logger.info(f"Found {len(uids)} candidate messages")

            for uid in uids:
                uid_str = uid.decode()
                try:
                    msg = client.fetch_message(uid)
                    subject = msg.get("Subject", "(no subject)")
                    from_addr = msg.get("From", "(unknown)")
                    date_h = msg.get("Date", "(unknown)")
                    logger.info(
                        f"[UID {uid_str}] {date_h} | {from_addr} | {subject}"
                    )

                    attachments = extract_attachments(msg)
                    pdf_attachments = [
                        a
                        for a in attachments
                        if a[1] == "application/pdf"
                        or a[0].lower().endswith(".pdf")
                    ]

                    if not pdf_attachments:
                        logger.warning(
                            f"[UID {uid_str}] No PDF attachments — skipping"
                        )
                        skipped_no_pdf += 1
                        summary.append({
                            "uid": uid_str,
                            "from": from_addr,
                            "subject": subject,
                            "date": date_h,
                            "status": "skipped_no_pdf",
                        })
                        continue

                    body_text = extract_body_text(msg)
                    fwd_subject = build_forward_subject(subject)
                    fwd_body = build_forward_body(msg, body_text)

                    if args.dry_run:
                        logger.info(
                            f"[UID {uid_str}] DRY-RUN — would forward "
                            f"{len(pdf_attachments)} PDF(s): "
                            f"{[a[0] for a in pdf_attachments]}"
                        )
                        summary.append({
                            "uid": uid_str,
                            "from": from_addr,
                            "subject": subject,
                            "date": date_h,
                            "status": "dry_run",
                            "pdf_count": len(pdf_attachments),
                            "pdf_names": [a[0] for a in pdf_attachments],
                        })
                        continue

                    client.send_forward(
                        FACTURACION_EMAIL, fwd_subject, fwd_body, pdf_attachments
                    )
                    client.mark_processed(uid)
                    processed_count += 1
                    summary.append({
                        "uid": uid_str,
                        "from": from_addr,
                        "subject": subject,
                        "date": date_h,
                        "status": "forwarded",
                        "pdf_count": len(pdf_attachments),
                        "pdf_names": [a[0] for a in pdf_attachments],
                    })
                except Exception as e:
                    logger.exception(f"[UID {uid_str}] FAILED: {e}")
                    errors += 1
                    summary.append({
                        "uid": uid_str,
                        "status": "error",
                        "error": str(e),
                    })
    except RuntimeError as e:
        logger.error(f"Fatal: {e}")
        return 3

    # Write summary
    SUMMARY_FILE.write_text(
        json.dumps(
            {
                "run_at": datetime.now().isoformat(),
                "since": since_date.isoformat(),
                "senders": senders,
                "dry_run": args.dry_run,
                "totals": {
                    "found": len(uids),
                    "forwarded": processed_count,
                    "skipped_no_pdf": skipped_no_pdf,
                    "errors": errors,
                },
                "items": summary,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    logger.info("=" * 70)
    logger.info(
        f"DONE | Found: {len(uids)} | Forwarded: {processed_count} | "
        f"Skipped (no PDF): {skipped_no_pdf} | Errors: {errors}"
    )
    logger.info(f"Summary: {SUMMARY_FILE}")
    logger.info("=" * 70)

    return 1 if errors > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
