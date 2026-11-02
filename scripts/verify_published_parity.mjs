// Compares the pushed GitHub content with the local working tree, file by file.
// Verifies main (source of truth) and the published gh-pages build both match
// what is on disk, so the submitted source cannot drift from what is served.
// Reads nothing secret; only public raw and Pages URLs.
import crypto from "node:crypto";
import fs from "node:fs";
import https from "node:https";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));

const get = (url) =>
  new Promise((resolve, reject) => {
    https
      .get(url, (res) => {
        if (res.statusCode !== 200) {
          res.resume();
          resolve({ status: res.statusCode, buf: null });
          return;
        }
        const d = [];
        res.on("data", (c) => d.push(c));
        res.on("end", () => resolve({ status: 200, buf: Buffer.concat(d) }));
      })
      .on("error", reject);
  });

const sha = (b) => crypto.createHash("sha256").update(b).digest("hex");

// .gitattributes forces LF in the object database, while the Windows working
// copy keeps CRLF. Text files are therefore compared after newline
// normalization; binaries are compared byte for byte.
const readLocal = (f, binary) => {
  const buf = fs.readFileSync(path.join(root, ...f.split("/")));
  return binary ? buf : Buffer.from(buf.toString("utf8").replace(/\r\n/g, "\n"), "utf8");
};
const isBinary = (f) => /\.(png|mp4|jpg|jpeg|zip|woff2?)$/i.test(f);

const MAIN_FILES = [
  "contracts/arena_veritas.py",
  "README.md",
  "docs/deployment.md",
  "docs/adversarial-review.md",
  "docs/logo.png",
  "docs/demo-video-subtitled.mp4",
  "docs/demo-video-subtitles.srt",
  "docs/evidence/av-rulebook.html",
  "docs/evidence/cs2-major-telemetry.html",
  "docs/evidence/valorant-sovereign-telemetry.html",
  "docs/evidence/elden-ring-anypercent-telemetry.html",
  "docs/evidence/dota-saigon-telemetry.html",
  "evidence/studionet_live_lifecycle.json",
  "evidence/emit-transfer-probe.json",
  "tests/test_arena_veritas_direct.py",
  "scripts/seed_studionet.mjs",
  "scripts/live_state_check.mjs",
  "frontend/src/main.js",
  "frontend/src/desk.js",
  "frontend/vite.config.js",
];

const PAGES_TO_DIST = [
  ["index.html", "frontend/dist/index.html"],
  ["logo.png", "frontend/dist/logo.png"],
  ["demo-video-subtitled.mp4", "frontend/dist/demo-video-subtitled.mp4"],
];

const CONTRACT_SHA = "5daf9b09cebffb8026d1515eebc73667830fea0dbc7f64375a5bd905ee92b58d";

console.log("== main branch vs local working tree ==");
let mismatch = 0;
for (const f of MAIN_FILES) {
  const res = await get(`https://raw.githubusercontent.com/richeroveis/arena-veritas/main/${f}`);
  const localPath = path.join(root, ...f.split("/"));
  if (!fs.existsSync(localPath)) {
    console.log(`  ${f}: LOCAL MISSING (remote HTTP ${res.status})`);
    mismatch += 1;
    continue;
  }
  if (res.status !== 200) {
    console.log(`  ${f}: remote HTTP ${res.status}`);
    mismatch += 1;
    continue;
  }
  const local = sha(readLocal(f, isBinary(f)));
  const remote = sha(res.buf);
  const same = remote === local;
  if (!same) mismatch += 1;
  console.log(`  ${f}: ${same ? "IDENTICAL" : "DIFFERS"}${isBinary(f) ? "" : " (LF)"} sha=${local.slice(0, 16)}...`);
}

const contractRemote = await get("https://raw.githubusercontent.com/richeroveis/arena-veritas/main/contracts/arena_veritas.py");
const contractSha = contractRemote.status === 200 ? sha(contractRemote.buf) : "unavailable";
console.log(`deployed source identity on remote main: ${contractSha === CONTRACT_SHA ? "MATCHES" : "DOES NOT MATCH"} the recorded sha256`);
if (contractSha !== CONTRACT_SHA) mismatch += 1;

console.log("== published gh-pages build vs local dist ==");
for (const [served, localFile] of PAGES_TO_DIST) {
  const res = await get(`https://richeroveis.github.io/arena-veritas/${served}`);
  const local = sha(fs.readFileSync(path.join(root, ...localFile.split("/"))));
  const ok = res.status === 200 && sha(res.buf) === local;
  if (!ok) mismatch += 1;
  console.log(`  ${served}: http=${res.status} ${ok ? "IDENTICAL" : "DIFFERS"}`);
}

console.log(mismatch === 0 ? "RESULT: pushed content matches the local build exactly" : `RESULT: ${mismatch} mismatch(es)`);
process.exit(mismatch === 0 ? 0 : 1);
