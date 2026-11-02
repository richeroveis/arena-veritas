// ArenaVeritas live studionet lifecycle: multi-signer seeding with explorer proof.
// Resumable via evidence/_checkpoint.json; evidence lands in
// evidence/studionet_live_lifecycle.json.
//
// Every transaction is polled through the Studio explorer JSON API until it is
// FINALIZED (the SDK resolves earlier at ACCEPTED, which is not canonical
// state), and the post-transaction contract read is retried until the consensus
// state delta becomes visible. Nothing here claims success without both.
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";
import dotenv from "dotenv";
import { toBytes } from "viem";
import { createAccount, createClient } from "genlayer-js";
import { studionet } from "genlayer-js/chains";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.join(__dirname, "..");
dotenv.config({ path: path.join(root, ".env") });

const ADDRESS = process.env.CONTRACT_ADDRESS || "0x1eC61228C0311150cAe42Af4d1C6C0bF847fc058";
const RAW = "https://raw.githubusercontent.com/richeroveis/arena-veritas/main/docs/evidence";
const EXPLORER = "https://studio.genlayer.com/api/explorer/transactions/";

const BOND = 10n ** 16n;          // 0.01 GEN anti-cheat bond
const PRIZE = 2n * 10n ** 18n;    // 2 AVT escrowed prize per bracket
const FUND = 10n * 10n ** 18n;    // 10 AVT prize custody vault funding

// Windows inside the contract floors and ceilings. The submission window is
// deliberately generous: studio consensus latency, not the contract, decides how
// long a multi-signer bond round takes.
const SUB_W = 1200n;
const MATCH_W = 300n;
const PROTEST_W = 900n;
const VTO_W = 3600n;

const FINAL_STATES = new Set(["FINALIZED", "REJECTED", "ERROR", "FAILED"]);

const burners = JSON.parse(fs.readFileSync(path.join(root, "evidence/_burners.json"), "utf8"));
// genlayer-js needs a real account instance so the signing address is derived;
// a bare {privateKey} object has no address and the RPC rejects the transaction.
const mk = (pk) => {
  const account = createAccount(pk);
  return Object.assign(createClient({ chain: studionet, account }), { _addr: account.address });
};
const org = mk(process.env.GENLAYER_PRIVATE_KEY);
const fa = mk(burners.finalistA.pk);
const fb = mk(burners.finalistB.pk);
const bs = mk(burners.bystander.pk);

for (const [name, client] of Object.entries({ finalistA: fa, finalistB: fb, bystander: bs })) {
  if (client._addr.toLowerCase() !== String(burners[name].address).toLowerCase()) {
    console.error(`SIGNER MISMATCH ${name}: key derives ${client._addr}`);
    process.exit(1);
  }
}
console.log(`signers ok organizer ${org._addr} finalistA ${fa._addr} finalistB ${fb._addr} bystander ${bs._addr}`);

const CK_PATH = path.join(root, "evidence/_checkpoint.json");
const EV_PATH = path.join(root, "evidence/studionet_live_lifecycle.json");
const ck = fs.existsSync(CK_PATH)
  ? JSON.parse(fs.readFileSync(CK_PATH, "utf8"))
  : { done: {}, txs: [], epochs: {}, notes: [] };
ck.notes = ck.notes ?? [];

// A FINALIZED transaction can still have failed execution (exit_code 1). Those
// attempts stay in the evidence history but are dropped from the resume map so
// the stage runs again with a correct call.
const executionFailed = (t) => {
  const results = t?.validator_results ?? t?.explorer?.distinct_results ?? [];
  return /REJECTED|ERROR|FAILED/.test(String(t?.status ?? ""))
    || results.some((r) => String(r).includes("exit_code 1") || String(r).includes("invalid_contract"));
};
for (const [label, rec] of Object.entries(ck.done)) {
  if (executionFailed(rec)) {
    ck.notes.push({ kind: "retry_after_failed_execution", label, tx: rec.hash, observed: rec.validator_results ?? rec.explorer?.distinct_results ?? null });
    delete ck.done[label];
  }
}

const retryNotes = ck.notes.some((n) => n.kind === "retry_after_failed_execution");

const bigintJson = (k, v) => (typeof v === "bigint" ? v.toString()
  : v && typeof v === "object" && v.bytes instanceof Uint8Array ? "0x" + Buffer.from(v.bytes).toString("hex")
    : typeof v === "string" && v.length > 3000 ? v.slice(0, 3000) : v);

