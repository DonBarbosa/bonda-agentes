# BONDA OS — Invoice Watcher

Pulls invoice emails from `rogeradrian@gmail.com` and forwards them to
`facturacion@steviabonda.com.mx` with the BONDA fiscal data block so the
counterpart can issue the CFDI.

**No Google Cloud Project. No OAuth flow. No Make.com.** Pure Python stdlib.

---

## Files

```
bonda-invoice-watcher/
├── README.md                                    ← this file
├── .env.example                                 ← env template
├── app/integrations/gmail_invoice_client.py     ← IMAP+SMTP client
└── scripts/invoice_fetcher.py                   ← orchestrator
```

Drop the two Python files into the corresponding folders of BONDA OS.
The structure mirrors the existing `app/integrations/ml_client.py` and
`scripts/ml_snapshot.py` from Marco 13.

---

## Setup (one-time, ~3 minutes)

### 1. Generate Gmail App Password

1. Go to <https://myaccount.google.com>
2. Security → **2-Step Verification** (must be enabled)
3. Scroll to bottom → **App passwords**
4. Select app: **Mail**
5. Select device: **Other (custom name)** → name it `BONDA OS Invoice Watcher`
6. Click **Generate**
7. Google shows a 16-char password in 4 groups: `abcd efgh ijkl mnop`
8. Copy it.

> The app password works only with `rogeradrian@gmail.com` and only
> with this generated string. You can revoke it any time from the same page.

### 2. Drop files into BONDA OS

```bash
# from your BONDA OS project root on the RDP:
cp /path/to/bonda-invoice-watcher/app/integrations/gmail_invoice_client.py  app/integrations/
cp /path/to/bonda-invoice-watcher/scripts/invoice_fetcher.py                scripts/
```

### 3. Configure `.env`

Append the variables from `.env.example` to the BONDA OS `.env`, filling in
the app password and the two pending fiscal fields:

```dotenv
BONDA_GMAIL_USER=rogeradrian@gmail.com
BONDA_GMAIL_APP_PASSWORD=abcd efgh ijkl mnop   # ← paste here
BONDA_FACTURACION_EMAIL=facturacion@steviabonda.com.mx
BONDA_FISCAL_NAME=BONDA ALIMENTOS SANOS
BONDA_FISCAL_RFC=BAS2112142V6
BONDA_FISCAL_ADDRESS=Encino #1385-A, Col. del Fresno, Guadalajara, Jalisco, México
BONDA_FISCAL_CP=                # ← fill if known
BONDA_FISCAL_REGIME=            # ← fill if known
BONDA_FISCAL_CFDI_USE=G03
```

> **The fiscal `CP` and `REGIME` are unconfirmed in BONDA OS docs.**
> If left empty, the forwarded body shows `(pendiente confirmar)` — the
> counterpart will likely ping back asking. Better to fill them now.

### 4. Verify credentials load

```bash
# From BONDA OS project root, with the venv activated:
python -c "import os; \
  print('USER:', os.environ['BONDA_GMAIL_USER']); \
  print('APP_PW len:', len(os.environ['BONDA_GMAIL_APP_PASSWORD'].replace(' ','')))"
```

You should see your email and `APP_PW len: 16`. If you don't, your `.env`
isn't being loaded — source it manually:
```bash
set -a; source .env; set +a
```

---

## Usage

### Dry run — see what would happen (no emails sent, no labels applied)

```bash
python scripts/invoice_fetcher.py --since 2026-06-01 --dry-run
```

The dry run:

- Connects to Gmail via IMAP
- Searches for invoice emails from configured senders since June 1
- For each candidate, lists the PDFs that would be forwarded
- Writes a summary JSON to `~/.bonda/logs/invoice_summary_<ts>.json`

**Always run dry-run first.** Inspect the summary, confirm the list of emails
matches what you expect, then move on.

### Live run — forwards everything from June 2026

```bash
python scripts/invoice_fetcher.py --since 2026-06-01
```

For each candidate the script:
1. Fetches the email
2. Extracts PDF attachments
3. Forwards via SMTP to `facturacion@steviabonda.com.mx` with the fiscal block
4. Tags the original email with Gmail label `📄 Facturas/Procesado`
5. The label excludes the email from future searches → idempotent

### Live run — Anthropic only (most conservative)

```bash
python scripts/invoice_fetcher.py --since 2026-06-01 --senders anthropic
```

Use this for the very first live run if you want to limit blast radius to the
one sender that's confirmed to ship real invoices.

---

## Senders monitored

| Email | Status | Notes |
|---|---|---|
| `invoice+statements@mail.anthropic.com` | ✅ Confirmed | The Anthropic billing email that delivers real invoices (e.g. thread `19ee89e5b55d25df`, recibo `#2905-9982-3628`) |
| `billing@openai.com` | 🟡 Future-proofing | No historical match in inbox, captures future charges |
| `receipts@perplexity.ai` | 🟡 Future-proofing | Same |
| `noreply@semrush.com` | 🟡 Future-proofing | Same |

Explicitly **not** included: `billing@anthropic.com` (sends only failed-payment /
trial), `*@stripe.com` (Manus AI is failing recurrently — would be false invoices).

To change the list, edit `SENDERS_ALL` in `scripts/invoice_fetcher.py`.

---

## How idempotency works

Each email forwarded gets the Gmail label `📄 Facturas/Procesado`.
The IMAP search query excludes that label (`-label:"📄 Facturas/Procesado"`),
so:

- Re-running with the same `--since` is **safe** — already-forwarded emails
  are skipped silently.
- You can run this once a day in a cron without checking what was processed.
- To re-send a specific email, remove the label from it in Gmail UI and
  re-run.

The label is auto-created on first run (`client.ensure_processed_label()`).

---

## Operations

### Logs

Each run writes to `~/.bonda/logs/`:

- `invoice_fetcher_<timestamp>.log` — full INFO-level log
- `invoice_summary_<timestamp>.json` — machine-readable per-email summary

```bash
# Quick check of today's runs
ls -lt ~/.bonda/logs/ | head
```

### Scheduling (Phase 2 — optional)

Once you're happy with manual runs, schedule via Task Scheduler on the RDP:

- **Frequency:** once a day at 08:30 MX (after Anthropic's nightly invoice run)
- **Command:**
  ```
  python C:\path\to\bonda-os\scripts\invoice_fetcher.py --since 2026-06-01
  ```
- **Notes:** keep the `--since` static or always 30 days back. The label
  filtering handles dedup. Re-running is free.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `IMAP login failed` | Wrong app password, or 2FA disabled | Regenerate app password; confirm 2FA enabled |
| `BODY[]` returns empty | Account in delegated mode | Use the owner's app password, not delegate |
| 0 messages found | No invoices in the date range, OR all already labeled | Try `--since 2026-01-01 --dry-run` to confirm searcher works |
| `5.7.0 Authentication Required` from SMTP | App password mismatch | Same as IMAP login fix above |
| Label not applied | Gmail API rate-limited (rare) | Re-run; idempotent |
| Forwarded body shows `(pendiente confirmar)` for CP/Regime | Env vars empty | Fill `BONDA_FISCAL_CP` and `BONDA_FISCAL_REGIME` in .env |

---

## What this gives you

- **Today**: full June pull executed by hand, all invoices in
  `facturacion@steviabonda.com.mx` before the contábil closes
- **Tomorrow**: daily auto-run via Task Scheduler, ~zero attention required
- **Always**: independent of Make.com being paused, OAuth scopes, MCP tokens
