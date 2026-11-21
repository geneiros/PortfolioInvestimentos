/* Prospeção → uma lista de acompanhamento, em quadro: os cartões arrastam-se entre estados, cada campo grava-se ao
   mudar; os estados, os parâmetros de cada ação, os alertas, copiar, exportar e importar. */
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
  const board = document.getElementById("board");
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

  document.querySelectorAll("[data-track-edit]").forEach((b) => b.addEventListener("click", (e) => {
    e.preventDefault();
    current = { name: b.dataset.trackEdit, currency: b.dataset.currency, method: b.dataset.method };
    document.getElementById("trackModalTitle").textContent = `Parâmetros · ${b.dataset.ticker}`;
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
      await pm.call("save_watch_rules", { name: current.name, rules });
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

  if (!board) return;

  // o quadro ocupa a altura do ecrã; cada coluna faz scroll na vertical só na lista dela
  const fit = () => {
    const top = board.getBoundingClientRect().top + window.scrollY;
    board.style.setProperty("--pm-board-h", `${Math.max(window.innerHeight - top - 16, 352)}px`);
  };
  fit();
  window.addEventListener("resize", fit);

  // ---------------------------------------------------------------- os campos do cartão (gravam-se ao mudar)
  const cardOf = (el) => el.closest("[data-card]");
  const saved = (el) => { el.classList.add("pm-saved"); setTimeout(() => el.classList.remove("pm-saved"), 900); };
  board.addEventListener("click", async (e) => {
    const p = e.target.closest("[data-prio]");
    if (!p) return;
    const card = cardOf(p);
    await pm.call("update_watch", { name: card.dataset.card, priority: p.dataset.prio }, { silent: true });
    card.querySelectorAll("[data-prio]").forEach((b) => b.classList.toggle("pm-prio-on", b === p));
  });
  board.addEventListener("change", async (e) => {
    const el = e.target;
    const card = cardOf(el);
    if (!card) return;
    if (el.dataset.field === "state_id") {
      await pm.call("update_watch", { name: card.dataset.card, state_id: el.value });
      const dest = board.querySelector(`[data-drop="${el.value}"]`);
      dest.insertBefore(card, dest.querySelector(".pm-board-empty"));
      counts();
    } else if (el.dataset.field) {
      await pm.call("update_watch", { name: card.dataset.card, [el.dataset.field]: el.value }, { silent: true });
      saved(el);
    } else if (el.dataset.answer) {
      const answers = Object.fromEntries([...card.querySelectorAll("[data-answer]")].map((t) => [t.dataset.answer, t.value]));
      await pm.call("save_triage_notes", { ticker: card.dataset.ticker, answers }, { silent: true });
      card.querySelector("[data-answered]").textContent = Object.values(answers).filter((v) => v.trim()).length;
      saved(el);
    }
  });

  // ---------------------------------------------------------------- arrastar os cartões
  const counts = () => board.querySelectorAll("[data-state]").forEach((col) => {
    const n = col.querySelectorAll("[data-card]").length;
    col.querySelector("[data-col-count]").textContent = n;
    col.querySelector(".pm-board-empty").classList.toggle("d-none", n > 0);
    col.querySelectorAll("[data-card] [data-field=state_id]").forEach((s) => { s.value = col.dataset.state; });
  });
  let dragged = null;
  // só se arrasta pegando no cartão (nas caixas de texto, o rato seleciona o texto)
  board.addEventListener("pointerdown", (e) => {
    const card = e.target.closest("[data-card]");
    if (card) card.draggable = !e.target.closest("textarea, select, input, button, a, summary, label");
  });
  board.addEventListener("dragstart", (e) => {
    const card = e.target.closest && e.target.closest("[data-card]");
    if (!card || e.target.closest("textarea, select, input, button")) return;
    dragged = card;
    card.classList.add("pm-dragging");
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", card.dataset.card);
  });
  board.addEventListener("dragend", () => {
    if (dragged) { dragged.classList.remove("pm-dragging"); dragged.draggable = false; }
    board.querySelectorAll(".pm-drop-on").forEach((x) => x.classList.remove("pm-drop-on"));
    dragged = null;
  });
  const after = (zone, y) => [...zone.querySelectorAll("[data-card]:not(.pm-dragging)")]
    .find((c) => y < c.getBoundingClientRect().top + c.offsetHeight / 2);
  board.addEventListener("dragover", (e) => {
    const zone = e.target.closest("[data-drop]");
    if (!zone || !dragged) return;
    e.preventDefault();
    board.querySelectorAll(".pm-drop-on").forEach((x) => x !== zone && x.classList.remove("pm-drop-on"));
    zone.classList.add("pm-drop-on");
    const next = after(zone, e.clientY);
    zone.insertBefore(dragged, next || zone.querySelector(".pm-board-empty"));
  });
  board.addEventListener("drop", async (e) => {
    const zone = e.target.closest("[data-drop]");
    if (!zone || !dragged) return;
    e.preventDefault();
    const card = dragged;
    const position = [...zone.querySelectorAll("[data-card]")].indexOf(card);
    counts();
    try { await pm.call("move_watch", { name: card.dataset.card, state_id: zone.dataset.drop, position }, { silent: true }); }
    catch (err) { location.reload(); }
  });

  // ---------------------------------------------------------------- os estados
  const stateNew = document.getElementById("stateNew");
  stateNew.addEventListener("submit", async (e) => {
    e.preventDefault();
    await pm.call("create_watch_state", { list_id: board.dataset.list, title: stateNew.title.value });
    location.reload();
  });
  board.addEventListener("click", async (e) => {
    const r = e.target.closest("[data-state-rename]");
    const m = e.target.closest("[data-state-move]");
    const d = e.target.closest("[data-state-delete]");
    if (!r && !m && !d) return;
    e.preventDefault();
    if (r) {
      const old = r.closest("[data-state]").dataset.title;
      const title = prompt("Novo nome do estado:", old);
      if (!title || title === old) return;
      await pm.call("rename_watch_state", { name: r.dataset.stateRename, title });
    } else if (m) {
      await pm.call("move_watch_state", { name: m.dataset.stateMove, direction: m.dataset.dir });
    } else {
      if (!confirm(`Apagar o estado «${d.closest("[data-state]").dataset.title}»?`)) return;
      await pm.call("delete_watch_state", { name: d.dataset.stateDelete });
    }
    location.reload();
  });

  // ---------------------------------------------------------------- copiar texto e importar
  const copy = document.getElementById("listCopy");
  if (copy) copy.addEventListener("click", async () => {
    const out = [document.querySelector("#listRename").dataset.title, ""];
    board.querySelectorAll("[data-state]").forEach((col) => {
      const cards = [...col.querySelectorAll("[data-card]")];
      if (!cards.length) return;
      out.push(`## ${col.dataset.title} (${cards.length})`);
      cards.forEach((c) => {
        const prio = c.querySelector(".pm-prio-on");
        const name = c.querySelector(".fw-bold").textContent.trim();
        out.push(`- ${name} (${c.dataset.ticker})${prio ? ` · prioridade ${prio.textContent.trim().toLowerCase()}` : ""}`);
        const line = c.querySelector(".small.text-secondary.mt-1");
        if (line && line.textContent.trim()) out.push(`  ${line.textContent.trim()}`);
        const lenses = c.querySelector(".text-success");
        if (lenses) out.push(`  Lentes: ${lenses.textContent.trim()}`);
        const reason = c.querySelector('[data-field="reason"]').value.trim();
        if (reason) out.push(`  Porque entrou: ${reason}`);
        const notes = c.querySelector('[data-field="notes"]').value.trim();
        if (notes) out.push(`  Notas: ${notes}`);
        c.querySelectorAll("[data-answer]").forEach((t) => {
          if (t.value.trim()) out.push(`  ${t.closest("label").querySelector(".fw-semibold").textContent.trim()} ${t.value.trim()}`);
        });
      });
      out.push("");
    });
    const text = out.join("\n").trim() + "\n";
    try { await navigator.clipboard.writeText(text); pm.toast("Lista copiada."); }
    catch (err) {  // sem acesso à área de transferência (ex.: sem HTTPS): mostra o texto para copiar à mão
      const ta = document.createElement("textarea");
      ta.value = text;
      document.body.appendChild(ta);
      ta.select();
      document.execCommand("copy");
      ta.remove();
      pm.toast("Lista copiada.");
    }
  });
  const imp = document.getElementById("listImport");
  if (imp) imp.addEventListener("change", async () => {
    if (!imp.files.length) return;
    const fd = new FormData();
    fd.append("file", imp.files[0]);
    try {
      const out = await pm.call("import_watch_list", fd);
      pm.toast(`Lista «${out.title}» importada (${out.n} ações).`);
      setTimeout(() => { location.href = `/radar/acompanhamento?lista=${out.id}`; }, 700);
    } finally { imp.value = ""; }
  });

  // ---------------------------------------------------------------- a ficha (o painel da triagem)
  const panel = document.getElementById("triagePanel");
  const body = document.getElementById("triagePanelBody");
  const open = async (ticker) => {
    panel.classList.add("pm-open");
    body.innerHTML = '<div class="text-center text-secondary py-5"><span class="spinner-border"></span></div>';
    const res = await fetch(`/radar/acao/${encodeURIComponent(ticker)}`, { credentials: "same-origin" });
    body.innerHTML = await res.text();
    body.scrollTop = 0;
    body.querySelectorAll("[data-save-ticker]").forEach((b) => b.remove());  // já está na lista
    body.querySelectorAll('[data-bs-toggle="tooltip"]').forEach((el) => bootstrap.Tooltip.getOrCreateInstance(el));
  };
  board.addEventListener("click", (e) => {
    const f = e.target.closest("[data-ficha]");
    if (f) { e.preventDefault(); open(f.dataset.ficha); }
  });
  panel.addEventListener("click", (e) => { if (e.target.closest("[data-panel-close]")) panel.classList.remove("pm-open"); });
  panel.addEventListener("submit", async (e) => {
    const form = e.target;
    e.preventDefault();
    if (form.dataset.moatForm) {
      const checked = (name) => [...form.querySelectorAll(`input[name="${name}"]:checked`)].map((i) => i.value);
      await pm.call("save_moat_checklist", { ticker: form.dataset.moatForm, pillars: checked("pillars"), tests: checked("tests"), note: form.note.value });
      pm.toast("Checklist do moat guardado.");
    } else if (form.dataset.notesForm) {
      const answers = Object.fromEntries([...form.querySelectorAll("textarea[name]")].map((t) => [t.name, t.value]));
      await pm.call("save_triage_notes", { ticker: form.dataset.notesForm, answers });
      pm.toast("Respostas guardadas.");
      setTimeout(() => location.reload(), 600);
    }
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") panel.classList.remove("pm-open"); });
})();
