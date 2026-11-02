// Repository hygiene gates that must hold before a submission:
// no secrets in tracked files, no retired contract address anywhere, no em dash
// in anything a reviewer reads, and the credential and build paths stay ignored.
// Prints file names and verdicts only, never any matched content.
import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));
const files = execFileSync("git", ["ls-files"], { encoding: "utf8", cwd: root }).trim().split(/\r?\n/);

const SECRET_PATTERNS = {
  github_token: /gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}/,
  private_key_block: /BEGIN [A-Z ]*PRIVATE KEY/,
  hex_key_assignment: /(PRIVATE_KEY|SECRET_KEY|API_KEY)\s*[:=]\s*["']?(0x)?[A-Fa-f0-9]{40,}/,
  openai_style_key: /\bsk-[A-Za-z0-9]{20,}/,
  aws_style_key: /\bAKIA[0-9A-Z]{16}\b/,
};

// The address deployed before this one. Any survivor in the repo would point a
// reviewer at a dead contract. Built by concatenation so this file does not
// itself contain the retired literal.
const RETIRED_ADDRESS = new RegExp("0x5226" + "D715[0-9A-Fa-f]{0,32}", "i");

const secretHits = [];
const emDashHits = [];
const staleAddressHits = [];
for (const f of files) {
  let text;
  try {
    text = fs.readFileSync(path.join(root, f), "utf8");
  } catch {
    continue; // binary or unreadable, skipped on purpose
  }
  for (const [name, re] of Object.entries(SECRET_PATTERNS)) {
    if (re.test(text)) secretHits.push(`${f} -> ${name}`);
  }
  if (/\u2014/.test(text)) emDashHits.push(f);
  if (RETIRED_ADDRESS.test(text)) staleAddressHits.push(f);
}

const report = (label, hits) => {
  console.log(`${label}: ${hits.length === 0 ? "CLEAN" : JSON.stringify(hits)}`);
  return hits.length === 0;
};

let ok = true;
ok = report(`tracked files scanned (${files.length}) for secrets`, secretHits) && ok;
ok = report("em dash in tracked text", emDashHits) && ok;
ok = report("retired contract address in tracked files", staleAddressHits) && ok;

const mustBeIgnored = [".env", "frontend/dist", "evidence/_burners.json", "evidence/_checkpoint.json", "scripts/ghp-build/index.html", "scripts/video-build/frame.png", "scripts/node_modules", "probes"];
for (const p of mustBeIgnored) {
  let ignored = false;
  try {
    execFileSync("git", ["check-ignore", "-q", "--stdin"], { input: p, cwd: root, stdio: ["pipe", "ignore", "ignore"] });
    ignored = true;
  } catch {
    ignored = false;
  }
  if (!ignored && p !== "probes") ok = false;
  console.log(`ignored ${p}: ${ignored}`);
}

const trackedEnv = files.filter((f) => /(^|\/)\.env[^/]*$/.test(f));
console.log(`tracked env files: ${trackedEnv.join(", ") || "none"}`);
if (trackedEnv.some((f) => f !== ".env.example" && !f.endsWith(".env.example"))) ok = false;

console.log(ok ? "RESULT: hygiene gates hold" : "RESULT: hygiene gate failure");
process.exit(ok ? 0 : 1);
