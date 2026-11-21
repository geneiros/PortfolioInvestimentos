/* Prospeção → Ações: a triagem. A tabela inteira vem na página (window.pmTriage) e filtra-se aqui; a ficha de uma
   ação vem do servidor (/radar/acao/<ticker>) e abre no painel ao lado. «Atualizar» recolhe o universo e completa os
   dados das ações aos poucos (o servidor não tem tarefas em segundo plano). */
(() => {
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const progress = document.getElementById("triageProgress");
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  // ---------------------------------------------------------------- atualizar (universo + dados de cada ação)
  let running = false;
  const enrich = async () => {
    for (;;) {
      const p = await pm.call("triage_enrich", {}, { silent: true });
      const done = p.total - p.left;
      if (progress) progress.innerHTML = `<span class="spinner-border spinner-border-sm"></span> A completar os dados: ${done} de ${p.total}…`;
      if (p.done) return;
      if (p.wait) {
        for (let s = p.wait; s > 0; s--) {
          if (progress) progress.textContent = `O Yahoo pediu uma pausa: continua daqui a ${s} s (${done} de ${p.total}).`;
          await sleep(1000);
        }
      }
    }
  };
  const update = async (full) => {
    if (running) return;
    running = true;
    document.querySelectorAll("#triageRefresh, [data-triage-start]").forEach((b) => { b.disabled = true; });
    try {
      if (full) {
        for (;;) {
          const p = await pm.call("triage_refresh");
          if (progress) progress.innerHTML = `<span class="spinner-border spinner-border-sm"></span> A procurar nas lentes: ${p.total - p.left} de ${p.total} pesquisas…`;
          if (p.done) break;
        }
        if (!window.pmTriage) { location.reload(); return; }  // primeira vez: mostra já a lista
      }
      await enrich();
      location.reload();
    } catch (err) {
      if (progress) progress.textContent = "A atualização parou. Carrega em Atualizar para continuar.";
      document.querySelectorAll("#triageRefresh, [data-triage-start]").forEach((b) => { b.disabled = false; });
      running = false;
    }
  };
  document.querySelectorAll("#triageRefresh, [data-triage-start]").forEach((b) => b.addEventListener("click", () => update(true)));

  const T = window.pmTriage;
  if (!T) return;
  const root = document.getElementById("triage");
  if (root && Number(root.dataset.missing) > 0) update(false);  // ficou a meio: continua a completar os dados

  // ---------------------------------------------------------------- a tabela
  const L = Object.fromEntries((window.pmLenses || []).map((l) => [l.key, l]));
  const ORDER = T.order;  // as lentes reais e, no fim, «varias»
  const REAL = ORDER.filter((k) => k !== "varias");
  const R = T.rows.map((r) => ({ t: r[0], n: r[1], c: r[2], g: r[3], s: r[4], cur: r[5], p: r[6], cap: r[7], pe: r[8], pb: r[9],
    roe: r[10], rg: r[11], dv: r[12], de: r[13], st: r[14], k: r[15], full: r[16] }));
  const st = (r, lens) => r.st[ORDER.indexOf(lens)];
  const nf = (d) => new Intl.NumberFormat("pt-PT", { minimumFractionDigits: d, maximumFractionDigits: d });
  const num = (v, d = 1) => (v === null || v === undefined ? "—" : nf(d).format(v));
  const pct = (v, d = 0) => (v === null || v === undefined ? "—" : nf(d).format(v * 100) + "%");
  const cap = (v) => (v ? nf(v >= 1e11 ? 0 : 1).format(v / 1e9) : "—");
  const tone = (v, good, bad) => (v === null || v === undefined ? "" : v >= good ? "text-success" : v <= bad ? "text-danger" : "");
  const BADGE = { e: ['pm-in', "Entra"], q: ['pm-near', "Quase"], f: ['pm-out', "Falha"], "-": ['pm-none', "Sem dados"] };
  const SORTS = {  // «melhor nesta lente»: o que conta mais em cada uma (depois de entra → quase → falha)
    graham_def: (r) => r.pe ?? 1e9, graham_num: (r) => r.pb ?? 1e9, templeton: (r) => r.pe ?? 1e9,
    // qualidade pelo preço: o ROE (até 50%, acima disso costuma ser capital próprio pequeno) ÷ P/L
    buffett: (r) => -(Math.min(r.roe ?? 0, 0.5) / (r.pe || 1e3)), greenblatt: (r) => -(Math.min(r.roe ?? 0, 0.5) / (r.pe || 1e3)),
    resumo: (r) => -(Math.min(r.roe ?? 0, 0.5) / (r.pe || 1e3)),
    lynch: (r) => -(r.rg ?? -1e9), fisher: (r) => -(r.rg ?? -1e9), oneil: (r) => -(r.rg ?? -1e9),
    bazin: (r) => -(r.dv ?? -1e9), varias: (r) => -r.k * 1000 - (r.roe ?? 0),
  };
  const RANK = { e: 0, q: 1, f: 2, "-": 3 };
  let lens = "varias";
  let shown = 150;
  let selected = null;

  const f = {
    search: document.getElementById("fSearch"), region: document.getElementById("fRegion"),
    sector: document.getElementById("fSector"), sort: document.getElementById("fSort"), only: document.getElementById("fOnly"),
  };
  const fold = (s) => String(s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  const base = () => {
    const q = fold(f.search.value.trim());
    return R.filter((r) => (!f.region.value || r.g === f.region.value) && (!f.sector.value || r.s === f.sector.value)
      && (!q || fold(r.n).includes(q) || fold(r.t).includes(q) || fold(r.c).includes(q)));
  };
  const counts = (rows) => {
    document.querySelectorAll("[data-count]").forEach((el) => {
      const k = el.dataset.count;
      el.textContent = rows.filter((r) => st(r, k) === "e").length;
    });
  };
  const dots = (r) => REAL.map((k) => {
    const s = st(r, k);
    return `<span class="pm-dot pm-dot-${s === "-" ? "none" : s}${k === lens ? " pm-dot-here" : ""}" title="${esc(L[k].name)}: ${BADGE[s][1].toLowerCase()}"></span>`;
  }).join("");
  const rowHtml = (r) => {
    const s = st(r, lens);
    const saved = (T.watched[r.t] || []).length > 0;
    return `<tr data-ticker="${esc(r.t)}" class="${r.t === selected ? "table-active" : ""}" tabindex="0">
      <td><div class="fw-semibold text-truncate pm-triage-name" title="${esc(r.n)}">${esc(r.n)}</div><div class="small text-secondary">${esc(r.t)} · ${esc(r.c)}${r.full ? "" : ' <i class="bi bi-hourglass-split" title="A completar os dados"></i>'}</div></td>
      <td class="text-nowrap">${dots(r)}</td>
      <td><span class="badge ${BADGE[s][0]}">${BADGE[s][1]}</span></td>
      <td class="text-end">${num(r.pe)}</td><td class="text-end">${num(r.pb)}</td>
      <td class="text-end ${tone(r.roe, 0.15, 0)}">${pct(r.roe)}</td><td class="text-end ${tone(r.rg, 0.1, -0.0001)}">${r.rg === null ? "—" : (r.rg > 0 ? "+" : "") + pct(r.rg)}</td>
      <td class="text-end">${r.dv ? pct(r.dv, 1) : "—"}</td><td class="text-end ${r.de === null ? "" : r.de > 1.5 ? "text-danger" : ""}">${num(r.de, 2)}</td>
      <td class="text-end">${cap(r.cap)}</td>
      <td class="text-center"><button class="btn btn-sm btn-link py-0" type="button" title="${saved ? "Já está numa lista" : "Guardar numa lista"}"
        data-save-ticker="${esc(r.t)}" data-save-name="${esc(r.n)}" data-save-currency="${esc(r.cur || "USD")}" data-save-lens="${lens === "varias" ? "" : lens}">
        <i class="bi ${saved ? "bi-bookmark-fill" : "bi-bookmark"}"></i></button></td></tr>`;
  };
  const scroller = document.getElementById("triageScroll");
  // a lista ocupa o resto do ecrã: a página não faz scroll, só a lista (com o cabeçalho sempre no topo)
  const fit = () => {
    if (!scroller || window.innerWidth < 768) { if (scroller) scroller.style.maxHeight = ""; return; }
    const top = scroller.getBoundingClientRect().top + window.scrollY;
    const more = document.getElementById("triageMore");
    const below = (more ? more.offsetHeight : 0) + 26;
    scroller.style.maxHeight = `${Math.max(window.innerHeight - top - below, 320)}px`;
    // as lentes e a ficha também cabem no ecrã (cada uma com o seu scroll)
    const lensesEl = document.getElementById("triageLenses");
    const card = document.getElementById("triagePanelBody");
    [[lensesEl, true], [card, window.innerWidth >= 1400]].forEach(([el, on]) => {
      if (!el) return;
      el.style.maxHeight = on ? `${Math.max(window.innerHeight - (el.getBoundingClientRect().top + window.scrollY) - 26, 320)}px` : "";
    });
  };
  window.addEventListener("resize", fit);
  const render = (keep) => {
    if (!keep && scroller) scroller.scrollTop = 0;  // lente ou filtros novos: a lista volta ao início
    const rows0 = base();
    counts(rows0);
    let rows = rows0.filter((r) => !f.only.checked || st(r, lens) === "e");
    const key = f.sort.value;
    const by = {
      best: (r) => [RANK[st(r, lens)], SORTS[lens](r)], cap: (r) => [-(r.cap || 0)], pe: (r) => [r.pe ?? 1e9],
      roe: (r) => [-(r.roe ?? -1e9)], rg: (r) => [-(r.rg ?? -1e9)], dv: (r) => [-(r.dv ?? 0)], name: (r) => [r.n.toLowerCase()],
    }[key];
    rows = rows.map((r) => [by(r), r]).sort((a, b) => {
      for (let i = 0; i < a[0].length; i++) { if (a[0][i] < b[0][i]) return -1; if (a[0][i] > b[0][i]) return 1; }
      return 0;
    }).map((x) => x[1]);
    const n = rows0.filter((r) => st(r, lens) === "e").length;
    const nq = rows0.filter((r) => st(r, lens) === "q").length;
    document.getElementById("lensName").textContent = L[lens].name;
    document.getElementById("lensText").textContent = L[lens].text;
    document.getElementById("lensSummary").innerHTML = `<b>${n}</b> entram · ${nq} quase · ${rows0.length} na lista`;
    document.getElementById("triageBody").innerHTML = rows.slice(0, shown).map(rowHtml).join("")
      || `<tr><td colspan="11" class="text-center text-secondary py-4">Nenhuma ação ${f.only.checked ? "entra nesta lente com estes filtros. Desliga «Só as que entram» para veres as que ficam perto." : "com estes filtros."}</td></tr>`;
    const more = document.getElementById("triageMore");
    more.innerHTML = rows.length > shown ? `A mostrar ${shown} de ${rows.length} · <a href="#" data-more>mostrar mais</a>` : (rows.length ? `${rows.length} ações` : "");
  };
  document.getElementById("triageMore").addEventListener("click", (e) => {
    if (e.target.closest("[data-more]")) { e.preventDefault(); shown += 300; render(true); }
  });
  [f.search, f.region, f.sector, f.sort, f.only].forEach((el) => el.addEventListener(el === f.search ? "input" : "change", () => { shown = 150; render(); }));
  document.querySelectorAll("[data-lens]").forEach((b) => b.addEventListener("click", () => {
    document.querySelectorAll("[data-lens]").forEach((x) => x.classList.toggle("active", x === b));
    lens = b.dataset.lens;
    shown = 150;
    render();
  }));
  document.addEventListener("pm:saved", () => render(true));

  // ---------------------------------------------------------------- a ficha
  const panel = document.getElementById("triagePanel");
  const body = document.getElementById("triagePanelBody");
  const open = async (ticker) => {
    selected = ticker;
    document.querySelectorAll("#triageBody tr").forEach((tr) => tr.classList.toggle("table-active", tr.dataset.ticker === ticker));
    panel.classList.add("pm-open");
    body.innerHTML = '<div class="text-center text-secondary py-5"><span class="spinner-border"></span></div>';
    try {
      const res = await fetch(`/radar/acao/${encodeURIComponent(ticker)}?lente=${encodeURIComponent(lens)}`, { credentials: "same-origin" });
      if (selected !== ticker) return;
      body.innerHTML = await res.text();
      body.scrollTop = 0;
      const sel = body.querySelector(`[data-lens-detail="${lens}"]`);
      if (sel) sel.open = true;
      body.querySelectorAll('[data-bs-toggle="tooltip"]').forEach((el) => bootstrap.Tooltip.getOrCreateInstance(el));
    } catch (err) {
      body.innerHTML = '<p class="text-danger p-3">Não foi possível abrir a ficha.</p>';
    }
  };
  document.getElementById("triageBody").addEventListener("click", (e) => {
    if (e.target.closest("button, a")) return;
    const tr = e.target.closest("tr[data-ticker]");
    if (tr) open(tr.dataset.ticker);
  });
  document.getElementById("triageBody").addEventListener("keydown", (e) => {
    const tr = e.target.closest("tr[data-ticker]");
    if (tr && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); open(tr.dataset.ticker); }
  });
  panel.addEventListener("click", async (e) => {
    if (e.target.closest("[data-panel-close]")) { panel.classList.remove("pm-open"); return; }
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
  document.addEventListener("pm:saved", (e) => { if (e.detail.ticker === selected) open(selected); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") panel.classList.remove("pm-open"); });

  render();
  fit();
})();
