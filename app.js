"use strict";

const $ = (id) => document.getElementById(id);
const token = document.querySelector('meta[name="audit-token"]').content;
let files = null;
let commonHeaders = [];
let downloadURL = null;

function clearResult() {
  if (downloadURL) URL.revokeObjectURL(downloadURL);
  downloadURL = null;
  $("download").removeAttribute("href");
  $("results").hidden = true;
}

function status(message, error = false) {
  $("status").textContent = message;
  $("status").className = error ? "error" : "";
}

function busy(value) {
  document.querySelectorAll("input, select, button").forEach((control) => {
    control.disabled = value;
  });
  if (!value) {
    document.querySelectorAll("#fields input").forEach((control) => {
      control.disabled = control.value === $("key").value;
    });
  }
}

function reset() {
  files = null;
  commonHeaders = [];
  clearResult();
  $("selection").hidden = true;
  $("metadata").textContent = "";
  status("");
}

function encodeFile(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("Could not read the selected file."));
    reader.onload = () => resolve(reader.result.slice(reader.result.indexOf(",") + 1));
    reader.readAsDataURL(file);
  });
}

async function request(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Audit-Token": token },
    body: JSON.stringify(payload),
    credentials: "omit",
    cache: "no-store",
  });
  if (!response.ok) {
    let message = `Request failed (${response.status}).`;
    try {
      const error = await response.json();
      if (typeof error.error === "string") message = error.error;
    } catch {
      // A broken local connection may not provide a JSON error body.
    }
    throw new Error(message);
  }
  return response;
}

function showFields() {
  clearResult();
  $("fields").replaceChildren();
  commonHeaders.forEach((name) => {
    const label = document.createElement("label");
    const input = document.createElement("input");
    input.type = "checkbox";
    input.value = name;
    input.disabled = name === $("key").value;
    input.addEventListener("change", () => {
      clearResult();
      const selected = document.querySelectorAll("#fields input:checked");
      if (selected.length > 5) {
        input.checked = false;
        status("Select no more than five correction fields.", true);
      } else {
        status("");
      }
    });
    label.append(input, document.createTextNode(name));
    $("fields").append(label);
  });
}

$("target").addEventListener("change", reset);
$("source").addEventListener("change", reset);
$("key").addEventListener("change", () => { showFields(); status(""); });
$("inspect").addEventListener("click", async () => {
  reset();
  const target = $("target").files[0];
  const source = $("source").files[0];
  if (!target || !source) return status("Choose both target and source CSV files.", true);
  if ([target, source].some((file) => file.size > 10 * 1024 * 1024)) {
    return status("Each CSV must be at most 10 MiB.", true);
  }
  busy(true);
  status("Reading files and inspecting columns locally…");
  try {
    const [targetData, sourceData] = await Promise.all([encodeFile(target), encodeFile(source)]);
    const candidate = { target: targetData, source: sourceData };
    const response = await request("/inspect", candidate);
    const metadata = await response.json();
    files = candidate;
    commonHeaders = metadata.common_headers;
    $("metadata").textContent = `${metadata.target_rows} target rows · ${metadata.source_rows} source rows · ` +
      `${metadata.target_headers.length} target columns · ${metadata.source_headers.length} source columns · ` +
      `${commonHeaders.length} shared columns`;
    if (commonHeaders.length < 2) {
      status("At least two shared columns are needed: a key and one correction field.", true);
      return;
    }
    $("key").replaceChildren(...commonHeaders.map((name) => {
      const option = document.createElement("option");
      option.value = name;
      option.textContent = name;
      return option;
    }));
    showFields();
    $("selection").hidden = false;
    status("Choose your key and correction fields. No fields are pre-approved.");
  } catch (error) {
    status(error.message || "Local request failed. Check that Python is still running.", true);
  } finally {
    busy(false);
  }
});

$("audit").addEventListener("click", async () => {
  clearResult();
  const fields = [...document.querySelectorAll("#fields input:checked")].map((input) => input.value);
  if (!files || fields.length < 1 || fields.length > 5) {
    return status("Inspect your files and select one to five correction fields.", true);
  }
  busy(true);
  status("Comparing locally using the Python engine…");
  try {
    const response = await request("/audit", { ...files, key: $("key").value, fields });
    const blob = await response.blob();
    downloadURL = URL.createObjectURL(blob);
    $("download").href = downloadURL;
    const counts = [
      ["Target rows", "X-Target-Rows"], ["Source rows", "X-Source-Rows"],
      ["Proposed cell changes", "X-Changed-Cells"], ["Manual-review items", "X-Review-Items"],
      ["Formula-like cells retained", "X-Formula-Like-Cells-Retained"],
    ];
    $("counts").replaceChildren(...counts.map(([label, header]) => {
      const card = document.createElement("div");
      const value = document.createElement("strong");
      value.textContent = response.headers.get(header);
      card.append(value, document.createTextNode(label));
      return card;
    }));
    $("preservation").textContent = response.headers.get("X-Unselected-Preserved") === "true"
      ? "All unselected cell values and the key are preserved. CSV formatting may change."
      : "Preservation could not be confirmed. Do not use this output.";
    $("results").hidden = false;
    status("Results ready. Review the audit and warnings before using either CSV.");
  } catch (error) {
    status(error.message || "Local request failed. Check that Python is still running.", true);
  } finally {
    busy(false);
  }
});
window.addEventListener("pagehide", () => {
  files = null;
  clearResult();
});
