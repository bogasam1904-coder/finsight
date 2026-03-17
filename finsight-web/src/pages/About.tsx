type Page = "home" | "about" | "contact";

interface Props {
  onNavigate: (page: Page) => void;
}

export default function AboutPage({ onNavigate }: Props) {
  return (
    <main className="main page-content">
      <section className="page-hero">
        <div className="page-eyebrow">Our Story</div>
        <h1 className="page-title">About Finsight</h1>
        <p className="page-subtitle">
          We're building the most authoritative AI-powered SEO analytics platform —
          combining machine intelligence with proven SEO methodology.
        </p>
      </section>

      <section className="about-section">
        <div className="about-grid">
          <div className="about-text">
            <h2>Our Mission</h2>
            <p>
              Finsight was founded on a simple belief: every business deserves access to
              enterprise-grade SEO intelligence without the complexity or cost. By
              combining AI document analysis with structured SEO frameworks, we make
              data-driven optimization accessible to everyone.
            </p>
            <p>
              Our platform is built on the principles outlined in{" "}
              <cite>
                <a href="https://developers.google.com/search/docs/fundamentals/seo-starter-guide" target="_blank" rel="noopener noreferrer">
                  Google's SEO Starter Guide
                </a>
              </cite>{" "}
              and validated against{" "}
              <cite>
                <a href="https://moz.com/beginners-guide-to-seo" target="_blank" rel="noopener noreferrer">
                  Moz's Beginner's Guide to SEO
                </a>
              </cite>
              , ensuring every recommendation meets current best practices.
            </p>
          </div>

          <div className="about-stats-box">
            <h3>Platform at a Glance</h3>
            <ul className="about-stats-list">
              <li><strong>290+</strong> Successful deployments</li>
              <li><strong>40%</strong> Average GEO visibility lift</li>
              <li><strong>3 schemas</strong> Structured data types supported</li>
              <li><strong>Real-time</strong> AI document analysis</li>
            </ul>
          </div>
        </div>
      </section>

      <section className="team-section">
        <h2 className="section-title">Author & Credentials</h2>
        <div className="author-card">
          <div className="author-avatar">B</div>
          <div className="author-info">
            <h3 className="author-name">Bogasam1904</h3>
            <p className="author-role">Founder & Lead Developer, Finsight</p>
            <p className="author-bio">
              Full-stack developer and SEO practitioner with deep expertise in AI
              integration, React/TypeScript, and performance optimization. Built
              Finsight to bridge the gap between AI-powered document intelligence and
              modern search engine optimization — including both traditional SEO and
              emerging Generative Engine Optimization (GEO) practices.
            </p>
            <div className="author-credentials">
              <span className="credential">🏗️ React & TypeScript</span>
              <span className="credential">🤖 AI/ML Integration</span>
              <span className="credential">📊 SEO Analytics</span>
              <span className="credential">🔗 GEO Optimization</span>
            </div>
            <a
              href="https://github.com/bogasam1904-coder/finsight"
              target="_blank"
              rel="noopener noreferrer"
              className="author-link"
            >
              View on GitHub →
            </a>
          </div>
        </div>
      </section>

      <section className="methodology-section">
        <h2 className="section-title">Our Methodology</h2>
        <div className="methodology-grid">
          <div className="method-card">
            <h3>E-E-A-T Framework</h3>
            <p>
              All Finsight recommendations are grounded in Google's Experience,
              Expertise, Authoritativeness, and Trustworthiness guidelines — the
              backbone of quality search results since the Helpful Content Update.
            </p>
          </div>
          <div className="method-card">
            <h3>GEO-First Approach</h3>
            <p>
              Beyond traditional SEO, we optimize for Generative Engine Optimization —
              ensuring your content is cited by ChatGPT, Claude, Gemini, and
              Perplexity through authoritative structure and citations.
            </p>
          </div>
          <div className="method-card">
            <h3>Data-Backed Decisions</h3>
            <p>
              Every recommendation is validated against peer-reviewed research and
              industry studies. We cite our sources, always — because transparency
              builds trust in both humans and AI engines.
            </p>
          </div>
        </div>
      </section>

      <div className="page-cta">
        <button className="analyze-btn" onClick={() => onNavigate("home")}>
          Try the Dashboard →
        </button>
        <button className="secondary-btn" onClick={() => onNavigate("contact")}>
          Get in Touch
        </button>
      </div>
    </main>
  );
}
