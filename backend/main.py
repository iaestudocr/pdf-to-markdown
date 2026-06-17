import os

import pymupdf
import pymupdf4llm
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="PDF to Markdown Converter")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MAX_FILE_SIZE_MB = 30


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


# Serve React build in production
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
if os.path.exists(STATIC_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(STATIC_DIR, "assets")), name="assets")

    @app.get("/")
    async def serve_root():
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))

    @app.get("/{path:path}")
    async def serve_spa(path: str):
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))
