"""
Gmail Invoice Client — BONDA OS
================================

Reads invoice emails from rogeradrian@gmail.com via IMAP and forwards them to
facturacion@steviabonda.com.mx via SMTP, attaching a fiscal data block so the
counterpart can issue a CFDI.

Authentication: Gmail App Password (16 chars, generated at
myaccount.google.com → Security → App Passwords). NO Google Cloud Project
required.

Idempotency: messages are tagged with the Gmail label "📄 Facturas/Procesado"
via the X-GM-LABELS IMAP extension, and excluded from future searches.

Dependencies: Python 3.8+ standard library only.
"""

from __future__ import annotations

import email
import email.policy
import imaplib
import logging
import re
import smtplib
from datetime import date
from email.message import EmailMessage
from email.parser import BytesParser

logger = logging.getLogger(__name__)

IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465

PROCESSED_LABEL = "📄 Facturas/Procesado"


def _sanitize_app_password(pw: str) -> str:
    """Google App Passwords are shown with spaces ('abcd efgh ijkl mnop').
    The actual password is 16 characters without spaces."""
    return pw.replace(" ", "").strip()


class GmailInvoiceClient:
    """Context-managed IMAP+SMTP client for the BONDA invoice pipeline.

    Usage:
        with GmailInvoiceClient(user, app_password) as client:
            client.ensure_processed_label()
            uids = client.search_invoices(senders, since_date)
            for uid in uids:
                msg = client.fetch_message(uid)
                client.send_forward(...)
                client.mark_processed(uid)
    """

    def __init__(self, user: str, app_password: str):
        self.user = user
        self.app_password = _sanitize_app_password(app_password)
        self._imap: imaplib.IMAP4_SSL | None = None

    # ------------------------------------------------------------------ #
    # Context manager
    # ------------------------------------------------------------------ #

    def __enter__(self) -> "GmailInvoiceClient":
        logger.info(f"Connecting to {IMAP_HOST}:{IMAP_PORT} as {self.user}")
        self._imap = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
        try:
            self._imap.login(self.user, self.app_password)
        except imaplib.IMAP4.error as e:
            raise RuntimeError(
                f"IMAP login failed for {self.user}. "
                f"Check the App Password is correct and 2FA is enabled. Root cause: {e}"
            ) from e
        self._imap.select("INBOX")
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._imap is not None:
            try:
                self._imap.close()
            except Exception:
                pass
            try:
                self._imap.logout()
            except Exception:
                pass
            self._imap = None

    # ------------------------------------------------------------------ #
    # Label management
    # ------------------------------------------------------------------ #

    def ensure_processed_label(self) -> None:
        """Create the nested Gmail label if it does not yet exist.

        Gmail's IMAP implementation auto-creates nested labels when the path
        contains '/'. The CREATE call returns NO if the label already exists,
        which is fine.
        """
        assert self._imap is not None
        label_quoted = f'"{PROCESSED_LABEL}"'
        typ, data = self._imap.create(label_quoted)
        if typ == "OK":
            logger.info(f"Created Gmail label: {PROCESSED_LABEL}")
        else:
            # Most likely "[ALREADYEXISTS]" — fine
            logger.debug(f"CREATE label returned {typ}: {data!r} (likely already exists)")

    # ------------------------------------------------------------------ #
    # Search
    # ------------------------------------------------------------------ #

    def search_invoices(self, senders: list[str], since: date) -> list[bytes]:
        """Search the inbox for invoice candidates.

        Uses Gmail's X-GM-RAW IMAP extension to leverage native Gmail search:
            from:(a@x OR b@y) after:YYYY/MM/DD -label:"📄 Facturas/Procesado"

        Returns:
            List of UIDs (bytes) ordered as Gmail returns them.
        """
        assert self._imap is not None
        if not senders:
            raise ValueError("senders must be a non-empty list")
        from_clause = " OR ".join(f"from:({s})" for s in senders)
        date_str = since.strftime("%Y/%m/%d")
        query = f'({from_clause}) after:{date_str} -label:"{PROCESSED_LABEL}"'
        logger.info(f"Gmail search query: {query}")
        typ, data = self._imap.uid("SEARCH", "X-GM-RAW", f'"{query}"')
        if typ != "OK":
            raise RuntimeError(f"IMAP search failed: typ={typ} data={data!r}")
        if not data or not data[0]:
            return []
        return data[0].split()

    # ------------------------------------------------------------------ #
    # Fetch
    # ------------------------------------------------------------------ #

    def fetch_message(self, uid: bytes) -> email.message.EmailMessage:
        """Fetch and parse a single message by UID. Uses BODY.PEEK so the
        message is not marked as seen."""
        assert self._imap is not None
        typ, data = self._imap.uid("FETCH", uid, "(BODY.PEEK[])")
        if typ != "OK" or not data or not data[0]:
            raise RuntimeError(f"Failed to fetch UID {uid!r}: typ={typ} data={data!r}")
        # data[0] is a tuple (b'1 (BODY[] {nnnn}', b'<raw bytes>')
        raw = data[0][1]
        return BytesParser(policy=email.policy.default).parsebytes(raw)

    # ------------------------------------------------------------------ #
    # Idempotency
    # ------------------------------------------------------------------ #

    def mark_processed(self, uid: bytes) -> None:
        """Apply the Procesado label so the message is excluded from future runs."""
        assert self._imap is not None
        typ, data = self._imap.uid(
            "STORE", uid, "+X-GM-LABELS", f'"{PROCESSED_LABEL}"'
        )
        if typ != "OK":
            raise RuntimeError(f"Failed to label UID {uid!r}: {data!r}")
        logger.info(f"Labeled UID {uid.decode()} → {PROCESSED_LABEL}")

    # ------------------------------------------------------------------ #
    # Send
    # ------------------------------------------------------------------ #

    def send_forward(
        self,
        to_addr: str,
        subject: str,
        body: str,
        attachments: list[tuple[str, str, bytes]],
    ) -> None:
        """Send a new email via SMTP with PDF attachments.

        Args:
            to_addr: destination email
            subject: subject line
            body: plain text body
            attachments: list of (filename, mime_type, content_bytes) tuples
        """
        msg = EmailMessage()
        msg["From"] = self.user
        msg["To"] = to_addr
        msg["Subject"] = subject
        msg.set_content(body)
        for fname, mime, data in attachments:
            maintype, _, subtype = mime.partition("/")
            if not maintype:
                maintype, subtype = "application", "octet-stream"
            if not subtype:
                subtype = "octet-stream"
            msg.add_attachment(
                data,
                maintype=maintype,
                subtype=subtype,
                filename=fname,
            )

        logger.info(f"Sending via {SMTP_HOST}:{SMTP_PORT} → {to_addr}")
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as smtp:
            smtp.login(self.user, self.app_password)
            smtp.send_message(msg)
        logger.info(f"Forwarded: {subject}")


