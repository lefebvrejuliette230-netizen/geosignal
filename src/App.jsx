import { useState, useEffect } from 'react'
import './App.css'

const API_BASE = import.meta.env.VITE_API_BASE || 'http://localhost:5001'

function RiskBadge({ score }) {
  const level = score > 70 ? 'high' : score > 40 ? 'medium' : 'low'
  const label = score > 70 ? 'HIGH' : score > 40 ? 'MEDIUM' : 'LOW'
  return (
    <span className={`risk-badge risk-${level}`}>
      {label} {score}
    </span>
  )
}

function AlertCard({ article }) {
  return (
    <article className={`alert-card ${article.flagged ? 'flagged' : ''}`}>
      <div className="alert-header">
        <RiskBadge score={article.score} />
        <span className="alert-source">{article.source}</span>
      </div>
      <h3 className="alert-title">
        <a href={article.url} target="_blank" rel="noopener noreferrer">
          {article.title}
        </a>
      </h3>
      {article.description && (
        <p className="alert-description">{article.description}</p>
      )}
      <time className="alert-time">
        {article.publishedAt
          ? new Date(article.publishedAt).toLocaleString()
          : ''}
      </time>
    </article>
  )
}

function SubscribeForm() {
  const [email, setEmail] = useState('')
  const [status, setStatus] = useState(null) // 'success' | 'error' | null
  const [message, setMessage] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    setLoading(true)
    setStatus(null)

    try {
      const res = await fetch(`${API_BASE}/subscribe`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      })
      const data = await res.json()
      setStatus(res.ok ? 'success' : 'error')
      setMessage(data.message || data.error)
      if (res.ok) setEmail('')
    } catch {
      setStatus('error')
      setMessage('Could not reach the server. Is the backend running?')
    } finally {
      setLoading(false)
    }
  }

  return (
    <form className="subscribe-form" onSubmit={handleSubmit}>
      <label htmlFor="email-input" className="subscribe-label">
        Get email alerts for high-risk events
      </label>
      <div className="subscribe-row">
        <input
          id="email-input"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder="you@example.com"
          required
          disabled={loading}
          className="subscribe-input"
        />
        <button type="submit" disabled={loading} className="subscribe-btn">
          {loading ? 'Subscribing…' : 'Subscribe'}
        </button>
      </div>
      {status && (
        <p className={`subscribe-feedback ${status}`}>{message}</p>
      )}
    </form>
  )
}

export default function App() {
  const [alerts, setAlerts] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    fetch(`${API_BASE}/api/alerts`)
      .then((res) => {
        if (!res.ok) throw new Error('Failed to load alerts')
        return res.json()
      })
      .then((data) => {
        setAlerts(data)
        setLoading(false)
      })
      .catch((err) => {
        setError(err.message)
        setLoading(false)
      })
  }, [])

  const highRisk = alerts.filter((a) => a.flagged)
  const rest = alerts.filter((a) => !a.flagged)

  return (
    <div className="layout">
      <header className="site-header">
        <div className="header-inner">
          <div className="brand">
            <span className="brand-icon">◈</span>
            <span className="brand-name">GeoSignal</span>
          </div>
          <p className="brand-tagline">
            AI-powered geopolitical risk intelligence, updated hourly
          </p>
        </div>
        <SubscribeForm />
      </header>

      <main className="main">
        {loading && <p className="state-msg">Loading intelligence feed…</p>}
        {error && (
          <p className="state-msg error">
            {error}. Make sure <code>python app.py</code> is running.
          </p>
        )}

        {!loading && !error && alerts.length === 0 && (
          <p className="state-msg">
            No alerts yet. The first fetch runs on backend startup.
          </p>
        )}

        {highRisk.length > 0 && (
          <section className="alert-section">
            <h2 className="section-title high">High-Risk Alerts</h2>
            <div className="alert-grid">
              {highRisk.map((a, i) => (
                <AlertCard key={i} article={a} />
              ))}
            </div>
          </section>
        )}

        {rest.length > 0 && (
          <section className="alert-section">
            <h2 className="section-title">Latest Signals</h2>
            <div className="alert-grid">
              {rest.map((a, i) => (
                <AlertCard key={i} article={a} />
              ))}
            </div>
          </section>
        )}
      </main>

      <footer className="site-footer">
        Powered by NewsAPI · Groq / LLaMA · SendGrid
      </footer>
    </div>
  )
}
