# Adversarial review: contracts/arena_veritas.py

Reviewed as an attacker: organizer, either finalist, the bystander, the LLM, the
content of the fetched evidence pages, and the validators themselves. The contract
is frozen at the deployed identity (`0x1eC61228C0311150cAe42Af4d1C6C0bF847fc058`,
sha256 `5daf9b09cebffb8026d1515eebc73667830fea0dbc7f64375a5bd905ee92b58d`), so
findings are marked FIXED (already in the deployed code and proven by a test or a
live transaction) or OPEN (documented, not patched, with the reason).

## 1. State machine and who may move money

| Status | Prize | Bonds | Protest bond | Who can exit | Exit method |
| --- | --- | --- | --- | --- | --- |
| OPEN | escrowed | 0 or 1 | none | organizer/any | `mark_void_no_contest` after `submission_close_epoch`, or `claim_abandoned_match_refund` after `verification_timeout_epoch` |
| ACTIVE | escrowed | 2 | optional | anyone | `verify_match_telemetry`, or void/refund as above |
| VERIFIED | escrowed | 2 | optional | anyone | `claim_tournament_settlement` at/after `protest_deadline_epoch` |
| SETTLED | paid | released | released | terminal | none needed |
| VOID | escrowed | 0 or 1 | optional | anyone | `claim_abandoned_match_refund` |
| REFUNDED | returned | to refundable | to refundable | terminal | none needed |

No status can hold value without an exit that does not require the counterparty to
act: settlement needs only that the deadline passed, and the void/abandoned paths
need only the submission or verification timeout.

## 2. Liveness findings

- **Stuck in VERIFIED forever?** No: settlement unlocks at `protest_deadline_epoch`
  regardless of whether anyone protests.
- **Delivered but never approved / created but never funded?** Registration escrows
  the prize atomically (from AVT credit or from exact native value), so there is no
  unfunded bracket. A bracket that never gets two bonds is voidable and refundable.
- **Appeal window never used?** Settlement does not depend on the protest window
  being used, only on it expiring.
- **Abandoned protest bond?** `protest_bond_escrow_wei` is always consumed at
  settlement (awarded to the protestant if upheld, forfeited to the accused if
  dismissed) or returned at the abandoned refund.
- FIXED (liveness, was a real bug): a second distinct protestant used to overwrite
  `protest_bond_escrow_wei` and orphan the first protest bond. The deployed guard is
  `elif rec.protest_filed: reason = "a protest is already filed for this bracket"`,
  with a regression test (`test_second_distinct_protest_...`) that asserts the first
  protest bond is untouched and the second sender is soft-failed into refundable.
- FIXED: `paused` blocks intake only. `verify_match_telemetry`,
  `claim_tournament_settlement`, `claim_abandoned_match_refund`, `withdraw_refund`
  and `claim_refundable_balance` ignore `paused`, so pausing can never strand funds.

## 3. Race matrix (both orderings checked)

| Pair | Guard that makes them exclusive |
| --- | --- |
| verify vs protest | verify requires `ACTIVE`; protest allows `ACTIVE` or `VERIFIED` but only while `now < protest_deadline_epoch`; verify re-reads the record after the nondet block and reverts with "bracket state moved mid verify" |
| settle vs protest | settle requires `now >= protest_deadline_epoch`, protest requires `now < protest_deadline_epoch`: strict complement, no overlap |
| settle vs abandoned refund | settle requires `VERIFIED`; abandoned refund requires `VOID` or (`OPEN`/`ACTIVE` past timeout) and `not refund_claimed` |
| bond vs void | bond requires `now <= submission_close_epoch`; void requires `now > submission_close_epoch` |
| bond vs settle | bond requires `OPEN`/`ACTIVE`; settle requires `VERIFIED` and flips to `SETTLED` |
| double settle / double withdraw | `SETTLED` status guard and `refund_claimed` flag; `_release_refundable` reverts when the amount exceeds the recorded balance |
| cancel vs fund | there is no cancel; the only exits are settlement and refund, both invariant-checked |

