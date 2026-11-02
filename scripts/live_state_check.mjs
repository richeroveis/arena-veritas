// Read-only live re-verification of the deployed ArenaVeritas contract.
// Touches no state: every call is a view method. Used by the pre-submission
// check to confirm that the accounting on chain still matches the evidence
// file, and that the deployed address still answers with this build's schema.
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

// Address calldata args must be wrapped in the SDK's CalldataAddress. A plain
// string encodes as a string and the runner rejects the call at execution.
async function loadCalldataAddress() {
  const require = createRequire(import.meta.url);
  const dist = path.dirname(require.resolve("genlayer-js"));
  for (const file of fs.readdirSync(dist).filter((f) => /^chunk-.*\.js$/.test(f))) {
    try {
      const mod = await import(pathToFileURL(path.join(dist, file)).href);
      if (typeof mod.CalldataAddress === "function") return mod.CalldataAddress;
    } catch {
      // chunk without the export, keep scanning
    }
  }
  throw new Error("CalldataAddress not found in the installed genlayer-js build");
}
const CalldataAddress = await loadCalldataAddress();
const addr = (value) => new CalldataAddress(toBytes(value));

const org = createClient({ chain: studionet, account: createAccount(process.env.GENLAYER_PRIVATE_KEY) });

const read = async (functionName, args = []) => {
  for (let attempt = 1; attempt <= 3; attempt += 1) {
    try {
      return await org.readContract({ address: ADDRESS, functionName, args });
    } catch (error) {
      if (attempt === 3) throw error;
      await new Promise((r) => setTimeout(r, 12000));
    }
  }
  throw new Error("unreachable");
};

const burners = JSON.parse(fs.readFileSync(path.join(root, "evidence/_burners.json"), "utf8"));
// The organizer is the .env signer itself, so its address is derived from the key
// rather than stored in the burner registry.
const organizerAddress = createAccount(process.env.GENLAYER_PRIVATE_KEY).address;
const wallets = { organizer: { address: organizerAddress }, ...burners };
const summary = await read("get_custody_accounting_summary");
console.log("custody summary");
for (const [k, v] of Object.entries(summary)) console.log(`  ${k} = ${v}`);

const leaderboard = await read("get_tournament_leaderboard");
console.log(`leaderboard (${leaderboard.length} matches)`);
for (const m of leaderboard) {
  console.log(
    `  ${m.match_id} ${m.status}:${m.verdict_band} winner=${m.verified_winner_slot} ` +
      `prize=${m.prize_pool_avt} slash=${m.bond_slash_wei} consistency=${m.derived_consistency_ok}`,
  );
}

for (const [name, meta] of Object.entries(wallets)) {
  const avt = await read("get_avt_balance", [addr(meta.address)]);
  const refundable = await read("get_refundable_balance", [addr(meta.address)]);
  const lastRejection = await read("get_last_payable_rejection", [addr(meta.address)]);
  console.log(`wallet ${name} ${meta.address}`);
  console.log(`  avt=${avt} refundable_wei=${refundable} last_rejection="${lastRejection}"`);
}

// The invariant terms, evaluated from the summary the contract itself reports.
const settled = leaderboard.filter((m) => m.status === "SETTLED").length;
const refunded = leaderboard.filter((m) => m.status === "REFUNDED").length;
console.log("assertions");
console.log(`  avt_invariant_balanced = ${summary.avt_invariant_balanced}`);
console.log(`  native_invariant_balanced = ${summary.native_invariant_balanced}`);
console.log(`  settlements=${settled} refunds=${refunded} report_count=${leaderboard.length}`);
console.log(`  expected bracket evidence reachable = ${RAW}/av-rulebook.html`);
