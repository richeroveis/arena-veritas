# ARENA VERITAS

**AI-verified esports, speedrun and competitive match integrity settlement on GenLayer.**

![ArenaVeritas emblem](docs/logo.png)

Broadcast Control Room and Match Integrity Desk: brackets are funded from an AVT
prize custody vault, competitors post native anti-cheat bonds from separate
wallets, telemetry and rulebook evidence are re-fetched and judged by validator
consensus, and payouts only settle after the protest deadline has passed.

| | |
| --- | --- |
| Live DApp | https://richeroveis.github.io/arena-veritas/ |
| Contract (studionet 61999) | `0x1eC61228C0311150cAe42Af4d1C6C0bF847fc058` |
| Explorer | https://explorer-studio.genlayer.com/address/0x1eC61228C0311150cAe42Af4d1C6C0bF847fc058 |
| Deploy tx (FINALIZED) | `0x43c78b2806abc474831ad18e803732ffd5a0b4bc48a1a5b70d2980f36e27a83e` |
| Contract sha256 | `5daf9b09cebffb8026d1515eebc73667830fea0dbc7f64375a5bd905ee92b58d` |
| Runner pin | `py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6` |
| Live lifecycle evidence | [evidence/studionet_live_lifecycle.json](evidence/studionet_live_lifecycle.json) |
| Deployment record | [docs/deployment.md](docs/deployment.md) |
| Adversarial review | [docs/adversarial-review.md](docs/adversarial-review.md) |
| Demo reel (subtitled, 50 s) | [docs/demo-video-subtitled.mp4](docs/demo-video-subtitled.mp4) |

---

## 1. What needs consensus, and what does not

The boundary was written down before the code, because it decides the whole
design.

**Frontend owns:** rendering the bracket ticker, the frame-tick preview, wallet
connection, and every non-authoritative convenience number. The analyzer in the
browser is a referee preview; it is never the verdict.

**GenLayer contract owns:** the prize custody vault, native bond escrow, the
protest window, the verdict band, the payout split, the refunds, and the
accounting invariants that must hold when money moves.

**External sources own:** the raw facts. Each bracket pins a
`telemetry_report_url` and a `rulebook_url`. The leader fetches them, and every
validator fetches them again on chain. Nobody's self-reported claim is trusted,
and a missing or truncated render fails closed as a transient error rather than
silently producing a verdict.

## 2. Lifecycle state machine

| Status | Reachable by | Methods still allowed | Money state |
| --- | --- | --- | --- |
| `OPEN` | `register_tournament_payable` | `post_competitor_bond_payable`, `submit_tournament_telemetry` | prize escrowed from the organizer AVT credit, no bonds yet |
| `ACTIVE` | both bond slots filled | `submit_tournament_telemetry`, `verify_match_telemetry` (after `match_close_epoch`), `file_anti_cheat_protest_payable` (inside the challenge window), `mark_void_no_contest` (after `submission_close_epoch`) | prize plus bonds plus protest bond locked |
| `VERIFIED` | consensus verdict committed | `file_anti_cheat_protest_payable` (until deadline), `claim_tournament_settlement` (at/after `protest_deadline_epoch`), `claim_abandoned_match_refund` (only via timeout path) | verdict amounts derived and stored, nothing paid yet |
| `SETTLED` | `claim_tournament_settlement` | none (idempotent guard) | prize split per band, bonds kept or slashed, protest bond awarded or forfeited |
| `VOID` | `mark_void_no_contest` | `claim_abandoned_match_refund` | escrow still locked, awaiting refund |
| `REFUNDED` | `claim_abandoned_match_refund` | none | organizer escrow returned, bonds and protest credit released to `refundable_balances` |

Every status that can hold money has an exit that does not depend on a
counterparty cooperating: the settlement path, the void path, and the
`verification_timeout_epoch` abandoned-refund path. Deadlines are derived from
`gl.message_raw["datetime"]`, never from a wall clock the contract trusts.

## 3. Verdict bands on a discrete grid

Inside one `gl.nondet` block the leader renders both evidence URLs, asks for a
fixed JSON shape, then snaps integrity and anomaly onto the 500 bps grid and
derives everything else from those two integers:

