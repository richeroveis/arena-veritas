import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";

// GenVM encodes an Address parameter with its own calldata type. genlayer-js
// implements it as an internal class that the package entry point does not
// re-export, so we resolve it from the installed build and expose it to the app
// under a stable module id. Without this wrapper the chain rejects address
// arguments and the call reverts.
function calldataChunkPath() {
  const here = path.dirname(fileURLToPath(import.meta.url));
  const dist = path.join(here, "node_modules", "genlayer-js", "dist");
  if (!fs.existsSync(dist)) {
    throw new Error("genlayer-js build missing; run npm install inside frontend/");
  }
  for (const file of fs.readdirSync(dist).filter((f) => /^chunk-.*\.js$/.test(f))) {
    const full = path.join(dist, file);
    const source = fs.readFileSync(full, "utf8");
    if (/CalldataAddress = class/.test(source) && /export \{[\s\S]*CalldataAddress,/.test(source)) {
      return full;
    }
  }
  throw new Error("CalldataAddress export not found in the installed genlayer-js build");
}

export default defineConfig({
  base: "/arena-veritas/",
  resolve: {
    alias: { "genlayer-calldata": calldataChunkPath() },
  },
  build: {
    outDir: "dist",
    assetsInlineLimit: 0,
  },
});
