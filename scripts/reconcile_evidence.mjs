// Reconcile evidence/studionet_live_lifecycle.json against the Studio explorer.
// Re-queries every recorded transaction hash, upgrades its status to the
// authoritative decided status, and refreshes consensus proof.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const EV = path.join(__dirname, "..", "evidence", "studionet_live_lifecycle.json");
const EXPLORER = "https://studio.genlayer.com/api/explorer/transactions/";

const ev = JSON.parse(fs.readFileSync(EV, "utf8"));
const log = (m) => console.log(new Date().toISOString().slice(11, 19), m);

async function view(hash) {
  const res = await fetch(EXPLORER + hash);
  if (!res.ok) return { explorer_http: res.status };
  const j = await res.json();
  const t = j?.transaction ?? {};
  const cd = t.consensus_data ?? {};
  const validators = (cd.validators ?? []).map((v) => ({
    mode: v.mode,
    vote: v.vote,
    result: v.result ? Buffer.from(v.result, "base64").toString("utf8").replace(/[^\x20-\x7e]/g, ".").slice(0, 160) : null,
  }));
  return {
    explorer_status: t.status ?? null,
    explorer_block: t.block_number ?? cd.block_number ?? null,
    leader_execution_result: cd.leader_receipt?.execution_result ?? null,
    votes: cd.votes ?? null,
    validators,
    distinct_results: [...new Set(validators.map((v) => v.result).filter((x) => x && x !== "idle" && x !== ".."))],
  };
}

let nonFinalized = 0;
for (const tx of ev.transactions ?? []) {
  try {
    const v = await view(tx.hash);
    tx.explorer = { ...tx.explorer, ...v };
    tx.status = v.explorer_status ?? tx.status;
    if (String(tx.status).toUpperCase() !== "FINALIZED") nonFinalized++;
    log(`${tx.label} -> ${tx.status} ${JSON.stringify(v.distinct_results ?? null)}`);
  } catch (e) {
    log(`${tx.label} -> query failed ${String(e.message).slice(0, 100)}`);
    nonFinalized++;
  }
}
ev.reconciled_at = new Date().toISOString();
ev.non_finalized_count = nonFinalized;
fs.writeFileSync(EV, JSON.stringify(ev, (k, v) => (typeof v === "bigint" ? v.toString() : v), 1));
log(`reconciled ${ev.transactions.length} txs, ${nonFinalized} not FINALIZED`);
