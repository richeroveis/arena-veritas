// Finish the CS2 bracket: the first verify attempt finalized with a reverted
// execution ([LLM_ERROR] bad compliant_slot), which is the contract failing
// closed rather than guessing a winner. Retry the consensus verification until
// a valid slot is committed, then settle, and merge the result into the single
// live lifecycle evidence file.
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
const EXPLORER = "https://studio.genlayer.com/api/explorer/transactions/";
const EV_PATH = path.join(root, "evidence", "studionet_live_lifecycle.json");
const FINAL_STATES = new Set(["FINALIZED", "REJECTED", "ERROR", "FAILED"]);

const require_ = createRequire(import.meta.url);
const distDir = path.dirname(require_.resolve("genlayer-js"));
let CalldataAddress = null;
for (const f of fs.readdirSync(distDir).filter((x) => /^chunk-.*\.js$/.test(x))) {
  const mod = await import(pathToFileURL(path.join(distDir, f)).href);
  if (typeof mod.CalldataAddress === "function") { CalldataAddress = mod.CalldataAddress; break; }
}
const addr = (a) => new CalldataAddress(toBytes(a));

const burners = JSON.parse(fs.readFileSync(path.join(root, "evidence", "_burners.json"), "utf8"));
const mk = (pk) => {
  const account = createAccount(pk);
  return Object.assign(createClient({ chain: studionet, account }), { _addr: account.address });
};
const org = mk(process.env.GENLAYER_PRIVATE_KEY);
const fa = mk(burners.finalistA.pk);
const fb = mk(burners.finalistB.pk);
const bs = mk(burners.bystander.pk);

const log = (m) => console.log(new Date().toISOString().slice(11, 19), m);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function view(hash) {
  for (let i = 0; i < 150; i++) {
    try {
      const res = await fetch(EXPLORER + hash);
      if (!res.ok) { await sleep(8000); continue; }
      const j = await res.json();
      const t = j?.transaction ?? {};
      const cd = t.consensus_data ?? {};
      const validators = (cd.validators ?? []).map((v) => ({
        mode: v.mode,
        vote: v.vote,
        result: v.result ? Buffer.from(v.result, "base64").toString("utf8").replace(/[^\x20-\x7e]/g, ".").slice(0, 200) : null,
      }));
      const status = String(t.status ?? "").toUpperCase();
      if (FINAL_STATES.has(status)) {
        return {
          explorer_status: status,
          explorer_block: t.block_number ?? cd.block_number ?? null,
          leader_execution_result: cd.leader_receipt?.execution_result ?? null,
          votes: cd.votes ?? null,
          validators,
          distinct_results: [...new Set(validators.map((v) => v.result).filter((x) => x && x !== "idle" && x !== ".."))],
        };
      }
    } catch { /* transient gateway hiccup */ }
    await sleep(8000);
  }
  return { explorer_status: "TIMEOUT" };
}

async function read(fn, args = [], client = org, tries = 15) {
  for (let i = 0; i < tries; i++) {
    try { return await client.readContract({ address: ADDRESS, functionName: fn, args }); }
    catch (e) {
      if (i === tries - 1) throw e;
      log(`read ${fn} retry ${i + 1}: ${String(e.message).slice(0, 70)}`);
      await sleep(7000);
    }
  }
}

const ev = JSON.parse(fs.readFileSync(EV_PATH, "utf8"));
const sanitize = (x) => {
  try { return JSON.parse(JSON.stringify(x, (k, v) => (typeof v === "bigint" ? v.toString() : typeof v === "string" && v.length > 3000 ? v.slice(0, 3000) : v))); }
  catch { return String(x).slice(0, 1500); }
};

async function record(label, client, functionName, args = [], value = 0n) {
  log(`>> ${label}`);
  let hash;
  for (let attempt = 0; attempt < 6; attempt++) {
    try { hash = await client.writeContract({ address: ADDRESS, functionName, args, value }); break; }
    catch (e) {
      log(`!! ${label} submit retry ${attempt + 1} ${String(e.message).slice(0, 80)}`);
      await sleep(20000);
    }
  }
  const proof = await view(hash);
  const rec = {
    label, functionName, args: sanitize(args), value: (value ?? 0n).toString(), hash, signer: client._addr,
    status: proof.explorer_status, block: proof.explorer_block ?? null,
    leader_execution_result: proof.leader_execution_result ?? null,
    validator_votes: proof.votes ?? null,
    validator_results: proof.distinct_results ?? [],
    validators: proof.validators ?? [],
  };
  ev.transactions.push(rec);
  fs.writeFileSync(EV_PATH, JSON.stringify(ev, (k, v) => (typeof v === "bigint" ? v.toString() : v), 1));
  log(`<< ${label} ${rec.status} ${hash}`);
  return rec;
}

async function main() {
  let rec = await read("get_match", ["cs2f"]);
  log(`cs2f status ${rec.status} band ${rec.verdict_band || "-"}`);
  for (let attempt = 1; attempt <= 4 && rec.status === "ACTIVE"; attempt++) {
    await record(`verify_cs2_attempt_${attempt}`, org, "verify_match_telemetry", ["cs2f"]);
    rec = await read("get_match", ["cs2f"]);
    log(`after attempt ${attempt}: cs2f ${rec.status} ${rec.verdict_band || "-"} winner ${rec.verified_winner_slot || "-"}`);
    if (rec.status !== "ACTIVE") break;
    await sleep(15000);
  }
  if (rec.status === "VERIFIED") {
    await record("settle_cs2_retry", org, "claim_tournament_settlement", ["cs2f"]);
    rec = await read("get_match", ["cs2f"]);
    log(`cs2f final ${rec.status} ${rec.verdict_band} winner ${rec.verified_winner_slot}`);
  }

  const summary = await read("get_custody_accounting_summary");
  const board = await read("get_tournament_leaderboard");
  const wallets = {};
  for (const [name, client] of Object.entries({ organizer: org, finalist_a: fa, finalist_b: fb, bystander: bs })) {
    wallets[name] = {
      address: client._addr,
      avt_credit: String(await read("get_avt_balance", [addr(client._addr)])),
      refundable_wei: String(await read("get_refundable_balance", [addr(client._addr)])),
      native_wei: (await client.request({ method: "eth_getBalance", params: [client._addr, "latest"] })).toString(),
    };
  }
  wallets.contract = {
    address: ADDRESS,
    native_wei: (await org.request({ method: "eth_getBalance", params: [ADDRESS, "latest"] })).toString(),
  };
  ev.final = {
    custody_summary: sanitize(summary),
    leaderboard: board.map(sanitize),
    wallets,
    native_after: { contract: wallets.contract.native_wei },
  };
  ev.updated_at = new Date().toISOString();
  fs.writeFileSync(EV_PATH, JSON.stringify(ev, (k, v) => (typeof v === "bigint" ? v.toString() : v), 1));
  log("FINAL " + JSON.stringify(sanitize(summary)));
  log("VERDICTS " + JSON.stringify(board.map((r) => [r.match_id, r.status, r.verdict_band, r.verified_winner_slot])));
}

main().catch((e) => { console.error("FINISH FAILED:", e); process.exit(1); });
