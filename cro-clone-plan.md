# CRO AI Clone — Project Plan

> **Objective**: Build an AI system that captures, replicates, and scales the CRO's decision-making across all revenue processes — pre-sales, sales, partnerships, renewals, and beyond.

---

## What We're Building

An AI assistant trained on the CRO's meeting transcripts, documents, decisions, and reasoning patterns — capable of reviewing deals, evaluating partners, challenging forecasts, and guiding reps the same way the CRO would, at scale and on demand.

---

## Sub-Project Status: Account Review App (Project Dolly v1) — COMPLETE

The Account Review Streamlit app is **finished**. It:

- Reads multi-regional account planning data from Google Sheets (Maps, Tech Stake, Summary tabs)
- Applies NRR/threading/expansion scoring with configurable weights
- Generates CRO-voiced comments via Claude (Sonnet or Opus, user-selectable)
- Provides a 3-step human-in-the-loop review workflow:
  1. **Portfolio Summary** — regional overview comments
  2. **Account Reviews** — per-account CRO comments (sorted by MRR, filterable by tier/region/AE)
  3. **Tech Stack Reviews** — vendor gap analysis comments
- Saves all review decisions to local JSON sessions (resumable)
- Generates downloadable Markdown executive reports

**Scope decision:** The app does **not** write comments back to Google Sheets. Comments are generated, reviewed, and approved within the app only. Write-back was explored but removed from scope.

---

## Phase 1: Knowledge Capture *(Weeks 1–6)*

The foundation of the entire system. Nothing can be built without this.

### 1.1 Meeting Intelligence
- Enable **full verbatim transcripts** in Google Workspace admin (we already use Gemini in Meet)
- Create a structured **Google Drive folder** to store and organize transcripts by process type
- Tag each transcript: deal stage, process type, outcome

> Gemini handles capture. A lightweight pipeline (Zapier or custom script) moves transcripts into the knowledge base automatically.

### 1.2 Artifact Collection
Everything the CRO has written, annotated, or approved:
- CRM deal notes and annotations
- Pricing and discount approval history
- Proposal redlines and email threads
- Forecast call notes
- Partner evaluation scorecards
- Any existing playbooks or frameworks

### 1.3 Structured Interviews
10–15 hours of dedicated sessions with the CRO, covering each major process:
- How he qualifies and reviews deals at each stage
- What makes him approve or reject a discount
- How he evaluates partner opportunities
- How he challenges forecast calls
- When and why he gets involved in pre-sales

All sessions recorded, transcribed, and labeled.

---

## Phase 2: Decision Framework Extraction *(Weeks 4–8)*

Running in parallel with Phase 1 as data accumulates.

### 2.1 Per-Process Decision Models
For every process he touches, document explicitly:

```
TRIGGER   → What brings him in?
INPUTS    → What data does he look at?
QUESTIONS → What does he always ask?
LOGIC     → How does he reason through it?
OUTPUT    → What decision or recommendation does he make?
EXCEPTIONS → When does he override the default?
```

### 2.2 Scoring Rubrics
Extract his real criteria (not the official playbook) for:
- Deal qualification
- Discount approval thresholds
- Partner quality scoring
- Forecast confidence adjustments
- Risk signals at each deal stage

### 2.3 Communication Style
Capture how he frames decisions, coaches reps, and challenges assumptions — so the AI communicates in his voice.

---

## Phase 3: Build the AI System *(Weeks 6–14)*

### 3.1 Vector Knowledge Base
Once 4–6 weeks of transcripts and artifacts are collected:
- Ingest all documents and transcripts
- Chunk, embed, and store in a vector database
- Query layer retrieves relevant context before any AI response
- Continuously updated as new meetings are recorded

**Tools**: Pinecone or Weaviate (vector DB) + LlamaIndex or LangChain (orchestration)

### 3.2 LLM Backbone
- **Base model**: Claude (Anthropic) or GPT-4o (OpenAI)
- **Architecture**: RAG (Retrieval-Augmented Generation) — the AI retrieves relevant knowledge from the CRO's data before generating any response
- Specialized prompt layers per process area

### 3.3 Process-Specific AI Modules

| Module | What It Does |
|---|---|
| **Deal Review Agent** | Reviews deals at any stage using his qualification logic |
| **Pricing / Discount Agent** | Evaluates discount requests using his approval patterns |
| **Forecast Review Agent** | Challenges or validates pipeline calls as he would |
| **Partner Evaluation Agent** | Scores partner opportunities using his criteria |
| **Pre-Sales Advisory Agent** | Guides SEs and AEs on complex deals using his input patterns |
| **Meeting Co-Pilot** | Surfaces his questions and flags in real time during calls |
| **Renewal / Expansion Agent** | Identifies risks and opportunities using his lens |

