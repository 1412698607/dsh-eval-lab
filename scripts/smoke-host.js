import { randomUUID } from "node:crypto";
import { resolve } from "node:path";
import { locateHost } from "./lib/host.js";
import { runHostSmoke } from "./lib/host-smoke.js";

const modulesDir = await locateHost(process.argv[2]);
const outputDir = resolve("runs", "host-smoke", randomUUID());
const result = await runHostSmoke({ modulesDir, outputDir });
console.info(`DSH 真实 SessionStore + Cordis 插件接入验证通过：${result.eventCount} 条事件。`);
console.info(`组件版本：${JSON.stringify(result.versions)}`);
console.info(`日志：${result.tracePath}`);
