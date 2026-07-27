"""Mutuals honesty label prefers structured fill_notes over substring false positives."""

from mast_freegsnke.planner import mutuals_honesty_label, residual_compare_class


def test_mutuals_prefers_fill_notes_over_auth_prose() -> None:
    # Authority prose historically said "mutuals=neglected..." but fill kept FreeGSNKE off-diag.
    label = mutuals_honesty_label(
        source="circuit_dynamics_authority:cite + freegsnke",
        notes=(
            "legacy prose mentions mutuals=neglected historically | "
            "fill=[] | L_model=diagonal_self_only | "
            "mutuals=freegsnke_offdiag_retained_cited_Lii_overlay"
        ),
        fill_notes={"mutuals": "freegsnke_offdiag_retained_cited_Lii_overlay"},
    )
    assert label == "freegsnke_offdiag_retained_cited_Lii_overlay"


def test_mutuals_last_token_without_fill_notes() -> None:
    misleading = (
        "auth notes mention mutuals=neglected historically as a warning | "
        "L_model=diagonal_self_only | mutuals=freegsnke_offdiag_retained_cited_Lii_overlay"
    )
    assert "mutuals=neglected" in misleading  # old substring matcher would misfire
    label = mutuals_honesty_label(source="x", notes=misleading, fill_notes=None)
    assert label == "freegsnke_offdiag_retained_cited_Lii_overlay"


def test_mutuals_exact_token_neglected() -> None:
    label = mutuals_honesty_label(
        source="L_model=diagonal_self_only(mutuals_neglected_declared)",
        notes="mutuals=neglected_diagonal_self_only_declared",
        fill_notes={"mutuals": "neglected_diagonal_self_only_declared"},
    )
    assert label == "neglected_diagonal_self_only_declared"


def test_residual_compare_class() -> None:
    assert residual_compare_class("measured_fairmast_V") == "measured_V"
    assert residual_compare_class("ohmic_synthetic_IxR") == "deferred_ohmic_synthetic"
    assert residual_compare_class("unknown") == "unknown"
