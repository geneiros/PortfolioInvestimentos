/* Prospeção → uma lista de acompanhamento: os parâmetros de cada ação, os alertas e a atualização dos indicadores. */
(() => {
  const rename = document.getElementById("listRename");
  if (rename) rename.addEventListener("click", async () => {
    const title = prompt("Novo nome da lista:", rename.dataset.title);
    if (!title || title === rename.dataset.title) return;
    await pm.call("rename_watch_list", { name: rename.dataset.list, title });
    location.reload();
  });

  const KINDS = window.pmTrackKinds || {};
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const box = document.getElementById("trackRules");
  let current = null;

  const unitOf = (kind, currency) => {
    const u = (KINDS[kind] || [])[1];
    return u === "price" ? currency : u === null ? null : u;
  };
  const rowHtml = (r, currency) => {
    const [label] = KINDS[r.kind] || [r.kind];
    const unit = unitOf(r.kind, currency);
    const value = unit === null ? "" : `<div class="input-group input-group-sm" style="max-width: 11rem">
        <input class="form-control text-end" data-k="threshold" inputmode="decimal" value="${esc(r.threshold ?? "")}" aria-label="${esc(label)}">
        ${unit ? `<span class="input-group-text">${esc(unit)}</span>` : ""}</div>`;
    return `<div class="d-flex flex-wrap align-items-center gap-2 py-2 border-bottom" data-rule="${esc(r.kind)}">
      <span class="flex-grow-1">${esc(label)}${unit === null ? ' <span class="small text-secondary">(avisa quando muda)</span>' : ""}</span>
      ${value}
      <div class="form-check form-switch mb-0"><input class="form-check-input" type="checkbox" data-k="alert" ${r.alert ? "checked" : ""} id="al-${Math.random().toString(36).slice(2)}">
        <label class="form-check-label small">Alertar</label></div>
      <button class="btn btn-sm btn-outline-danger" type="button" data-rule-del aria-label="Tirar"><i class="bi bi-x"></i></button></div>`;
  };

  document.querySelectorAll("[data-track-edit]").forEach((b) => b.addEventListener("click", () => {
    current = { name: b.dataset.trackEdit, currency: b.dataset.currency, method: b.dataset.method };
    document.getElementById("trackModalTitle").textContent = `Parâmetros · ${b.dataset.ticker}`;
    document.getElementById("trackNote").value = b.dataset.note || "";
    const rules = JSON.parse(b.dataset.rules || "[]");
    box.innerHTML = rules.length ? rules.map((r) => rowHtml(r, current.currency)).join("") : '<p class="small text-secondary" data-empty>Sem parâmetros. Junta um em baixo.</p>';
    bootstrap.Modal.getOrCreateInstance(document.getElementById("trackModal")).show();
  }));
  document.addEventListener("click", (e) => {
    const del = e.target.closest("[data-rule-del]");
    if (del) del.closest("[data-rule]").remove();
    const add = e.target.closest("[data-track-add]");
    if (add && current) {
      e.preventDefault();
      const kind = add.dataset.trackAdd;
      if (kind === "method" && !current.method) { pm.toast("Esta ação não veio da triagem: não tem uma lente para verificar.", "warning"); return; }
      if ((kind === "method" || kind === "moat") && box.querySelector(`[data-rule="${kind}"]`)) return;
      const empty = box.querySelector("[data-empty]");
      if (empty) empty.remove();
      box.insertAdjacentHTML("beforeend", rowHtml({ kind, alert: true, threshold: kind === "from_high" ? 20 : "" }, current.currency));
    }
  });
  const save = document.getElementById("trackSave");
  if (save) save.addEventListener("click", async () => {
    const rules = [...box.querySelectorAll("[data-rule]")].map((row) => ({
      kind: row.dataset.rule,
      threshold: (row.querySelector('[data-k="threshold"]') || {}).value ?? null,
      alert: row.querySelector('[data-k="alert"]').checked,
    }));
    save.disabled = true;
    try {
      await pm.call("save_watch_rules", { name: current.name, rules, note: document.getElementById("trackNote").value });
      location.reload();
    } catch (err) { save.disabled = false; }
  });

  // analisar o moat a partir daqui
  document.addEventListener("click", async (e) => {
    const el = e.target.closest("[data-moat]");
    if (!el) return;
    el.disabled = true;
    try { await pm.call("analyse_moat", { ticker: el.dataset.moat }); location.reload(); } catch (err) { el.disabled = false; }
  });

  // atualizar os indicadores do Yahoo, uma ação de cada vez (o servidor não tem tarefas em segundo plano)
  const refresh = document.getElementById("trackRefresh");
  if (refresh) refresh.addEventListener("click", async () => {
    const list = JSON.parse(refresh.dataset.tickers || "[]");
    const progress = document.getElementById("trackProgress");
    refresh.disabled = true;
    let fails = 0;
    for (let i = 0; i < list.length; i++) {
      progress.textContent = `A atualizar ${list[i]} (${i + 1} de ${list.length})…`;
      try { await pm.call("refresh_tracking", { ticker: list[i] }, { silent: true }); } catch (err) { fails += 1; }
    }
    progress.textContent = fails ? `${fails} sem dados no Yahoo.` : "";
    location.reload();
  });
})();
