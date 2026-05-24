# tg-invoice-bot

A Telegram bot that generates PDF invoices via a conversational AI interface (Gemini). Send invoice details in plain language; the bot extracts the data, generates a PDF invoice, logs the record to a Google Sheet, and sends the PDF back.

**Stack:** FastAPI · python-telegram-bot · LangGraph (Gemini) · ReportLab · Google Sheets (ADC) · Cloud Run

**Optional:** MongoDB — persists conversation state and session management across restarts. Without it, state is kept in memory and lost on restart.

---

## Local Development

Useful for verifying the PDF output and Sheet writes before deploying.

**Prerequisites:** Python 3.12+, a GCP project, a Telegram bot token. MongoDB Atlas is optional but recommended for persistence.

### 1. Clone and install

```bash
git clone <repo-url>
cd invoice-agent
pip install -r requirements.txt
```

### 2. Google Sheets auth (ADC)

The app uses [Application Default Credentials](https://cloud.google.com/docs/authentication/application-default-credentials) for Sheets access. Export your credentials before running:

```bash
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service_account.json
```

The service account only needs to be shared on the Google Sheet as **Editor** — no project-level IAM roles required.

### 3. Google Sheet

Create a new Google Sheet. Leave it blank — the app automatically creates a tab named after `INVOICE_PREFIX` and writes headers on first run.

Copy the Sheet ID from the URL:
`https://docs.google.com/spreadsheets/d/<SHEET_ID>/edit`

### 4. Configure `.env`

```bash
cp .env.example .env
# fill in all values
```

### 5. Run

```bash
uvicorn app.main:app --reload --port 8000
```

> Telegram webhooks require a public HTTPS URL, so bot messaging only works once deployed to Cloud Run. Local runs are useful for testing PDF generation and Sheet writes directly.

### 6. Signature image (optional)

To embed a scanned signature in the PDF, set:

```
ISSUER_SIGNATURE_PATH=path/to/signature.png
```

The PDF falls back to the typed name if the path is unset or missing.

---

## Cloud Run Deployment

On Cloud Run, Google Sheets auth uses ADC from the attached service identity — no credentials file or env var needed.

### 1. Enable APIs

```bash
gcloud services enable \
  run.googleapis.com \
  sheets.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com
```

### 2. Create Artifact Registry repository

```bash
gcloud artifacts repositories create cloud-run-source-deploy \
  --repository-format=docker \
  --location=asia-south1 \
  --description="Docker images for Cloud Run"
```

### 3. Create the service account

```bash
gcloud iam service-accounts create invoice-bot-sa \
  --display-name="Invoice Bot"
```

Share your Google Sheet with the service account email as **Editor**:
`invoice-bot-sa@<PROJECT_ID>.iam.gserviceaccount.com`

### 4. First deploy

```bash
cp env.yaml.example env.yaml
# edit env.yaml — fill in all placeholder values
# leave WEBHOOK_BASE_URL blank for now (set in step 4)
```

```bash
PROJECT_ID=your-gcp-project-id
REGION=asia-south1
SERVICE=invoice-agent
SA=invoice-bot-sa@${PROJECT_ID}.iam.gserviceaccount.com

gcloud run deploy $SERVICE \
  --source . \
  --platform managed \
  --region $REGION \
  --service-account $SA \
  --allow-unauthenticated \
  --env-vars-file=env.yaml \
  --min-instances=0 \
  --max-instances=2 \
  --memory=512Mi \
  --timeout=120

SERVICE_URL=$(gcloud run services describe $SERVICE \
  --region $REGION --format "value(status.url)")
echo "Service URL: $SERVICE_URL"
```

### 5. Set WEBHOOK_BASE_URL and redeploy

Update `WEBHOOK_BASE_URL` in `env.yaml` with the service URL, then redeploy:

```bash
gcloud run deploy $SERVICE \
  --source . \
  --platform managed \
  --region $REGION \
  --service-account $SA \
  --allow-unauthenticated \
  --env-vars-file=env.yaml \
  --min-instances=0 \
  --max-instances=2 \
  --memory=512Mi \
  --timeout=120
```

The startup handler registers the Telegram webhook automatically.

### 6. Verify

```bash
curl "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/getWebhookInfo"
```

Look for `"url": "<SERVICE_URL>/webhook"` and `"pending_update_count": 0`.

---

## Updating

```bash
gcloud run deploy $SERVICE \
  --source . \
  --region $REGION \
  --env-vars-file=env.yaml
```

---

## Example Conversation

```
User:   New invoice for Acme Corp, 123 Business Park, Mumbai.
        Fees: Legal consultation 15000, Contract drafting 10000.
        Disbursements: Filing fee 500, Stamp duty 200.
        Date: today.

Bot:    Invoice 2026-27/1 for ₹25,700 is ready.
        [sends PDF]
```

---

## Architecture

```
User (Telegram)
      │ natural language message
      ▼
Telegram Bot
      │ HTTPS webhook
      ▼
FastAPI /webhook  ── secret-token check
      │
      ▼
LangGraph ReAct Agent  (Gemini)
      │ tool call when all fields collected
      ▼
generate_invoice tool
      ├── Google Sheets  →  reserve invoice number, append row  (ADC)
      └── ReportLab PDF  →  temp file → sent to Telegram → deleted
```

## Project Structure

```
invoice-agent/
├── app/
│   ├── __init__.py
│   ├── main.py              # FastAPI app + Telegram webhook
│   ├── agent.py             # LangGraph graph + system prompt
│   ├── sessions.py          # Checkpointer + session/thread-ID management
│   ├── config.py            # Settings (pydantic-settings + .env)
│   └── tools/
│       ├── __init__.py
│       ├── invoice_tool.py  # @tool generate_invoice
│       ├── pdf_generator.py # ReportLab PDF generator
│       └── sheets_ledger.py # gspread read/append via ADC
├── Dockerfile
├── .dockerignore
├── .env.example
├── env.yaml.example
├── requirements.txt
└── LICENSE
```

---

## License

[MIT](LICENSE)