---

## Phase 4: Integrations *(Weeks 10–16)*

### Data Sources
| System | Purpose |
|---|---|
| CRM (Salesforce / HubSpot) | Deal data, account history, stage history, approval notes |
| Product Analytics (Amplitude / Mixpanel) | Usage data, feature adoption, login activity |
| Google Meet + Gemini | Live and recorded call transcripts |
| Partner Portal | Deal registrations, co-sell activity |
| Billing / Finance | Contract values, discount history, renewal dates |
| Forecast Tool (Clari / native CRM) | Pipeline data, rep-level forecasts |

### User-Facing Surfaces
| Surface | Use Case |
|---|---|
| **Slack bot** | Reps ask questions, get CRO-style answers instantly |
| **CRM sidebar** | AI commentary on any deal or account, inline |
| **Meeting co-pilot** | Real-time prompts and flags during live calls |
| **Deal desk workflow** | Auto-review of approval requests before escalation |
| **Weekly digest** | CRO-style pipeline and forecast commentary to leadership |

---

## Phase 5: Calibration & Rollout *(Weeks 14–22)*

### 5.1 Shadow Mode (6–8 weeks)
- AI runs in parallel with the real CRO on every process
- Outputs compared — where does the AI agree vs. disagree?
- Target: **>80% alignment** before trusting autonomously

### 5.2 Disagreement as Training Signal
Every time the CRO corrects the AI:
- Capture the correction and his reasoning
- Update the knowledge base and decision frameworks

### 5.3 Phased Sign-Off by Process
| Wave | Processes |
|---|---|
| Wave 1 | Meeting summaries, deal commentary, account flags |
| Wave 2 | Partner evaluations, pre-sales guidance |
| Wave 3 | Discount reviews, forecast challenges |

---

## Phase 6: Ongoing Maintenance

- **Weekly**: CRO reviews a sample of AI outputs and flags disagreements
- **Monthly**: New transcripts ingested, frameworks updated
- **Quarterly**: Decision rubrics reviewed as strategy evolves
- **Continuous**: Drift detection — monitor when AI recommendations diverge from actual outcomes

---

## Sub-Project: Partner Email Generator (Dolly Outreach)

> **Objective**: Generate weekly CRO-voiced partner emails — drafted by AI in Serhat's tone, reviewed and sent by Serhat himself.

### What It Is

A lightweight, standalone module under the Dolly umbrella. AEs and CSMs submit partner names (and optional context like relationship status, recent meetings, or deal stage), and the system drafts personalized outreach emails in Serhat's voice. No scoring, no data pipelines — just high-quality writing that sounds like Serhat wrote it himself.

### Cadence

4 partner emails per week. AEs/CSMs provide the partner names and any relevant context; the AI drafts; Serhat reviews, edits if needed, and sends.

### How It Works

```
AE/CSM submits partner name + optional context (Slack, form, or simple UI)
    ↓
Partner Email Generator pulls Serhat's voice profile (cro_persona.yaml + cro_tone_profile.yaml)
    ↓
Claude drafts a personalized partner email using:
  - Partner name and company
  - Any context provided by AE/CSM (relationship notes, recent activity, goal of outreach)
  - Serhat's communication style, vocabulary, and tone
    ↓
Serhat reviews the draft in a simple UI or receives it via email/Slack
    ↓
Serhat edits (if needed) → sends directly
```

### Input

| Field | Required? | Source |
|---|---|---|
| Partner company name | Yes | AE/CSM |
| Contact name + title | Yes | AE/CSM |
| Context / goal of the email | Optional | AE/CSM (e.g., "re-engage after quiet Q4", "intro after partner event", "follow up on co-sell opportunity") |
| Relationship history | Optional | AE/CSM or CRM if integrated later |

### Email Types (Initial Scope)

| Type | Description |
|---|---|
| Warm intro / first touch | CRO reaching out to a new partner contact |
| Re-engagement | Reviving a quiet or dormant partner relationship |
| Follow-up | After a meeting, event, or milestone |
| Strategic alignment | Proposing a co-sell, joint initiative, or deeper collaboration |

### Voice & Tone

Reuses the same CRO voice infrastructure already built for Project Dolly (Account Review):
- `cro_persona.yaml` — Serhat's philosophy, title, framing
- `cro_tone_profile.yaml` — sentence patterns, vocabulary, action orientation extracted from his real writing
- Prompt templates specific to partner emails (new `partner_email_templates.yaml`)

