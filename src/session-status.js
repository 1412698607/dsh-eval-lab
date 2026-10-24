import { writeFile, rename, unlink } from "node:fs/promises";
import { randomUUID } from "node:crypto";
import { setTimeout } from "node:timers/promises";

const replacementRetryDelays = [10, 20, 40, 80, 160];
const retryableReplacementCodes = new Set(["EPERM", "EACCES", "EBUSY"]);

export function statusFilename(traceFile) {
  return traceFile.replace(/\.jsonl$/, ".status.json");
}

// Same-directory replacement; this is not an fsync or power-loss guarantee.
export async function writeStatus(path, status) {
  const temporary = `${path}.${randomUUID()}.tmp`;
  try {
    await writeFile(temporary, JSON.stringify(status, null, 2) + "\n", { flag: "wx" });
    // Retry only replacement, using the already written bytes. Permanent access
    // failures still reject after six attempts / 310 ms of scheduled backoff.
    for (let attempt = 0; ; attempt++) {
      try { await rename(temporary, path); break; } catch (error) {
        if (!retryableReplacementCodes.has(error.code) || attempt === replacementRetryDelays.length) throw error;
        await setTimeout(replacementRetryDelays[attempt]);
      }
    }
  } finally {
    await unlink(temporary).catch((error) => { if (error.code !== "ENOENT") throw error; });
  }
}
