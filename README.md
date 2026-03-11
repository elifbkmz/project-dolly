# Global Account Review Agent 🎯

**CRO Digital Twin** — A Streamlit web app that reads multi-regional Google Sheets account planning data, applies strategic scoring logic, generates AI-voiced CRO comments via Claude, and enables a one-by-one Review Card workflow with write-back to Google Sheets.

---

## Quick Start

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Set up Google Cloud credentials

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a new project (or use existing)
3. Enable **Google Drive API** and **Google Sheets API**
4. Go to **IAM & Admin → Service Accounts** → Create a service account
5. Download the JSON key file
6. **Share your Google Drive folder** with the service account email (`...@...iam.gserviceaccount.com`)

### 3. Configure secrets

Copy the template and fill in your credentials:
```bash
# .streamlit/secrets.toml is gitignored — do not commit it
```

Edit `.streamlit/secrets.toml`:
- Paste the full Google Service Account JSON
- Add your `ANTHROPIC_API_KEY`

### 4. Configure regions

Edit `config/regions.yaml`:
```yaml
drive:
  shared_folder_id: "YOUR_GOOGLE_DRIVE_FOLDER_ID"   # From the folder URL
  file_pattern_map:
    APAC:  "*APAC*"
    EMEA:  "*EMEA*"
    LATAM: "*LATAM*"
    NA:    "*NA*"
```

The folder ID is in your Drive URL: `drive.google.com/drive/folders/**FOLDER_ID**`

### 5. Configure CRO persona (optional)

Edit `config/cro_persona.yaml` to set the CRO's name and company.

### 6. Run the app
```bash
streamlit run app.py
```

---

## Project Structure

```
project-dolly/
├── app.py                    # Main Streamlit entry point
├── pages/
│   ├── review.py             # Account Review tab (human-in-the-loop)
│   ├── dashboard.py          # Risk Dashboard tab
│   └── report.py             # Executive Report tab
├── ui/
│   ├── components/
│   │   ├── review_card.py    # Review Card UI component
│   │   ├── risk_badges.py    # Tier/NRR/threading badges
│   │   ├── tech_stake_chart.py  # Channel breakdown visualization
│   │   └── progress_sidebar.py  # Session progress sidebar
│   └── styles/custom.css    # Custom dark theme styles
├── src/
│   ├── google/               # Google Drive + Sheets API clients
│   ├── ingestion/            # Data loading, normalization, joining, tone scraping
│   ├── scoring/              # NRR, threading, expansion, composite scorers
│   ├── llm/                  # Claude API client + prompt builder
│   ├── session/              # Session state + JSON persistence
│   ├── report/               # Markdown report generator
│   └── utils/                # Config loaders, validators
├── config/
│   ├── column_mappings.yaml  # Column drift normalization
│   ├── scoring_weights.yaml  # Scoring thresholds (tunable)
│   ├── cro_persona.yaml      # CRO name, voice rules
│   ├── prompt_templates.yaml # Claude prompt templates
│   ├── cro_tone_profile.yaml # Auto-generated tone profile
│   └── regions.yaml          # Drive folder + file pattern config
└── requirements.txt
```

---

## How It Works

### Data Flow
1. **Discover** → Agent scans your Google Drive folder, matches files to regions by filename pattern
2. **Load** → Reads Maps, Tech Stake, and Summary tabs from each regional Google Sheet
3. **Normalize** → Maps inconsistent column names to canonical names (YAML-driven + fuzzy matching)
4. **Join** → Merges Maps + Tech Stake + Summary per region, then globally
5. **Score** → Applies NRR risk, multi-threading gap, and expansion opportunity scoring
6. **Review** → CRO reviews accounts one-by-one in the Review Card UI
7. **Write-back** → Approved comments written to the "CRO Comment" column in each Summary tab
8. **Report** → Markdown executive summary generated and available for download

### Scoring Logic

| Dimension | Weight | Signal |
|-----------|--------|--------|
| NRR Risk | 50% | < 90% = CRITICAL (P1 override), < 100% = AT_RISK |
| Threading Gap | 25% | 1 contact = SINGLE (85 risk pts), 2 = DUAL, 3+ = MULTI |
| Expansion Opportunity | 25% | Each competitor channel = +8 pts, each white space = +5 pts |

- **P1**: Composite ≥ 65 OR NRR CRITICAL OR renewal < 90 days
- **P2**: Composite 40–64
- **P3**: Composite < 40

### Voice Learning
The agent automatically extracts the "Next Steps" column from all regional sheets and uses Claude to synthesize a **CRO Tone Profile** — capturing sentence patterns, vocabulary, and action orientation. This profile is injected as few-shot examples into every Claude prompt.

To rebuild the tone profile after adding new data:
```bash
python -m src.ingestion.tone_scraper
```

---

## Configuration Reference

### `config/column_mappings.yaml`
Maps regional column name variants to canonical names. Add new aliases here when onboarding a new region with different column naming.

### `config/scoring_weights.yaml`
Tune the scoring thresholds without touching Python code. Adjust NRR critical threshold, threading scores, expansion bonuses, and P1/P2/P3 cutoffs.

### `config/cro_persona.yaml`
Set the CRO's name, company, philosophy paragraph, and voice rules. These are injected verbatim into the Claude system prompt.

### `config/prompt_templates.yaml`
Customize the exact structure of the system and user prompts. Use `{placeholders}` as defined in `src/llm/prompt_builder.py`.

---

## Session Management

Sessions are auto-saved as JSON after every Approve/Skip action:
```
data/sessions/session_YYYYMMDD_HHMMSS.json
```

To resume a session, click **📂 Load** in the sidebar and select the session file.

---

## Secrets Reference

`.streamlit/secrets.toml` (gitignored):
```toml
GOOGLE_SERVICE_ACCOUNT_JSON = """{ ... full JSON ... }"""
ANTHROPIC_API_KEY = "sk-ant-..."
```

---

*Built with [Streamlit](https://streamlit.io) · [Anthropic Claude](https://anthropic.com) · [Google Sheets API](https://developers.google.com/sheets/api)*
