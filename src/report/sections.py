"""
Individual Markdown section generators for the executive report.
"""

from datetime import datetime
from typing import Optional

import pandas as pd


def section_header(scored_df: pd.DataFrame, session=None, generated_at: str = "") -> str:
    """Generate the report header block."""
    if not generated_at:
        generated_at = datetime.now().strftime("%Y-%m-%d %H:%M")

    region_list = ", ".join(sorted(scored_df["region"].unique())) if "region" in scored_df.columns else "N/A"
    total = len(scored_df)
    reviewed = len(session.decisions) if session else 0
    approved = session.approved_count() if session else 0
    model = session.model_used if session else "claude-sonnet-4-6"
    session_id = session.session_id if session else "N/A"

    return f"""# Global Account Review — CRO Executive Summary

**Generated:** {generated_at}
**Session ID:** {session_id}
**Model:** {model}
**Regions:** {region_list}
**Accounts Covered:** {total} total | {reviewed} reviewed | {approved} approved

---
"""


def section_risk_dashboard(scored_df: pd.DataFrame) -> str:
    """Generate the risk dashboard section with regional breakdown table."""
    lines = ["## 1. Risk Dashboard\n"]

    # Regional table
    if "region" in scored_df.columns and "attention_tier" in scored_df.columns:
        lines.append("| Region | Total | P1 🔴 | P2 🟡 | P3 🟢 | Avg NRR |")
        lines.append("|--------|-------|-------|-------|-------|---------|")
        totals = {"total": 0, "p1": 0, "p2": 0, "p3": 0, "nrr_sum": 0.0, "nrr_count": 0}
        for region in sorted(scored_df["region"].unique()):
            rdf = scored_df[scored_df["region"] == region]
            p1 = (rdf["attention_tier"] == "P1").sum()
            p2 = (rdf["attention_tier"] == "P2").sum()
            p3 = (rdf["attention_tier"] == "P3").sum()
            avg_nrr = _avg_nrr_str(rdf)
            lines.append(f"| {region} | {len(rdf)} | {p1} | {p2} | {p3} | {avg_nrr} |")
            totals["total"] += len(rdf); totals["p1"] += p1; totals["p2"] += p2; totals["p3"] += p3
        lines.append(
            f"| **Total** | **{totals['total']}** | **{totals['p1']}** | **{totals['p2']}** | **{totals['p3']}** | {_avg_nrr_str(scored_df)} |"
        )
        lines.append("")

    # NRR tier distribution
    if "nrr_tier" in scored_df.columns:
        lines.append("### NRR Distribution\n")
        lines.append("| NRR Tier | Count | % of Portfolio |")
        lines.append("|----------|-------|----------------|")
        tier_order = ["CRITICAL", "AT_RISK", "HEALTHY", "STRONG", "UNKNOWN"]
        total = len(scored_df)
        for tier in tier_order:
            count = (scored_df["nrr_tier"] == tier).sum()
            pct = count / total * 100 if total else 0
            lines.append(f"| {tier} | {count} | {pct:.0f}% |")
        lines.append("")

    return "\n".join(lines)


def section_top_risk_accounts(
    scored_df: pd.DataFrame,
    session=None,
    top_n: int = 10,
) -> str:
    """Generate the top P1 risk accounts section."""
    lines = ["## 2. Top Risk Accounts (P1 — Immediate Attention)\n"]

    if "attention_tier" not in scored_df.columns:
        return "\n".join(lines) + "_No tier data available._\n"

    p1_df = scored_df[scored_df["attention_tier"] == "P1"].head(top_n)
    if p1_df.empty:
        lines.append("_No P1 accounts identified._\n")
        return "\n".join(lines)

    lines.append("| # | Account | Region | AE | ARR | NRR | Primary Risk | CRO Comment |")
    lines.append("|---|---------|--------|----|-----|-----|--------------|-------------|")

    decisions = session.decisions if session else {}

    for i, (_, row) in enumerate(p1_df.iterrows(), 1):
        account_name = str(row.get("account_name", "")).strip()
        region = str(row.get("region", "")).strip()
        ae = str(row.get("ae_name", "N/A")).strip()
        arr = _fmt_currency(row.get("arr"))
        nrr = str(row.get("nrr_display", "N/A"))
        primary = str(row.get("primary_signal", "N/A"))

        from src.ingestion.joiner import get_account_key
        key = get_account_key(row)
        decision = decisions.get(key)
        if decision and decision.status == "approved" and decision.final_comment:
            comment = decision.final_comment[:100] + "…" if len(decision.final_comment) > 100 else decision.final_comment
        elif decision and decision.status == "skipped":
            comment = "_(skipped)_"
        else:
            comment = "_(pending)_"

        lines.append(f"| {i} | {account_name} | {region} | {ae} | {arr} | {nrr} | {primary} | {comment} |")

    lines.append("")
    return "\n".join(lines)