| Band | Condition | Prize effect | Bond effect |
| --- | --- | --- | --- |
| `VERIFIED_CHAMPION_PAYOUT` | integrity >= 8500 and anomaly <= 1000 | 100% to the verified winner slot | both bonds returned |
| `SPLIT_DRAW_SETTLEMENT` | verified technical draw | 50/50 between slots | both bonds returned |
| `RULE_VIOLATION_PENALTY` | minor infraction, compliant slot kept | 75% champion, 25% back to organizer | 10% slash on the violator bond |
| `CHEAT_DISQUALIFICATION_SLASH` | anomaly >= 3000 or concrete cheat evidence | full prize to the clean slot | violator bond fully slashed, protest bond to the protestant, forfeited if the protest is dismissed |

`gl.eq_principle.prompt_comparative` then demands **100% exact equality** on all
seven decision fields: `verdict_band`, `verified_winner_slot`,
`quantized_integrity_baseline_bps`, `quantized_anomaly_bps`,
`derived_champion_payout`, `derived_runner_up_payout`, `derived_bond_slash`.
There is no numeric tolerance anywhere near a transfer.

## 4. Custody accounting

Two invariants, recomputed by a single helper and asserted inside the settlement
transaction itself:

```
vault_custody_balance_avt == escrowed_prize_total_avt + token_ledger_total_avt
native_custody_balance_wei == escrowed_bond_total_wei + escrowed_protest_total_wei + refundable_total_wei
```

`get_custody_accounting_summary` exposes both sides plus `avt_invariant_balanced`
and `native_invariant_balanced`, so a reviewer can check the books without
trusting the UI. If a settlement would break either equality the transaction
reverts instead of paying.

## 5. Soft-fail payables (the rule that funded calls never revert)

`fund_prize_vault_payable`, `register_tournament_payable`,
`post_competitor_bond_payable` and `file_anti_cheat_protest_payable` are payable
and never revert when `gl.message.value > 0`. A rejected call with value attached
credits `refundable_balances[sender]`, records the reason in
`last_payable_rejection[sender]`, and returns a rejection payload. The sender
recovers the funds with `claim_refundable_balance` or `withdraw_refund(amount)`.
A zero-value call with a bad argument still reverts, because there is nothing to
strand.

Live proof on studionet: a bystander wallet that is not a listed finalist sent
0.01 GEN with `post_competitor_bond_payable`. The transaction finalized without a
revert, `get_refundable_balance` returned `10000000000000000`, and
`get_last_payable_rejection` returned `caller is not a listed finalist`. The
bystander then reclaimed it with `claim_refundable_balance`.

## 6. Broadcast Control Room (frontend)

Vite vanilla app in `frontend/`, themed Cyber-Obsidian and Signal Lime
(`#07090E`, `#101520`, `#A3E635`, `#F43F5E`, Chakra Petch with JetBrains Mono), with
three pods:

1. **Live Tournament Bracket and Prize Custody Ticker.** Reads the leaderboard and
   the custody summary, shows per-bracket status, escrow, bond requirements,
   temporal gates and countdowns, plus the connected wallet's AVT credit and
   refundable balance.
2. **Frame-Tick and Replay Integrity Analyzer.** Sliders for frame-time variance,
   input-tick entropy and packet loss, mapped through the same 500 bps quantize
   and band-derivation functions the contract uses, clearly labelled
   non-authoritative.
3. **Referee Equivalence and Protest Docket Console.** Shows the equivalence
   fields validators must agree on, the protest window bar, and the gated desk
   actions.

Load budget is 2 RPC calls. All contract interaction goes through `genlayer-js`
by function name against the on-chain schema, with no local ABI override. Address
arguments are wrapped in the SDK's GenVM calldata address type (see
`frontend/vite.config.js`), because a plain hex string is encoded as text and the
chain reverts. Wallets: 1-click burner competitor wallet for signing, MetaMask for
read-only inspection.

## 7. Verification

```bash
# contract lint and semantics
.venv/Scripts/genvm-lint.exe check contracts/arena_veritas.py
# 82 direct mode tests, ~8 s
.venv/Scripts/python.exe -m pytest tests/test_arena_veritas_direct.py -q
# live studionet lifecycle (resumable, writes evidence)
node scripts/seed_studionet.mjs
# read-only re-check of the deployed books (view methods only)
node scripts/live_state_check.mjs
# brand assets and demo reel
.venv/Scripts/python.exe scripts/render_arena_brand_assets.py
.venv/Scripts/python.exe scripts/build_broadcast_demo_reel.py
# frontend
cd frontend && npm install && npm run build
```

Direct mode covers state transitions, every guard (wrong caller, wrong status,
too early, too late, exactly at the boundary, zero, overpay), the four verdict
bands through mocked web and LLM responses, double credit and double withdraw,
and the accounting invariant after each step of mixed scenarios. Direct mode runs
the leader only: it does **not** prove validator agreement. That part is covered
by the live studionet run, where every transaction is re-queried through the
Studio explorer JSON API and recorded with its validator votes.