function evShell() {
  return {
    project: "ArenaVeritas",
    contract_address: ADDRESS,
    chain: "studionet",
    chain_id: 61999,
    deploy_tx: "0x43c78b2806abc474831ad18e803732ffd5a0b4bc48a1a5b70d2980f36e27a83e",
    contract_sha256: "5daf9b09cebffb8026d1515eebc73667830fea0dbc7f64375a5bd905ee92b58d",
    runner_pin: "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6",
    explorer_base: "https://explorer-studio.genlayer.com/tx/",
    signers: { organizer: org._addr, finalist_a: fa._addr, finalist_b: fb._addr, bystander: bs._addr },
    windows_secs: { submission: Number(SUB_W), match: Number(MATCH_W), protest: Number(PROTEST_W), verification_timeout: Number(VTO_W) },
    notes: ck.notes,
    native_wei: { before: ck.native_before ?? null, after: ck.final?.native_after ?? null },
    transactions: ck.txs,
    final: ck.final ?? null,
    updated_at: new Date().toISOString(),
  };
}

const save = () => {
  fs.writeFileSync(CK_PATH, JSON.stringify(ck, bigintJson, 1));
  fs.writeFileSync(EV_PATH, JSON.stringify(evShell(), bigintJson, 1));
};
if (retryNotes) save();

const log = (m) => console.log(new Date().toISOString().slice(11, 19), m);

// GenVM encodes an Address parameter as its own calldata type, not as a string.
// genlayer-js does not export the wrapper class, so it is located in the
// package's own chunk files. Passing a plain hex string makes the EVM side
// revert, which is exactly how the first JS-driven register batch failed.
async function loadCalldataAddress() {
  const require = createRequire(import.meta.url);
  const dist = path.dirname(require.resolve("genlayer-js"));
  for (const file of fs.readdirSync(dist).filter((f) => /^chunk-.*\.js$/.test(f))) {
    try {
      const mod = await import(pathToFileURL(path.join(dist, file)).href);
      if (typeof mod.CalldataAddress === "function") return mod.CalldataAddress;
    } catch {
      /* chunk without the class */
    }
  }
  throw new Error("CalldataAddress not found in the installed genlayer-js build");
}

let addr = () => { throw new Error("CalldataAddress not loaded"); };

async function initAddressCodec() {
  const CalldataAddress = await loadCalldataAddress();
  addr = (value) => new CalldataAddress(toBytes(value));
}

async function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }

async function explorerView(hash) {
  try {
    const res = await fetch(EXPLORER + hash);
    if (!res.ok) return { explorer_http: res.status };
    const j = await res.json();
    const t = j?.transaction ?? {};
    const cd = t.consensus_data ?? {};
    const validators = (cd.validators ?? []).map((v) => ({
      mode: v.mode,
      vote: v.vote,
      result: v.result ? Buffer.from(v.result, "base64").toString("utf8").replace(/[^\x20-\x7e]/g, ".").slice(0, 200) : null,
    }));
    return {
      explorer_status: t.status ?? null,
      explorer_block: t.block_number ?? cd.block_number ?? null,
      leader_execution_result: cd.leader_receipt?.execution_result ?? null,
      votes: cd.votes ?? null,
      validators,
      distinct_results: [...new Set(validators.map((v) => v.result).filter((x) => x && x !== "idle" && x !== ".."))],
    };
  } catch (e) {
    return { explorer_error: String(e.message ?? e).slice(0, 200) };
  }
}

async function pollFinalized(label, hash, maxMs = 900000) {
  const started = Date.now();
  let view = {};
  let misses = 0;
  while (Date.now() - started < maxMs) {
    view = await explorerView(hash);
    const s = String(view.explorer_status ?? "").toUpperCase();
    if (FINAL_STATES.has(s)) return { ...view, explorer_status: s, waited_ms: Date.now() - started };
    if (view.explorer_error || view.explorer_http) {
      misses++;
      if (misses > 30) return { ...view, explorer_status: "QUERY_UNAVAILABLE", waited_ms: Date.now() - started };
    }
    await sleep(6000);
  }
  return { ...view, explorer_status: view.explorer_status ?? "TIMEOUT", waited_ms: Date.now() - started };
}