def section_expansion_opportunities(
    scored_df: pd.DataFrame,
    session=None,
    top_n: int = 10,
) -> str:
    """Generate the expansion opportunities section."""
    lines = ["## 3. Expansion Opportunities\n"]

    if "expansion_score" not in scored_df.columns:
        return "\n".join(lines) + "_No expansion data available._\n"

    exp_df = scored_df.nlargest(top_n, "expansion_score")
    if exp_df.empty:
        lines.append("_No expansion data._\n")
        return "\n".join(lines)

    lines.append("| # | Account | Region | ARR | Exp. Score | Tier | Key Channels | CRO Comment |")
    lines.append("|---|---------|--------|-----|------------|------|--------------|-------------|")

    decisions = session.decisions if session else {}

    for i, (_, row) in enumerate(exp_df.iterrows(), 1):
        account_name = str(row.get("account_name", "")).strip()
        region = str(row.get("region", "")).strip()
        arr = _fmt_currency(row.get("arr"))
        exp_score = row.get("expansion_score", 0)
        exp_tier = str(row.get("expansion_tier", "N/A"))

        # Summarize key channels
        comp = row.get("competitor_channels", [])
        ws = row.get("whitespace_channels", [])
        if isinstance(comp, str):
            try:
                import ast
                comp = ast.literal_eval(comp)
            except Exception:
                comp = []
        if isinstance(ws, str):
            try:
                import ast
                ws = ast.literal_eval(ws)
            except Exception:
                ws = []
        comp_names = [c.get("channel", "") for c in comp[:2]] if comp else []
        ws_names = ws[:2] if ws else []
        channels_str = ", ".join(comp_names + ws_names) or "N/A"

        from src.ingestion.joiner import get_account_key
        key = get_account_key(row)
        decision = decisions.get(key)
        comment = "_(pending)_"
        if decision and decision.status == "approved" and decision.final_comment:
            comment = decision.final_comment[:80] + "…" if len(decision.final_comment) > 80 else decision.final_comment
        elif decision and decision.status == "skipped":
            comment = "_(skipped)_"

        lines.append(f"| {i} | {account_name} | {region} | {arr} | {exp_score:.0f}/100 | {exp_tier} | {channels_str} | {comment} |")

    lines.append("")
    return "\n".join(lines)


def section_cross_regional_patterns(scored_df: pd.DataFrame) -> str:
    """Generate the cross-regional patterns analysis section."""
    lines = ["## 4. Cross-Regional Patterns\n"]

    if "region" not in scored_df.columns:
        return "\n".join(lines) + "_No regional data._\n"

    # NRR by region
    lines.append("### NRR Risk by Region\n")
    if "nrr_raw" in scored_df.columns:
        for region in sorted(scored_df["region"].unique()):
            rdf = scored_df[scored_df["region"] == region]
            avg = _avg_nrr_float(rdf)
            critical_count = (rdf.get("nrr_tier", pd.Series()) == "CRITICAL").sum()
            if avg is not None:
                lines.append(
                    f"- **{region}**: Average NRR {avg:.1f}% "
                    f"({critical_count} account(s) CRITICAL)"
                )
        lines.append("")

    # Threading gaps by region
    lines.append("### Threading Gap by Region\n")
    if "threading_tier" in scored_df.columns:
        lines.append("| Region | Single-threaded | Dual | Multi | % Single |")
        lines.append("|--------|----------------|------|-------|----------|")
        for region in sorted(scored_df["region"].unique()):
            rdf = scored_df[scored_df["region"] == region]
            single = (rdf["threading_tier"] == "SINGLE").sum()
            dual = (rdf["threading_tier"] == "DUAL").sum()
            multi = (rdf["threading_tier"] == "MULTI").sum()
            pct = single / len(rdf) * 100 if len(rdf) else 0
            lines.append(f"| {region} | {single} | {dual} | {multi} | {pct:.0f}% |")
        lines.append("")

    return "\n".join(lines)


