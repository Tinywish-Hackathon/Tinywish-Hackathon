# TinyWish — Autonomous Scholarship Discovery & Application Agent

An AI-powered agent that discovers, ranks, and applies to scholarships on behalf of students. Built for the TinyFish Hackathon.

## What It Does

1. **Discovers** scholarships from multiple sources (NSP, Buddy4Study, Startup India, etc.)
2. **Matches** schemes against a student profile (state, category, income, course level)
3. **Ranks** results using TinyFish AI + rule-based scoring with deadline awareness
4. **Decides** the best execution strategy per scheme — not blind automation, but intelligent decision-making:
   - `FULL_APPLY` → direct form exists, go for it
   - `EXTRACT_ONLY` → login wall detected, gather requirements and stop
   - `SKIP` → expired or no actionable path
5. **Hands off** to the student with a pre-filled guide: fields, documents, steps, and the best apply link

## Quick Start

```bash
pip install -r requirements.txt
```

Set your API key in `.env`:
```
TINYFISH_API_KEY=your_key_here
```

Add your profile to `profile.json`:
```json
{
  "full_name": "Your Name",
  "state": "Your State",
  "category": "OBC",
  "annual_income": 250000,
  "course_level": "undergraduate"
}
```

Run discovery:
```bash
python main.py --discover --mode agent
```

Demo mode (prioritizes low-friction, direct-apply schemes):
```bash
python main.py --discover --mode demo --demo-mode
```

## Architecture

```
main.py                  → CLI entry point, strategy engine
core/
  application_agent.py   → TinyFish-powered application execution
  discovery/
    ranking.py           → AI + rule-based scheme ranking
    eligibility.py       → Profile-to-scheme matching
    multi_source.py      → Multi-portal scraper orchestration
  integrations/
    tinyfish_client.py   → TinyFish SDK wrapper
schemas/
  scheme_model.py        → Pydantic data model
sites/                   → Per-portal configs (NSP, Startup India)
utils/                   → Logger, tracker, helpers
```

## Key Design Decisions

- **Strategy-first execution** — the agent explicitly chooses HOW to act before acting
- **Login wall detection** — stops automation at auth boundaries, switches to intelligence-gathering mode
- **Demo mode** — deprioritizes government OTP/login flows, boosts private portals and direct forms
- **Source diversity** — ranking ensures multiple scholarship sources appear in results, not just one portal

## Built With

- [TinyFish AI](https://tinyfish.ai) — web automation & intelligent ranking
- [Playwright](https://playwright.dev) — browser automation fallback
- [Pydantic](https://docs.pydantic.dev) — data validation
- Python 3.11+
