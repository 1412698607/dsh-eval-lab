import { readFileSync } from "node:fs";

const manifest = JSON.parse(readFileSync(new URL("../package.json", import.meta.url), "utf8"));

export const pluginVersion = manifest.version;
export const supportedSessionVersion = manifest.peerDependencies["@deepseek-ai/dsh-session"];
