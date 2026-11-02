# Deployment record

All statements in this file are backed by a command run against the network, not
by a CLI banner. Every transaction id below was re-queried through the Studio
explorer JSON API (`https://studio.genlayer.com/api/explorer/transactions/<hash>`)
and its validator votes are stored in [evidence/studionet_live_lifecycle.json](../evidence/studionet_live_lifecycle.json).

## Identity

| Item | Value |
| --- | --- |
| Network | studionet (GenLayer Studio, chain id 61999) |
| Contract | `0x1eC61228C0311150cAe42Af4d1C6C0bF847fc058` |
| Explorer | https://explorer-studio.genlayer.com/address/0x1eC61228C0311150cAe42Af4d1C6C0bF847fc058 |
| Deploy tx | `0x43c78b2806abc474831ad18e803732ffd5a0b4bc48a1a5b70d2980f36e27a83e` (FINALIZED) |
| Deployer | `0x154a452b0755EE812014C1405B15D905BA06f9c7` |
| Constructor args | `0x1111111111111111111111111111111111111111`, `AVT` |
| Runner pin | `py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6` |
| Source size | 37,467 bytes, 698 lines |
| Source sha256 | `5daf9b09cebffb8026d1515eebc73667830fea0dbc7f64375a5bd905ee92b58d` |

### Four-way source identity

The same sha256 was verified for:

1. the working tree file `contracts/arena_veritas.py`,
2. the git blob at `HEAD:contracts/arena_veritas.py`,
3. the raw GitHub copy `https://raw.githubusercontent.com/richeroveis/arena-veritas/main/contracts/arena_veritas.py`,
4. the `contract_code` field of the deploy transaction returned by the explorer,
   decoded from base64 and compared byte for byte with the local file.

Reproduce with:

```powershell
Get-FileHash contracts/arena_veritas.py -Algorithm SHA256
git hash-object contracts/arena_veritas.py
node scripts/reconcile_evidence.mjs   # re-checks every recorded tx
```

## Toolchain

| Step | Command | Result |
| --- | --- | --- |
| Lint and semantics | `.venv/Scripts/genvm-lint.exe check contracts/arena_veritas.py` | ok, 19 methods (7 view, 12 write), 2 ctor params |
| Direct tests | `.venv/Scripts/python.exe -m pytest tests/test_arena_veritas_direct.py -q` | 82 passed |
| Deploy | `genlayer deploy --contract contracts/arena_veritas.py --args ...` | FINALIZED, contract readable |
| Live lifecycle | `node scripts/seed_studionet.mjs` | see below |

## Live lifecycle on studionet

Signers: organizer plus three separate burner wallets (finalist A, finalist B,
bystander). Windows used for every bracket: submission 1200 s, match 300 s,
protest 900 s, verification timeout 3600 s, all inside the contract floors and
ceilings.

The machine readable record with every hash, status, validator vote and returned
payload is [evidence/studionet_live_lifecycle.json](../evidence/studionet_live_lifecycle.json).
Summary of the stages:

| Stage | Method | Signer | What it proves |
| --- | --- | --- | --- |
| Vault funding | `fund_prize_vault_payable` | organizer | 10 GEN native in, credited 1:1 as AVT, AVT invariant balanced |
| Registration | `register_tournament_payable` x4 | organizer | prize escrowed from AVT credit, four brackets OPEN |
| Bonds | `post_competitor_bond_payable` x7 | two finalists | native bond custody, both slots activate the bracket, one overpayment surplus credited to refundable |
| Telemetry | `submit_tournament_telemetry` x3 | finalists | evidence submission inside the window |
| Soft fail | `post_competitor_bond_payable` | bystander | funded call does NOT revert; `refundable_balances` credited 0.01 GEN and `last_payable_rejection` records "caller is not a listed finalist" |
| Protest | `file_anti_cheat_protest_payable` | finalist B | protest bond escrowed inside the challenge window |
| Consensus verify | `verify_match_telemetry` x3 | organizer | leader and validators each render the telemetry and rulebook URLs, verdict bands committed with validator votes |
| Void and refund | `mark_void_no_contest`, `claim_abandoned_match_refund` | organizer | zero-winner bracket returns escrow and bonds |
| Refund release | `claim_refundable_balance`, `withdraw_refund` | bystander, finalist A | soft-failed credit and overpaid surplus released |
| Settlement | `claim_tournament_settlement` x3 | organizer | payouts after the protest deadline, invariants asserted in the same tx |

## Deployment gotchas found the hard way

1. **Prose comments directly under the pinned header break the deploy.** The
   contiguous `#` block at the top of the file is parsed as runner metadata. Any
   comment line between the `# { "Depends": ... }` header and the first import
   makes genvm reject the contract with `invalid_contract`, even though
   `genvm-lint check`, schema generation and 82 direct tests all pass locally.
   Line 1 must be the pin, imports must follow immediately, and prose comments
   belong below the imports.
2. **`ACCEPTED` is not execution success.** A transaction can finalize while the
   contract call reverted. The seeding driver polls the explorer until
   `FINALIZED` and inspects `consensus_data.validators[].result` (base64) before
   treating a stage as done, and it keeps failed attempts in the evidence file.
3. **Address arguments need the GenVM calldata address type.** A plain hex string
   is encoded as text and the call reverts. `genlayer-js` does not export the
   wrapper class, so `scripts/seed_studionet.mjs` and `frontend/vite.config.js`
   locate it inside the installed build and wrap every address argument.
4. **The hosted studio can finalize before the canonical read catches up.** Reads
   after a write are retried instead of assumed.
5. **Native value cannot leave an intelligent contract to an EOA on this runner.**
   Proven with a throwaway contract: `gl.get_contract_at(eoa).emit_transfer(value)`
   debited the probe contract to zero but the wallet balance never increased.
   See [evidence/emit-transfer-probe.json](../evidence/emit-transfer-probe.json)
   (deposit tx `0xda2911f9...`, payout tx `0x22adcb48...`). The consequence for
   this contract is written up in
   [docs/adversarial-review.md](adversarial-review.md).
