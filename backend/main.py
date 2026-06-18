import hashlib
import hmac as _hmac
import json as _json
import os
import secrets
import smtplib
import time
from collections import defaultdict
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
    allow_origins=["http://localhost:5173", "https://pdf-to-markdown-xr0v.onrender.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_FILE_SIZE_MB = 30
ABACATEPAY_API_URL = "https://api.abacatepay.com/v2"

# ── Rate limiting (in-memory, por IP) ───────────────────
_rate_store: dict = defaultdict(lambda: defaultdict(list))


def get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("X-Forwarded-For", "")
    return forwarded.split(",")[0].strip() if forwarded else (request.client.host or "unknown")


def check_rate(bucket: str, ip: str, limit: int, window_secs: int) -> bool:
    """Retorna True se a requisição é permitida, False se excedeu o limite."""
    now = time.time()
    _rate_store[bucket][ip] = [t for t in _rate_store[bucket][ip] if now - t < window_secs]
    if len(_rate_store[bucket][ip]) >= limit:
        return False
    _rate_store[bucket][ip].append(now)
    return True


# ── Supabase ─────────────────────────────────────────────

def get_supabase():
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url or not key:
        raise HTTPException(status_code=500, detail="Supabase não configurado.")
    return create_client(url, key)


# ── Email ────────────────────────────────────────────────

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
async def create_checkout(body: CheckoutRequest, request: Request):
    # Rate limit: 5 tentativas por hora por IP
    ip = get_client_ip(request)
    if not check_rate("checkout", ip, 5, 3600):
        raise HTTPException(status_code=429, detail="Muitas tentativas. Aguarde e tente novamente.")

    if body.plan not in ("monthly", "yearly"):
        raise HTTPException(status_code=400, detail="Plano inválido.")

    # Validação básica de email
    email = body.email.strip().lower()
    if "@" not in email or "." not in email.split("@")[-1]:
        raise HTTPException(status_code=400, detail="Email inválido.")

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
                        "id": body.plan,
                        "name": label,
                        "quantity": 1,
                        "price": price,
                    }
                ],
                "returnUrl": "https://pdf-to-markdown-xr0v.onrender.com",
                "completionUrl": "https://pdf-to-markdown-xr0v.onrender.com/?paid=1",
                "customer": {"email": email},
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
    body_bytes = await request.body()

    # Camada 1: verificar assinatura do webhook
    webhook_secret = os.environ.get("ABACATEPAY_WEBHOOK_SECRET", "")
    if webhook_secret:
        # Loga os headers na primeira vez para identificar qual header a AbacatePay usa
        print(f"Webhook headers recebidos: {dict(request.headers)}")

        received_sig = (
            request.headers.get("X-AbacatePay-Signature", "")
            or request.headers.get("X-Webhook-Signature", "")
            or request.headers.get("Authorization", "").replace("Bearer ", "")
        )

        if received_sig:
            # Tenta HMAC-SHA256
            expected_hmac = _hmac.new(
                webhook_secret.encode("utf-8"),
                body_bytes,
                hashlib.sha256,
            ).hexdigest()

            valid_hmac = _hmac.compare_digest(received_sig, expected_hmac)
            # Tenta comparação direta (alguns gateways enviam o segredo puro)
            valid_direct = _hmac.compare_digest(received_sig, webhook_secret)

            if not valid_hmac and not valid_direct:
                print(f"Assinatura inválida. Recebida: {received_sig}")
                raise HTTPException(status_code=401, detail="Assinatura inválida.")
        else:
            print("WARNING: Webhook recebido sem cabeçalho de assinatura.")

    try:
        payload = _json.loads(body_bytes)
    except Exception:
        raise HTTPException(status_code=400, detail="Payload inválido.")

    if payload.get("event") not in ("checkout.completed", "billing.paid"):
        return JSONResponse({"ok": True})

    billing = payload.get("data", {})
    email = (
        billing.get("customer", {}).get("email")
        or billing.get("metadata", {}).get("email", "")
    )

    # Tenta extrair o plano de "items" ou "products" (compatibilidade)
    items = billing.get("items") or billing.get("products") or [{}]
    plan = items[0].get("id") or items[0].get("externalId", "monthly")
    payment_id = billing.get("id", "")

    if not email:
        return JSONResponse({"ok": True})

    supabase = get_supabase()

    # Camada 2: idempotência — não gerar licença duplicada para o mesmo pagamento
    if payment_id:
        existing = supabase.table("licenses").select("license_key").eq(
            "payment_id", payment_id
        ).execute()
        if existing.data:
            print(f"Pagamento {payment_id} já processado. Ignorando.")
            return JSONResponse({"ok": True})

    days = 30 if plan == "monthly" else 365
    expires_at = datetime.utcnow() + timedelta(days=days)
    license_key = secrets.token_hex(16).upper()

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
async def validate_license(body: ValidateLicenseRequest, request: Request):
    # Rate limit: 20 tentativas por hora (brute force é matematicamente impossível,
    # mas limitamos por boa prática)
    ip = get_client_ip(request)
    if not check_rate("validate", ip, 20, 3600):
        raise HTTPException(status_code=429, detail="Muitas tentativas. Aguarde.")

    supabase = get_supabase()
    result = supabase.table("licenses").select("*").eq(
        "license_key", body.license_key.upper()
    ).eq("is_active", True).execute()

    if not result.data:
        raise HTTPException(status_code=404, detail="Licença não encontrada.")

    lic = result.data[0]
    expires_at = datetime.fromisoformat(lic["expires_at"].replace("Z", ""))

    if datetime.utcnow() > expires_at:
        raise HTTPException(status_code=403, detail="Licença expirada.")

    return {
        "valid": True,
        "plan": lic["plan"],
        "expires_at": lic["expires_at"],
    }


# ── Conversão PDF ────────────────────────────────────────

@app.post("/convert")
async def convert_pdf(request: Request, file: UploadFile = File(...)):
    ip = get_client_ip(request)

    # Camada 3: validação de licença server-side
    license_key = request.headers.get("X-License-Key", "").strip().upper()
    is_premium = False

    if license_key:
        try:
            supabase = get_supabase()
            result = supabase.table("licenses").select("expires_at").eq(
                "license_key", license_key
            ).eq("is_active", True).execute()
            if result.data:
                exp = datetime.fromisoformat(result.data[0]["expires_at"].replace("Z", ""))
                is_premium = datetime.utcnow() <= exp
        except Exception as e:
            print(f"Erro ao verificar licença no /convert: {e}")

    # Camada 4: rate limiting para usuários gratuitos (10/hora por IP)
    if not is_premium:
        if not check_rate("convert_free", ip, 10, 3600):
            raise HTTPException(
                status_code=429,
                detail="Limite gratuito atingido (10 conversões/hora). Faça upgrade para Premium.",
            )

    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Apenas arquivos PDF são aceitos.")

    pdf_data = await file.read()

    size_mb = len(pdf_data) / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        raise HTTPException(
            status_code=413,
            detail=f"Arquivo muito grande ({size_mb:.1f} MB). Limite: {MAX_FILE_SIZE_MB} MB.",
        )

    # Camada 5: validar magic bytes — arquivo deve começar com %PDF
    if not pdf_data.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="Arquivo não é um PDF válido.")

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
