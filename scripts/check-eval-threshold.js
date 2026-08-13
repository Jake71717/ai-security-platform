#!/usr/bin/env node
// Fails CI if the promptfoo eval pass-rate drops below the given threshold.
// Usage: node check-eval-threshold.js promptfoo-eval.json 0.95
const fs = require("fs");

const [, , reportPath, thresholdArg] = process.argv;
const threshold = parseFloat(thresholdArg || "0.95");

if (!reportPath || !fs.existsSync(reportPath)) {
  console.error(`Report file not found: ${reportPath}`);
  process.exit(1);
}

const data = JSON.parse(fs.readFileSync(reportPath, "utf8"));
const stats = data.results?.stats || data.results?.table?.head || {};
const successes = stats.successes ?? data.results?.stats?.successes ?? 0;
const failures = stats.failures ?? data.results?.stats?.failures ?? 0;
const total = successes + failures;

if (total === 0) {
  console.warn("No test results found - skipping threshold check.");
  process.exit(0);
}

const passRate = successes / total;
console.log(`Pass rate: ${(passRate * 100).toFixed(1)}% (${successes}/${total}) - threshold ${threshold * 100}%`);

if (passRate < threshold) {
  console.error("FAIL: pass rate below required threshold.");
  process.exit(1);
}
console.log("PASS: threshold met.");
