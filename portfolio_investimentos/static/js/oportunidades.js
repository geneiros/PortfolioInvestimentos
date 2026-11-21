/* Radar e alertas → Oportunidades: procurar (1.º passo), analisar o moat (2.º passo) e guardar o checklist. */
(() => {
  const form = document.getElementById("screenForm");
  if (form) form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const btn = document.getElementById("screenRun");
    btn.disabled = true;
    const old = btn.innerHTML;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> A procurar…';
    try {
      const args = Object.fromEntries(new FormData(form).entries());
      args.method = form.dataset.method;
      const msg = await pm.call("run_screen", args);
      pm.toast(msg);
      location.href = `/oportunidades?metodo=${encodeURIComponent(form.dataset.method)}`;
    } catch (err) {
      btn.disabled = false;
      btn.innerHTML = old;
    }
  });

  // analisar o moat de uma empresa
  document.addEventListener("click", async (e) => {
    const el = e.target.closest("[data-moat]");
    if (!el) return;
    e.preventDefault();
    el.classList.add("disabled");
    try {
      await pm.call("analyse_moat", { ticker: el.dataset.moat });
      location.reload();
    } catch (err) { el.classList.remove("disabled"); }
  });

  // as próximas 10 sem análise, uma de cada vez (o servidor não tem tarefas em segundo plano)
  const batch = document.getElementById("moatBatch");
  if (batch) {
    const todo = JSON.parse(batch.dataset.tickers || "[]");
    if (!todo.length) batch.disabled = true;
    batch.addEventListener("click", async () => {
      const progress = document.getElementById("moatProgress");
      const list = todo.slice(0, 10);
      batch.disabled = true;
      let fails = 0;
      for (let i = 0; i < list.length; i++) {
        progress.textContent = `A analisar ${list[i]} (${i + 1} de ${list.length})…`;
        try { await pm.call("analyse_moat", { ticker: list[i] }, { silent: true }); } catch (err) { fails += 1; }
      }
      progress.textContent = fails ? `${fails} sem dados no Yahoo.` : "";
      location.reload();
    });
  }

  // o checklist dos pilares e dos testes
  document.querySelectorAll("[data-moat-form]").forEach((f) => f.addEventListener("submit", async (e) => {
    e.preventDefault();
    const checked = (name) => [...f.querySelectorAll(`input[name="${name}"]:checked`)].map((i) => i.value);
    await pm.call("save_moat_checklist", { ticker: f.dataset.moatForm, pillars: checked("pillars"), tests: checked("tests"), note: f.note.value });
    pm.toast("Checklist guardado.");
    setTimeout(() => location.reload(), 600);
  }));
})();
