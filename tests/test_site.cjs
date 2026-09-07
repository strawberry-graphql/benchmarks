const fs = require("node:fs");
const vm = require("node:vm");
const assert = require("node:assert/strict");
const path = require("node:path");
const html = fs.readFileSync(
  path.join(__dirname, "../html/index.html"),
  "utf8",
);
const source = html
  .match(/<script>([\s\S]*?)<\/script>/)[1]
  .replace("sources.forEach(showStatus);", "");
class Element {
  constructor() {
    this.children = [];
    this.textContent = "";
  }
  append(child) {
    this.children.push(child);
  }
  replaceChildren() {
    this.children = [];
  }
  text() {
    return this.textContent + this.children.map((c) => c.text()).join(" ");
  }
}
const boxes = new Map(
  ["cpu", "memory", "walltime"].map((id) => [id, new Element()]),
);
const context = {
  Date,
  AbortSignal,
  location: { hash: "", replace() {} },
  document: {
    getElementById: (id) => boxes.get(id),
    createElement: () => new Element(),
  },
  fetch: async () => ({ ok: true, json: async () => ({ workflow_runs: [] }) }),
};
vm.createContext(context);
vm.runInContext(source, context);
(async () => {
  const success = {
    id: 123,
    head_sha: "abcdefgh12345678",
    name: "Unit tests",
    status: "completed",
    conclusion: "success",
    updated_at: "2020-01-01T00:00:00Z",
  };
  context.fetch = async () => ({
    ok: true,
    json: async () => ({
      workflow_runs: [{ ...success, conclusion: "failure" }, success],
    }),
  });
  await context.showStatus({
    id: "cpu",
    repo: "strawberry",
    workflow: "test.yml",
    maxAge: 14,
  });
  assert.match(boxes.get("cpu").text(), /Latest run: failure/);
  assert.match(boxes.get("cpu").text(), /stale/);
  assert.equal(
    boxes.get("cpu").children[1].href,
    "https://github.com/strawberry-graphql/strawberry/actions/runs/123",
  );
  context.fetch = async () => ({ ok: false });
  await context.showStatus({ id: "memory" });
  assert.match(boxes.get("memory").text(), /Live status unavailable/);
  context.fetch = async () => ({
    ok: true,
    json: async () => ({ workflow_runs: [{ ...success, name: "ASV Bot" }] }),
  });
  await context.showStatus({ id: "walltime" });
  assert.match(boxes.get("walltime").text(), /Live status unavailable/);
  context.fetch = async () => ({
    ok: true,
    json: async () => ({
      workflow_runs: [{ ...success, name: "Native benchmarks" }],
    }),
  });
  await context.showStatus({ id: "walltime", repo: "benchmarks", maxAge: 2 });
  assert.match(
    boxes.get("walltime").text(),
    /Strawberry revision is recorded inside each artifact/,
  );
  let redirected;
  context.location = {
    hash: "#benchmarks.ExecuteSync.time_execute",
    replace(value) {
      redirected = value;
    },
  };
  vm.runInContext(
    'if (location.hash) location.replace("history.html" + location.hash);',
    context,
  );
  assert.equal(redirected, "history.html#benchmarks.ExecuteSync.time_execute");
  console.log(
    "PASS: failure, stale success, unavailable API, ASV/native separation, source identity and legacy hash redirects",
  );
})();