## 4. Accounting invariants

```
vault_custody_balance_avt  == escrowed_prize_total_avt + token_ledger_total_avt
native_custody_balance_wei == escrowed_bond_total_wei + escrowed_protest_total_wei + refundable_total_wei
```

- Both are asserted inside `claim_tournament_settlement` after every transfer, and
  the transaction reverts if either breaks ("AVT custody invariant broken" /
  "native custody invariant broken").
- Every payout split sums exactly to the escrow: `SPLIT_DRAW_SETTLEMENT` uses
  `prize // 2` and `prize - prize // 2`, so an odd prize cannot lose a wei.
- `_compute_match_settlement_view` recomputes the band's payouts from the stored
  band, prize and bond and exposes `derived_consistency_ok`; settlement refuses to
  run on drift, so a stale record cannot pay a different amount than the band implies.
- Live proof: after the full lifecycle the on-chain summary reported
  `avt_invariant_balanced: true` and `native_invariant_balanced: true` with
  `vault_custody_balance_avt = 10e18`, `token_ledger_total_avt = 10e18`,
  `escrowed_prize_total_avt = 0`, `total_paid_out_avt = 6e18`, and the four wallet
  credits summing to exactly 10e18.

## 5. Input validation at every entry point

- Length caps: match id 64, title 120, game 48, URL 2048, protest reason 500,
  token symbol 16.
- Positive and ceiling bounds: prize `<= 1e24`, bond and protest bond `<= 1e20`,
  vault funding `<= 1e25`.
- Every time window has both a floor and a ceiling (submission 300..2419200,
  match 60..604800, protest 300..86400, verification timeout 3600..2419200). The
  live run used 1200/300/900/3600.
- Caller sanity: `finalist_a != finalist_b`, neither may be the zero address,
  bonds and protests require the caller to occupy a slot, self-protest is rejected,
  `set_paused` is admin only.
- Value sanity: `register_tournament_payable` with native value requires
  `value == prize_pool_avt` exactly; bonds and protest bonds require at least the
  recorded amount and credit any surplus to refundable instead of keeping it.
- Epochs come only from `gl.message_raw["datetime"]` through a strict ISO parser
  (shape, component ranges, no pre-1970 values); there is no `advance_clock`, no
  owner-settable clock and no wall-clock read.

## 6. Consensus safety

- Anything that decides a transfer (`verify_match_telemetry`) runs inside one
  nondet block whose result is compared with `prompt_comparative` and requires
  **exact equality on all seven decision fields**. No numeric tolerance.
- Money amounts are never taken from the model: the band and the payouts are
  derived in deterministic Python from the two quantized integers, and the
  quantization snaps to a 500 bps grid, which removes the float/rounding
  disagreement surface.
- Evidence is fetched independently: the leader renders the telemetry and rulebook
  URLs, and each validator re-runs the same function, so every evaluator fetches
  the same URLs itself.
- Fail closed: a render shorter than 24/16 characters raises `[TRANSIENT]`, a
  non-dict LLM answer or a bad slot raises `[LLM_ERROR]`, and both force
  disagreement/rotation instead of a default verdict. Proven live:
  `verify_cs2` (tx `0x9111416c1cdacd9a5fbdbec8e30d9f62e78eae4b2d308af06d76b693e5798949`)
  finalized with `[LLM_ERROR] bad compliant_slot` and **did not change state**;
  the bracket stayed ACTIVE and `settle_cs2` then reverted with
  "[EXPECTED] bracket is not VERIFIED". The retry
  (`verify_cs2_attempt_1`, tx `0x02ff2ab12a45e8f3856243444c8f731acca76992ffdf7c782a7031d36ccfa2b1`)
  committed `VERIFIED_CHAMPION_PAYOUT / FINALIST_A` with three validators agreeing.