## 8. Live lifecycle results (studionet)

38 transactions, every one reconciled against the Studio explorer JSON API and
stored with its validator votes in
[evidence/studionet_live_lifecycle.json](evidence/studionet_live_lifecycle.json).
Four brackets reached four different terminal states:

| Bracket | Band | Winner | Final status | Settle tx |
| --- | --- | --- | --- | --- |
| `cs2f` CS2 Major Grand Final | `VERIFIED_CHAMPION_PAYOUT` | `FINALIST_A` | SETTLED | `0x6f46a9ea2e63acdd3694ceb7b82a598150691028b0dd20c3404c12065ab8c966` |
| `valf` Valorant Sovereign Cup | `SPLIT_DRAW_SETTLEMENT` | `DRAW` | SETTLED | `0x3c30f6e1be51094b90357eb31a60ca68ef5a714b7c9246cc63e962dfcf0389d5` |
| `eldenf` Elden Ring Any% WR | `CHEAT_DISQUALIFICATION_SLASH` | `FINALIST_B` | SETTLED | `0xa8e0368a8ab5c94fee2527c2be0a614e61d56ccbfde96db55469b49eeb0b3523` |
| `dotaf` Dota 2 Saigon Invitational | `VOID_NO_CONTEST_REFUND` | `NONE` | REFUNDED | `0x97c3c27c460164fc3289c565af9624471ada22fbcd138146d7a246334db024b3` |

Consensus evidence: `verify_val` `0x892a1de2...` and `verify_elden` `0x06f990d9...`
finalized with three validators agreeing and two idle. `verify_cs2`
`0x9111416c...` finalized with `[LLM_ERROR] bad compliant_slot` and committed no
state: the contract refused to invent a winner, and `settle_cs2` then reverted with
"bracket is not VERIFIED". The retry `0x02ff2ab1...` produced the champion payout
band. That pair of transactions is the fail-closed behaviour demonstrated on chain.

Final books read from the contract: `vault_custody_balance_avt = 10e18`,
`token_ledger_total_avt = 10e18`, `escrowed_prize_total_avt = 0`,
`total_paid_out_avt = 6e18`, `refundable_total_wei = 8e16`,
`settlement_count = 3`, `void_count = 1`, `abandoned_refund_count = 1`, and both
`avt_invariant_balanced` and `native_invariant_balanced` true. The four wallet AVT
credits (organizer 4, finalist A 3, finalist B 3, bystander 0) sum to exactly 10.

## 9. Known limits, stated plainly

- AVT custody is an internal ledger credit inside this contract, minted 1:1 from
  native value deposited through `fund_prize_vault_payable`. It is not an ERC20
  and `external_avt_custody_probe` only reports a token contract balance when the
  configured `avt_token_address` really implements `balanceOf`.
- Studio consensus latency, not the contract, decides how long a multi-signer
  round takes. The first JS-driven registration batch reverted because address
  arguments were encoded as strings; those attempts are kept in the evidence file
  marked with their failed execution result, and the corrected batch is recorded
  next to them.
- The hosted studio can finalize a non-deterministic transaction before the
  canonical read reflects it. The seeding driver therefore polls the explorer
  until `FINALIZED` and retries the follow-up read instead of trusting the SDK's
  earlier `ACCEPTED` state.
- Native value cannot leave an intelligent contract to an EOA on this runner. The
  refund methods release the custody claim in contract state and decrement the
  invariant, but the GEN itself stays at the contract address; this was proven with
  an isolated `emit_transfer` probe and with the before/after wallet balances of the
  live run. See [evidence/emit-transfer-probe.json](evidence/emit-transfer-probe.json)
  and [docs/adversarial-review.md](docs/adversarial-review.md).
- Fetched evidence is treated as untrusted text and is truncated into the prompt;
  the verdict rule is fixed by the contract, not by anything a page can instruct.
  Prompt-injection resistance here means "instructions in evidence cannot change
  the band thresholds", which is structural, not learned.

## 10. Repository layout

```
contracts/arena_veritas.py            intelligent contract, 37,467 bytes
tests/test_arena_veritas_direct.py    82 direct mode tests
frontend/                             Broadcast Control Room (Vite)
docs/                                 logo, subtitled demo reel, deployment and review records
docs/evidence/                        telemetry and rulebook pages the validators fetch
scripts/                              seeding, evidence reconciliation, asset and reel builders
evidence/                             machine readable live run record
```
