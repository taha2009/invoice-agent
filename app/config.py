from pydantic import computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    port: int = 8000
    debug: bool = False

    # Telegram
    telegram_bot_token: str
    telegram_webhook_secret: str = ""
    webhook_base_url: str = ""
    allowed_telegram_ids: str = ""  # comma-separated user IDs; empty = allow all

    @computed_field
    @property
    def allowed_ids(self) -> set[int]:
        if not self.allowed_telegram_ids.strip():
            return set()
        return {
            int(uid.strip())
            for uid in self.allowed_telegram_ids.split(",")
            if uid.strip()
        }

    # Gemini
    gemini_api_key: str
    gemini_model: str = "gemini-2.0-flash"

    # Google Sheets
    google_sheet_id: str

    # Invoice numbering
    invoice_prefix: str = "2026-27"

    # Issuer details (printed on every invoice)
    issuer_name: str
    issuer_designation: str = ""
    issuer_address: str
    issuer_phone: str
    issuer_email: str

    # Bank details
    bank_beneficiary: str
    bank_name: str
    bank_ac_type: str
    bank_ac_number: str
    bank_ifsc: str

    # GCS bucket shared across storage needs
    gcs_bucket: str = ""
    # Object path inside the bucket for the issuer signature image (PNG/JPG)
    gcs_signature_object: str = ""

    # WhatsApp (Meta Cloud API)
    whatsapp_access_token: str = ""
    whatsapp_phone_number_id: str = ""
    whatsapp_verify_token: str = ""
    allowed_whatsapp_numbers: str = (
        ""  # comma-separated E.164 numbers; empty = allow all
    )

    @computed_field
    @property
    def allowed_whatsapp_set(self) -> set[str]:
        if not self.allowed_whatsapp_numbers.strip():
            return set()
        return {
            n.strip() for n in self.allowed_whatsapp_numbers.split(",") if n.strip()
        }

    # MongoDB
    mongodb_uri: str = ""
    mongodb_database: str = "invoice_agent"

    # Session idle timeout — new thread_id generated after this many minutes of inactivity
    session_idle_minutes: int = 30


settings = Settings()
