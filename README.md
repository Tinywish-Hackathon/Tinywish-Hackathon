<div align="center">
  <h1>🚀 FundPilot</h1>
  <p><b>Autonomous Application & Discovery Engine for Grants, Scholarships, and Schemes</b></p>
</div>

---

**FundPilot** is an intelligent execution engine designed to autonomously navigate, evaluate, and apply for complex funding opportunities. Built to bridge the gap between discovery and execution, it handles everything from student scholarships to tier-1 startup grants. 

Unlike traditional RPA or blind web scrapers, FundPilot uses an intent-driven architecture to dynamically adapt to varying authentication walls, portal structures, and application forms.

## ✨ Core Capabilities

1. 🔍 **Multi-Source Discovery Orchestration**: Simultaneously queries and scrapes diverse data sources, from strict government portals (e.g., NSP, Startup India) to private enterprise platforms.
2. 🎯 **Algorithmic Eligibility Matching**: Cross-references parsed schemes against a structured user profile (`profile.json`) to accurately determine eligibility before wasting computational cycles.
3. 🥇 **AI-Driven Ranking System**: Scores schemes dynamically using TinyFish AI and heuristic models, prioritizing actionable applications with approaching deadlines.
4. 🧠 **Adaptive Execution Strategy**: Evaluates the application path in real-time to determine the optimal interaction mode:
   - 🟢 `FULL_APPLY`: Automates the entire form submission end-to-end.
   - 🟡 `EXTRACT_ONLY`: Detects complex auth (OTP/Captcha) or login walls, extracts requirements, and transitions seamlessly to intelligence-gathering mode.
   - 🔴 `SKIP`: Pre-emptively filters out closed, expired, or irrelevant schemes.
5. 🤝 **Deterministic Handoffs**: Generates structured, pre-filled guides with extracted fields and fallback manual links when fully autonomous execution is intentionally bypassed.

## 🚀 Quick Start

### 1. Installation

Requires Python 3.11+.

```bash
git clone https://github.com/yourusername/fundpilot.git
cd fundpilot
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Identity Configuration

Set up your `profile.json` to define the target applicant (supports both student and founder personas):

```json
{
  "full_name": "Applicant Name / Startup Name",
  "state": "State",
  "category": "General / OBC / SC / ST / Startup",
  "annual_income": 250000,
  "course_level": "undergraduate",
  "funding_type": ["scholarship", "startup_grant"]
}
```

Configure your environment variables securely in `.env`:

```env
TINYFISH_API_KEY=your_key_here
```

### 3. Execution Interfaces

**Autonomous Target Discovery:**
Initiates the scrape → match → rank cycle.
```bash
python main.py --discover --mode agent
```

**Targeted Application Fallback (Local Flow):**
Forces the system into a local browser context using Playwright.
```bash
python main.py --apply
```

**View Application History:**
Reads local state persistence via `applications.db`.
```bash
python main.py --history
```

*(Note: Use the `--demo-mode` flag combined with `--discover` for curated application paths that prioritize live demonstrations by bypassing rigid government portals.)*

## 🏗️ System Architecture

FundPilot utilizes a modular, decoupled structure allowing for highly robust runtimes and easy scalability.

```text
fundpilot/
├── main.py                  # Stateful CLI & execution orchestrator
├── applications.db          # Local SQLite persistence for tracking state
├── core/
│   ├── application_agent.py # TinyFish-powered form execution subengine
│   └── discovery/
│       ├── ranking.py       # Algorithmic & AI-based scheme scoring
│       ├── eligibility.py   # Deterministic profile-to-scheme matching
│       └── multi_source.py  # Portal scraper multiplexer
├── executor/                # Browser automation (Playwright local fallback)
├── extractor/               # DOM traversal and field extraction logic
├── mapper/                  # Profile schemas -> Form field mappers
├── schemas/                 # Strict Pydantic validation models
├── sites/                   # Deterministic portal configs (NSP, Startup India)
└── utils/                   # Telemetry, trackers, and structured loggers
```

## 🛠️ Key Design Principles

- **Intent-Driven Over Deterministic Scripting**: Relies on semantic signals rather than rigid CSS selectors to navigate forms, preventing silent failures on UI updates.
- **Fail-Safe Auth Handling**: Intentionally short-circuits execution before strict auth boundaries (like CAPTCHAs or OTPs) to prevent bot blacklisting, escalating gracefully to the human operator.
- **Pluggable Integrations**: The `sites/` directory allows for immediate integration of new funding platforms without modifying the core orchestration logic.

## 💻 Tech Stack & Substrate

- **[TinyFish AI](https://tinyfish.ai)** — Cognitive web automation & heuristic ranking
- **[Playwright](https://playwright.dev)** — Headless browser execution environment
- **[Pydantic](https://docs.pydantic.dev)** — Type-safe data validation
- **[BeautifulSoup4](https://beautiful-soup-4.readthedocs.io)** — HTML parsing
- **SQLite3** — Embedded state management

---
<div align="center">
  <i>FundPilot: Bridging the execution gap in funding discovery.</i>
</div>