- Validator agreement is only provable on chain: direct mode runs the leader. The
  live run shows the votes for every verify: `verify_val` and `verify_elden` each
  finalized with 3 agree / 2 idle and identical verdict payloads.
- Prompt injection: fetched text is embedded in the prompt, so it can try to steer
  the reported numbers. What it cannot change is the rule: thresholds, the 500 bps
  grid, the band mapping and the payout formulas are contract constants, and the
  slot must be one of two literal labels. Tested: a garbage LLM answer, a bad slot
  and an empty render all revert (direct tests), and the live run reverted on a bad
  slot. Not claimed to be injection-proof in general.

## 7. Findings marked OPEN

1. **Native value cannot leave the contract to an EOA on this runner (platform,
   not code).** `withdraw_refund` and `claim_refundable_balance` correctly release
   the custody claim and decrement `native_custody_balance_wei`, but the GEN itself
   stays at the contract address. Proven twice:
   - isolated probe: deposit tx `0xda2911f9...` then `payout` with
     `gl.get_contract_at(sender).emit_transfer(value)` tx `0x22adcb48...` drove the
     probe contract balance to 0 while the sender wallet balance did not increase;
   - live lifecycle: after `claim_refundable_bystander`
     (`0x30b93ede...`) and `withdraw_refund_surplus` (`0xe669b321...`) the bystander
     and finalist A native balances are byte-identical to the pre-claim snapshot,
     while the contract still holds 10.10 GEN against
     `native_custody_balance_wei = 0.08e17` of released claims.
   Consequence: native bond refunds are claims against the operator, not automatic
   wallet credits. Not patched because the pinned runner offers no primitive that
   works, and the redeploy would break the verified four-way source identity.
2. **`claim_abandoned_match_refund` does not re-assert the two invariants** the way
   settlement does. All of its mutations are balanced by construction and the direct
   tests assert both invariants after the abandoned refund, so this is a defense in
   depth gap rather than an exploitable path. Left open for the same identity reason.
3. **`_coerce_bps` reads a percent-style answer as bps.** `"92.5"` becomes 92, not
   9250. It is deterministic and identical for every validator, so consensus is
   safe, but a model that answers in percent produces a low integrity value and the
   `RULE_VIOLATION_PENALTY` band instead of a champion payout. The prompt demands
   0..10000 bps; the residual risk is documented, not eliminated.
4. **`technical_draw_verified` outranks cheat evidence** in `_derive_band`, so a
   telemetry page that asserts a verified server interruption converts a
   disqualification into a 50/50 split. The remedy is human: the protest window and
   the appeal path, not an automatic re-ordering.
5. **The organizer controls the evidence pages until registration closes**, and
   consensus only guarantees that every validator read the same pinned URLs. A
   fabricated page can produce a fabricated verdict as long as validators agree.
   This is the oracle trust boundary of the design, stated rather than solved.
6. **Studio read-after-finalize lag** is real: a canonical read can still return the
   pre-transaction state for a short while. The drivers retry reads instead of
   trusting `ACCEPTED`; nothing in the contract depends on it.

## 8. Test evidence

- 82 direct mode tests pass (`tests/test_arena_veritas_direct.py`), including a
  negative test for every guard listed above, boundary tests at exactly
  `submission_close_epoch`, `match_close_epoch` and `protest_deadline_epoch`,
  zero/under/over payment, double withdraw, double credit, all four bands, the
  quantization edges (8600 to 8500, 999 to 1000), the LLM garbage paths, the
  second-protest regression, and the invariant checks after each mixed scenario.
- `genvm-lint check` passes: 19 methods, 7 views, 12 writes, 2 constructor params.
- Live: 38 transactions reconciled through the Studio explorer JSON API, all
  FINALIZED, in [evidence/studionet_live_lifecycle.json](../evidence/studionet_live_lifecycle.json).
