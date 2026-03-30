const form = document.getElementById("report-form");
const result = document.getElementById("result");
const statusText = document.getElementById("status-text");
const submitButton = document.getElementById("submit-button");

function optionalValue(value) {
  return value && value.trim() ? value.trim() : null;
}

function optionalNumber(value) {
  if (!value || !value.trim()) {
    return null;
  }

  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function boolValue(formData, key) {
  return formData.get(key) === "on";
}

function formatList(items) {
  if (!items || !items.length) {
    return "<li>None recorded</li>";
  }

  return items.map((item) => `<li>${escapeHtml(String(item))}</li>`).join("");
}

function escapeHtml(value) {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function renderResult(payload) {
  const report = payload.report;
  const forwarding = payload.forwarding;
  const email = payload.email;

  result.className = "result-card";
  result.innerHTML = `
    <div class="result-summary">
      <h3>${escapeHtml(report.case_title)}</h3>
      <p>${escapeHtml(report.incident_summary)}</p>
      <p><strong>Police narrative</strong></p>
      <p>${escapeHtml(report.police_narrative)}</p>
    </div>

    <div class="result-meta">
      <div class="meta-box">
        <strong>Threat level</strong>
        <span>${escapeHtml(report.threat_level)}</span>
      </div>
      <div class="meta-box">
        <strong>Recommended police report</strong>
        <span>${report.should_report_to_police ? "Yes" : "No"}</span>
      </div>
      <div class="meta-box">
        <strong>Confidence</strong>
        <span>${escapeHtml(String(report.confidence))}</span>
      </div>
    </div>

    <div class="result-grid">
      <section class="result-section">
        <h3>Evidence to preserve</h3>
        <ul class="result-list">${formatList(report.evidence_to_preserve)}</ul>
      </section>
      <section class="result-section">
        <h3>Next steps</h3>
        <ul class="result-list">${formatList(report.recommended_next_steps)}</ul>
      </section>
      <section class="result-section">
        <h3>Timeline</h3>
        <ul class="result-list">${formatList(report.timeline)}</ul>
      </section>
      <section class="result-section">
        <h3>Requested money or data</h3>
        <ul class="result-list">${formatList(report.requested_money_or_data)}</ul>
      </section>
      <section class="result-section">
        <h3>People and numbers</h3>
        <ul class="result-list">${formatList(report.people_and_numbers)}</ul>
      </section>
      <section class="result-section">
        <h3>Saved files</h3>
        <p class="mono">${escapeHtml(payload.files.pdf_path)}</p>
        <p class="mono">${escapeHtml(payload.files.json_path)}</p>
        <p class="mono">${escapeHtml(payload.files.markdown_path)}</p>
      </section>
    </div>

    <section class="result-section">
      <h3>Forwarding</h3>
      <p>${escapeHtml(forwarding.reason)}</p>
      <p><strong>Destination</strong> <span class="mono">${escapeHtml(forwarding.destination || "Not configured")}</span></p>
      <p><strong>Status code</strong> ${escapeHtml(String(forwarding.status_code || "N/A"))}</p>
    </section>

    <section class="result-section">
      <h3>Email Delivery</h3>
      <p>${escapeHtml(email.reason)}</p>
      <p><strong>Recipient</strong> <span class="mono">${escapeHtml(email.recipient || "Not configured")}</span></p>
      <p><strong>Sent</strong> ${email.sent ? "Yes" : "No"}</p>
    </section>

    <section class="result-section">
      <h3>Disclaimer</h3>
      <p>${escapeHtml(payload.disclaimer)}</p>
    </section>
  `;
}

function renderError(message) {
  result.className = "";
  result.innerHTML = `<div class="error-box">${escapeHtml(message)}</div>`;
}

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  const formData = new FormData(form);
  const payload = {
    reporter_name: optionalValue(formData.get("reporter_name")),
    reporter_phone: optionalValue(formData.get("reporter_phone")),
    reporter_email: optionalValue(formData.get("reporter_email")),
    incident_country: optionalValue(formData.get("incident_country")),
    incident_city: optionalValue(formData.get("incident_city")),
    call_received_at: optionalValue(formData.get("call_received_at")),
    scam_phone_number: optionalValue(formData.get("scam_phone_number")),
    suspected_scam_type: optionalValue(formData.get("suspected_scam_type")),
    transcript: optionalValue(formData.get("transcript")) || "",
    short_notes: optionalValue(formData.get("short_notes")),
    money_requested: boolValue(formData, "money_requested"),
    money_lost_amount: optionalNumber(formData.get("money_lost_amount")),
    payment_method: optionalValue(formData.get("payment_method")),
    wants_forwarding: boolValue(formData, "wants_forwarding"),
  };

  statusText.textContent = "Generating police report...";
  submitButton.disabled = true;

  try {
    const response = await fetch("/reports", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(payload),
    });

    const data = await response.json();
    if (!response.ok) {
      const detail = data.detail || "Request failed.";
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }

    renderResult(data);
    statusText.textContent = "Report generated.";
  } catch (error) {
    const message = error instanceof Error ? error.message : "Unexpected error.";
    renderError(message);
    statusText.textContent = "Failed to generate report.";
  } finally {
    submitButton.disabled = false;
  }
});