// Native GEN actually held by each account and by the contract. Recorded before
// and after the lifecycle so the refund path can be described from evidence.
async function nativeBalances() {
  const out = {};
  for (const [name, who] of Object.entries({ contract: ADDRESS, organizer: org._addr, finalist_a: fa._addr, finalist_b: fb._addr, bystander: bs._addr })) {
    out[name] = (await org.request({ method: "eth_getBalance", params: [who, "latest"] })).toString();
  }
  return out;
}

async function read(fn, args = [], client = org, tries = 12) {
  for (let i = 0; i < tries; i++) {
    try {
      return await client.readContract({ address: ADDRESS, functionName: fn, args });
    } catch (e) {
      const m = String(e.message ?? e);
      if (i === tries - 1) throw e;
      if (!/execution failed|not valid JSON|unknown RPC|rate|timeout|fetch failed|not found/i.test(m)) throw e;
      await sleep(7000);
    }
  }
}

function sanitize(x) {
  try {
    const s = JSON.stringify(x, bigintJson);
    return s ? JSON.parse(s) : null;
  } catch {
    return String(x).slice(0, 1500);
  }
}

async function submit(label, client, functionName, args = [], value = 0n) {
  if (ck.done[label]) { log(`skip ${label}`); return null; }
  log(`>> ${label} :: ${functionName}`);
  for (let attempt = 0; attempt < 8; attempt++) {
    try {
      const hash = await client.writeContract({ address: ADDRESS, functionName, args, value });
      return { label, functionName, args: sanitize(args), value: value.toString(), hash, signer: client._addr };
    } catch (e) {
      const m = String(e.message ?? e);
      if (attempt === 7) throw e;
      log(`!! ${label} submit retry ${attempt + 1} after ${m.slice(0, 90)}`);
      await sleep(20000);
    }
  }
  return null;
}

async function finish(label, rec) {
  const proof = await pollFinalized(label, rec.hash);
  const record = {
    ...rec,
    status: proof.explorer_status,
    block: proof.explorer_block ?? null,
    leader_execution_result: proof.leader_execution_result ?? null,
    validator_votes: proof.votes ?? null,
    validator_results: proof.distinct_results ?? [],
    validators: proof.validators ?? [],
    waited_ms: proof.waited_ms ?? null,
    result: rec.result ?? null,
  };
  ck.txs.push(record);
  ck.done[label] = record;
  save();
  log(`<< ${label} ${record.status} ${record.hash}`);
  return record;
}

async function run(label, client, functionName, args = [], value = 0n) {
  const rec = await submit(label, client, functionName, args, value);
  if (!rec) return ck.done[label];
  return finish(label, rec);
}

async function runBatch(items) {
  const pending = [];
  for (const it of items) {
    const rec = await submit(it.label, it.client, it.fn, it.args ?? [], it.value ?? 0n);
    if (rec) pending.push(rec);
  }
  const settled = {};
  await Promise.all(pending.map(async (rec) => { settled[rec.label] = await finish(rec.label, rec); }));
  const out = {};
  for (const it of items) out[it.label] = ck.done[it.label];
  return out;
}

async function waitUntil(label, epoch, pad = 20) {
  const drift = Math.max(0, (Number(epoch) + pad) * 1000 - Date.now());
  if (drift > 0) log(`waiting ${Math.round(drift / 1000)}s for ${label}`);
  await sleep(drift);
}

// Round 1 brackets were registered before the multi-signer round could start;
// they are recovered through the zero-winner void and abandoned-refund path,
// which returns their escrow to the organizer AVT ledger.
const STALE = ["cs2", "val", "elden", "dota"];
const TITLES = {
  cs2f: ["CS2 Major Grand Final", "CS2", "cs2-major-telemetry.html"],
  valf: ["Valorant Sovereign Cup", "Valorant", "valorant-sovereign-telemetry.html"],
  eldenf: ["Elden Ring Any% Speedrun WR Verification", "EldenRing", "elden-ring-anypercent-telemetry.html"],
  dotaf: ["Dota 2 Saigon Invitational", "Dota2", "dota-saigon-telemetry.html"],
};

