"""
Session state dataclasses.

SessionState tracks all decisions made during a CRO review session.
AccountDecision holds the outcome (approved/skipped) and comment for one account.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Optional, List


@dataclass
class AccountDecision:
    account_key: str              # "REGION::AccountName"
    status: str                   # "approved" | "skipped" | "pending"
    final_comment: Optional[str] = None
    original_comment: Optional[str] = None
    edited: bool = False          # True if the CRO modified the AI comment
    regenerate_count: int = 0     # How many times Regenerate was clicked
    reviewed_at: Optional[str] = None   # ISO 8601 timestamp
    spreadsheet_id: Optional[str] = None  # Source sheet for write-back routing
    comment_type: str = "account"       # "portfolio" | "account" | "tech_stake"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "AccountDecision":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class SessionState:
    session_id: str               # e.g., "20260304_143022"
    created_at: str               # ISO 8601
    last_saved_at: str            # ISO 8601
    model_used: str               # Claude model ID
    regions_loaded: list[str] = field(default_factory=list)
    total_accounts: int = 0
    current_index: int = 0        # Index into review_order
    review_order: list[str] = field(default_factory=list)  # Ordered account_keys
    decisions: dict[str, AccountDecision] = field(default_factory=dict)  # {account_key: decision}
    tiers_reviewed: list[str] = field(default_factory=lambda: ["P1", "P2"])
    review_step: int = 1                # 1=Portfolio, 2=Account Reviews, 3=Tech Stake
    portfolio_decisions: dict = field(default_factory=dict)  # {region_key: AccountDecision}
    tech_stake_order: list[str] = field(default_factory=list)  # Ordered account_keys for tech stake
    tech_stake_decisions: dict = field(default_factory=dict)  # {account_key: AccountDecision}

    # ── Computed properties ────────────────────────────────────────────────

    def is_complete(self) -> bool:
        return self.current_index >= self.total_accounts

    def approved_count(self) -> int:
        return sum(1 for d in self.decisions.values() if d.status == "approved")

    def skipped_count(self) -> int:
        return sum(1 for d in self.decisions.values() if d.status == "skipped")

    def pending_count(self) -> int:
        return self.total_accounts - len(self.decisions)

    def approved_decisions(self) -> dict[str, AccountDecision]:
        return {k: v for k, v in self.decisions.items() if v.status == "approved"}

    def current_account_key(self) -> Optional[str]:
        if self.current_index < len(self.review_order):
            return self.review_order[self.current_index]
        return None

    def progress_pct(self) -> float:
        if self.total_accounts == 0:
            return 0.0
        return min(1.0, self.current_index / self.total_accounts)

    # ── Multi-step helpers ───────────────────────────────────────────────

    def advance_step(self) -> None:
        """Move to the next review step (max 3)."""
        if self.review_step < 3:
            self.review_step += 1

    def step_label(self) -> str:
        """Human-readable label for the current step."""
        return {1: "Portfolio Summary", 2: "Account Reviews", 3: "Tech Stack Reviews"}.get(
            self.review_step, "Unknown"
        )

    def portfolio_approved_count(self) -> int:
        return sum(1 for d in self.portfolio_decisions.values() if d.status == "approved")

    def tech_stake_approved_count(self) -> int:
        return sum(1 for d in self.tech_stake_decisions.values() if d.status == "approved")

    def all_approved_decisions(self) -> dict:
        """Return all approved decisions across all three steps."""
        merged = {}
        for k, d in self.portfolio_decisions.items():
            if d.status == "approved":
                merged[k] = d
        for k, d in self.decisions.items():
            if d.status == "approved":
                merged[k] = d
        for k, d in self.tech_stake_decisions.items():
            if d.status == "approved":
                merged[k] = d
        return merged

    # ── Serialization ──────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        d = asdict(self)
        d["decisions"] = {k: v.to_dict() for k, v in self.decisions.items()}
        d["portfolio_decisions"] = {k: v.to_dict() for k, v in self.portfolio_decisions.items()}
        d["tech_stake_decisions"] = {k: v.to_dict() for k, v in self.tech_stake_decisions.items()}
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "SessionState":
        decisions_raw = d.pop("decisions", {})
        portfolio_raw = d.pop("portfolio_decisions", {})
        tech_stake_raw = d.pop("tech_stake_decisions", {})
        session = cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})
        session.decisions = {
            k: AccountDecision.from_dict(v) for k, v in decisions_raw.items()
        }
        session.portfolio_decisions = {
            k: AccountDecision.from_dict(v) for k, v in portfolio_raw.items()
        }
        session.tech_stake_decisions = {
            k: AccountDecision.from_dict(v) for k, v in tech_stake_raw.items()
        }
        return session

    # ── Factory ────────────────────────────────────────────────────────────

    @classmethod
    def new(
        cls,
        model: str,
        regions: list[str],
        review_order: list[str],
        tiers: Optional[List[str]] = None,
    ) -> "SessionState":
        now = datetime.now(timezone.utc).isoformat()
        session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        return cls(
            session_id=session_id,
            created_at=now,
            last_saved_at=now,
            model_used=model,
            regions_loaded=regions,
            total_accounts=len(review_order),
            current_index=0,
            review_order=review_order,
            decisions={},
            tiers_reviewed=tiers or ["P1", "P2"],
        )