# ---------------------------------------------------------------------- #
# Helpers (module-level pure functions)
# ---------------------------------------------------------------------- #


def extract_attachments(
    msg: email.message.EmailMessage,
) -> list[tuple[str, str, bytes]]:
    """Extract every part with Content-Disposition: attachment.

    Returns:
        List of (filename, mime_type, content_bytes) tuples. Inline images
        and the body parts are excluded.
    """
    out: list[tuple[str, str, bytes]] = []
    for part in msg.walk():
        if part.get_content_disposition() != "attachment":
            continue
        fname = part.get_filename() or "attachment.bin"
        mime = part.get_content_type() or "application/octet-stream"
        try:
            payload = part.get_payload(decode=True)
        except Exception as e:
            logger.warning(f"Failed to decode attachment {fname}: {e}")
            continue
        if payload:
            out.append((fname, mime, payload))
    return out


def extract_body_text(msg: email.message.EmailMessage) -> str:
    """Best-effort plain-text body extraction.

    Order:
        1. First text/plain non-attachment part
        2. First text/html non-attachment part, with tags stripped
        3. Empty string
    """
    if msg.is_multipart():
        for part in msg.walk():
            if (
                part.get_content_type() == "text/plain"
                and part.get_content_disposition() != "attachment"
            ):
                try:
                    return part.get_content()
                except Exception:
                    continue
        for part in msg.walk():
            if (
                part.get_content_type() == "text/html"
                and part.get_content_disposition() != "attachment"
            ):
                try:
                    html = part.get_content()
                    return _strip_html(html)
                except Exception:
                    continue
    else:
        try:
            content = msg.get_content()
            if msg.get_content_type() == "text/html":
                return _strip_html(content)
            return content
        except Exception:
            return ""
    return ""


def _strip_html(html: str) -> str:
    """Crude HTML → text conversion. Good enough for invoice bodies."""
    text = re.sub(r"<(script|style)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    # collapse whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()
