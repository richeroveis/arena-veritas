// ArenaVeritas studionet seeding and evidence collection.
// Resumable: stages are checkpointed to evidence/_checkpoint.json (gitignored).
// Every transaction hash and receipt is written to evidence/studionet-run.json.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import dotenv from "dotenv";
import { createClient } from "genlayer-js";
import { studionet } from "genlayer-js/chains";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const root = path.join(__dirname, "..");
dotenv.config({ path: path.join(root, ".env") });

const ADDRESS = process.env.CONTRACT_ADDRESS || "0x1eC61228C0311150cAe42Af4d1C6C0bF847fc058";
const RAW = "https://raw.githubusercontent.com/richeroveis/arena-veritas/main/docs/evidence";
const BOND = 10n ** 16n;
const PRIZE = 2n * 10n ** 18n;
const FUND = 10n * 10n ** 18n;

const burners = JSON.parse(fs.readFileSync(path.join(root, "evidence/_burners.json"), "utf8"));
const org = createClient({ chain: studionet, account: { privateKey: process.env.GENLAYER_PRIVATE_KEY } });
const fa = createClient({ chain: studionet, account: { privateKey: burners.finalistA.pk } });
const fb = createClient({ chain: studionet, account: { privateKey: burners.finalistB.pk } });
const bs = createClient({ chain: studionet, account: { privateKey: burners.bystander.pk } });

const CK_PATH = path.join(root, "evidence/_checkpoint.json");
const EV_PATH = path.join(root, "evidence/studionet-run.json");
const ck = fs.existsSync(CK_PATH) ? JSON.parse(fs.readFileSync(CK_PATH, "utf8")) : { done: {}, txs: [], epochs: {} };
const save = () => {
  fs.writeFileSync(CK_PATH, JSON.stringify(ck, (k, v) => (typeof v === "bigint" ? v.toString() : v), 1));
  fs.writeFileSync(EV_PATH, JSON.stringify({
    contract: ADDRESS, chain: "studionet 61999", account: "tidex22",
    runner_pin: "py-genlayer:1jb45aa8ynh2a9c9xn3b7qqh8sm5q93hwfp7jqmwsfhh8jpz09h6",
    transactions: ck.txs,
  }, (k, v) => (typeof v === "bigint" ? v.toString() : v), 1));
};

const log = (m) => console.log(new Date().toISOString().slice(11, 19), m);

async function run(label, client, functionName, args = [], value = 0n, waitOpts = {}) {
  if (ck.done[label]) { log(`skip ${label}`); return ck.done[label]; }
  log(`>> ${label} :: ${functionName}`);
  const hash = await client.writeContract({ address: ADDRESS, functionName, args, value });
  const receipt = await client.waitForTransactionReceipt({ hash, ...({ retries: 60, interval: 4000 }, waitOpts) });
  const status = receipt.status_name ?? receipt.status ?? "UNKNOWN";
  const record = {
    label, functionName, hash, status,
    result: sanitize(receipt.result ?? receipt.stdout ?? receipt.output ?? null),
    validator_votes_name: receipt.validation?.validator_votes_name ?? receipt.validator_votes_name ?? null,
  };
  ck.txs.push(record);
  ck.done[label] = record;
  save();
  log(`<< ${label} ${status} ${hash}`);
  return record;
}

function sanitize(x) {
  try {
    const s = JSON.stringify(x, (k, v) => (typeof v === "bigint" ? v.toString() : typeof v === "number" ? v : (typeof v === "string" && v.length > 4000 ? v.slice(0, 4000) : v)));
    return s ? JSON.parse(s) : null;
  } catch { return String(x).slice(0, 2000); }
}

async function read(fn, args = [], client = org) {
  return client.readContract({ address: ADDRESS, functionName: fn, args });
}

async function sleep(ms) { return new Promise((r) => setTimeout(r, ms)); }
async function waitUntil(label, epoch) {
  const drift = Math.max(0, (epoch + 20) * 1000 - Date.now());
  if (drift > 0) log(`waiting ${Math.round(drift / 1000)}s for ${label}`);
  await sleep(drift);
}

const matches = [
  ["cs2", "CS2 Major Grand Final", "CS2", "cs2-major-telemetry.html", burners.finalistA.address, burners.finalistB.address],
  ["val", "Valorant Sovereign Cup", "Valorant", "valorant-sovereign-telemetry.html", burners.finalistA.address, burners.finalistB.address],
  ["elden", "Elden Ring Any% Speedrun WR Verification", "EldenRing", "elden-ring-anypercent-telemetry.html", burners.finalistA.address, burners.finalistB.address],
  ["dota", "Dota 2 Saigon Invitational", "Dota2", "dota-saigon-telemetry.html", burners.finalistA.address, burners.bystander.address],
];

