import { useCallback, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";

const API_URL = import.meta.env.VITE_API_URL || "";

export default function App() {
  const [file, setFile] = useState(null);
  const [markdown, setMarkdown] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [dragging, setDragging] = useState(false);
  const [view, setView] = useState("preview"); // "preview" | "raw"
  const inputRef = useRef(null);

  const handleFile = useCallback((f) => {
    if (!f) return;
    if (f.type !== "application/pdf") {
      setError("Selecione um arquivo PDF.");
      return;
    }
    setFile(f);
    setMarkdown("");
    setError("");
  }, []);

  const onDrop = useCallback(
    (e) => {
      e.preventDefault();
      setDragging(false);
      const f = e.dataTransfer.files[0];
      handleFile(f);
    },
    [handleFile]
  );

  const onDragOver = (e) => {
    e.preventDefault();
    setDragging(true);
  };

  const onDragLeave = () => setDragging(false);

  const convert = async () => {
    if (!file) return;
    setLoading(true);
    setError("");
    setMarkdown("");

    const form = new FormData();
    form.append("file", file);

    try {
      const res = await fetch(`${API_URL}/convert`, {
        method: "POST",
        body: form,
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || `Erro ${res.status}`);
      }

      const data = await res.json();
      setMarkdown(data.markdown);
    } catch (err) {
      setError(err.message || "Erro ao converter. Verifique se o backend está rodando.");
    } finally {
      setLoading(false);
    }
  };

  const download = () => {
    const blob = new Blob([markdown], { type: "text/markdown" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = file.name.replace(/\.pdf$/i, ".md");
    a.click();
    URL.revokeObjectURL(url);
  };

  const reset = () => {
    setFile(null);
    setMarkdown("");
    setError("");
    if (inputRef.current) inputRef.current.value = "";
  };

  return (
    <div className="app">
      <header>
        <h1>PDF → Markdown</h1>
        <p>Converte PDFs digitais e escaneados para Markdown usando IA</p>
      </header>

      <main>
        {/* Upload zone */}
        <div
          className={`drop-zone ${dragging ? "dragging" : ""} ${file ? "has-file" : ""}`}
          onDrop={onDrop}
          onDragOver={onDragOver}
          onDragLeave={onDragLeave}
          onClick={() => !file && inputRef.current?.click()}
        >
          <input
            ref={inputRef}
            type="file"
            accept=".pdf,application/pdf"
            className="hidden"
            onChange={(e) => handleFile(e.target.files[0])}
          />

          {file ? (
            <div className="file-info">
              <span className="file-icon">📄</span>
              <span className="file-name">{file.name}</span>
              <span className="file-size">
                {(file.size / 1024 / 1024).toFixed(2)} MB
              </span>
              <button className="btn-ghost" onClick={(e) => { e.stopPropagation(); reset(); }}>
                ✕ Remover
              </button>
            </div>
          ) : (
            <div className="drop-hint">
              <span className="drop-icon">📂</span>
              <p>Arraste um PDF aqui ou <strong>clique para selecionar</strong></p>
              <p className="hint-small">Suporta PDFs digitais e escaneados · Máx. 30 MB</p>
            </div>
          )}
        </div>

        {/* Error */}
        {error && <div className="error-box">⚠️ {error}</div>}

        {/* Convert button */}
        {file && !markdown && (
          <button
            className="btn-primary"
            onClick={convert}
            disabled={loading}
          >
            {loading ? (
              <>
                <span className="spinner" /> Convertendo…
              </>
            ) : (
              "Converter para Markdown"
            )}
          </button>
        )}

        {/* Loading hint */}
        {loading && (
          <p className="loading-hint">
            Convertendo PDF. Documentos longos podem levar alguns segundos…
          </p>
        )}

        {/* Result */}
        {markdown && (
          <div className="result">
            <div className="result-toolbar">
              <div className="view-toggle">
                <button
                  className={view === "preview" ? "active" : ""}
                  onClick={() => setView("preview")}
                >
                  Preview
                </button>
                <button
                  className={view === "raw" ? "active" : ""}
                  onClick={() => setView("raw")}
                >
                  Markdown bruto
                </button>
              </div>
              <div className="result-actions">
                <button className="btn-secondary" onClick={download}>
                  ⬇ Baixar .md
                </button>
                <button className="btn-ghost" onClick={reset}>
                  Novo arquivo
                </button>
              </div>
            </div>

            {view === "preview" ? (
              <div className="markdown-preview">
                <ReactMarkdown>{markdown}</ReactMarkdown>
              </div>
            ) : (
              <textarea
                className="markdown-raw"
                readOnly
                value={markdown}
              />
            )}
          </div>
        )}
      </main>
    </div>
  );
}
