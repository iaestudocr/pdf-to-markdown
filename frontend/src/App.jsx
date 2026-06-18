import { useCallback, useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";

const API_URL = import.meta.env.VITE_API_URL || "";
const MAX_FREE_FILES = 1;
const MAX_PREMIUM_FILES = 10;

export default function App() {
  const [files, setFiles] = useState([]);
  const [results, setResults] = useState([]);
  const [loading, setLoading] = useState(false);
  const [currentFile, setCurrentFile] = useState("");
  const [error, setError] = useState("");
  const [dragging, setDragging] = useState(false);
  const [view, setView] = useState("preview");
  const [activeResult, setActiveResult] = useState(0);

  // Licença
  const [licenseKey, setLicenseKey] = useState(() => localStorage.getItem("license_key") || "");
  const [licenseValid, setLicenseValid] = useState(false);
  const [licenseInfo, setLicenseInfo] = useState(null);
  const [showLicenseModal, setShowLicenseModal] = useState(false);
  const [showUpgradeModal, setShowUpgradeModal] = useState(false);
  const [licenseInput, setLicenseInput] = useState("");
  const [licenseError, setLicenseError] = useState("");
  const [email, setEmail] = useState("");
  const [checkoutLoading, setCheckoutLoading] = useState(false);

  const inputRef = useRef(null);
  const maxFiles = licenseValid ? MAX_PREMIUM_FILES : MAX_FREE_FILES;

  useEffect(() => {
    if (licenseKey) validateLicense(licenseKey, false);
  }, []);

  const validateLicense = async (key, showError = true) => {
    try {
      const res = await fetch(`${API_URL}/validate-license`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ license_key: key }),
      });
      if (res.ok) {
        const data = await res.json();
        setLicenseValid(true);
        setLicenseInfo(data);
        localStorage.setItem("license_key", key);
        return true;
      } else {
        if (showError) setLicenseError("Chave inválida ou expirada.");
        setLicenseValid(false);
        localStorage.removeItem("license_key");
        return false;
      }
    } catch {
      return false;
    }
  };

  const handleActivateLicense = async () => {
    setLicenseError("");
    const ok = await validateLicense(licenseInput, true);
    if (ok) {
      setLicenseKey(licenseInput);
      setShowLicenseModal(false);
      setLicenseInput("");
    }
  };

  const handleCheckout = async (plan) => {
    if (!email) { setLicenseError("Digite seu email para continuar."); return; }
    setCheckoutLoading(true);
    setLicenseError("");
    try {
      const res = await fetch(`${API_URL}/checkout`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email, plan }),
      });
      const data = await res.json();
      if (data.checkout_url) {
        window.open(data.checkout_url, "_blank");
      } else {
        setLicenseError(data.detail || "Erro ao gerar o link de pagamento. Tente novamente.");
      }
    } catch {
      setLicenseError("Erro ao conectar ao servidor. Tente novamente.");
    } finally {
      setCheckoutLoading(false);
    }
  };

  const handleFiles = useCallback((newFiles) => {
    const pdfs = Array.from(newFiles).filter(f => f.name.toLowerCase().endsWith(".pdf"));
    if (!pdfs.length) { setError("Selecione arquivos PDF."); return; }
    if (pdfs.length > maxFiles) {
      if (!licenseValid) {
        setShowUpgradeModal(true);
        return;
      }
      setError(`Máximo de ${maxFiles} arquivos.`);
      return;
    }
    setFiles(pdfs);
    setResults([]);
    setError("");
  }, [maxFiles, licenseValid]);

  const onDrop = useCallback((e) => {
    e.preventDefault();
    setDragging(false);
    handleFiles(e.dataTransfer.files);
  }, [handleFiles]);

  const convert = async () => {
    if (!files.length) return;
    setLoading(true);
    setError("");
    setResults([]);

    const newResults = [];
    for (const file of files) {
      setCurrentFile(file.name);
      const form = new FormData();
      form.append("file", file);
      try {
        const res = await fetch(`${API_URL}/convert`, {
            method: "POST",
            headers: licenseKey ? { "X-License-Key": licenseKey } : {},
            body: form,
          });
        if (!res.ok) {
          const d = await res.json().catch(() => ({}));
          newResults.push({ filename: file.name, error: d.detail || `Erro ${res.status}` });
        } else {
          const d = await res.json();
          newResults.push({ filename: file.name, markdown: d.markdown });
        }
      } catch (err) {
        newResults.push({ filename: file.name, error: "Erro ao conectar ao servidor." });
      }
    }

    setResults(newResults);
    setActiveResult(0);
    setLoading(false);
    setCurrentFile("");
  };

  const download = (result) => {
    const blob = new Blob([result.markdown], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = result.filename.replace(/\.pdf$/i, ".md");
    a.click();
    URL.revokeObjectURL(url);
  };

  const reset = () => {
    setFiles([]);
    setResults([]);
    setError("");
    if (inputRef.current) inputRef.current.value = "";
  };

  const current = results[activeResult];

  return (
    <div className="app">
      <header>
        <h1>PDF → Markdown</h1>
        <p>Converte PDFs digitais para Markdown</p>
        <div className="header-license">
          {licenseValid ? (
            <span className="badge-premium">
              Premium ativo · {licenseInfo?.plan === "monthly" ? "Mensal" : "Anual"}
            </span>
          ) : (
            <button className="btn-upgrade" onClick={() => setShowUpgradeModal(true)}>
              ⭐ Upgrade Premium
            </button>
          )}
        </div>
      </header>

      <main>
        <div
          className={`drop-zone ${dragging ? "dragging" : ""} ${files.length ? "has-file" : ""}`}
          onDrop={onDrop}
          onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
          onDragLeave={() => setDragging(false)}
          onClick={() => !files.length && inputRef.current?.click()}
        >
          <input
            ref={inputRef}
            type="file"
            accept=".pdf,application/pdf"
            multiple={licenseValid}
            className="hidden"
            onChange={(e) => handleFiles(e.target.files)}
          />

          {files.length ? (
            <div className="file-list">
              {files.map((f, i) => (
                <div key={i} className="file-info">
                  <span className="file-icon">📄</span>
                  <span className="file-name">{f.name}</span>
                  <span className="file-size">{(f.size / 1024 / 1024).toFixed(2)} MB</span>
                </div>
              ))}
              <button className="btn-ghost" onClick={(e) => { e.stopPropagation(); reset(); }}>
                ✕ Remover
              </button>
            </div>
          ) : (
            <div className="drop-hint">
              <span className="drop-icon">📂</span>
              <p>Arraste {licenseValid ? "até 10 PDFs" : "um PDF"} aqui ou <strong>clique para selecionar</strong></p>
              <p className="hint-small">Máx. 30 MB por arquivo{!licenseValid ? " · Plano gratuito: 1 arquivo" : ""}</p>
            </div>
          )}
        </div>

        {error && <div className="error-box">⚠️ {error}</div>}

        {files.length > 0 && !results.length && (
          <button className="btn-primary" onClick={convert} disabled={loading}>
            {loading ? (
              <><span className="spinner" /> {currentFile ? `Convertendo: ${currentFile}` : "Convertendo…"}</>
            ) : (
              `Converter ${files.length > 1 ? `${files.length} arquivos` : "para Markdown"}`
            )}
          </button>
        )}

        {results.length > 0 && (
          <div className="result">
            {results.length > 1 && (
              <div className="result-tabs">
                {results.map((r, i) => (
                  <button
                    key={i}
                    className={activeResult === i ? "active" : ""}
                    onClick={() => setActiveResult(i)}
                  >
                    {r.filename.replace(/\.pdf$/i, "")}
                  </button>
                ))}
              </div>
            )}

            {current?.error ? (
              <div className="error-box" style={{margin:"1rem"}}>⚠️ {current.error}</div>
            ) : (
              <>
                <div className="result-toolbar">
                  <div className="view-toggle">
                    <button className={view === "preview" ? "active" : ""} onClick={() => setView("preview")}>Preview</button>
                    <button className={view === "raw" ? "active" : ""} onClick={() => setView("raw")}>Markdown bruto</button>
                  </div>
                  <div className="result-actions">
                    <button className="btn-secondary" onClick={() => download(current)}>⬇ Baixar .md</button>
                    <button className="btn-ghost" onClick={reset}>Novo arquivo</button>
                  </div>
                </div>
                {view === "preview" ? (
                  <div className="markdown-preview"><ReactMarkdown>{current.markdown}</ReactMarkdown></div>
                ) : (
                  <textarea className="markdown-raw" readOnly value={current.markdown} />
                )}
              </>
            )}
          </div>
        )}
      </main>

      {/* Modal Upgrade */}
      {showUpgradeModal && (
        <div className="modal-overlay" onClick={() => setShowUpgradeModal(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <button className="modal-close" onClick={() => setShowUpgradeModal(false)}>✕</button>
            <h2>Planos</h2>

            {/* Plano Gratuito */}
            <div className="plan-free-box">
              <div className="plan-free-label">Seu plano atual — Gratuito</div>
              <ul className="plan-free-features">
                <li>✅ 1 arquivo por vez</li>
                <li>✅ PDFs digitais</li>
                <li>✅ Download .md</li>
                <li>✅ Sem cadastro</li>
              </ul>
            </div>

            <div className="plan-divider">
              <span>Quer mais? Faça upgrade</span>
            </div>

            {/* Plano Premium */}
            <div className="plan-premium-box">
              <div className="plan-premium-header">
                <span className="plan-premium-tag">⭐ Premium</span>
                <span className="plan-premium-extra">+ até 10 arquivos por vez</span>
              </div>

              <div className="plans">
                <div className="plan-card">
                  <div className="plan-name">Mensal</div>
                  <div className="plan-price">R$ 6,90<span>/30 dias</span></div>
                </div>
                <div className="plan-card featured">
                  <div className="plan-badge">Melhor valor</div>
                  <div className="plan-name">Anual</div>
                  <div className="plan-price">R$ 49,97<span>/ano</span></div>
                </div>
              </div>

              <input
                className="input-email"
                type="email"
                placeholder="Seu email (receberá a chave de licença)"
                value={email}
                onChange={(e) => { setEmail(e.target.value); setLicenseError(""); }}
              />

              {licenseError && <p className="license-error">{licenseError}</p>}

              <div className="modal-actions">
                <button className="btn-primary" onClick={() => handleCheckout("monthly")} disabled={checkoutLoading}>
                  {checkoutLoading ? <><span className="spinner" /> Aguarde…</> : "Pagar Mensal — R$ 6,90"}
                </button>
                <button className="btn-primary featured" onClick={() => handleCheckout("yearly")} disabled={checkoutLoading}>
                  {checkoutLoading ? <><span className="spinner" /> Aguarde…</> : "Pagar Anual — R$ 49,97"}
                </button>
              </div>
            </div>

            <button className="btn-link" onClick={() => { setShowUpgradeModal(false); setShowLicenseModal(true); }}>
              Já tenho uma chave de licença
            </button>
          </div>
        </div>
      )}

      {/* Modal Licença */}
      {showLicenseModal && (
        <div className="modal-overlay" onClick={() => setShowLicenseModal(false)}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h2>Ativar licença</h2>
            <p>Cole a chave que você recebeu por email:</p>
            <input
              className="input-license"
              type="text"
              placeholder="XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"
              value={licenseInput}
              onChange={(e) => setLicenseInput(e.target.value.toUpperCase())}
            />
            {licenseError && <p className="license-error">{licenseError}</p>}
            <div className="modal-actions">
              <button className="btn-primary" onClick={handleActivateLicense}>Ativar</button>
            </div>
            <button className="modal-close" onClick={() => setShowLicenseModal(false)}>✕</button>
          </div>
        </div>
      )}
    </div>
  );
}