async function main() {
  await initAddressCodec();
  log(`contract ${ADDRESS}`);
  const boot = await read("get_custody_accounting_summary");
  ck.native_before = await nativeBalances();
  log(`boot vault ${boot.vault_custody_balance_avt} AVT ledger ${boot.token_ledger_total_avt} escrow ${boot.escrowed_prize_total_avt} balanced ${boot.avt_invariant_balanced}`);
  log(`boot native ${JSON.stringify(ck.native_before)}`);
  save();

  // 0. Recover the first registration round through void + abandoned refund.
  // One no-argument read lists every bracket, so absent ids are cheap to detect.
  const known = new Set((await read("get_tournament_leaderboard")).map((r) => r.match_id));
  for (const mid of STALE) {
    if (!known.has(mid)) { log(`stale ${mid} not present on chain`); continue; }
    const rec = await read("get_match", [mid]);
    if (rec.status === "VOID" || rec.status === "REFUNDED") { log(`stale ${mid} already ${rec.status}`); continue; }
    await run(`void_stale_${mid}`, org, "mark_void_no_contest", [mid]);
    await run(`abandon_stale_${mid}`, org, "claim_abandoned_match_refund", [mid]);
  }
  const afterRecover = await read("get_custody_accounting_summary");
  log(`after recovery ledger ${afterRecover.token_ledger_total_avt} escrow ${afterRecover.escrowed_prize_total_avt} refundable ${afterRecover.refundable_total_wei}`);

  // 1. Fund the AVT prize custody vault with real native value (credited 1:1).
  if (!ck.done.fund_vault) {
    await run("fund_vault", org, "fund_prize_vault_payable", [], FUND);
  } else {
    log("skip fund_vault (already funded in an earlier round)");
  }

  // 2. Register 4 finals brackets concurrently; escrowed from organizer AVT credit.
  const plan = Object.entries(TITLES).map(([mid, [title, game]]) => ({
    label: `register_${mid}`, client: org, fn: "register_tournament_payable",
    args: [mid, title, game, PRIZE, BOND, BOND, `${RAW}/${TITLES[mid][2]}`, `${RAW}/av-rulebook.html`,
      SUB_W, MATCH_W, PROTEST_W, VTO_W, addr(fa._addr), addr(mid === "dotaf" ? bs._addr : fb._addr)],
  }));
  await runBatch(plan);

  const epochs = {};
  for (const mid of Object.keys(TITLES)) {
    epochs[mid] = await read("get_match", [mid]);
    ck.epochs[mid] = epochs[mid];
  }
  save();
  log(`${Object.keys(TITLES)[0]} sub close ${epochs.cs2f.submission_close_epoch} match close ${epochs.cs2f.match_close_epoch} deadline ${epochs.cs2f.protest_deadline_epoch}`);

  // 3. Multi-signer anti-cheat bonds (real native value from separate wallets).
  //    valf/FINALIST_A overpays by one bond to exercise the surplus-to-refundable
  //    path. dotaf's bystander slot never bonds: that drives the void path.
  await runBatch([
    { label: "bond_cs2_a", client: fa, fn: "post_competitor_bond_payable", args: ["cs2f"], value: BOND },
    { label: "bond_cs2_b", client: fb, fn: "post_competitor_bond_payable", args: ["cs2f"], value: BOND },
    { label: "bond_val_a", client: fa, fn: "post_competitor_bond_payable", args: ["valf"], value: BOND * 2n },
    { label: "bond_val_b", client: fb, fn: "post_competitor_bond_payable", args: ["valf"], value: BOND },
    { label: "bond_elden_a", client: fa, fn: "post_competitor_bond_payable", args: ["eldenf"], value: BOND },
    { label: "bond_elden_b", client: fb, fn: "post_competitor_bond_payable", args: ["eldenf"], value: BOND },
    { label: "bond_dota_a", client: fa, fn: "post_competitor_bond_payable", args: ["dotaf"], value: BOND },
  ]);

  // 4. Telemetry / replay submissions by the finalists.
  await runBatch([
    { label: "submit_cs2_a", client: fa, fn: "submit_tournament_telemetry", args: ["cs2f", "grand final 16-14 tick stream with no pause anomalies"] },
    { label: "submit_val_a", client: fa, fn: "submit_tournament_telemetry", args: ["valf", "map decider server rollback at round 14"] },
    { label: "submit_elden_b", client: fb, fn: "submit_tournament_telemetry", args: ["eldenf", "WR holder split file and input log"] },
  ]);

  // 5. Soft-fail payable: a bystander that is not a listed finalist funds a bond
  //    call. The call must NOT revert; the native value is credited to
  //    refundable_balances and is later withdrawn on chain.
  const soft = await run("softfail_bystander", bs, "post_competitor_bond_payable", ["cs2f"], BOND);
  const refundable = await read("get_refundable_balance", [addr(bs._addr)], bs);
  const rejection = await read("get_last_payable_rejection", [addr(bs._addr)], bs);
  ck.notes.push({
    kind: "soft_fail_payable",
    tx: soft.hash,
    status: soft.status,
    expectation: "no revert with value > 0; credit lands in refundable_balances",
    observed_refundable_wei: String(refundable),
    observed_last_rejection: rejection,
  });
  save();
  log(`softfail ${soft.status} refundable ${refundable} rejection ${JSON.stringify(rejection)}`);

  const bonded = await read("get_match", ["cs2f"]);
  log(`cs2f status ${bonded.status} bond_a ${bonded.bond_a_wei} bond_b ${bonded.bond_b_wei}`);

  // 6. Match close: live prompt_comparative consensus verification of the three
  //    contested brackets, plus the anti-cheat protest inside the challenge window.
  await waitUntil("match close", epochs.cs2f.match_close_epoch);
  await runBatch([
    { label: "protest_elden", client: fb, fn: "file_anti_cheat_protest_payable", args: ["eldenf", "FINALIST_A", "input tick automation and frame splice detected in the WR split file"], value: BOND },
    { label: "verify_cs2", client: org, fn: "verify_match_telemetry", args: ["cs2f"] },
    { label: "verify_val", client: org, fn: "verify_match_telemetry", args: ["valf"] },
    { label: "verify_elden", client: org, fn: "verify_match_telemetry", args: ["eldenf"] },
  ]);
  for (const mid of ["cs2f", "valf", "eldenf"]) {
    const r = await read("get_match", [mid]);
    ck.notes.push({ kind: "post_verify_read", match_id: mid, status: r.status, verdict_band: r.verdict_band, verified_winner_slot: r.verified_winner_slot, integrity_bps: String(r.quantized_integrity_baseline_bps), anomaly_bps: String(r.quantized_anomaly_bps) });
    log(`${mid} -> ${r.status} ${r.verdict_band} ${r.verified_winner_slot}`);
  }
  save();

  // 7. Dota: zero-winner void path once the submission window closed.
  await waitUntil("dota submission close", epochs.dotaf.submission_close_epoch);
  await run("void_dota", org, "mark_void_no_contest", ["dotaf"]);
  await run("abandon_dota", org, "claim_abandoned_match_refund", ["dotaf"]);

  // 8. Refund withdrawals: the bystander claims its soft-failed credit and
  //    finalist A withdraws its overpaid bond surplus by amount.
  await run("claim_refundable_bystander", bs, "claim_refundable_balance");
  await run("withdraw_refund_surplus", fa, "withdraw_refund", [BOND]);

  // 9. Settlements after the protest deadline.
  await waitUntil("protest deadline", epochs.cs2f.protest_deadline_epoch);
  await runBatch([
    { label: "settle_cs2", client: org, fn: "claim_tournament_settlement", args: ["cs2f"] },
    { label: "settle_val", client: org, fn: "claim_tournament_settlement", args: ["valf"] },
    { label: "settle_elden", client: org, fn: "claim_tournament_settlement", args: ["eldenf"] },
  ]);

  // 10. Final accounting snapshot plus per-wallet claims.
  const summary = await read("get_custody_accounting_summary");
  const board = await read("get_tournament_leaderboard");
  const wallets = {};
  for (const [name, client] of Object.entries({ organizer: org, finalist_a: fa, finalist_b: fb, bystander: bs })) {
    wallets[name] = {
      address: client._addr,
      avt_credit: String(await read("get_avt_balance", [addr(client._addr)])),
      refundable_wei: String(await read("get_refundable_balance", [addr(client._addr)])),
    };
  }
  ck.final = { custody_summary: sanitize(summary), leaderboard: board.map(sanitize), wallets, native_after: await nativeBalances() };
  save();
  log("FINAL SUMMARY " + JSON.stringify(sanitize(summary)));
  log("VERDICTS " + JSON.stringify(board.map((r) => [r.match_id, r.status, r.verdict_band, r.verified_winner_slot])));
  log("scenarios complete");
}

main().catch((e) => { console.error("SEED FAILED:", e); process.exit(1); });
