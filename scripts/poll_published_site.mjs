// Polls the published Pages site and its assets until every URL answers 200.
// Public URLs only, no credentials involved.
import path from "node:path";
import https from "node:https";
import { fileURLToPath } from "node:url";

const root = path.dirname(path.dirname(fileURLToPath(import.meta.url)));

const PATHS = [
  "",
  "logo.png",
  "demo-video-subtitled.mp4",
];
const BASE = "https://richeroveis.github.io/arena-veritas/";

const get = (url) =>
  new Promise((resolve) => {
    https
      .get(url, (res) => {
        let n = 0;
        res.on("data", (c) => (n += c.length));
        res.on("end", () => resolve({ status: res.statusCode, bytes: n, type: res.headers["content-type"] || "" }));
      })
      .on("error", (e) => resolve({ status: `ERR ${e.code}`, bytes: 0, type: "" }));
  });

// The hashed bundle name changes with the build, so read it from the local dist
// listing instead of hardcoding it.
import fs from "node:fs";
const assetsDir = path.join(root, "frontend", "dist", "assets");
const bundles = fs.existsSync(assetsDir) ? fs.readdirSync(assetsDir) : [];

const targets = [
  ...PATHS.filter((p) => p !== "assets/").map((p) => `${BASE}${p}`),
  ...bundles.map((f) => `${BASE}assets/${f}`),
];

const deadline = Date.now() + 420000;
let last = "";
while (Date.now() < deadline) {
  const results = await Promise.all(targets.map((u) => get(u)));
  const line = results.map((r) => r.status).join(",");
  if (line !== last) {
    console.log(new Date().toISOString().slice(11, 19), line);
    last = line;
  }
  if (results.every((r) => r.status === 200)) {
    console.log("every published URL answers 200:");
    for (const [i, r] of results.entries()) {
      console.log(`  ${r.status} ${r.bytes}B ${r.type.split(";")[0]} ${targets[i]}`);
    }
    process.exit(0);
  }
  await new Promise((r) => setTimeout(r, 15000));
}
console.log("TIMEOUT: not every published URL is serving 200 yet");
for (const [i, r] of (await Promise.all(targets.map((u) => get(u)))).entries()) {
  console.log(`  ${r.status} ${targets[i]}`);
}
process.exit(1);
