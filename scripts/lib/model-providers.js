// Deliberately restricted to text models over the pi-ai Chat Completions route.
export function validateModelProviders(value) {
  const object = (item) => item !== null && typeof item === "object" && !Array.isArray(item);
  const fields = (item, names) => {
    if (!object(item) || Object.keys(item).length !== names.length
        || names.some((name) => !Object.hasOwn(item, name))) {
      throw new TypeError("Invalid modelProviders fields; use credential references, never embedded keys");
    }
  };
  if (!object(value)) throw new TypeError("modelProviders must be an object");
  for (const [route, profile] of Object.entries(value)) {
    if (!/^[a-z][a-z0-9-]*$/.test(route) || /\s/.test(route) || ["deepseek-official", "deepseek-account"].includes(route)) {
      throw new TypeError("Invalid external provider route");
    }
    fields(profile, ["api", "baseURL", "apiKeyEnv", "models"]);
    if (profile.api !== "openai-completions") throw new TypeError("External providers require openai-completions");
    if (typeof profile.apiKeyEnv !== "string" || !/^[A-Za-z_][A-Za-z0-9_]*$/.test(profile.apiKeyEnv)
        || /\s/.test(profile.apiKeyEnv)) {
      throw new TypeError("apiKeyEnv must be a credential reference name");
    }
    if (typeof profile.baseURL !== "string" || !profile.baseURL.startsWith("https://")
        || !/^[\x21-\x7E]+$/.test(profile.baseURL) || /[\\@?#]/.test(profile.baseURL)) {
      throw new TypeError("baseURL must be an ASCII HTTPS endpoint without credentials, query or fragment");
    }
    const authority = profile.baseURL.slice(8).split("/")[0];
    if (!/^[A-Za-z0-9.-]+(?::[0-9]+)?$/.test(authority)) throw new TypeError("Invalid HTTPS provider endpoint");
    const endpoint = new URL(profile.baseURL);
    if (endpoint.protocol !== "https:" || !/^[A-Za-z0-9.-]+$/.test(endpoint.hostname)
        || endpoint.username || endpoint.password || endpoint.port === "0") {
      throw new TypeError("Invalid HTTPS provider endpoint");
    }
    if (!Array.isArray(profile.models) || !profile.models.length) throw new TypeError("Provider models must be nonempty");
    const identifiers = new Set();
    for (const model of profile.models) {
      fields(model, ["id", "contextWindow", "maxTokens"]);
      if (typeof model.id !== "string" || !model.id.trim() || identifiers.has(model.id)) {
        throw new TypeError("Model IDs must be nonempty and unique");
      }
      identifiers.add(model.id);
      if ([model.contextWindow, model.maxTokens].some((number) => !Number.isSafeInteger(number) || number <= 0)) {
        throw new TypeError("Model capacities must be positive safe integers");
      }
    }
  }
  return value;
}
