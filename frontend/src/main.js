import {
  loadDeskSnapshot, loadWalletLedger, read, act,
  connectBurner, connectMetaMask, contractAddress,
} from "./desk.js";

const GRID = 500;
const FLOOR = 8500, ANOM_CEIL = 1000, CHEAT_AT = 3000;

const $ = (id) => document.getElementById(id);
// All chain-sourced strings are organizer/validator supplied; escape before any
// innerHTML interpolation and only allow http(s) URLs through.
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const safeUrl = (u) => (/^https?:\/\/[^\s"']+$/.test(String(u ?? "")) ? esc(u) : "#");
const fmt = (v) => {
  const n = BigInt(v ?? 0);
  if (n === 0n) return "0";
  if (n % 10n ** 15n === 0n) return (n / 10n ** 15n) + "K";
  if (n > 10n ** 15n) return (Number(n) / 1e15).toFixed(2) + "e15";
  return n.toString();
};
const short = (a) => (a ? a.slice(0, 8) + ".." + a.slice(-6) : "--");

function toast(msg, ok = true) {
  const t = $("toast");
  t.textContent = msg;
  t.className = "toast" + (ok ? "" : " err");
  setTimeout(() => t.classList.add("hidden"), 6000);
}

function quantize(raw) {
  const v = Math.max(0, Math.min(10000, Math.round(raw)));
  const r = v % GRID;
  return Math.min(10000, r * 2 >= GRID ? v - r + GRID : v - r);
}

function deriveBand(iq, aq, draw, viol, cheat) {
  if (draw) return "SPLIT_DRAW_SETTLEMENT";
  if (cheat || aq >= CHEAT_AT) return "CHEAT_DISQUALIFICATION_SLASH";
  if (iq >= FLOOR && aq <= ANOM_CEIL && !viol) return "VERIFIED_CHAMPION_PAYOUT";
  return "RULE_VIOLATION_PENALTY";
}

const state = { rows: [], selected: null, summary: null };

async function refresh() {
  const { leaderboard, summary } = await loadDeskSnapshot();
  state.rows = leaderboard.map((r) => ({
    ...r,
    prize_pool_avt: BigInt(r.prize_pool_avt),
    bond_a_wei: BigInt(r.bond_a_wei),
    bond_b_wei: BigInt(r.bond_b_wei),
    champion_payout_avt: BigInt(r.champion_payout_avt),
  }));
  state.summary = summary;
  renderTicker();
  renderLedger();
  if (state.selected) {
    const row = state.rows.find((r) => r.match_id === state.selected);
    if (row) renderDocket(row);
  }
  updateAnalyzer();
}

function renderTicker() {
  const host = $("bracket-list");
  host.innerHTML = "";
  if (!state.rows.length) {
    host.innerHTML = '<p class="mono dim">No brackets registered on this desk yet.</p>';
    return;
  }
  for (const r of state.rows) {
    const div = document.createElement("div");
    div.className = "bracket" + (r.match_id === state.selected ? " sel" : "");
    div.innerHTML = `
      <div><div class="title">${esc(r.title)}</div>
      <div class="meta">${esc(r.game)} // ${esc(r.match_id)} // PRIZE ${fmt(r.prize_pool_avt)} AVT //
      BOND ${fmt(BigInt(r.bond_required_wei ?? 0))} wei // A:${short(r.finalist_a)} B:${short(r.finalist_b)}</div>
      <div class="meta">BONDS POSTED ${fmt(r.bond_a_wei)}/${fmt(r.bond_b_wei)} ${r.protest_filed ? "// PROTEST FILED" : ""}</div></div>
      <span class="status st-${esc(r.status)}">${esc(r.status)}</span>`;
    div.addEventListener("click", () => {
      state.selected = r.match_id;
      renderTicker();
      renderDocket(r);
      updateAnalyzer();
    });
    host.appendChild(div);
  }
}

function renderLedger() {
  const s = state.summary;
  $("led-vault").textContent = fmt(s.vault_custody_balance_avt) + " AVT";
  $("led-escrow").textContent = fmt(s.escrowed_prize_total_avt);
  $("led-bonds").textContent = fmt(s.escrowed_bond_total_wei) + "+" + fmt(s.escrowed_protest_total_wei);
  $("led-refund").textContent = fmt(s.refundable_total_wei);
  $("led-counts").textContent = `${s.settlement_count}/${s.void_count}/${s.abandoned_refund_count}`;
  $("custody-led").textContent =
    (s.avt_invariant_balanced && s.native_invariant_balanced ? "VAULT OK " : "VAULT !! ") + fmt(s.vault_custody_balance_avt) + " AVT";
}

function countdown(row, now) {
  const open = row.match_close_epoch - now;
  const prot = row.protest_deadline_epoch - now;
  if (prot > 0 && open <= 0) return { label: "PROTEST WINDOW", secs: prot, from: row.match_close_epoch, to: row.protest_deadline_epoch, now };
  if (open > 0) return { label: "UNTIL MATCH CLOSE", secs: open, from: now, to: row.match_close_epoch, now };
  const settle = row.verification_timeout_epoch - now;
  if (settle > 0) return { label: "VERIFICATION WINDOW", secs: settle, from: row.protest_deadline_epoch, to: row.verification_timeout_epoch, now };
  return { label: "TIMEOUT REACHED", secs: 0, from: 0, to: 1, now };
}

function renderDocket(row) {
  const now = Math.floor(Date.now() / 1000);
  const cd = countdown(row, now);
  const pct = Math.max(0, Math.min(100, 100 * (cd.now - cd.from) / Math.max(1, cd.to - cd.from)));
  const bandCls = row.verdict_band || "neutral";
  $("docket-detail").innerHTML = `
    <div class="field-row"><span>BRACKET</span><b>${esc(row.title)} [${esc(row.match_id)}]</b></div>
    <div class="field-row"><span>OFFICIAL TELEMETRY PAGE</span><b><a class="evidence-link" target="_blank" rel="noopener" href="${safeUrl(row.telemetry_url)}">${esc(row.telemetry_url)}</a></b></div>
    <div class="field-row"><span>RULEBOOK PAGE</span><b><a class="evidence-link" target="_blank" rel="noopener" href="${safeUrl(row.rulebook_url)}">${esc(row.rulebook_url)}</a></b></div>
    <div class="field-row"><span>STATUS</span><b class="lime">${esc(row.status)}</b></div>
    <div class="field-row"><span>CONSENSUS VERDICT BAND</span><b class="${row.verdict_band ? "lime" : ""}">${esc(row.verdict_band) || "PENDING VALIDATOR CONSENSUS"}</b></div>
    <div class="field-row"><span>VERIFIED WINNER SLOT</span><b>${esc(row.verified_winner_slot) || "--"}</b></div>
    <div class="field-row"><span>QUANTIZED INTEGRITY / ANOMALY</span><b>${row.quantized_integrity_baseline_bps ?? 0} / ${row.quantized_anomaly_bps ?? 0} bps (grid ${row.derived_consistency_ok ? "CONSISTENT" : "DRIFT!"})</b></div>
    <div class="field-row"><span>DERIVED CHAMPION / RUNNER-UP / SLASH</span><b>${fmt(row.champion_payout_avt)} / ${fmt(row.runner_up_payout_avt)} AVT / ${fmt(row.bond_slash_wei)} wei</b></div>
    <div class="field-row"><span>${cd.label}</span><b>${Math.max(0, Math.floor(cd.secs))}s</b></div>
    <div class="window-bar"><i style="width:${pct}%"></i></div>
    <div class="field-row"><span>GATES</span><b>
      BOND:${row.can_post_bond ? "OPEN" : "SHUT"} VERIFY:${row.can_verify ? "READY" : "LOCKED"}
      PROTEST:${row.can_protest ? "WINDOW" : "SHUT"} SETTLE:${row.can_settle ? "UNLOCKED" : "LOCKED"}</b></div>
    <div class="field-row"><span>ABANDONED REFUND</span><b class="${row.can_abandon_refund ? "crimson" : ""}">${row.can_abandon_refund ? "CLAIMABLE (VOID/TIMEOUT)" : "--"}</b></div>`;
  for (const btn of document.querySelectorAll("#action-panel .btn")) {
    const actName = btn.dataset.act;
    btn.disabled = !(
      (actName === "bond" && row.can_post_bond) ||
      (actName === "submit" && row.status === "ACTIVE") ||
      (actName === "protest" && row.can_protest) ||
      (actName === "verify" && row.can_verify) ||
      (actName === "settle" && row.can_settle) ||
      (actName === "abandon" && row.can_abandon_refund)
    );
    btn.dataset.match = row.match_id;
  }
}

function updateAnalyzer() {
  const frame = +$("sl-frame").value, entropy = +$("sl-entropy").value, loss = +$("sl-loss").value;
  $("out-frame").textContent = frame;
  $("out-entropy").textContent = entropy;
  $("out-loss").textContent = loss;
  const rawIntegrity = 10000 - frame * 40 - loss * 25;
  const rawAnomaly = entropy * 45;
  const iq = quantize(rawIntegrity), aq = quantize(rawAnomaly);
  $("q-integrity").textContent = iq + " bps";
  $("q-anomaly").textContent = aq + " bps";
  const band = deriveBand(iq, aq, $("ck-draw").checked, $("ck-viol").checked, $("ck-cheat").checked);
  const el = $("band-preview");
  el.className = "band " + band;
  const row = state.rows.find((r) => r.match_id === state.selected);
  if (!row) {
    el.textContent = "SELECT A BRACKET TO PREVIEW SETTLEMENT BAND";
    return;
  }
  const prize = row.prize_pool_avt;
  let desc;
  if (band === "VERIFIED_CHAMPION_PAYOUT") desc = `100% prize (${fmt(prize)} AVT) to verified winner, full bond return`;
  else if (band === "SPLIT_DRAW_SETTLEMENT") desc = `50/50 split (${fmt(prize / 2n)} AVT each), full bond return`;
  else if (band === "RULE_VIOLATION_PENALTY") desc = `75% (${fmt(prize * 75n / 100n)} AVT) to compliant opponent, 25% refund to organizer, minor bond deduction`;
  else desc = `cheater bond slashed 100% to clean opponent + protestant, prize (${fmt(prize)} AVT) to clean opponent`;
  el.textContent = `${band} :: ${desc}`;
}

async function onAction(btn) {
  const row = state.rows.find((r) => r.match_id === btn.dataset.match);
  if (!row) return;
  try {
    let tx;
    switch (btn.dataset.act) {
      case "bond":
        tx = await act("post_competitor_bond_payable", [row.match_id], BigInt(row.bond_required_wei));
        break;
      case "submit":
        tx = await act("submit_tournament_telemetry", [row.match_id, "broadcast desk replay note"]);
        break;
      case "protest": {
        const target = row.finalist_a && row.finalist_b
          ? (walletIs(row.finalist_a) ? "FINALIST_B" : "FINALIST_A") : "";
        tx = await act("file_anti_cheat_protest_payable", [row.match_id, target, "suspected input automation in finals ticks"], BigInt(row.protest_bond_wei));
        break;
      }
      case "verify":
        toast("Requesting live validator consensus over pinned evidence. This can take a minute...", true);
        tx = await act("verify_match_telemetry", [row.match_id]);
        break;
      case "settle":
        tx = await act("claim_tournament_settlement", [row.match_id]);
        break;
      case "abandon":
        tx = await act("claim_abandoned_match_refund", [row.match_id]);
        break;
    }
    toast(`${btn.dataset.act} submitted: ${typeof tx === "string" ? tx : JSON.stringify(tx)}`);
    setTimeout(refreshAndWallet, 8000);
  } catch (e) {
    toast(`${btn.dataset.act} failed: ${e?.message ?? e}`, false);
  }
}

function walletIs(addr) {
  return wallet && addr && wallet.address.toLowerCase() === String(addr).toLowerCase();
}

async function refreshAndWallet() {
  await refresh();
  if (window.walletAddr) await refreshWallet(window.walletAddr);
}

async function refreshWallet(address) {
  const led = await loadWalletLedger(address);
  $("led-me-avt").textContent = "AVT " + fmt(led.avt);
  $("led-me-ref").textContent = "REFUNDABLE " + fmt(led.refundable) + " wei";
  $("guard-diag").textContent = led.rejection
    ? `LAST GUARD: ${led.rejection} (credit ${fmt(led.refundable)} wei refundable)`
    : "No payable rejection recorded for this wallet.";
  $("wallet-addr").textContent = short(address) + (window.walletSource === "burner" ? " [BURNER]" : " [MM read-only]");
}

window.walletAddr = null;
window.walletSource = null;

async function boot() {
  $("contract-link").textContent = contractAddress || "set VITE_CONTRACT_ADDRESS";
  $("contract-link").href = contractAddress
    ? `https://explorer-studio.genlayer.com/address/${contractAddress}` : "#";
  await refresh();
  $("btn-metamask").addEventListener("click", async () => {
    try {
      const w = await connectMetaMask();
      window.walletAddr = w.address; window.walletSource = "metamask";
      document.querySelector(".wallet-only").classList.add("on");
      await refreshWallet(w.address);
    } catch (e) { toast(String(e.message ?? e), false); }
  });
  $("btn-burner").addEventListener("click", async () => {
    try {
      const w = await connectBurner();
      window.walletAddr = w.address; window.walletSource = "burner";
      document.querySelector(".wallet-only").classList.add("on");
      toast(`Burner competitor wallet ${short(w.address)} ready. Fund it from the studionet faucet to transact.`);
      await refreshWallet(w.address);
    } catch (e) { toast(String(e.message ?? e), false); }
  });
  $("btn-claim-refund").addEventListener("click", async () => {
    try {
      const tx = await act("claim_refundable_balance");
      toast("refund released: " + tx);
      await refreshAndWallet();
    } catch (e) { toast(String(e.message ?? e), false); }
  });
  for (const btn of document.querySelectorAll("#action-panel .btn")) {
    btn.addEventListener("click", () => onAction(btn));
  }
  for (const id of ["sl-frame", "sl-entropy", "sl-loss"]) $(id).addEventListener("input", updateAnalyzer);
  for (const id of ["ck-draw", "ck-viol", "ck-cheat"]) $(id).addEventListener("change", updateAnalyzer);
  setInterval(refresh, 45000);
}

boot().catch((e) => toast("desk offline: " + e, false));
