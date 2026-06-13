// Dashboard smoke test: load docs/index.html in jsdom against the static
// JSON in docs/data and exercise rendering, filters, sorting, and theming.
import { JSDOM } from "jsdom";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const DOCS = resolve(dirname(fileURLToPath(import.meta.url)), "../../docs");
const html = readFileSync(resolve(DOCS, "index.html"), "utf8");

const dom = new JSDOM(html, {
  url: "https://example.github.io/report-collector/",
  runScripts: "dangerously",
  pretendToBeVisual: true,
});
const { window } = dom;

// jsdom has no fetch; serve ./data/* straight from the docs folder.
window.fetch = async (path) => {
  const rel = String(path).replace(/^\.\//, "");
  try {
    const body = readFileSync(resolve(DOCS, rel), "utf8");
    return { ok: true, json: async () => JSON.parse(body) };
  } catch (error) {
    return {
      ok: false,
      json: async () => {
        throw error;
      },
    };
  }
};

// Execute app.js manually (jsdom does not load external file-backed scripts here).
const appJs = readFileSync(resolve(DOCS, "assets/app.js"), "utf8");
window.eval(appJs);

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
await sleep(400);

const doc = window.document;
const fails = [];
const check = (label, ok) => {
  console.log(`${ok ? "PASS" : "FAIL"}  ${label}`);
  if (!ok) fails.push(label);
};

check("theme attribute set on <html>", ["light", "dark"].includes(doc.documentElement.dataset.theme));
check("date select populated", doc.getElementById("dateSelect").options.length > 0);
check("category select populated", doc.getElementById("categorySelect").options.length > 1);
check("broker select populated", doc.getElementById("brokerSelect").options.length > 1);

const reportList = doc.getElementById("reportList");
const initialCount = reportList.querySelectorAll(".report-card").length;
check(`report cards rendered (${initialCount})`, initialCount > 0);
check("must-read rendered", doc.getElementById("mustReadList").children.length > 0);
check("stats rendered", doc.getElementById("statsGrid").children.length > 0);
check("hero count populated", doc.getElementById("heroMustReadCount").textContent !== "-");

// Broker filter narrows the feed and shows in the hint bar.
const brokerSelect = doc.getElementById("brokerSelect");
const someBroker = brokerSelect.options[1].value;
brokerSelect.value = someBroker;
brokerSelect.dispatchEvent(new window.Event("change", { bubbles: true }));
await sleep(50);
const filteredCount = reportList.querySelectorAll(".report-card").length;
check(
  `broker filter narrows feed (${initialCount} -> ${filteredCount})`,
  filteredCount > 0 && filteredCount <= initialCount
);
check(
  "hint bar shows broker",
  [...doc.querySelectorAll("#activeFilterBar .hint-chip")].some((chip) =>
    chip.textContent.includes(someBroker)
  )
);
const brokers = new Set(
  [...reportList.querySelectorAll(".report-card .badge")].map((badge) => badge.textContent)
);
check("filtered cards mention selected broker", brokers.has(someBroker));

// Debounced search.
const searchInput = doc.getElementById("searchInput");
searchInput.value = "zzz-no-such-term-zzz";
searchInput.dispatchEvent(new window.Event("input", { bubbles: true }));
await sleep(350);
check("search empties feed", reportList.querySelectorAll(".report-card").length === 0);
check("empty state shown", reportList.querySelector(".empty") !== null);

// Reset restores everything.
doc.getElementById("resetFiltersButton").dispatchEvent(new window.Event("click", { bubbles: true }));
await sleep(50);
check("reset restores feed", reportList.querySelectorAll(".report-card").length === initialCount);
check("reset restores broker select", brokerSelect.value === "all");

// Dark mode toggle flips the attribute and persists.
const darkToggle = doc.getElementById("darkModeToggle");
darkToggle.checked = true;
darkToggle.dispatchEvent(new window.Event("change", { bubbles: true }));
check("dark toggle sets data-theme", doc.documentElement.dataset.theme === "dark");
check("dark preference persisted", window.localStorage.getItem("broker-report-theme") === "dark");
darkToggle.checked = false;
darkToggle.dispatchEvent(new window.Event("change", { bubbles: true }));
check("light toggle restores", doc.documentElement.dataset.theme === "light");

// Sort change still renders.
const sortSelect = doc.getElementById("sortSelect");
sortSelect.value = "latest";
sortSelect.dispatchEvent(new window.Event("change", { bubbles: true }));
await sleep(50);
check("sort change re-renders", reportList.querySelectorAll(".report-card").length === initialCount);

// Filters are reflected in the URL and restored from it (see app.js URL sync).
sortSelect.value = "score";
sortSelect.dispatchEvent(new window.Event("change", { bubbles: true }));
brokerSelect.value = someBroker;
brokerSelect.dispatchEvent(new window.Event("change", { bubbles: true }));
await sleep(50);
const params = new window.URLSearchParams(window.location.search);
check("broker filter synced to URL", params.get("broker") === someBroker);

// A fresh page load with filter params restores the filters.
{
  const dom2 = new JSDOM(html, {
    url: `https://example.github.io/report-collector/?broker=${encodeURIComponent(someBroker)}&sort=latest&q=리포트`,
    runScripts: "dangerously",
    pretendToBeVisual: true,
  });
  dom2.window.fetch = window.fetch;
  dom2.window.eval(appJs);
  await sleep(400);
  const doc2 = dom2.window.document;
  check("restored broker select from URL", doc2.getElementById("brokerSelect").value === someBroker);
  check("restored sort from URL", doc2.getElementById("sortSelect").value === "latest");
  check("restored search input from URL", doc2.getElementById("searchInput").value === "리포트");
  check(
    "restored hint bar mentions broker",
    [...doc2.querySelectorAll("#activeFilterBar .hint-chip")].some((chip) =>
      chip.textContent.includes(someBroker)
    )
  );
}

// Opening a subject pushes history; back returns to the daily view.
{
  const subjectIndex = JSON.parse(readFileSync(resolve(DOCS, "data/subjects/index.json"), "utf8"));
  const subjectKey = subjectIndex.subjects?.[0]?.subject_key;
  if (subjectKey) {
    const input = doc.getElementById("subjectSearchInput");
    input.value = subjectIndex.subjects[0].subject_name || subjectKey;
    doc.getElementById("subjectSearchButton").dispatchEvent(new window.Event("click", { bubbles: true }));
    await sleep(300);
    check("subject view opens", doc.getElementById("subjectView").hidden === false);
    check("subject in URL", new window.URLSearchParams(window.location.search).get("subject") !== null);

    window.history.back();
    await sleep(300);
    check("back button returns to daily view", doc.getElementById("subjectView").hidden === true);
    check(
      "subject removed from URL after back",
      new window.URLSearchParams(window.location.search).get("subject") === null
    );
  }
}

console.log(fails.length ? `\n${fails.length} FAILURES` : "\nALL CHECKS PASSED");
process.exit(fails.length ? 1 : 0);
