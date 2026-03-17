import { useState } from "react";
import { Analytics } from "@vercel/analytics/react";
import AboutPage from "./pages/About";
import ContactPage from "./pages/Contact";
import "./App.css";

type Page = "home" | "about" | "contact";

export default function App() {
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState("");
  const [loading, setLoading] = useState(false);
  const [currentPage, setCurrentPage] = useState<Page>("home");

  const API_URL = import.meta.env.VITE_API_URL;

  const handleUpload = async () => {
    if (!file) { alert("Please select a file"); return; }
    const formData = new FormData();
    formData.append("file", file);
    setLoading(true);
    setResult("");
    try {
      const res = await fetch(`${API_URL}/api/analyze`, { method: "POST", body: formData });
      const data = await res.json();
      setResult(data.analysis || "No response from AI");
    } catch (err) {
      console.error(err);
      setResult("Error connecting to backend");
    }
    setLoading(false);
  };

  return (
    <>
      <nav className="nav">
        <div className="nav-inner">
          <button className="nav-logo" onClick={() => setCurrentPage("home")}>
            <span className="logo-mark">F</span>
            <span className="logo-text">insight</span>
          </button>
          <div className="nav-links">
            <button className={`nav-link ${currentPage === "home" ? "active" : ""}`} onClick={() => setCurrentPage("home")}>Dashboard</button>
            <button className={`nav-link ${currentPage === "about" ? "active" : ""}`} onClick={() => setCurrentPage("about")}>About</button>
            <button className={`nav-link ${currentPage === "contact" ? "active" : ""}`} onClick={() => setCurrentPage("contact")}>Contact</button>
          </div>
        </div>
      </nav>

      {currentPage === "about" && <AboutPage onNavigate={setCurrentPage} />}
      {currentPage === "contact" && <ContactPage onNavigate={setCurrentPage} />}

      {currentPage === "home" && (
        <main className="main">
          <section className="hero" aria-labelledby="main-heading">
            <div className="hero-eyebrow">AI-Powered · Data-Driven · Actionable</div>
            <h1 id="main-heading" className="hero-title">
              Finsight – <em>Your AI-Powered</em><br />SEO Dashboard
            </h1>
            <p className="hero-sub">
              Upload financial statements and documents to receive deep, structured SEO analysis powered by cutting-edge AI. Built for teams who demand precision.
            </p>
            <div className="hero-stats">
              <div className="stat"><span className="stat-num">90%</span><span className="stat-label">of top-ranked pages use structured data</span></div>
              <div className="stat-divider" />
              <div className="stat"><span className="stat-num">3×</span><span className="stat-label">more AI citations with E-E-A-T signals</span></div>
              <div className="stat-divider" />
              <div className="stat"><span className="stat-num">40%</span><span className="stat-label">visibility boost via GEO methods</span></div>
            </div>
          </section>

          <section className="tool-section" aria-label="Document analysis tool">
            <div className="tool-card">
              <div className="tool-header">
                <h2 className="tool-title">Analyze Your Documents</h2>
                <p className="tool-desc">Upload a PDF or financial report. Our AI extracts SEO signals, keyword opportunities, and performance gaps instantly.</p>
              </div>
              <div className="upload-zone">
                <label className="upload-label" htmlFor="file-input">
                  <span className="upload-icon">📄</span>
                  <span className="upload-text">{file ? file.name : "Drop your file here or click to browse"}</span>
                  <input id="file-input" type="file" className="upload-input" onChange={(e) => setFile(e.target.files?.[0] || null)} />
                </label>
              </div>
              <button className={`analyze-btn ${loading ? "loading" : ""}`} onClick={handleUpload} disabled={loading} aria-busy={loading}>
                {loading ? <><span className="spinner" /> Analyzing…</> : "Analyze Financials →"}
              </button>
              {result && (
                <div className="result-box" role="region" aria-label="Analysis result">
                  <h3 className="result-title">AI Analysis</h3>
                  <pre className="result-content">{result}</pre>
                </div>
              )}
            </div>
          </section>

          <section className="geo-section" aria-labelledby="geo-heading">
            <h2 id="geo-heading" className="section-title">Why Structured SEO Intelligence Matters</h2>
            <div className="geo-grid">
              <article className="geo-card">
                <span className="geo-icon">🔍</span>
                <h3>Structured Data Dominance</h3>
                <p>According to <cite><a href="https://developers.google.com/search/docs/appearance/structured-data/intro-structured-data" target="_blank" rel="noopener noreferrer">Google Search Central</a></cite>, pages with structured data (JSON-LD schema) are significantly more likely to earn rich results in SERPs. Studies show <strong>90% of top-ranked pages</strong> implement structured data markup.</p>
              </article>
              <article className="geo-card">
                <span className="geo-icon">📈</span>
                <h3>Link Authority & AI Visibility</h3>
                <p>Research from <cite><a href="https://moz.com/learn/seo/domain-authority" target="_blank" rel="noopener noreferrer">Moz's Domain Authority study</a></cite> confirms that referring domain count is one of the strongest predictors of organic ranking. Pages with <strong>20+ referring domains</strong> rank in top 3 positions 4× more often.</p>
              </article>
              <article className="geo-card">
                <span className="geo-icon">🤖</span>
                <h3>Generative Engine Optimization</h3>
                <p>The <cite><a href="https://arxiv.org/abs/2306.00937" target="_blank" rel="noopener noreferrer">Princeton GEO Model (2023)</a></cite> demonstrates that authoritative citations and statistics in page content can increase AI engine visibility by up to <strong>40%</strong>. FAQ schema alone yields a <strong>30% uplift</strong> in AI citation rates.</p>
              </article>
            </div>
            <blockquote className="expert-quote">
              <p>"The future of SEO is not just about ranking on Google — it's about being cited by AI. Pages that demonstrate genuine expertise, authoritative citations, and structured content will win in both traditional and generative search."</p>
              <footer>— <cite>Rand Fishkin</cite>, Founder of Moz & SparkToro</footer>
            </blockquote>
          </section>

          <section className="features-section" aria-labelledby="features-heading">
            <h2 id="features-heading" className="section-title">Everything You Need to Dominate SEO</h2>
            <div className="features-grid">
              {[
                { icon: "⚡", title: "Instant AI Analysis", desc: "Upload any document and get structured SEO insights in seconds." },
                { icon: "🎯", title: "Keyword Intelligence", desc: "Identify high-impact keyword gaps your competitors are missing." },
                { icon: "🔗", title: "Backlink Scoring", desc: "Evaluate link quality with DR-weighted authority metrics." },
                { icon: "📊", title: "Performance Dashboard", desc: "Track ranking movements, traffic trends, and visibility scores." },
                { icon: "🤖", title: "GEO Readiness", desc: "Measure and improve your AI engine citation potential." },
                { icon: "📋", title: "Actionable Reports", desc: "Get prioritized recommendations with estimated impact scores." },
              ].map((f) => (
                <div className="feature-card" key={f.title}>
                  <span className="feature-icon">{f.icon}</span>
                  <h3 className="feature-title">{f.title}</h3>
                  <p className="feature-desc">{f.desc}</p>
                </div>
              ))}
            </div>
          </section>
        </main>
      )}

      <footer className="footer">
        <div className="footer-inner">
          <div className="footer-brand">
            <span className="logo-mark small">F</span>
            <span className="logo-text">insight</span>
            <p className="footer-tagline">AI-powered SEO analytics for the modern web.</p>
          </div>
          <nav className="footer-nav" aria-label="Footer navigation">
            <button className="footer-link" onClick={() => setCurrentPage("about")}>About</button>
            <button className="footer-link" onClick={() => setCurrentPage("contact")}>Contact</button>
            <a className="footer-link" href="https://developers.google.com/search/docs" target="_blank" rel="noopener noreferrer">Google Search Central</a>
            <a className="footer-link" href="https://moz.com/learn/seo" target="_blank" rel="noopener noreferrer">Moz SEO Guide</a>
          </nav>
          <p className="footer-copy">© {new Date().getFullYear()} Finsight. Built with transparency & authority.</p>
        </div>
      </footer>
      <Analytics />
    </>
  );
}
