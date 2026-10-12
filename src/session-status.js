import { writeFile, rename, unlink } from "node:fs/promises";
import { randomUUID } from "node:crypto";

export function statusFilename(traceFile) {
  return traceFile.replace(/\.jsonl$/, ".status.json");
}

// Same-directory replacement; this is not an fsync or power-loss guarantee.
export async function writeStatus(path, status) {
  const temporary = `${path}.${randomUUID()}.tmp`;
  try {
    await writeFile(temporary, JSON.stringify(status, null, 2) + "\n", { flag: "wx" });
    await rename(temporary, path);
  } finally {
    await unlink(temporary).catch((error) => { if (error.code !== "ENOENT") throw error; });
  }
}
