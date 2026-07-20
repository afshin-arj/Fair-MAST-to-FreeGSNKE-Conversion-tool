"""Shot suitability gate for Fair-MAST → FreeGSNKE analysis.

A shot is suitable when required Level-2 groups are available (local cache or
public S3) and, when reachable, MastApp lists the shot. Never invents data.
Portable: pathlib, optional network, cache-first for offline lab machines.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from .availability import check_groups
from .config import AppConfig, cache_dir_for_shot
from .download import BulkDownloader, group_cache_hit
from .mastapp import MastAppClient

# Distinct from pipeline hard-fail (11) so batch can skip and continue.
EXIT_UNSUITABLE = 20


@dataclass(frozen=True)
class ShotSuitability:
    shot: int
    suitable: bool
    reasons: List[str] = field(default_factory=list)
    checks: Dict[str, Any] = field(default_factory=dict)
    hints: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "shot": int(self.shot),
            "suitable": bool(self.suitable),
            "reasons": list(self.reasons),
            "checks": dict(self.checks),
            "hints": list(self.hints),
        }


def format_unsuitable_message(report: ShotSuitability) -> str:
    """Professional operator-facing message (no emojis)."""
    lines = [
        "",
        "=" * 75,
        f"Shot {report.shot} is not suitable for Fair-MAST → FreeGSNKE analysis",
        "=" * 75,
    ]
    if report.reasons:
        lines.append("Reasons:")
        for r in report.reasons:
            lines.append(f"  • {r}")
    if report.hints:
        lines.append("What you can do:")
        for h in report.hints:
            lines.append(f"  • {h}")
    lines.append("=" * 75)
    lines.append("")
    return "\n".join(lines)


def assess_shot_suitability(
    cfg: AppConfig,
    shot: int,
    *,
    repo_root: Optional[Path] = None,
) -> ShotSuitability:
    """Return suitability for a shot without downloading trees.

    Order (fail-fast, cache-friendly):
      1) positive shot number
      2) all required_groups present in local data_cache → suitable
      3) MastApp shot listing (if reachable; missing shot → unsuitable)
      4) required Level-2 groups discoverable on S3 via s5cmd
    """
    checks: Dict[str, Any] = {}
    reasons: List[str] = []
    hints: List[str] = [
        "Enter a different MAST shot number that has public Level-2 pf_active, magnetics, and wall data.",
        "Reference smoke shot on public FAIR-MAST: 30201.",
        "If you already downloaded this shot elsewhere, copy data_cache/shot_<N>/ into this machine and retry.",
    ]

    try:
        shot_i = int(shot)
    except Exception:
        return ShotSuitability(
            shot=0,
            suitable=False,
            reasons=["Shot number must be an integer."],
            hints=hints,
        )

    if shot_i < 1:
        return ShotSuitability(
            shot=shot_i,
            suitable=False,
            reasons=["Shot number must be a positive integer."],
            hints=hints,
        )

    required = list(cfg.required_groups or [])
    checks["required_groups"] = required
    cache = cache_dir_for_shot(cfg, shot_i)
    checks["cache_dir"] = str(cache).replace("\\", "/")

    if bool(getattr(cfg, "allow_cache_reuse", True)) and required:
        hits = {g: group_cache_hit(cache, g) for g in required}
        checks["cache_hits"] = hits
        if all(hits.values()):
            checks["decision"] = "all_required_groups_cached"
            return ShotSuitability(
                shot=shot_i,
                suitable=True,
                checks=checks,
                hints=[],
            )

    # MastApp listing (best-effort network)
    mastapp_ok: Optional[bool] = None
    try:
        client = MastAppClient(base_url=str(cfg.mastapp_base_url), timeout_s=8.0)
        mastapp_ok = bool(client.shot_exists(shot_i))
        checks["mastapp"] = {
            "base_url": str(cfg.mastapp_base_url),
            "exists": mastapp_ok,
        }
        if not mastapp_ok:
            reasons.append(
                f"Shot {shot_i} is not available via MastApp REST "
                f"({cfg.mastapp_base_url})."
            )
    except Exception as e:
        checks["mastapp"] = {
            "base_url": str(cfg.mastapp_base_url),
            "error": f"{type(e).__name__}: {e}",
            "note": "unreachable — continuing with Level-2 S3 discovery",
        }

    if reasons:
        return ShotSuitability(
            shot=shot_i,
            suitable=False,
            reasons=reasons,
            checks=checks,
            hints=hints,
        )

    # Level-2 S3 discovery for required groups
    try:
        dl = BulkDownloader(
            s5cmd_path=str(cfg.s5cmd_path),
            level2_s3_prefix=str(cfg.level2_s3_prefix),
            layout_patterns=list(cfg.s3_layout_patterns),
            s3_endpoint_url=cfg.s3_endpoint_url,
            s3_no_sign_request=bool(cfg.s3_no_sign_request),
            timeout_s=int(cfg.s5cmd_timeout_s),
        )
        avail = check_groups(
            shot=shot_i,
            groups=required,
            discover=dl.discover_group_path,
        )
        checks["s3_availability"] = {k: v.__dict__ for k, v in avail.items()}
        missing = [k for k, v in avail.items() if not v.exists]
        if missing:
            detail = []
            for g in missing:
                err = avail[g].error
                detail.append(f"{g}" + (f" ({err})" if err else ""))
            reasons.append(
                "Required FAIR-MAST Level-2 groups are missing or unreachable: "
                + ", ".join(detail)
            )
            hints = [
                "Confirm the shot has public Level-2 data under "
                f"{cfg.level2_s3_prefix}.",
                "Ensure s5cmd is installed and can reach the STFC Echo endpoint.",
                "Try a known-good shot such as 30201, or restore data_cache/shot_<N>/.",
            ]
    except Exception as e:
        reasons.append(
            f"Could not check Level-2 availability for shot {shot_i}: "
            f"{type(e).__name__}: {e}"
        )
        checks["s3_availability_error"] = f"{type(e).__name__}: {e}"
        hints = [
            "Verify s5cmd / network access to the FAIR-MAST S3 endpoint.",
            "If offline, place a complete data_cache/shot_<N>/ tree for this shot and retry.",
        ]

    if reasons:
        return ShotSuitability(
            shot=shot_i,
            suitable=False,
            reasons=reasons,
            checks=checks,
            hints=hints,
        )

    checks["decision"] = "mastapp_ok_and_required_groups_present"
    return ShotSuitability(shot=shot_i, suitable=True, checks=checks, hints=[])
