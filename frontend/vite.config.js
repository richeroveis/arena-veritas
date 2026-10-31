import { defineConfig } from "vite";

export default defineConfig({
  base: "/arena-veritas/",
  build: {
    outDir: "dist",
    assetsInlineLimit: 0,
  },
});
