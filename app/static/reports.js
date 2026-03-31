const archiveList = document.getElementById("archive-list");
const archiveStatus = document.getElementById("archive-status");

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function linkOrPlaceholder(url, label) {
  if (!url) {
    return `<span class="archive-missing">${escapeHtml(label)} unavailable</span>`;
  }
  return `<a href="${escapeHtml(url)}" target="_blank" rel="noreferrer">${escapeHtml(label)}</a>`;
}

function renderArchive(payload) {
  if (!payload.reports || !payload.reports.length) {
    archiveList.className = "result-empty";
    archiveList.innerHTML = "No reports are saved on this server yet.";
    archiveStatus.textContent = "No saved reports found.";
    return;
  }

  archiveList.className = "archive-list";
  archiveList.innerHTML = payload.reports
    .map(
      (report) => `
        <article class="archive-card">
          <h3>${escapeHtml(report.title)}</h3>
          <p class="archive-meta"><strong>ID</strong> <span class="mono">${escapeHtml(report.id)}</span></p>
          <p class="archive-meta"><strong>Updated</strong> ${escapeHtml(report.updated_at)}</p>
          <div class="archive-links">
            ${linkOrPlaceholder(report.files.pdf, "PDF")}
            ${linkOrPlaceholder(report.files.markdown, "Markdown")}
            ${linkOrPlaceholder(report.files.json, "JSON")}
          </div>
        </article>
      `,
    )
    .join("");
  archiveStatus.textContent = `${payload.count} report(s) found.`;
}

async function loadArchive() {
  archiveStatus.textContent = "Loading reports...";
  try {
    const response = await fetch("/reports/list");
    const payload = await response.json();
    if (!response.ok) {
      throw new Error(payload.detail || "Failed to load reports.");
    }
    renderArchive(payload);
  } catch (error) {
    archiveList.className = "";
    archiveList.innerHTML = `<div class="error-box">${escapeHtml(error instanceof Error ? error.message : "Failed to load reports.")}</div>`;
    archiveStatus.textContent = "Failed to load reports.";
  }
}

loadArchive();
