import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { test } from "node:test";
import vm from "node:vm";

const script = await readFile(new URL("../dsh_eval/web/app.js", import.meta.url), "utf8");

// Minimal DOM surface: execute the real page's event handlers and text rendering without a browser dependency.
class Element {
  constructor(tag) { this.tag = tag; this.children = []; this.value = ""; this.text = ""; this.listeners = new Map(); }
  set textContent(value) { this.text = String(value); this.children = []; }
  get textContent() { return this.text + this.children.map((child) => child.textContent).join(" "); }
  append(...children) { this.children.push(...children); }
  replaceChildren(...children) { this.children = children; this.text = ""; }
  addEventListener(type, callback) { this.listeners.set(type, callback); }
  setAttribute() {}
  trigger(type) { this.listeners.get(type)?.(); }
}

async function viewer(items, artifact = null) {
  const elements = new Map();
  const get = (id) => {
    if (!elements.has(id)) elements.set(id, new Element(id));
    return elements.get(id);
  };
  const context = vm.createContext({
    document: { getElementById: get, createElement: (tag) => new Element(tag), createDocumentFragment: () => new Element("fragment") },
    Node: Element, URLSearchParams, location: { hash: "#token=test-token" },
    sessionStorage: { setItem() {}, getItem() { return null; } }, window: { scrollTo() {} },
    fetch: async (path) => ({ ok: true, json: async () => path.startsWith("/api/catalog")
      ? { items, warnings: [], truncated: false } : artifact }),
  });
  vm.runInContext(script, context, { filename: "dsh_eval/web/app.js" });
  await new Promise(setImmediate);
  return get;
}

function findButton(element, label) {
  if (element.tag === "button" && element.textContent === label) return element;
  for (const child of element.children) {
    const found = findButton(child, label);
    if (found) return found;
  }
  return null;
}

test("source filters retain mixed results with missing sample provenance", async () => {
  const get = await viewer([
    { kind: "experiment", title: "mixed", path: "mixed", sources: ["live", "unknown"] },
    { kind: "experiment", title: "live", path: "live", sources: ["live"] },
    { kind: "experiment", title: "missing", path: "missing", sources: [] },
    { kind: "experiment", title: "synthetic", path: "synthetic", sources: ["synthetic"] },
  ]);
  for (const [source, count] of [["unknown", 2], ["live", 2], ["synthetic", 1], ["", 4]]) {
    get("source").value = source;
    get("source").trigger("change");
    assert.equal(get("count").textContent, `${count} 项`);
    if (source === "unknown") {
      assert.ok(findButton(get("catalog"), "mixed"));
      assert.equal(findButton(get("catalog"), "live"), null);
    }
  }
});

test("sample errors render their type and message while preserving string errors and reasons", async () => {
  const artifact = { kind: "experiment", links: [], data: { experimentName: "broken", entries: [
    { entryId: "one", status: "error", outcome: "unevaluable", error: { type: "ValueError", message: "Batch/case association mismatch" } },
    { entryId: "two", status: "error", error: "Legacy startup error" },
    { entryId: "three", status: "error", reasons: ["First reason", "Second reason"] },
  ] } };
  const get = await viewer([{ id: "runs:broken/experiment-result.json", kind: "experiment", title: "broken", path: "broken" }], artifact);
  findButton(get("catalog"), "broken").trigger("click");
  await new Promise(setImmediate);
  const text = get("detail").textContent;
  assert.match(text, /ValueError: Batch\/case association mismatch/);
  assert.match(text, /Legacy startup error/);
  assert.match(text, /First reason；Second reason/);
  assert.doesNotMatch(text, /\[object Object\]/);
});
