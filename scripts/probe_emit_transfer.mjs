// Does an intelligent contract on studionet actually return native value to an
// EOA through emit_transfer? This decides whether the ArenaVeritas refund path
// releases real funds or only bookkeeping.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import dotenv from "dotenv";
import { createAccount, createClient } from "genlayer-js";
import { studionet } from "genlayer-js/chains";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
dotenv.config({ path: path.join(__dirname, "..", ".env") });

const ADDR = "0xd3aBC5bc71346035D69137a77e8D9CCD16BB89CB";
const AMOUNT = 10n ** 16n;
const EXPLORER = "https://studio.genlayer.com/api/explorer/transactions/";

const account = createAccount(process.env.GENLAYER_PRIVATE_KEY);
const client = createClient({ chain: studionet, account });
const log = (m) => console.log(new Date().toISOString().slice(11, 19), m);

async function bal(addr) {
  return BigInt(await client.request({ method: "eth_getBalance", params: [addr, "latest"] }));
}

async function waitFinalized(hash) {
  for (let i = 0; i < 120; i++) {
    const r = await fetch(EXPLORER + hash);
    const j = await r.json();
    const t = j?.transaction;
    if (t && /FINALIZED|REJECTED|ERROR|FAILED/.test(String(t.status))) {
      const results = (t.consensus_data?.validators ?? [])
        .map((v) => (v.result ? Buffer.from(v.result, "base64").toString("utf8").replace(/[^\x20-\x7e]/g, ".").slice(0, 80) : null))
        .filter((x) => x && x !== "idle");
      return { status: t.status, results: [...new Set(results)] };
    }
    await new Promise((s) => setTimeout(s, 6000));
  }
  return { status: "TIMEOUT", results: [] };
}

const startUser = await bal(account.address);
const startContract = await bal(ADDR);
log(`start user ${startUser} contract ${startContract}`);

const dep = await client.writeContract({ address: ADDR, functionName: "deposit", args: [], value: AMOUNT });
log(`deposit tx ${dep}`);
log("deposit " + JSON.stringify(await waitFinalized(dep)));
const afterDeposit = await bal(account.address);
const held = await client.readContract({ address: ADDR, functionName: "get_held", args: [] });
log(`after deposit user ${afterDeposit} held ${String(held)} contract ${await bal(ADDR)}`);

const pay = await client.writeContract({ address: ADDR, functionName: "payout", args: [AMOUNT] });
log(`payout tx ${pay}`);
log("payout " + JSON.stringify(await waitFinalized(pay)));
await new Promise((s) => setTimeout(s, 20000));
const afterPayout = await bal(account.address);
log(`after payout user ${afterPayout} held ${String(await client.readContract({ address: ADDR, functionName: "get_held", args: [] }))} contract ${await bal(ADDR)}`);
log(`DELTA user ${afterPayout - startUser} wei  (deposit moved ${afterDeposit - startUser} wei out)`);
fs.writeFileSync(path.join(__dirname, "emit_transfer_probe.json"), JSON.stringify({
  account: account.address, contract: ADDR, amount: AMOUNT.toString(),
  start_user: startUser.toString(), after_deposit: afterDeposit.toString(), after_payout: afterPayout.toString(),
  deposit_tx: dep, payout_tx: pay,
}, null, 1));
