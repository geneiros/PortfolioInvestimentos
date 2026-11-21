/* Planeamento (independência financeira): as hipóteses na URL, os gráficos e os modais.
   As contas são feitas no servidor: mudar uma hipótese muda a URL e recarrega a página, sem gravar. */
(() => {
  const SCROLL_KEY = "pm-plan-scroll";
  const store = {
    get: (k) => { try { return sessionStorage.getItem(k); } catch (e) { return null; } },
    set: (k, v) => { try { sessionStorage.setItem(k, v); } catch (e) { /* sem armazenamento: não faz mal */ } },
    del: (k) => { try { sessionStorage.removeItem(k); } catch (e) { /* idem */ } },
  };
  const num = (v) => parseFloat(String(v).replace(/\s/g, "").replace(",", "."));
  // ao mudar uma hipótese, a página volta ao mesmo sítio
  const go = (url) => { store.set(SCROLL_KEY, String(window.scrollY)); location.href = url; };
  const saved = store.get(SCROLL_KEY);
  if (saved !== null) { store.del(SCROLL_KEY); window.addEventListener("load", () => window.scrollTo(0, +saved)); }

  // ---------------------------------------------------------------- ecrã inicial: escolher o rendimento
  const setGoal = async (income) => {
    await pm.call("set_plan_goal", { income });
    location.href = "/planeamento";
  };
  document.querySelectorAll("[data-plan-goal]").forEach((b) => b.addEventListener("click", () => setGoal(b.dataset.planGoal)));
  const other = document.getElementById("planOtherForm");
  if (other) other.addEventListener("submit", (e) => { e.preventDefault(); setGoal(other.income.value); });

  // ---------------------------------------------------------------- hipóteses: −/+ e campos
  const inputs = document.getElementById("planInputs");
  const urlWith = (key, value) => {
    const u = new URL(location.href);
    u.searchParams.set(key, value);
    u.searchParams.delete("ano");
    return u.pathname + u.search;
  };
  let timer = null;
  const schedule = (key, value) => { clearTimeout(timer); timer = setTimeout(() => go(urlWith(key, value)), 700); };
  document.querySelectorAll("[data-plan-step]").forEach((b) => b.addEventListener("click", () => {
    const field = document.querySelector(`[data-plan-field="${b.dataset.planStep}"]`);
    const step = num(b.dataset.step);
    const min = b.dataset.planStep === "inf" ? -5 : b.dataset.planStep === "rend" ? 1000 : 0;
    const v = Math.max(min, Math.round(((num(field.value) || 0) + step) * 10) / 10);
    field.value = String(v).replace(".", ",");
    schedule(b.dataset.planStep, v);
  }));
  document.querySelectorAll("[data-plan-field]").forEach((f) => f.addEventListener("change", () => {
    const v = num(f.value);
    if (!Number.isNaN(v)) schedule(f.dataset.planField, v);
  }));
  document.querySelectorAll("[data-plan-nav]").forEach((a) => a.addEventListener("click", (e) => {
    e.preventDefault();
    go(a.getAttribute("href"));
  }));
  const save = document.getElementById("planSave");
  if (save) save.addEventListener("click", async () => {
    save.disabled = true;
    try {
      await pm.call("save_plan", JSON.parse(save.dataset.args));
      pm.toast("Objetivo guardado.");
      setTimeout(() => go("/planeamento" + (new URL(location.href).searchParams.get("cenario") ? `?cenario=${new URL(location.href).searchParams.get("cenario")}` : "")), 500);
    } catch (e) { save.disabled = false; }
  });
  const reset = document.getElementById("planReset");
  if (reset) reset.addEventListener("click", async () => {
    if (!confirm("Apagar o objetivo e as hipóteses do Planeamento e começar de novo?")) return;
    await pm.call("reset_plan");
    location.href = "/planeamento";
  });

  // ---------------------------------------------------------------- modais: rendimentos e despesas
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const rowHtml = {
    income: (r) => `<div class="row g-2 mb-2 align-items-end" data-row>
      <div class="col-12 col-sm-5"><label class="small text-secondary">Nome<input class="form-control form-control-sm" data-k="name" value="${esc(r.name)}" placeholder="ex.: Reforma"></label></div>
      <div class="col-5 col-sm-3"><label class="small text-secondary">€ por mês<input class="form-control form-control-sm" data-k="monthly" inputmode="decimal" value="${esc(r.monthly)}"></label></div>
      <div class="col-5 col-sm-3"><label class="small text-secondary">Desde<input class="form-control form-control-sm" data-k="year" type="number" value="${esc(r.year)}"></label></div>
      <div class="col-2 col-sm-1 text-end"><button class="btn btn-sm btn-outline-danger" type="button" data-row-del aria-label="Apagar"><i class="bi bi-x"></i></button></div></div>`,
    items: (r) => `<div class="row g-2 mb-2 align-items-end" data-row>
      <div class="col-7"><input class="form-control form-control-sm" data-k="name" value="${esc(r.name)}" aria-label="Despesa" placeholder="ex.: Casa"></div>
      <div class="col-4"><div class="input-group input-group-sm"><span class="input-group-text">€</span><input class="form-control" data-k="amount" inputmode="decimal" value="${esc(r.amount)}" aria-label="Valor por mês"></div></div>
      <div class="col-1 text-end"><button class="btn btn-sm btn-outline-danger" type="button" data-row-del aria-label="Apagar"><i class="bi bi-x"></i></button></div></div>`,
  };
  const boxes = {};
  document.querySelectorAll("[data-plan-rows]").forEach((box) => {
    const kind = box.dataset.planRows;
    boxes[kind] = box;
    let rows = [];
    try { rows = JSON.parse(box.dataset.rows || "[]"); } catch (e) { rows = []; }
    box.innerHTML = rows.map(rowHtml[kind]).join("");
  });
  const total = () => {
    const box = boxes.items;
    const out = document.querySelector("[data-plan-total]");
    if (!box || !out) return;
    const sum = [...box.querySelectorAll('[data-k="amount"]')].reduce((a, el) => a + (num(el.value) || 0), 0);
    out.textContent = pm.money(sum, 0);
  };
  const addRow = (kind, r = {}) => { boxes[kind].insertAdjacentHTML("beforeend", rowHtml[kind](r)); total(); };
  document.addEventListener("click", (e) => {
    const del = e.target.closest("[data-row-del]");
    if (del) { del.closest("[data-row]").remove(); total(); }
    const add = e.target.closest("[data-plan-add]");
    if (add) addRow(add.dataset.planAdd, add.dataset.planAdd === "income" ? { year: new Date().getFullYear() } : {});
  });
  document.addEventListener("input", (e) => { if (e.target.closest('[data-plan-rows="items"]')) total(); });
  total();
  document.querySelectorAll("[data-plan-save]").forEach((b) => b.addEventListener("click", async () => {
    const kind = b.dataset.planSave;
    const rows = [...boxes[kind].querySelectorAll("[data-row]")].map((row) => Object.fromEntries(
      [...row.querySelectorAll("[data-k]")].map((el) => [el.dataset.k, el.value])));
    b.disabled = true;
    try {
      await pm.call(kind === "income" ? "save_plan_income" : "save_plan_items", { rows });
      go(kind === "items" ? "/planeamento" : location.pathname + location.search);
    } catch (e) { b.disabled = false; }
  }));
  // «O que mexe na data» → «Juntar»: abre os rendimentos com a reforma sugerida
  document.querySelectorAll("[data-plan-pension]").forEach((b) => b.addEventListener("click", () => {
    addRow("income", { name: "Reforma", monthly: 500, year: b.dataset.planPension });
    bootstrap.Modal.getOrCreateInstance(document.getElementById("planIncomeModal")).show();
  }));

  // ---------------------------------------------------------------- gráficos
  const d = window.pmPlan;
  if (!d) return;
  // cor com transparência, seja «#rrggbb» ou «rgb(...)»
  const alpha = (c, a) => {
    c = (c || "").trim();
    if (/^#[0-9a-f]{6}$/i.test(c)) return c + Math.round(a * 255).toString(16).padStart(2, "0");
    const m = c.match(/rgba?\(([^)]+)\)/);
    if (m) { const [r, g, b] = m[1].split(",").map((x) => x.trim()); return `rgba(${r}, ${g}, ${b}, ${a})`; }
    return c;
  };
  const drawMain = () => {
    const accent = pm.css("--pm-accent"), text = pm.css("--pm-text"), muted = pm.css("--bs-secondary-color");
    pm.chart("planChart", {
      type: "line",
      data: { datasets: [
        { label: "Prudente", data: d.low, borderColor: "transparent", pointRadius: 0, fill: false, tension: .2, isBand: true },
        { label: "Prudente a otimista", data: d.high, borderColor: "transparent", backgroundColor: alpha(accent, 0.13), pointRadius: 0, fill: "-1", tension: .2, isBand: true },
        { label: "O que a carteira fez", data: d.history, borderColor: text, borderWidth: 2, pointRadius: 0, tension: .2 },
        { label: "Cenário escolhido", data: d.projection, borderColor: accent, borderWidth: 2, borderDash: [6, 4], pointRadius: 0, tension: .2 },
        { label: "O número FIRE", data: d.need, borderColor: muted, borderWidth: 1.5, borderDash: [3, 4], pointRadius: 0, stepped: false },
        { type: "scatter", label: "Datas", data: d.marks.map((m) => ({ x: m.x, y: d.number, label: m.label, key: m.key })),
          pointRadius: (c) => (c.raw && c.raw.key !== "prudente" && c.raw.key !== "otimista" ? 6 : 4),
          backgroundColor: accent, borderColor: pm.css("--pm-surface"), borderWidth: 1.5, isMark: true },
      ] },
      options: {
        maintainAspectRatio: false, interaction: { mode: "nearest", intersect: false },
        plugins: {
          legend: { position: "bottom", labels: { filter: (item, data) => !data.datasets[item.datasetIndex].isMark && item.text !== "Prudente" } },
          tooltip: { callbacks: {
            title: (it) => String(Math.floor(it[0].parsed.x)),
            label: (it) => (it.dataset.isMark ? `Chega ao número FIRE em ${it.raw.label}` : `${it.dataset.label}: ${pm.money(it.parsed.y, 0)}`),
          } },
        },
        scales: {
          x: { type: "linear", min: d.start, max: d.end, ticks: { callback: (v) => Math.floor(v), maxTicksLimit: 10, maxRotation: 0 }, grid: { display: false } },
          y: { position: "right", min: 0, ticks: { callback: (v) => pm.money(v, 0) } },
        },
      },
    });
  };

  // a probabilidade: as simulações e o ano escolhido
  const probYear = document.getElementById("planProbYear");
  const bad = document.getElementById("planProbBad");
  const monthOf = (y) => (y - d.probStart) * 12 + 11;
  const updateProb = () => {
    const y = +probYear.value;
    const m = monthOf(y);
    const k = d.paths.filter((p) => p.month !== null && p.month <= m).length;
    const share = d.paths.length ? k / d.paths.length : 0;
    document.querySelectorAll("[data-prob-year]").forEach((el) => { el.textContent = y; });
    document.querySelectorAll("[data-prob-k]").forEach((el) => { el.textContent = Math.round(share * 10); });
    document.querySelectorAll("[data-prob-miss]").forEach((el) => { el.textContent = 10 - Math.round(share * 10); });
    const ring = document.getElementById("planRing");
    if (ring) ring.style.setProperty("--pm-ring", `${(share * 100).toFixed(1)}%`);
    drawProb();
  };
  const drawProb = () => {
    if (!probYear) return;
    const accent = pm.css("--pm-accent"), down = pm.css("--pm-down") || "#f05252", muted = pm.css("--bs-secondary-color");
    const y = +probYear.value, m = monthOf(y);
    const showBad = bad && bad.checked;
    const datasets = d.paths.map((p) => {
      const ok = p.month !== null && p.month <= m;
      const color = ok ? accent : showBad ? down : muted;
      return { label: `A partir de ${p.from}`, data: p.data, borderColor: alpha(color, ok || showBad ? 0.7 : 0.25), borderWidth: ok || showBad ? 1.4 : 1, pointRadius: 0, tension: .2 };
    });
    datasets.push({ label: "O número FIRE", data: d.need, borderColor: pm.css("--pm-text"), borderWidth: 1.5, borderDash: [3, 4], pointRadius: 0 });
    datasets.push({ label: "O ano escolhido", data: [{ x: y + 0.999, y: 0 }, { x: y + 0.999, y: Math.max(...d.need.map((q) => q.y)) * 1.6 }], borderColor: accent, borderWidth: 2, pointRadius: 0 });
    pm.chart("planProbChart", {
      type: "line", data: { datasets },
      options: {
        maintainAspectRatio: false, animation: false, interaction: { mode: "nearest", intersect: false },
        plugins: { legend: { display: false }, tooltip: { callbacks: { title: (it) => String(Math.floor(it[0].parsed.x)), label: (it) => `${it.dataset.label}: ${pm.money(it.parsed.y, 0)}` } } },
        scales: {
          x: { type: "linear", min: d.probStart, max: d.end, ticks: { callback: (v) => Math.floor(v), maxTicksLimit: 10, maxRotation: 0 }, grid: { display: false } },
          y: { position: "right", min: 0, ticks: { callback: (v) => pm.money(v, 0) } },
        },
      },
    });
  };
  if (probYear) probYear.addEventListener("input", updateProb);
  if (bad) bad.addEventListener("change", drawProb);
  const draw = () => { drawMain(); drawProb(); };
  draw();
  document.addEventListener("pm:theme", draw);
})();
