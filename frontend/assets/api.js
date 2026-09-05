"use strict";

// Thin, safe fetch helpers. Errors are thrown as Error objects with a
// human-readable message; no stack traces are ever shown to users.

async function getJSON(path) {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(await errorMessage(response));
  }
  return response.json();
}

async function postJSON(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(await errorMessage(response));
  }
  return response.json();
}

async function errorMessage(response) {
  let message = `Request failed (HTTP ${response.status}).`;
  try {
    const data = await response.json();
    if (data && data.detail && data.detail.message) {
      message = data.detail.message;
    } else if (data && data.detail && typeof data.detail === "string") {
      message = data.detail;
    }
  } catch (_) {
    // Non-JSON body: fall back to the status-based message.
  }
  return message;
}