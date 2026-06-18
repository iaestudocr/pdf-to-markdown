import os
import secrets
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import httpx
import pymupdf
import pymupdf4llm
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from supabase import create_client

app = FastAPI(title="PDF to Markdown Converter")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_FILE_SIZE_MB = 30
ABACATEPAY_API_URL = "https://api.abacatepay.com/v2"


def get_supabase():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        raise HTTPException(status_code=500, detail="Supabase não configurado.")
    return create_client(url, key)


def send_license_email(to_email: str, license_key: str, plan: str, expires_at: datetime):
    gmail_user = os.environ.get("GMAIL_USER")
    gmail_password = os.environ.get("GMAIL_APP_PASSWORD")
    if not gmail_user or not gmail_password:
        raise Exception("Gmail não configurado.")

    plan_label = "Mensal (30 dias)" if plan == "monthly" else "Anual (12 meses)"
    expires_str = expires_at.strftime("%d/%m/%Y")
    app_url = "https://pdf-to-markdown-xr0v.onrender.com"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "Sua chave de licença Premium — PDF to Markdown"
    msg["From"] = gmail_user
    msg["To"] = to_email

    html = f"""
    <div style="font-family:sans-serif;max-width:520px;margin:0 auto;padding:32px;">
      <h2 style="color:#6366f1">PDF → Markdown Premium</h2>
      <p>Obrigado pela sua compra! Aqui está sua chave de licença:</p>
      <div style="background:#f3f4f6;border-radius:8px;padding:20px;text-align:center;margin:24px 0;">
        <code style="font-size:1.3rem;letter-spacing:4px;color:#111">{license_key}</code>
      </div>
      <p><strong>Plano:</strong> {plan_label}<br>
      <strong>Válido até:</strong> {expires_str}</p>
      <p>Para ativar:</p>
      <ol>
        <li>Acesse <a href="{app_url}">{app_url}</a></li>
        <li>Clique em <strong>"Ativar licença"</strong></li>
        <li>Cole a chave acima</li>
      </ol>
      <p style="color:#888;font-size:0.85rem">Guarde esta chave em local seguro.</p>
    </div>
    """

    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(gmail_user, gmail_password)
        server.sendmail(gmail_user, to_email, msg.as_string())


# ── Modelos ──────────────────────────────────────────────

class CheckoutRequest(BaseModel):
    email: str
    plan: str  # "monthly" | "yearly"


class ValidateLicenseRequest(BaseModel):
    license_key: str


# ── Endpoints de pagamento ───────────────────────────────

@app.post("/checkout")
async def create_checkout(body: CheckoutRequest):
    if body.plan not in ("monthly", "yearly"):
        raise HTTPException(status_code=400, detail="Plano inválido.")

    api_key = os.environ.get("ABACATEPAY_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="AbacatePay não configurado.")

    price = 690 if body.plan == "monthly" else 4997  # centavos
    label = "PDF to Markdown — Mensal" if body.plan == "monthly" else "PDF to Markdown — Anual"

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{ABACATEPAY_API_URL}/checkouts/create",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "items": [
                    {
                        "externalId": body.plan,
                        "name": label,
                        "quantity": 1,
                        "price": price,
                    }
                ],
                "returnUrl": "https://pdf-to-markdown-xr0v.onrender.com",
                "completionUrl": "https://pdf-to-markdown-xr0v.onrender.com/?paid=1",
                "customer": {"email": body.email},
            },
        )

    print(f"AbacatePay status: {resp.status_code} — {resp.text}")

    if resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Erro AbacatePay ({resp.status_code}): {resp.text}")

    data = resp.json()
    url = (
        data.get("data", {}).get("url")
        or data.get("data", {}).get("checkoutUrl")
        or data.get("url")
    )
    if not url:
        raise HTTPException(status_code=502, detail=f"URL de checkout não retornada: {data}")

    return {"checkout_url": url}


@app.post("/webhook/abacatepay")
async def abacatepay_webhook(request: Request):
    payload = await request.json()

    if payload.get("event") not in ("checkout.completed", "billing.paid"):
        return JSONResponse({"ok": True})

    billing = payload.get("data", {})
    email = (
        billing.get("customer", {}).get("email")
        or billing.get("metadata", {}).get("email", "")
    )
    plan = billing.get("products", [{}])[0].get("externalId", "monthly")
    payment_id = billing.get("id", "")

    if not email:
        return JSONResponse({"ok": True})

    days = 30 if plan == "monthly" else 365
    expires_at = datetime.utcnow() + timedelta(days=days)
    license_key = secrets.token_hex(16).upper()

    supabase = get_supabase()
    supabase.table("licenses").insert({
        "license_key": license_key,
        "email": email,
        "plan": plan,
        "expires_at": expires_at.isoformat(),
        "payment_id": payment_id,
        "is_active": True,
    }).execute()

    try:
        send_license_email(email, license_key, plan, expires_at)
    except Exception as e:
        print(f"Erro ao enviar email: {e}")

    return JSONResponse({"ok": True})


@app.post("/validate-license")
async def validate_license(body: ValidateLicenseRequest):
    supabase = get_supabase()
    result = supabase.table("licenses").select("*").eq(
        "license_key", body.license_key.upper()
    ).eq("is_active", True).execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Licença não encontrada.")

    license = result.data[0]
    expires_at = datetime.fromisoformat(license["expires_at"].replace("Z", ""))

    if datetime.utcnow() > expires_at:
        raise HTTPException(status_code=403, detail="Licença expirada.")

    return {
        "valid": True,
        "plan": license["plan"],
        "expires_at": license["expires_at"],
    }


# ── Conversão PDF ────────────────────────────────────────

@app.post("/convert")
async def convert_pdf(file: UploadFile = File(...)):
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Apenas arquivos PDF são aceitos.")

    pdf_data = await file.read()
    size_mb = len(pdf_data) / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        raise HTTPException(
            status_code=413,
            detail=f"Arquivo muito grande ({size_mb:.1f} MB). Limite: {MAX_FILE_SIZE_MB} MB.",
        )

    try:
        doc = pymupdf.open(stream=pdf_data, filetype="pdf")
        md_text = pymupdf4llm.to_markdown(doc)
        doc.close()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Erro ao converter PDF: {str(e)}")

    if not md_text.strip():
        raise HTTPException(
            status_code=422,
            detail="PDF escaneado ou sem texto selecionável. Esta versão processa apenas PDFs digitais.",
        )

    return {
        "markdown": md_text,
        "filename": file.filename,
        "pages_note": "Processado com sucesso.",
    }


@app.get("/health")
async def health():
    return {"status": "ok"}


# ── Frontend estático ────────────────────────────────────

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(STATIC_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(STATIC_DIR, "assets")), name="assets")

    @app.get("/")
    async def serve_root():
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))

    @app.get("/{path:path}")
    async def serve_spa(path: str):
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))
