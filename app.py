import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS
from groq import Groq
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

load_dotenv()

app = Flask(__name__)
CORS(app)

NEWSAPI_KEY = os.getenv("NEWSAPI_KEY")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
SENDGRID_API_KEY = os.getenv("SENDGRID_API_KEY")
SENDGRID_FROM_EMAIL = os.getenv("SENDGRID_FROM_EMAIL")

SUBSCRIBERS_FILE = Path("subscribers.json")
ALERT_THRESHOLD = 70
MAX_CACHED_ALERTS = 50

groq_client = Groq(api_key=GROQ_API_KEY)

# In-memory cache of scored articles
cached_alerts = []


# --------------------------------------------------------------------------- #
# Subscriber store                                                             #
# --------------------------------------------------------------------------- #

def load_subscribers():
    if not SUBSCRIBERS_FILE.exists():
        return []
    with open(SUBSCRIBERS_FILE) as f:
        return json.load(f)


def save_subscribers(subscribers):
    with open(SUBSCRIBERS_FILE, "w") as f:
        json.dump(subscribers, f, indent=2)


# --------------------------------------------------------------------------- #
# News fetching                                                                #
# --------------------------------------------------------------------------- #

GEOPOLITICAL_QUERY = (
    "war OR conflict OR sanctions OR missile OR nuclear OR coup OR invasion "
    "OR terrorism OR geopolitical OR military OR NATO OR UN Security Council"
)


def fetch_headlines():
    resp = requests.get(
        "https://newsapi.org/v2/everything",
        params={
            "q": GEOPOLITICAL_QUERY,
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": 20,
            "apiKey": NEWSAPI_KEY,
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json().get("articles", [])


# --------------------------------------------------------------------------- #
# Risk scoring via Groq / LLaMA                                               #
# --------------------------------------------------------------------------- #

SYSTEM_PROMPT = """\
You are a senior geopolitical risk analyst at a tier-1 hedge fund.
Analyze the headline and return ONLY valid JSON (no markdown):

{
  "riskScore": <number 1-100>,
  "riskLabel": "<Low|Moderate|Elevated|High|Critical>",
  "headline_summary": "<1 sentence restating the event clearly>",
  "signal": "<primary sector: ENERGY|DEFENSE|TRADE|POLITICAL|FINANCIAL|TECH>",
  "regions": ["<affected regions>"],
  "geopolitical_analysis": "<3-4 sentences explaining the geopolitical context and implications>",
  "market_impact": "<3-4 sentences on specific market movements expected>",
  "assets": [
    {"name": "<asset name>", "ticker": "<ticker>", "direction": "<UP|DOWN>", "confidence": "<HIGH|MEDIUM|LOW>"}
  ],
  "time_horizon": "<Immediate|Short-term|Medium-term|Long-term>"
}

Risk scoring: 1-25 Low, 26-45 Moderate, 46-65 Elevated, 66-85 High, 86-100 Critical\
"""


def score_article(headline, description):
    user_content = f'Analyze: "{headline}"'
    if description:
        user_content += f'\nContext: {description}'

    response = groq_client.chat.completions.create(
        model="llama-3.1-8b-instant",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        max_tokens=800,
        temperature=0.3,
    )
    raw = response.choices[0].message.content.strip()
    raw = raw.replace("```json", "").replace("```", "").strip()
    parsed = json.loads(raw)
    return parsed


# --------------------------------------------------------------------------- #
# SendGrid email alert                                                         #
# --------------------------------------------------------------------------- #

def send_alert_email(subscribers, article, score):
    if not subscribers or not SENDGRID_API_KEY:
        return

    subject = f"[GeoSignal Alert] Risk {score}/100 — {article['title'][:60]}"
    body = f"""\
<h2>GeoSignal High-Risk Alert</h2>
<p><strong>Risk Score: {score}/100</strong></p>
<h3>{article['title']}</h3>
<p>{article.get('description', '')}</p>
<p><a href="{article.get('url', '#')}">Read full article</a></p>
<hr>
<small>You're receiving this because you subscribed to GeoSignal alerts.</small>
"""

    sg = SendGridAPIClient(SENDGRID_API_KEY)
    for email in subscribers:
        message = Mail(
            from_email=SENDGRID_FROM_EMAIL,
            to_emails=email,
            subject=subject,
            html_content=body,
        )
        sg.send(message)


# --------------------------------------------------------------------------- #
# Main scheduled job                                                           #
# --------------------------------------------------------------------------- #

def fetch_and_score():
    global cached_alerts
    print(f"[{datetime.now(timezone.utc).isoformat()}] Running fetch_and_score...")

    try:
        articles = fetch_headlines()
    except Exception as e:
        print(f"NewsAPI fetch failed: {e}")
        return

    subscribers = load_subscribers()
    new_alerts = []

    for article in articles:
        title = article.get("title") or ""
        description = article.get("description") or ""

        if not title or title == "[Removed]":
            continue

        try:
            analysis = score_article(title, description)
        except Exception as e:
            print(f"Scoring failed for '{title[:50]}': {e}")
            continue

        score = min(100, max(1, int(analysis.get("riskScore", 0))))
        entry = {
            "title": title,
            "description": description,
            "url": article.get("url", ""),
            "source": article.get("source", {}).get("name", ""),
            "publishedAt": article.get("publishedAt", ""),
            "score": score,
            "riskLabel": analysis.get("riskLabel", ""),
            "signal": analysis.get("signal", ""),
            "regions": analysis.get("regions", []),
            "geopolitical_analysis": analysis.get("geopolitical_analysis", ""),
            "market_impact": analysis.get("market_impact", ""),
            "assets": analysis.get("assets", []),
            "time_horizon": analysis.get("time_horizon", ""),
            "flagged": score > ALERT_THRESHOLD,
        }
        new_alerts.append(entry)

        if score > ALERT_THRESHOLD:
            try:
                send_alert_email(subscribers, article, score)
            except Exception as e:
                print(f"SendGrid failed for '{title[:50]}': {e}")

    # Merge with cache, keep newest MAX_CACHED_ALERTS unique by title
    seen = set()
    merged = []
    for a in new_alerts + cached_alerts:
        if a["title"] not in seen:
            seen.add(a["title"])
            merged.append(a)
        if len(merged) >= MAX_CACHED_ALERTS:
            break

    cached_alerts = sorted(merged, key=lambda x: x["score"], reverse=True)
    print(f"  Scored {len(new_alerts)} articles. Cache size: {len(cached_alerts)}")


# --------------------------------------------------------------------------- #
# Routes                                                                       #
# --------------------------------------------------------------------------- #

@app.route("/api/alerts")
def get_alerts():
    return jsonify(cached_alerts)


@app.route("/subscribe", methods=["POST"])
def subscribe():
    data = request.get_json(silent=True) or {}
    email = (data.get("email") or "").strip().lower()

    if not email or "@" not in email:
        return jsonify({"error": "Invalid email address"}), 400

    subscribers = load_subscribers()
    if email in subscribers:
        return jsonify({"message": "Already subscribed"}), 200

    subscribers.append(email)
    save_subscribers(subscribers)
    return jsonify({"message": "Subscribed successfully"}), 201


# --------------------------------------------------------------------------- #
# Scheduler bootstrap                                                          #
# --------------------------------------------------------------------------- #

scheduler = BackgroundScheduler()
scheduler.add_job(fetch_and_score, "interval", hours=1, next_run_time=datetime.now(timezone.utc))
scheduler.start()

if __name__ == "__main__":
    app.run(debug=False, port=5001)
