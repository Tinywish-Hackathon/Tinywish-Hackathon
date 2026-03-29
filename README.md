<div align="center">
  <h1>🚀 FundPilot</h1>
  <p><b>Autonomous Discovery & Application Agent for Grants, Scholarships & Schemes</b></p>
  <p>
    Built for the TinyFish Hackathon 🐠
  </p>
</div>

---

**FundPilot** is an intelligent execution engine that autonomously discovers, evaluates, and applies to funding opportunities—whether you're a student looking for scholarships or a founder seeking startup grants. 

Instead of blind automation, FundPilot acts as a strategic co-pilot. It navigates complex government portals and private platforms, determines the optimal application strategy, and seamlessly bridges the gap between discovery and execution.

## ✨ What It Does

1. 🔍 **Multi-Source Discovery**: Scans diverse funding sources, from government platforms (NSP, Startup India) to private portals (Buddy4Study).
2. 🎯 **Intelligent Matching**: Cross-references opportunities against your detailed profile (demographics, income, business stage, education).
3. 🥇 **AI-Driven Ranking**: Evaluates and scores schemes using TinyFish AI, prioritizing deadlines and high-probability matches.
4. 🧠 **Strategic Execution Engine**: Makes real-time decisions on the best way to handle each opportunity:
   - 🟢 `FULL_APPLY`: Direct form available? The agent auto-fills and submits.
   - 🟡 `EXTRACT_ONLY`: Hits a login wall or complex auth? Gathers full requirements, eligibility, and links, then gracefully alerts you.
   - 🔴 `SKIP`: Expired or irrelevant schemes are aggressively filtered out.
5. 🤝 **Frictionless Handoff**: Generates a pre-filled, comprehensive guide containing the exact steps, required documents, and direct links for any manual steps.

## 🚀 Quick Start

### 1. Installation

```bash
git clone https://github.com/yourusername/fundpilot.git
cd fundpilot
pip install -r requirements.txt
```

### 2. Configuration

Create a `.env` file in the root directory and add your TinyFish API key:

```env
TINYFISH_API_KEY=your_key_here
```

Set up your profile in `profile.json`. (Supports both student and startup founder profiles):

```json
{
  "full_name": "Your Name / Startup Name",
  "state": "Your State",
  "category": "OBC / General / SC / ST / Startup",
  "annual_income": 250000,
  "course_level": "undergraduate",
  "funding_type": ["scholarship", "startup_grant"]
}
```

### 3. Usage

**Run standard discovery mode:**
```bash
python main.py --discover --mode agent
```

**Run Demo Mode:**
*(Prioritizes low-friction, direct-apply schemes for seamless live demonstrations without complex government OTPs)*
```bash
python main.py --discover --mode demo --demo-mode
```

## 🏗️ Architecture Under the Hood

```text
fundpilot/
├── main.py                  # CLI entry point & global strategy orchestrator
├── core/
│   ├── application_agent.py # TinyFish-powered form execution
│   └── discovery/
│       ├── ranking.py       # Algorithmic & AI-based scheme scoring
│       ├── eligibility.py   # Profile-to-scheme matching engine
│       └── multi_source.py  # Orchestrator for various portal scrapers
├── integrations/
│   └── tinyfish_client.py   # Wrapper for TinyFish SDK interactions
├── schemas/
│   └── scheme_model.py      # Strict Pydantic data models for validation
└── utils/                   # Standard loggers, trackers, and helpers
```

## 🛠️ Key Design Decisions

- **Intent-Driven Execution**: The agent doesn't just click blindly; it explicitly decides *how* to approach a form based on context.
- **Graceful Auth Handling**: It detects login boundaries and OTP walls, switching seamlessly into intelligence-gathering mode rather than failing.
- **Optimized Demo Path**: Easily toggleable modes to bypass rigid government portals in favor of smooth, private applications during showcases.
- **Agnostic Sourcing**: Built to aggregate and rank funding from a vast array of sources, preventing single-platform dependency.

## 💻 Tech Stack

- **[TinyFish AI](https://tinyfish.ai)** — Cognitive web automation & intelligent ranking
- **[Playwright](https://playwright.dev)** — Bulletproof browser automation fallback
- **[Pydantic](https://docs.pydantic.dev)** — Type-safe data validation
- **Python 3.11+** — Core runtime

---
<div align="center">
  <i>Empowering builders and learners to secure funding without the friction.</i>
</div>
