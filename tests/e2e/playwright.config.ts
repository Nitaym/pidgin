import { defineConfig } from "@playwright/test";
import path from "path";

const ROOT = path.resolve(__dirname, "../..");
const PORT = process.env.PIDGIN_E2E_PORT ?? "9876";
const BASE = `http://127.0.0.1:${PORT}`;

export default defineConfig({
  testDir: ".",
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  timeout: 60_000,
  use: {
    baseURL: BASE,
    trace: "on-first-retry",
  },
  webServer: {
    command: "uv run python scripts/e2e_server.py",
    cwd: ROOT,
    url: `${BASE}/health`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
    env: {
      ...process.env,
      PIDGIN_E2E_PORT: PORT,
      PIDGIN_ALLOW_DEV_AUTH: "1",
    },
  },
});