async function main() {
  log(`contract ${ADDRESS}`);
  const info = await read("get_custody_accounting_summary");
  log(`vault ${info.vault_custody_balance_avt} AVT, balanced: ${info.avt_invariant_balanced}`);

  // 1. Fund the AVT prize custody vault (real native value, credited 1:1 AVT).
  await run("fund_vault", org, "fund_prize_vault_payable", [], FUND);

  // 2. Register 4 finals brackets, escrowed from the organizer AVT credit.
  for (const [mid, title, game, page, a, b] of matches) {
    const rec = await run(`register_${mid}`, org, "register_tournament_payable", [
      mid, title, game, PRIZE, BOND, BOND,
      `${RAW}/${page}`, `${RAW}/av-rulebook.html`,
      300n, 60n, 300n, 3600n, a, b,
    ]);
    if (rec.result && !ck.epochs[mid]) {
      ck.epochs[mid] = rec.result;
      save();
    }
  }
  // Pull epochs deterministically from chain if the checkpoint predates them.
  for (const [mid] of matches) {
    if (!ck.epochs[mid]) {
      ck.epochs[mid] = await read("get_match", [mid]);
      save();
    }
  }

  // 3. Anti-cheat bonds (multi-signer deposits). Dota bystander never bonds.
  const bondPlan = [
    ["bond_cs2_a", fa, "cs2"], ["bond_cs2_b", fb, "cs2"],
    ["bond_val_a", fa, "val"], ["bond_val_b", fb, "val"],
    ["bond_elden_a", fa, "elden"], ["bond_elden_b", fb, "elden"],
    ["bond_dota_a", fa, "dota"],
  ];
  for (const [label, client, mid] of bondPlan) {
    await run(label, client, "post_competitor_bond_payable", [mid], BOND);
  }

  // 4. Telemetry / replay submissions by finalists.
  await run("submit_cs2_a", fa, "submit_tournament_telemetry", ["cs2", "demo 16-14 verified tick stream"]);
  await run("submit_val_a", fa, "submit_tournament_telemetry", ["val", "map decider rollback stream"]);
  await run("submit_elden_b", fb, "submit_tournament_telemetry", ["elden", "WR holder split file"]);

  // 5. Wait for gates, then live validator consensus verification.
  await waitUntil("cs2 match close", Number(ck.epochs.cs2.match_close_epoch));
  await run("verify_cs2", org, "verify_match_telemetry", ["cs2"], 0n, { retries: 150 });

  await waitUntil("val match close", Number(ck.epochs.val.match_close_epoch));
  await run("verify_val", org, "verify_match_telemetry", ["val"], 0n, { retries: 150 });

  // Elden protest inside the challenge window (before deadline), then verify.
  await waitUntil("elden protest window", Number(ck.epochs.elden.match_close_epoch));
  await run("protest_elden", fb, "file_anti_cheat_protest_payable",
    ["elden", "FINALIST_A", "input tick automation and frame splice in the WR split file"], BOND);
  await run("verify_elden", org, "verify_match_telemetry", ["elden"], 0n, { retries: 150 });

  // 6. Dota: zero-winner void path once the submission deadline passed.
  await waitUntil("dota submission close", Number(ck.epochs.dota.submission_close_epoch));
  await run("void_dota", org, "mark_void_no_contest", ["dota"]);
  await run("abandon_dota", org, "claim_abandoned_match_refund", ["dota"]);

  // 7. Settlements after the protest deadline.
  await waitUntil("cs2 protest deadline", Number(ck.epochs.cs2.protest_deadline_epoch));
  await run("settle_cs2", org, "claim_tournament_settlement", ["cs2"]);
  await run("settle_val", org, "claim_tournament_settlement", ["val"]);
  await run("settle_elden", org, "claim_tournament_settlement", ["elden"]);

  // 8. Soft-fail payable demo + withdrawal (bystander is not a finalist).
  await run("softfail_bystander", bs, "post_competitor_bond_payable", ["cs2"], BOND);
  await run("withdraw_bystander", bs, "claim_refundable_balance");

  // 9. Final accounting snapshot.
  const summary = await read("get_custody_accounting_summary");
  const board = await read("get_tournament_leaderboard");
  ck.final = { summary: sanitize(summary), leaderboard_rows: board.length, verdicts: board.map((r) => ({ match: r.match_id, status: r.status, band: r.verdict_band, winner: r.verified_winner_slot })) };
  save();
  log("FINAL SUMMARY " + JSON.stringify(ck.final.summary));
  log("scenarios complete");
}

main().catch((e) => { console.error("SEED FAILED:", e); process.exit(1); });