def section_approved_comments(scored_df: pd.DataFrame, session=None) -> str:
    """Generate the full approved comments section organized by region."""
    lines = ["## 5. CRO Approved Comments\n"]

    if not session or not session.decisions:
        lines.append("_No approved comments yet._\n")
        return "\n".join(lines)

    approved = session.approved_decisions()
    if not approved:
        lines.append("_No approved comments._\n")
        return "\n".join(lines)

    # Group by region
    from collections import defaultdict
    by_region: dict[str, list] = defaultdict(list)
    for key, decision in approved.items():
        region = key.split("::")[0]
        account = key.split("::", 1)[-1]
        by_region[region].append((account, decision))

    for region in sorted(by_region.keys()):
        lines.append(f"### {region}\n")
        for account, decision in sorted(by_region[region]):
            edited_flag = " *(edited)*" if decision.edited else ""
            regen_str = f" | {decision.regenerate_count} regen(s)" if decision.regenerate_count else ""
            timestamp = decision.reviewed_at[:19].replace("T", " ") if decision.reviewed_at else ""
            lines.append(f"#### {account}{edited_flag}")
            lines.append(f"> {decision.final_comment}")
            lines.append(f"\n*Approved: {timestamp}{regen_str}*\n")

    return "\n".join(lines)


def section_appendix(scored_df: pd.DataFrame, session=None) -> str:
    """Generate the full account list appendix."""
    lines = ["## 6. Appendix — All Accounts\n"]
    lines.append("| Rank | Account | Region | AE | ARR | NRR | Tier | Review Status |")
    lines.append("|------|---------|--------|----|-----|-----|------|---------------|")

    decisions = session.decisions if session else {}
    from src.ingestion.joiner import get_account_key

    for _, row in scored_df.iterrows():
        account_name = str(row.get("account_name", "")).strip()
        region = str(row.get("region", "")).strip()
        ae = str(row.get("ae_name", "N/A")).strip()
        arr = _fmt_currency(row.get("arr"))
        nrr = str(row.get("nrr_display", "N/A"))
        tier = str(row.get("attention_tier", "N/A"))
        rank = row.get("rank", "–")

        key = get_account_key(row)
        decision = decisions.get(key)
        status = decision.status.capitalize() if decision else "Pending"
        lines.append(f"| {rank} | {account_name} | {region} | {ae} | {arr} | {nrr} | {tier} | {status} |")

    lines.append("")
    return "\n".join(lines)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _avg_nrr_str(df: pd.DataFrame) -> str:
    val = _avg_nrr_float(df)
    return f"{val:.1f}%" if val is not None else "N/A"


def _avg_nrr_float(df: pd.DataFrame) -> Optional[float]:
    if "nrr_raw" not in df.columns:
        return None
    vals = pd.to_numeric(df["nrr_raw"], errors="coerce").dropna()
    return float(vals.mean()) if not vals.empty else None


def _fmt_currency(value) -> str:
    if value is None:
        return "N/A"
    try:
        num = float(str(value).replace("$", "").replace(",", "").strip())
        if num >= 1_000_000:
            return f"${num/1_000_000:.1f}M"
        if num >= 1_000:
            return f"${num/1_000:.0f}K"
        return f"${num:.0f}"
    except (ValueError, TypeError):
        return str(value) if value else "N/A"


from typing import Optional
