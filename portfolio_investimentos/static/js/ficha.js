/* Carteira: a ficha de uma ação (a mesma da Prospeção → Ações) num painel à direita, ao clicar numa posição.
   As linhas com data-ficha="<símbolo do Yahoo>" abrem-na; fecha com o X, com Esc ou clicando fora. */
(() => {
  const panel = document.getElementById("fichaPanel");
  const body = document.getElementById("fichaPanelBody");
  const backdrop = document.getElementById("fichaBackdrop");
  if (!panel || !body) return;
  let selected = null;
  const mark = () => document.querySelectorAll("tr[data-ficha]").forEach((tr) =>
    tr.classList.toggle("table-active", panel.classList.contains("pm-open") && tr.dataset.ficha === selected));
  const close = () => { panel.classList.remove("pm-open"); backdrop.classList.remove("pm-open"); mark(); };
  const open = async (symbol) => {
    selected = symbol;
    panel.classList.add("pm-open");
    backdrop.classList.add("pm-open");
    mark();
    body.innerHTML = '<div class="text-center text-secondary py-5"><span class="spinner-border"></span></div>';
    try {
      const res = await fetch(`/radar/acao/${encodeURIComponent(symbol)}?origem=carteira`, { credentials: "same-origin" });
      if (selected !== symbol) return;
      body.innerHTML = await res.text();
      body.scrollTop = 0;
      body.querySelectorAll('[data-bs-toggle="tooltip"]').forEach((el) => bootstrap.Tooltip.getOrCreateInstance(el));
    } catch (err) {
      body.innerHTML = '<div class="d-flex"><button class="btn-close ms-auto" type="button" data-panel-close aria-label="Fechar"></button></div>'
        + '<p class="text-danger p-3">Não foi possível abrir a ficha.</p>';
    }
  };
  document.addEventListener("click", (e) => {
    const tr = e.target.closest("tr[data-ficha]");
    if (!tr || e.target.closest("button, a, input, select")) return;
    open(tr.dataset.ficha);
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && panel.classList.contains("pm-open")) { close(); return; }
    const tr = e.target.closest && e.target.closest("tr[data-ficha]");
    if (tr && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); open(tr.dataset.ficha); }
  });
  backdrop.addEventListener("click", close);
  panel.addEventListener("click", async (e) => {
    if (e.target.closest("[data-panel-close]")) { close(); return; }
    const m = e.target.closest("[data-moat]");  // analisar o moat
    if (m) {
      m.disabled = true;
      try { await pm.call("analyse_moat", { ticker: m.dataset.moat }); open(m.dataset.moat); } catch (err) { m.disabled = false; }
    }
  });
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
    }
  });
})();