### Technical Approach

- **Standalone app or new tab** within the Dolly ecosystem (TBD — could be a simple Streamlit page, a Slack workflow, or a lightweight web form)
- **No data pipeline required** — input is manual (partner name + context from AE/CSM)
- **Same Claude API integration** as account review (src/llm/client.py with retry logic)
- **New prompt templates** tailored to partner outreach (different from account review prompts)
- **Draft history** saved locally (JSON or simple DB) so Serhat can reference past emails to the same partner

### Build Estimate

| Item | Estimate | Notes |
|---|---|---|
| Prompt template design | 1–2 days | Partner-specific templates + few-shot examples |
| UI / input form | 1–2 days | Simple form: partner name, contact, context, email type |
| Draft generation + review flow | 1–2 days | Generate → preview → edit → copy/send |
| Voice calibration for partner tone | 1 day | May need additional tone examples beyond account review voice |
| **Total** | **4–7 days** | Leverages existing Dolly infrastructure |

### Open Questions for Serhat

- Should the email drafts be delivered via the Streamlit app, Slack, or email?
- Are there specific partner email examples we can use for tone calibration (similar to how we used "Next Steps" for account comments)?
- Should the system track which partners have been emailed and when, or is that handled elsewhere?
- Any standard email structure preferences (e.g., always open with a specific kind of hook, always include a CTA)?

---

## Timeline Summary

| Phase | Weeks |
|---|---|
| Meeting capture setup + artifact collection | 1–2 |
| Structured interviews + framework extraction | 2–8 |
| Vector DB build + RAG pipeline | 6–10 |
| Module development + integrations | 10–16 |
| Shadow mode calibration | 14–20 |
| Phased rollout to team | 18+ |

---

## Cost Estimate

### One-Time Build Costs

| Item | Low | High | Notes |
|---|---|---|---|
| Engineering (design, build, integrate) | $50,000 | $120,000 | 400–600 hrs at $100–200/hr; lower if internal team |
| Structured interviews + framework extraction | $5,000 | $15,000 | Facilitation + documentation |
| Data pipeline setup (Zapier / custom) | $2,000 | $8,000 | Connecting Meet → Drive → vector DB |
| **Total one-time** | **$57,000** | **$143,000** | |

> If using an internal engineering team, one-time costs drop significantly. The range above assumes a mix of internal and external resources.

### Monthly Running Costs

| Item | Low | High | Notes |
|---|---|---|---|
| LLM API (Claude / GPT-4o) | $500 | $3,000 | Scales with query volume |
| Vector DB (Pinecone / Weaviate) | $70 | $400 | Scales with data volume |
| Data pipeline (Zapier / Make) | $50 | $200 | |
| Engineering maintenance | $2,000 | $6,000 | ~20–40 hrs/month |
| **Total monthly** | **$2,620** | **$9,600** | |

### Year 1 Total Estimate

| Scenario | Cost |
|---|---|
| **Conservative** (internal team, lean build) | ~$90,000 |
| **Mid-range** (mixed internal/external) | ~$160,000 |
| **Full external build** | ~$255,000 |

### What's Already Paid For
- **Google Gemini** meeting transcription — included in your existing Google Workspace plan
- **CRM** — already licensed
- **Product analytics** — already licensed

---

## Immediate Next Steps

1. **Enable full transcripts** in Google Workspace admin settings
2. **Create a Google Drive folder structure** for transcript organization
3. **Schedule structured interview sessions** with the CRO (block 10–15 hrs over 3–4 weeks)
4. **Begin artifact collection** — CRM notes, emails, Slack, existing playbooks
5. **Map every process** the CRO is involved in (this will determine exact module scope)
6. **Partner Email Generator** — Collect 5–10 sample partner emails from Serhat for tone calibration; design prompt templates; build input form and draft review flow

---

## Key Risks

| Risk | Mitigation |
|---|---|
| CRO doesn't have bandwidth for interviews | Schedule in short 45-min blocks over several weeks |
| Transcripts lack enough decision-level detail | Supplement with 1:1 shadow sessions |
| AI drifts as strategy evolves | Quarterly rubric reviews + continuous feedback loop |
| Over-reliance on AI for high-stakes decisions | Keep CRO in the loop for Wave 3 processes until confidence is high |
| Data quality is inconsistent early on | Start with most structured processes first |
| Partner emails sound generic without enough context | Require AEs/CSMs to provide at least a one-line context; build a "context prompt" to guide them |

---

*This document is a living plan and will be refined once a full map of the CRO's process involvement is completed.*
