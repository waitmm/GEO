import assert from "node:assert/strict";
import { test } from "node:test";
import { loadConfigFromFile } from "vite";

for (const mode of ["development", "release", "production", "legacy"]) {
  test(`${mode} uses matching UI and API defaults`, async () => {
    const loaded = await loadConfigFromFile({ command: "serve", mode }, "vite.config.ts");
    const release = mode !== "legacy";
    assert.equal(loaded.config.define["import.meta.env.VITE_GEO_RELEASE_FIRST_SLICE"], JSON.stringify(release ? "1" : "0"));
    assert.equal(loaded.config.server.proxy["/api"], `http://127.0.0.1:${release ? 8021 : 8000}`);
    assert.equal(loaded.config.server.strictPort, true);
  });
}

test("custom backend port is propagated without changing release mode", async () => {
  process.env.GEO_API_PROXY_TARGET = "http://127.0.0.1:8031";
  try {
    const { config } = await loadConfigFromFile({ command: "serve", mode: "release" }, "vite.config.ts");
    assert.equal(config.server.proxy["/api"], process.env.GEO_API_PROXY_TARGET);
    assert.equal(config.define["import.meta.env.VITE_GEO_RELEASE_FIRST_SLICE"], '"1"');
  } finally {
    delete process.env.GEO_API_PROXY_TARGET;
  }
});
