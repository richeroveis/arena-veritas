# Direct mode tests for contracts/arena_veritas.py.
# Fast in-memory VM, no server. Covers state transitions, fund accounting,
# soft-fail payables, temporal gates, verdict band derivation and refunds.
import datetime
import json
import sys

import pytest

PRIZE = 10**18
BOND = 10**15
PROTEST_BOND = 10**15
TELE_URL = "https://telemetry.av/bracket/m1"
RULES_URL = "https://rules.av/cs2"


def warp(vm, stamp: str):
    """vm.warp plus direct injection into gl.message_raw['datetime'] which the
    contract reads as its only time source (classic SDK warp parity)."""
    vm.warp(stamp)
    glmod = sys.modules.get("genlayer.gl")
    raw = getattr(glmod, "message_raw", None) if glmod else None
    if isinstance(raw, dict):
        raw["datetime"] = stamp
    vm._datetime = stamp


def iso(epoch: int) -> str:
    return datetime.datetime.fromtimestamp(epoch, datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def payable(vm, value, fn, *args):
    vm.value = value
    try:
        return fn(*args)
    finally:
        vm.value = 0


def register_args(alice, bob):
    return ("m1", "CS2 Major Grand Final", "CS2", PRIZE, BOND, PROTEST_BOND,
            TELE_URL, RULES_URL, 3600, 7200, 3600, 86400, alice, bob)


@pytest.fixture
def desk(direct_deploy, direct_vm):
    contract = direct_deploy("contracts/arena_veritas.py", "0x" + "11" * 20, "AVT")
    warp(direct_vm, "2026-01-01T00:00:00Z")
    return contract


@pytest.fixture
def registered(desk, direct_vm, direct_alice, direct_bob):
    res = payable(direct_vm, PRIZE, desk.register_tournament_payable, *register_args(direct_alice, direct_bob))
    assert res["ok"]
    return desk, res


def both_bonds(vm, registered, alice, bob):
    desk = registered[0]
    with vm.prank(alice):
        payable(vm, BOND, desk.post_competitor_bond_payable, "m1")
    with vm.prank(bob):
        payable(vm, BOND, desk.post_competitor_bond_payable, "m1")
    return desk


def mock_evidence(vm, llm_payload: dict):
    vm.mock_web(r"telemetry\.av", {"status": 200, "body": "TELEMETRY MATRIX tick entropy frame delta live bracket feed"})
    vm.mock_web(r"rules\.av", {"status": 200, "body": "OFFICIAL RULEBOOK anti cheat settings policy window"})
    vm.mock_llm(r".*integrity desk.*", json.dumps(llm_payload))


def verify_at_close(vm, registered, llm_payload):
    desk = both_bonds(vm, registered, registered[2], registered[3])
    mock_evidence(vm, llm_payload)
    warp(vm, iso(registered[1]["match_close_epoch"]))
    return desk, desk.verify_match_telemetry("m1")


@pytest.fixture
def registered4(desk, direct_vm, direct_alice, direct_bob, direct_charlie):
    res = payable(direct_vm, PRIZE, desk.register_tournament_payable, *register_args(direct_alice, direct_bob))
    return desk, res, direct_alice, direct_bob


# ---------------------------------------------------------------------------
# Deployment and deterministic datetime parsing
# ---------------------------------------------------------------------------
def test_deploy_defaults(desk, direct_owner):
    summary = desk.get_custody_accounting_summary()
    assert summary["vault_custody_balance_avt"] == 0
    assert summary["native_custody_balance_wei"] == 0
    assert desk.get_refundable_balance(direct_owner) == 0


def test_register_bad_datetime_reverts(desk, direct_vm, direct_alice, direct_bob):
    warp(direct_vm, "not-an-iso-stamp")
    with direct_vm.expect_revert("bad datetime"):
        payable(direct_vm, PRIZE, desk.register_tournament_payable, *register_args(direct_alice, direct_bob))


def test_register_without_separator_reverts(desk, direct_vm, direct_alice, direct_bob):
    warp(direct_vm, "20260101")
    with direct_vm.expect_revert("bad datetime"):
        payable(direct_vm, PRIZE, desk.register_tournament_payable, *register_args(direct_alice, direct_bob))


def test_register_offset_datetime_parsed(registered):
    assert registered[1]["submission_close_epoch"] == 1767225600 + 3600


def test_register_fractional_seconds_accepted(desk, direct_vm, direct_alice, direct_bob):
    warp(direct_vm, "2026-01-01T00:00:00.500Z")
    res = payable(direct_vm, PRIZE, desk.register_tournament_payable, *register_args(direct_alice, direct_bob))
    assert res["ok"]


def test_register_pre_epoch_datetime_reverts(desk, direct_vm, direct_alice, direct_bob):
    warp(direct_vm, "1960-01-01T00:00:00Z")
    with direct_vm.expect_revert("before unix epoch"):
        payable(direct_vm, PRIZE, desk.register_tournament_payable, *register_args(direct_alice, direct_bob))


# ---------------------------------------------------------------------------
# fund_prize_vault_payable
# ---------------------------------------------------------------------------
def test_fund_credits_avt(desk, direct_vm, direct_alice):
    with direct_vm.prank(direct_alice):
        res = payable(direct_vm, 5 * 10**18, desk.fund_prize_vault_payable)
    assert res["ok"] and res["avt_balance"] == 5 * 10**18
    summary = desk.get_custody_accounting_summary()
    assert summary["vault_custody_balance_avt"] == 5 * 10**18
    assert summary["avt_invariant_balanced"]


def test_fund_zero_value_reverts(desk, direct_vm):
    with direct_vm.expect_revert("funding requires value"):
        desk.fund_prize_vault_payable()


def test_fund_paused_soft_fail_never_reverts(desk, direct_vm, direct_charlie):
    desk.set_paused(True)
    with direct_vm.prank(direct_charlie):
        res = payable(direct_vm, 10**18, desk.fund_prize_vault_payable)
    assert res["soft_fail"] and res["rejected_reason"] == "contract paused"
    assert res["refunded_wei"] == 10**18
    assert desk.get_refundable_balance(direct_charlie) == 10**18


def test_fund_ceiling_soft_fail(desk, direct_vm, direct_alice):
    with direct_vm.prank(direct_alice):
        res = payable(direct_vm, 10**26, desk.fund_prize_vault_payable)
    assert res["rejected_reason"] == "funding exceeds ceiling"


# ---------------------------------------------------------------------------
# register_tournament_payable
# ---------------------------------------------------------------------------
def test_register_escrows_full_prize(registered):
    summary = registered[0].get_custody_accounting_summary()
    assert summary["escrowed_prize_total_avt"] == PRIZE
    assert summary["vault_custody_balance_avt"] == PRIZE
    assert summary["avt_invariant_balanced"]


def test_register_wrong_value_soft_fail_refunds(registered, direct_vm, direct_alice, direct_bob):
    desk = registered[0]
    with direct_vm.prank(direct_alice):
        res = payable(
            direct_vm, PRIZE + 7, desk.register_tournament_payable,
            "m2", "Valorant Sovereign Cup", "Valorant", PRIZE, BOND, PROTEST_BOND,
            "https://telemetry.av/m2", "https://rules.av/val", 3600, 7200, 3600, 86400,
            direct_alice, direct_bob,
        )
    assert res["soft_fail"] and res["refunded_wei"] == PRIZE + 7
    assert [row["match_id"] for row in desk.get_tournament_leaderboard()] == ["m1"]


def test_register_duplicate_id_soft_fail(registered, direct_vm, direct_alice, direct_bob):
    desk = registered[0]
    with direct_vm.prank(direct_alice):
        res = payable(direct_vm, PRIZE, desk.register_tournament_payable, *register_args(direct_alice, direct_bob))
    assert res["rejected_reason"] == "duplicate match id"


def test_register_from_ledger_credit(registered, direct_vm, direct_alice, direct_bob):
    desk = registered[0]
    with direct_vm.prank(direct_alice):
        payable(direct_vm, 4 * PRIZE, desk.fund_prize_vault_payable)
        res = payable(
            direct_vm, 0, desk.register_tournament_payable,
            "m3", "Elden Ring Any% WR", "ER", PRIZE, BOND, PROTEST_BOND,
            "https://telemetry.av/m3", "https://rules.av/er", 3600, 7200, 3600, 86400,
            direct_alice, direct_bob,
        )
    assert res["ok"]


def test_register_insufficient_credit_reverts(desk, direct_vm, direct_alice, direct_bob):
    with direct_vm.prank(direct_alice):
        with direct_vm.expect_revert("insufficient AVT vault credit"):
            payable(direct_vm, 0, desk.register_tournament_payable, *register_args(direct_alice, direct_bob))


def test_register_window_floor_rejected(registered, direct_vm, direct_alice, direct_bob):
    desk = registered[0]
    with direct_vm.prank(direct_alice):
        res = payable(
            direct_vm, PRIZE, desk.register_tournament_payable,
            "m4", "T", "CS2", PRIZE, BOND, PROTEST_BOND, TELE_URL, RULES_URL,
            10, 7200, 3600, 86400, direct_alice, direct_bob,
        )
    assert res["rejected_reason"] == "submission window outside bounds"


def test_register_window_ceiling_rejected(registered, direct_vm, direct_alice, direct_bob):
    desk = registered[0]
    with direct_vm.prank(direct_alice):
        res = payable(
            direct_vm, PRIZE, desk.register_tournament_payable,
            "m5", "T", "CS2", PRIZE, BOND, PROTEST_BOND, TELE_URL, RULES_URL,
            3600, 99999999, 3600, 86400, direct_alice, direct_bob,
        )
    assert res["rejected_reason"] == "match window outside bounds"


def test_register_same_finalists_rejected(registered, direct_vm, direct_alice):
    desk = registered[0]
    with direct_vm.prank(direct_alice):
        res = payable(
            direct_vm, PRIZE, desk.register_tournament_payable,
            "m6", "T", "CS2", PRIZE, BOND, PROTEST_BOND, TELE_URL, RULES_URL,
            3600, 7200, 3600, 86400, direct_alice, direct_alice,
        )
    assert res["rejected_reason"] == "finalists must be distinct"


def test_register_bad_url_rejected(registered, direct_vm, direct_alice, direct_bob):
    desk = registered[0]
    with direct_vm.prank(direct_alice):
        res = payable(
            direct_vm, PRIZE, desk.register_tournament_payable,
            "m7", "T", "CS2", PRIZE, BOND, PROTEST_BOND, "ftp://nope", RULES_URL,
            3600, 7200, 3600, 86400, direct_alice, direct_bob,
        )
    assert res["rejected_reason"] == "bad verification url"


def test_register_zero_prize_rejected(registered, direct_vm, direct_alice, direct_bob):
    desk = registered[0]
    with direct_vm.prank(direct_alice):
        res = payable(
            direct_vm, 1, desk.register_tournament_payable,
            "m8", "T", "CS2", 0, BOND, PROTEST_BOND, TELE_URL, RULES_URL,
            3600, 7200, 3600, 86400, direct_alice, direct_bob,
        )
    assert res["rejected_reason"] == "prize pool outside bounds"


def test_register_paused_soft_fail(registered, direct_vm, direct_alice, direct_bob):
    desk = registered[0]
    desk.set_paused(True)
    with direct_vm.prank(direct_alice):
        res = payable(
            direct_vm, PRIZE, desk.register_tournament_payable,
            "mp", "T", "CS2", PRIZE, BOND, PROTEST_BOND, TELE_URL, RULES_URL,
            3600, 7200, 3600, 86400, direct_alice, direct_bob,
        )
    assert res["rejected_reason"] == "contract paused"
    assert res["refunded_wei"] == PRIZE


def test_set_paused_only_admin(registered, direct_vm, direct_charlie):
    with direct_vm.prank(direct_charlie):
        with direct_vm.expect_revert("only admin may pause"):
            desk_set = registered[0]
            desk_set.set_paused(True)


# ---------------------------------------------------------------------------
# post_competitor_bond_payable
# ---------------------------------------------------------------------------
def test_post_bond_locks_exact_and_surplus(registered, direct_vm, direct_alice):
    desk = registered[0]
    with direct_vm.prank(direct_alice):
        res = payable(direct_vm, BOND + 123, desk.post_competitor_bond_payable, "m1")
    assert res["ok"] and res["bond_locked_wei"] == BOND and res["surplus_refunded_wei"] == 123
    assert desk.get_refundable_balance(direct_alice) == 123


def test_post_bond_activates_when_both(registered, direct_vm, direct_alice, direct_bob):
    desk = both_bonds(direct_vm, registered, direct_alice, direct_bob)
    assert desk.get_match("m1")["status"] == "ACTIVE"


def test_post_bond_non_finalist_soft_fail(registered, direct_vm, direct_charlie):
    desk = registered[0]
    with direct_vm.prank(direct_charlie):
        res = payable(direct_vm, BOND, desk.post_competitor_bond_payable, "m1")
    assert res["soft_fail"] and res["refunded_wei"] == BOND
    assert res["rejected_reason"] == "caller is not a listed finalist"


def test_post_bond_insufficient_soft_fail(registered, direct_vm, direct_alice):
    desk = registered[0]
    with direct_vm.prank(direct_alice):
        res = payable(direct_vm, BOND - 1, desk.post_competitor_bond_payable, "m1")
    assert res["rejected_reason"] == "insufficient bond value"
    assert desk.get_match("m1")["bond_a_wei"] == 0


def test_post_bond_duplicate_soft_fail(registered, direct_vm, direct_alice):
    desk = registered[0]
    with direct_vm.prank(direct_alice):
        payable(direct_vm, BOND, desk.post_competitor_bond_payable, "m1")
        res = payable(direct_vm, BOND, desk.post_competitor_bond_payable, "m1")
    assert res["rejected_reason"] == "bond already posted for this slot"


def test_post_bond_after_deadline_soft_fail(registered, direct_vm, direct_alice):
    desk, res = registered
    warp(direct_vm, iso(res["submission_close_epoch"] + 1))
    with direct_vm.prank(direct_alice):
        out = payable(direct_vm, BOND, desk.post_competitor_bond_payable, "m1")
    assert out["rejected_reason"] == "bond deadline passed"


def test_post_bond_zero_value_invalid_reverts(registered, direct_vm, direct_charlie):
    desk = registered[0]
    with direct_vm.prank(direct_charlie):
        with direct_vm.expect_revert("caller is not a listed finalist"):
            desk.post_competitor_bond_payable("m1")


def test_post_bond_unknown_match_soft_fail(registered, direct_vm, direct_alice):
    desk = registered[0]
    with direct_vm.prank(direct_alice):
        res = payable(direct_vm, BOND, desk.post_competitor_bond_payable, "nope")
    assert res["rejected_reason"] == "unknown match id"


# ---------------------------------------------------------------------------
# submit_tournament_telemetry
# ---------------------------------------------------------------------------
def test_submit_telemetry_sets_flags(registered, direct_vm, direct_alice):
    desk = registered[0]
    with direct_vm.prank(direct_alice):
        res = desk.submit_tournament_telemetry("m1", "replay tick entropy nominal")
    assert res["telemetry_submitted_a"] and not res["telemetry_submitted_b"]


def test_submit_telemetry_non_finalist_reverts(registered, direct_vm, direct_charlie):
    desk = registered[0]
    with direct_vm.prank(direct_charlie):
        with direct_vm.expect_revert("not a finalist"):
            desk.submit_tournament_telemetry("m1", "x")


def test_submit_telemetry_after_close_reverts(registered, direct_vm, direct_alice):
    desk, res = registered
    warp(direct_vm, iso(res["match_close_epoch"] + 1))
    with direct_vm.prank(direct_alice):
        with direct_vm.expect_revert("telemetry window closed"):
            desk.submit_tournament_telemetry("m1", "late")


def test_submit_telemetry_long_note_reverts(registered, direct_vm, direct_alice):
    desk = registered[0]
    with direct_vm.prank(direct_alice):
        with direct_vm.expect_revert("replay note too long"):
            desk.submit_tournament_telemetry("m1", "y" * 501)


# ---------------------------------------------------------------------------
# verify_match_telemetry gates and bands
# ---------------------------------------------------------------------------
def test_verify_before_match_close_reverts(registered, direct_vm, direct_alice, direct_bob):
    desk = both_bonds(direct_vm, registered, direct_alice, direct_bob)
    with direct_vm.expect_revert("match has not closed yet"):
        desk.verify_match_telemetry("m1")


def test_verify_unknown_match_reverts(desk, direct_vm):
    with direct_vm.expect_revert("unknown match id"):
        desk.verify_match_telemetry("ghost")


def test_verify_requires_active_status(registered, direct_vm, direct_alice):
    desk = registered[0]
    with direct_vm.prank(direct_alice):
        payable(direct_vm, BOND, desk.post_competitor_bond_payable, "m1")
    with direct_vm.expect_revert("requires an ACTIVE bracket"):
        desk.verify_match_telemetry("m1")


def test_verify_champion_band(registered4, direct_vm):
    desk, out = verify_at_close(direct_vm, registered4, {"integrity_baseline_bps": 9000, "anomaly_index_bps": 500, "compliant_slot": "FINALIST_A"})
    assert out["verdict_band"] == "VERIFIED_CHAMPION_PAYOUT"
    assert out["verified_winner_slot"] == "FINALIST_A"
    assert out["quantized_integrity_baseline_bps"] == 9000
    assert out["quantized_anomaly_bps"] == 500


def test_verify_quantizes_to_grid(registered4, direct_vm):
    desk, out = verify_at_close(direct_vm, registered4, {"integrity_baseline_bps": 8600, "anomaly_index_bps": 999, "compliant_slot": "FINALIST_B"})
    assert out["quantized_integrity_baseline_bps"] == 8500
    assert out["quantized_anomaly_bps"] == 1000
    assert out["verdict_band"] == "VERIFIED_CHAMPION_PAYOUT"


def test_verify_split_draw_band(registered4, direct_vm):
    desk, out = verify_at_close(direct_vm, registered4, {"integrity_baseline_bps": 7000, "anomaly_index_bps": 0, "technical_draw_verified": True})
    assert out["verdict_band"] == "SPLIT_DRAW_SETTLEMENT"
    assert out["verified_winner_slot"] == "DRAW"


def test_verify_violation_band(registered4, direct_vm):
    desk, out = verify_at_close(direct_vm, registered4, {"integrity_baseline_bps": 8000, "anomaly_index_bps": 1500, "compliant_slot": "FINALIST_A"})
    assert out["verdict_band"] == "RULE_VIOLATION_PENALTY"


def test_verify_cheat_band_by_anomaly(registered4, direct_vm):
    desk, out = verify_at_close(direct_vm, registered4, {"integrity_baseline_bps": 9500, "anomaly_index_bps": 3000, "compliant_slot": "FINALIST_A"})
    assert out["verdict_band"] == "CHEAT_DISQUALIFICATION_SLASH"


def test_verify_cheat_flag_overrides(registered4, direct_vm):
    desk, out = verify_at_close(direct_vm, registered4, {"integrity_baseline_bps": 9999, "anomaly_index_bps": 0, "cheat_confirmed": True, "compliant_slot": "FINALIST_B"})
    assert out["verdict_band"] == "CHEAT_DISQUALIFICATION_SLASH"
    assert out["verified_winner_slot"] == "FINALIST_B"


def test_verify_violation_flag_downgrades_champion(registered4, direct_vm):
    desk, out = verify_at_close(direct_vm, registered4, {"integrity_baseline_bps": 9000, "anomaly_index_bps": 0, "rule_violation": True, "compliant_slot": "FINALIST_A"})
    assert out["verdict_band"] == "RULE_VIOLATION_PENALTY"


def test_verify_llm_garbage_reverts(registered4, direct_vm, direct_alice):
    desk = both_bonds(direct_vm, registered4, direct_alice, registered4[3])
    mock_evidence(direct_vm, {"reasoning": "no numbers here"})
    warp(direct_vm, iso(registered4[1]["match_close_epoch"]))
    with direct_vm.expect_revert("[LLM_ERROR]"):
        desk.verify_match_telemetry("m1")
    assert desk.get_match("m1")["status"] == "ACTIVE"


def test_verify_missing_slot_reverts(registered4, direct_vm, direct_alice, direct_bob):
    desk = both_bonds(direct_vm, registered4, direct_alice, direct_bob)
    mock_evidence(direct_vm, {"integrity_baseline_bps": 9000, "anomaly_index_bps": 500, "compliant_slot": "CENTER"})
    warp(direct_vm, iso(registered4[1]["match_close_epoch"]))
    with direct_vm.expect_revert("bad compliant_slot"):
        desk.verify_match_telemetry("m1")


def test_verify_empty_render_reverts(registered4, direct_vm, direct_alice, direct_bob):
    desk = both_bonds(direct_vm, registered4, direct_alice, direct_bob)
    direct_vm.mock_web(r"telemetry\.av", {"status": 200, "body": "short"})
    direct_vm.mock_web(r"rules\.av", {"status": 200, "body": "rulebook rulebook rulebook"})
    direct_vm.mock_llm(r".*integrity desk.*", "{}")
    warp(direct_vm, iso(registered4[1]["match_close_epoch"]))
    with direct_vm.expect_revert("[TRANSIENT]"):
        desk.verify_match_telemetry("m1")


def test_verify_twice_reverts(registered4, direct_vm):
    desk, out = verify_at_close(direct_vm, registered4, {"integrity_baseline_bps": 9000, "anomaly_index_bps": 500, "compliant_slot": "FINALIST_A"})
    with direct_vm.expect_revert("requires an ACTIVE bracket"):
        desk.verify_match_telemetry("m1")


def test_verify_no_telemetry_after_submission_close_ok(registered4, direct_vm):
    desk = both_bonds(direct_vm, registered4, registered4[2], registered4[3])
    mock_evidence(direct_vm, {"integrity_baseline_bps": 9000, "anomaly_index_bps": 500, "compliant_slot": "FINALIST_A"})
    warp(direct_vm, iso(registered4[1]["match_close_epoch"]))
    out = desk.verify_match_telemetry("m1")
    assert out["ok"]


# ---------------------------------------------------------------------------
# file_anti_cheat_protest_payable
# ---------------------------------------------------------------------------
def protest(vm, desk, who, target, value=PROTEST_BOND, when=None, reason="aimbot suspicious ticks"):
    if when is not None:
        warp(vm, iso(when))
    with vm.prank(who):
        return payable(vm, value, desk.file_anti_cheat_protest_payable, "m1", target, reason)


def test_protest_before_window_soft_fail(registered4, direct_vm):
    desk = both_bonds(direct_vm, registered4, registered4[2], registered4[3])
    res = protest(direct_vm, desk, registered4[2], "FINALIST_B", when=registered4[1]["match_close_epoch"] - 10)
    assert res["rejected_reason"] == "protest window not open yet"
    assert res["refunded_wei"] == PROTEST_BOND


def test_protest_happy_path(registered4, direct_vm):
    desk = both_bonds(direct_vm, registered4, registered4[2], registered4[3])
    res = protest(direct_vm, desk, registered4[2], "FINALIST_B", when=registered4[1]["match_close_epoch"])
    assert res["ok"] and res["protest_bond_locked_wei"] == PROTEST_BOND
    assert desk.get_match("m1")["protest_filed"]


def test_protest_surplus_refunded(registered4, direct_vm):
    desk = both_bonds(direct_vm, registered4, registered4[2], registered4[3])
    res = protest(direct_vm, desk, registered4[2], "FINALIST_B", value=PROTEST_BOND + 55, when=registered4[1]["match_close_epoch"])
    assert res["surplus_refunded_wei"] == 55


def test_protest_self_protest_rejected(registered4, direct_vm):
    desk = both_bonds(direct_vm, registered4, registered4[2], registered4[3])
    res = protest(direct_vm, desk, registered4[2], "FINALIST_A", when=registered4[1]["match_close_epoch"])
    assert res["rejected_reason"] == "self protest is not permitted"


def test_protest_non_finalist_rejected(registered4, direct_vm, direct_charlie):
    desk = both_bonds(direct_vm, registered4, registered4[2], registered4[3])
    res = protest(direct_vm, desk, direct_charlie, "FINALIST_B", when=registered4[1]["match_close_epoch"])
    assert res["rejected_reason"] == "only listed finalists may file protests"


def test_protest_insufficient_bond_rejected(registered4, direct_vm):
    desk = both_bonds(direct_vm, registered4, registered4[2], registered4[3])
    res = protest(direct_vm, desk, registered4[2], "FINALIST_B", value=PROTEST_BOND - 1, when=registered4[1]["match_close_epoch"])
    assert res["rejected_reason"] == "insufficient protest bond"


def test_protest_after_deadline_rejected(registered4, direct_vm):
    desk = both_bonds(direct_vm, registered4, registered4[2], registered4[3])
    res = protest(direct_vm, desk, registered4[2], "FINALIST_B", when=registered4[1]["protest_deadline_epoch"])
    assert res["rejected_reason"] == "protest window closed"


def test_protest_duplicate_rejected(registered4, direct_vm):
    desk = both_bonds(direct_vm, registered4, registered4[2], registered4[3])
    at = registered4[1]["match_close_epoch"]
    protest(direct_vm, desk, registered4[2], "FINALIST_B", when=at)
    res = protest(direct_vm, desk, registered4[2], "FINALIST_B", when=at + 5)
    assert res["rejected_reason"] == "a protest is already filed for this bracket"


def test_protest_second_distinct_protestant_refunded(registered4, direct_vm):
    # Regression: a second protest must not orphan the first protest bond.
    desk = both_bonds(direct_vm, registered4, registered4[2], registered4[3])
    at = registered4[1]["match_close_epoch"]
    protest(direct_vm, desk, registered4[2], "FINALIST_B", when=at)
    res = protest(direct_vm, desk, registered4[3], "FINALIST_A", when=at + 5)
    assert res["soft_fail"] and res["refunded_wei"] == PROTEST_BOND
    summary = desk.get_custody_accounting_summary()
    assert summary["escrowed_protest_total_wei"] == PROTEST_BOND
    assert summary["native_invariant_balanced"]


def test_protest_long_reason_rejected(registered4, direct_vm):
    desk = both_bonds(direct_vm, registered4, registered4[2], registered4[3])
    res = protest(direct_vm, desk, registered4[2], "FINALIST_B", when=registered4[1]["match_close_epoch"], reason="z" * 501)
    assert res["rejected_reason"] == "protest reason too long"


# ---------------------------------------------------------------------------
# claim_tournament_settlement
# ---------------------------------------------------------------------------
def settle_after_deadline(vm, desk, res):
    warp(vm, iso(res["protest_deadline_epoch"]))
    return desk.claim_tournament_settlement("m1")


def test_settle_before_deadline_reverts(registered4, direct_vm):
    desk, out = verify_at_close(direct_vm, registered4, {"integrity_baseline_bps": 9000, "anomaly_index_bps": 500, "compliant_slot": "FINALIST_A"})
    with direct_vm.expect_revert("protest window still open"):
        desk.claim_tournament_settlement("m1")


def test_settle_without_verify_reverts(registered4, direct_vm):
    desk = both_bonds(direct_vm, registered4, registered4[2], registered4[3])
    with direct_vm.expect_revert("bracket is not VERIFIED"):
        settle_after_deadline(direct_vm, desk, registered4[1])


def test_settle_champion_payout_and_bonds(registered4, direct_vm):
    desk, out = verify_at_close(direct_vm, registered4, {"integrity_baseline_bps": 9000, "anomaly_index_bps": 500, "compliant_slot": "FINALIST_A"})
    res = settle_after_deadline(direct_vm, desk, registered4[1])
    assert res["ok"] and res["champion_payout_avt"] == PRIZE
    assert desk.get_avt_balance(registered4[2]) == PRIZE
    assert desk.get_refundable_balance(registered4[2]) == BOND
    assert desk.get_refundable_balance(registered4[3]) == BOND
    summary = desk.get_custody_accounting_summary()
    assert summary["avt_invariant_balanced"] and summary["native_invariant_balanced"]
    assert summary["escrowed_prize_total_avt"] == 0


def test_settle_split_draw(registered4, direct_vm):
    desk, out = verify_at_close(direct_vm, registered4, {"integrity_baseline_bps": 7000, "anomaly_index_bps": 0, "technical_draw_verified": True})
    settle_after_deadline(direct_vm, desk, registered4[1])
    assert desk.get_avt_balance(registered4[2]) == PRIZE // 2
    assert desk.get_avt_balance(registered4[3]) == PRIZE - PRIZE // 2


def test_settle_violation_75_25_and_minor_slash(registered4, direct_vm, direct_owner):
    desk, out = verify_at_close(direct_vm, registered4, {"integrity_baseline_bps": 8000, "anomaly_index_bps": 1500, "compliant_slot": "FINALIST_A"})
    settle_after_deadline(direct_vm, desk, registered4[1])
    champion = PRIZE * 7500 // 10000
    assert desk.get_avt_balance(registered4[2]) == champion
    assert desk.get_avt_balance(direct_owner) == PRIZE - champion
    summary = desk.get_custody_accounting_summary()
    assert summary["avt_invariant_balanced"]
    minor_slash = BOND * 1000 // 10000
    assert desk.get_refundable_balance(registered4[3]) == BOND - minor_slash
    assert desk.get_refundable_balance(registered4[2]) == BOND + minor_slash


def test_settle_cheat_slashes_full_bond(registered4, direct_vm):
    desk = both_bonds(direct_vm, registered4, registered4[2], registered4[3])
    protest(direct_vm, desk, registered4[2], "FINALIST_B", when=registered4[1]["match_close_epoch"])
    mock_evidence(direct_vm, {"integrity_baseline_bps": 9500, "anomaly_index_bps": 3500, "compliant_slot": "FINALIST_A"})
    warp(direct_vm, iso(registered4[1]["match_close_epoch"]))
    desk.verify_match_telemetry("m1")
    settle_after_deadline(direct_vm, desk, registered4[1])
    assert desk.get_avt_balance(registered4[2]) == PRIZE
    # alice: own bond + full slashed bond (own clean half + protest half) + protest bond back; bob: zero
    assert desk.get_refundable_balance(registered4[2]) == BOND + BOND + PROTEST_BOND
    assert desk.get_refundable_balance(registered4[3]) == 0
    summary = desk.get_custody_accounting_summary()
    assert summary["native_invariant_balanced"] and summary["escrowed_bond_total_wei"] == 0


def test_settle_dismissed_protest_forfeits_bond(registered4, direct_vm):
    desk = both_bonds(direct_vm, registered4, registered4[2], registered4[3])
    protest(direct_vm, desk, registered4[2], "FINALIST_B", when=registered4[1]["match_close_epoch"])
    mock_evidence(direct_vm, {"integrity_baseline_bps": 9000, "anomaly_index_bps": 500, "compliant_slot": "FINALIST_A"})
    warp(direct_vm, iso(registered4[1]["match_close_epoch"]))
    desk.verify_match_telemetry("m1")
    settle_after_deadline(direct_vm, desk, registered4[1])
    # protest dismissed: protest bond goes to the protested (clean) finalist bob
    assert desk.get_refundable_balance(registered4[3]) == BOND + PROTEST_BOND
    assert desk.get_refundable_balance(registered4[2]) == BOND


def test_settle_twice_reverts(registered4, direct_vm):
    desk, out = verify_at_close(direct_vm, registered4, {"integrity_baseline_bps": 9000, "anomaly_index_bps": 500, "compliant_slot": "FINALIST_A"})
    settle_after_deadline(direct_vm, desk, registered4[1])
    with direct_vm.expect_revert("not VERIFIED"):
        settle_after_deadline(direct_vm, desk, registered4[1])


# ---------------------------------------------------------------------------
# void and abandoned refunds
# ---------------------------------------------------------------------------
def test_void_before_submission_close_reverts(registered, direct_vm):
    desk = registered[0]
    with direct_vm.expect_revert("submission window still open"):
        desk.mark_void_no_contest("m1")


def test_void_with_two_bonds_reverts(registered4, direct_vm):
    desk = both_bonds(direct_vm, registered4, registered4[2], registered4[3])
    warp(direct_vm, iso(registered4[1]["submission_close_epoch"] + 1))
    with direct_vm.expect_revert("two bonded finalists"):
        desk.mark_void_no_contest("m1")


def test_void_single_bond_then_refund(registered4, direct_vm):
    desk = registered4[0]
    with direct_vm.prank(registered4[2]):
        payable(direct_vm, BOND, desk.post_competitor_bond_payable, "m1")
    warp(direct_vm, iso(registered4[1]["submission_close_epoch"] + 1))
    res = desk.mark_void_no_contest("m1")
    assert res["ok"] and desk.get_match("m1")["verdict_band"] == "VOID_NO_CONTEST_REFUND"
    refund = desk.claim_abandoned_match_refund("m1")
    assert refund["ok"] and refund["organizer_prize_refunded_avt"] == PRIZE
    assert desk.get_refundable_balance(registered4[2]) == BOND
    summary = desk.get_custody_accounting_summary()
    assert summary["avt_invariant_balanced"] and summary["native_invariant_balanced"]


def test_abandoned_timeout_refund_full(registered4, direct_vm):
    desk = both_bonds(direct_vm, registered4, registered4[2], registered4[3])
    with direct_vm.expect_revert("abandoned refund not eligible"):
        desk.claim_abandoned_match_refund("m1")
    warp(direct_vm, iso(registered4[1]["verification_timeout_epoch"]))
    res = desk.claim_abandoned_match_refund("m1")
    assert res["ok"] and desk.get_match("m1")["status"] == "REFUNDED"
    assert desk.get_refundable_balance(registered4[2]) == BOND
    assert desk.get_refundable_balance(registered4[3]) == BOND


def test_abandoned_refund_double_claim_reverts(registered4, direct_vm):
    desk = both_bonds(direct_vm, registered4, registered4[2], registered4[3])
    warp(direct_vm, iso(registered4[1]["verification_timeout_epoch"]))
    desk.claim_abandoned_match_refund("m1")
    with direct_vm.expect_revert("not eligible"):
        desk.claim_abandoned_match_refund("m1")


def test_abandoned_after_verify_blocked(registered4, direct_vm):
    desk, out = verify_at_close(direct_vm, registered4, {"integrity_baseline_bps": 9000, "anomaly_index_bps": 500, "compliant_slot": "FINALIST_A"})
    warp(direct_vm, iso(registered4[1]["verification_timeout_epoch"]))
    with direct_vm.expect_revert("not eligible"):
        desk.claim_abandoned_match_refund("m1")


# ---------------------------------------------------------------------------
# refundable ledger and withdrawal
# ---------------------------------------------------------------------------
def test_withdraw_refund_partial_then_rest(registered, direct_vm, direct_charlie):
    desk = registered[0]
    with direct_vm.prank(direct_charlie):
        payable(direct_vm, 500, desk.post_competitor_bond_payable, "m1")
        res = desk.withdraw_refund(200)
        assert res["released_wei"] == 200 and res["remaining_refundable"] == 300
        assert desk.get_refundable_balance(direct_charlie) == 300


def test_withdraw_over_balance_reverts(registered, direct_vm, direct_charlie):
    desk = registered[0]
    with direct_vm.prank(direct_charlie):
        payable(direct_vm, 100, desk.post_competitor_bond_payable, "m1")
        with direct_vm.expect_revert("exceeds refundable balance"):
            desk.withdraw_refund(101)


def test_withdraw_empty_reverts(desk, direct_vm):
    with direct_vm.expect_revert("no refundable balance"):
        desk.withdraw_refund(10)


def test_claim_refundable_balance_full(registered, direct_vm, direct_charlie):
    desk = registered[0]
    with direct_vm.prank(direct_charlie):
        payable(direct_vm, 777, desk.post_competitor_bond_payable, "m1")
        res = desk.claim_refundable_balance()
    assert res["released_wei"] == 777 and res["remaining_refundable"] == 0
    summary = desk.get_custody_accounting_summary()
    assert summary["total_refunds_released_wei"] == 777
    assert summary["native_invariant_balanced"]


def test_last_payable_rejection_recorded_and_cleared(registered, direct_vm, direct_charlie):
    desk = registered[0]
    with direct_vm.prank(direct_charlie):
        payable(direct_vm, BOND, desk.post_competitor_bond_payable, "m1")
        assert desk.get_last_payable_rejection(direct_charlie) == "caller is not a listed finalist"
        payable(direct_vm, PRIZE, desk.fund_prize_vault_payable)
        assert desk.get_last_payable_rejection(direct_charlie) == ""


# ---------------------------------------------------------------------------
# accounting views
# ---------------------------------------------------------------------------
def test_leaderboard_gates(registered4, direct_vm):
    desk = both_bonds(direct_vm, registered4, registered4[2], registered4[3])
    rows = desk.get_tournament_leaderboard()
    assert len(rows) == 1
    row = rows[0]
    assert not row["can_verify"]
    assert not row["can_protest"]
    warp(direct_vm, iso(registered4[1]["match_close_epoch"]))
    match = desk.get_match("m1")
    assert match["can_protest"]
    assert match["can_verify"]
    assert not match["can_settle"]
    warp(direct_vm, iso(registered4[1]["protest_deadline_epoch"]))
    assert not desk.get_match("m1")["can_protest"]


def test_custody_summary_balanced_after_full_flow(registered4, direct_vm):
    desk, out = verify_at_close(direct_vm, registered4, {"integrity_baseline_bps": 9000, "anomaly_index_bps": 500, "compliant_slot": "FINALIST_A"})
    settle_after_deadline(direct_vm, desk, registered4[1])
    summary = desk.get_custody_accounting_summary()
    assert summary["avt_invariant_balanced"] and summary["native_invariant_balanced"]
    assert summary["settlement_count"] == 1
    assert summary["total_paid_out_avt"] == PRIZE
    assert summary["void_count"] == 0 and summary["abandoned_refund_count"] == 0


def test_derived_drift_flag_absent_before_verify(registered, direct_vm):
    row = registered[0].get_match("m1")
    assert row["derived_consistency_ok"]


def test_offset_warp_gate_math(registered, direct_vm):
    res = registered[1]
    assert res["protest_deadline_epoch"] - res["match_close_epoch"] == 3600
    assert res["verification_timeout_epoch"] - res["protest_deadline_epoch"] == 86400
