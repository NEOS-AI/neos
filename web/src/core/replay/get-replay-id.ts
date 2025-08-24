export function extractReplayIdFromSearchParams(params: string) {
  const urlParams = new URLSearchParams(params);
  if (urlParams.has("replay")) {
    return urlParams.get("replay");
  }
  return null;
}


export function extractFromSearchParams(params: string, name: string = "replay") {
  const urlParams = new URLSearchParams(params);
  if (urlParams.has(name)) {
    return urlParams.get(name);
  }
  return null;
}
