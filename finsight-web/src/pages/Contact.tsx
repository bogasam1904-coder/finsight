import { useState } from "react";

type Page = "home" | "about" | "contact";

interface Props {
  onNavigate: (page: Page) => void;
}

export default function ContactPage({ onNavigate }: Props) {
  const [submitted, setSubmitted] = useState(false);
  const [form, setForm] = useState({ name: "", email: "", subject: "", message: "" });

  const handleSubmit = (e: React.MouseEvent) => {
    e.preventDefault();
    if (!form.name || !form.email || !form.message) {
      alert("Please fill in all required fields.");
      return;
    }
    setSubmitted(true);
  };

  return (
    <main className="main page-content">
      <section className="page-hero">
        <div className="page-eyebrow">We'd love to hear from you</div>
        <h1 className="page-title">Contact Finsight</h1>
        <p className="page-subtitle">
          Have a question, partnership inquiry, or want to contribute a guest article?
          Reach out — we respond within 24 hours.
        </p>
      </section>

      <section className="contact-section">
        <div className="contact-grid">
          {/* Contact Info */}
          <div className="contact-info">
            <h2>Get in Touch</h2>

            <div className="contact-item">
              <span className="contact-icon">🌐</span>
              <div>
                <strong>Website</strong>
                <p><a href="https://finsight-vert.vercel.app" target="_blank" rel="noopener noreferrer">finsight-vert.vercel.app</a></p>
              </div>
            </div>

            <div className="contact-item">
              <span className="contact-icon">💻</span>
              <div>
                <strong>GitHub</strong>
                <p><a href="https://github.com/bogasam1904-coder/finsight" target="_blank" rel="noopener noreferrer">bogasam1904-coder/finsight</a></p>
              </div>
            </div>

            <div className="contact-item">
              <span className="contact-icon">📝</span>
              <div>
                <strong>Guest Posts & Backlinks</strong>
                <p>We welcome data-driven guest articles on SEO, AI search, and GEO optimization. Articles must include citations from authoritative sources.</p>
              </div>
            </div>

            <div className="contact-item">
              <span className="contact-icon">🤝</span>
              <div>
                <strong>Partnership Inquiries</strong>
                <p>Interested in link-building partnerships, tool integrations, or co-marketing? We'd love to connect.</p>
              </div>
            </div>

            <div className="backlink-box">
              <h3>📣 Backlink & Guest Post Opportunity</h3>
              <p>
                Finsight accepts guest contributions from SEO professionals and AI researchers.
                Published articles receive a permanent do-follow backlink and promotion
                across our network. Minimum 800 words, must include at least 3 authoritative
                citations.
              </p>
              <p className="backlink-anchor">
                Natural anchor text: <strong>"AI-powered SEO dashboard"</strong> or{" "}
                <strong>"SEO analytics platform"</strong>
              </p>
            </div>
          </div>

          {/* Contact Form */}
          <div className="contact-form-wrap">
            {submitted ? (
              <div className="success-box">
                <span className="success-icon">✅</span>
                <h3>Message Sent!</h3>
                <p>Thanks for reaching out. We'll get back to you within 24 hours.</p>
                <button className="analyze-btn" onClick={() => onNavigate("home")}>
                  Back to Dashboard →
                </button>
              </div>
            ) : (
              <div className="contact-form">
                <h2>Send a Message</h2>
                <div className="form-group">
                  <label htmlFor="name">Name *</label>
                  <input id="name" type="text" placeholder="Your name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
                </div>
                <div className="form-group">
                  <label htmlFor="email">Email *</label>
                  <input id="email" type="email" placeholder="you@example.com" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
                </div>
                <div className="form-group">
                  <label htmlFor="subject">Subject</label>
                  <input id="subject" type="text" placeholder="Guest post / Partnership / Question" value={form.subject} onChange={(e) => setForm({ ...form, subject: e.target.value })} />
                </div>
                <div className="form-group">
                  <label htmlFor="message">Message *</label>
                  <textarea id="message" rows={5} placeholder="Tell us about your inquiry..." value={form.message} onChange={(e) => setForm({ ...form, message: e.target.value })} />
                </div>
                <button className="analyze-btn" onClick={handleSubmit}>
                  Send Message →
                </button>
              </div>
            )}
          </div>
        </div>
      </section>
    </main>
  );
}
