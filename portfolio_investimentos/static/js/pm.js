/* Portfolio Investimentos — utilitários comuns às páginas /portfolio */
(function () {
  const pm = (window.pm = window.pm || {});

  // ---------------------------------------------------------------- formatação
  const nf = (d) => new Intl.NumberFormat("pt-PT", { minimumFractionDigits: d, maximumFractionDigits: d });
  pm.money = (v, d = 0, sign = false) => {
    if (v === null || v === undefined || isNaN(v)) return "—";
    const s = nf(d).format(Math.abs(v)).replace(/ /g, " ");
    return (v < 0 && Math.abs(v) >= Math.pow(10, -d) / 2 ? "−" : sign && v > 0 ? "+" : "") + "€" + s;
  };
  pm.pct = (v, d = 1, sign = true) => {
    if (v === null || v === undefined || isNaN(v)) return "—";
    const x = v * 100;
    return (x < 0 ? "−" : sign && x > 0 ? "+" : "") + nf(d).format(Math.abs(x)) + "%";
  };
  pm.tone = (v) => (!v ? "text-secondary" : v > 0 ? "text-up" : "text-down");
  pm.css = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();

  // ---------------------------------------------------------------- API Frappe
  pm.call = async (method, args = {}, opts = {}) => {
    const body = args instanceof FormData ? args : new URLSearchParams(
      Object.entries(args).filter(([, v]) => v !== undefined && v !== null)
        .map(([k, v]) => [k, typeof v === "object" ? JSON.stringify(v) : v]));
    let res;
    try {
      res = await fetch("/api/" + method, {
        method: "POST", body, credentials: "same-origin",
        headers: { "X-CSRF-Token": window.csrf_token, Accept: "application/json" },
      });
    } catch (err) {
      // o pedido não teve resposta ("Failed to fetch"): a aplicação parou ou deixou de estar acessível
      const msg = "Sem ligação à aplicação. Confirma que ela continua a correr (no Android, que o Termux não foi fechado) e tenta de novo.";
      if (!opts.silent) pm.toast(msg, "danger");
      throw new Error(msg);
    }
    const data = await res.json().catch(() => ({}));
    if (res.status === 401) {  // sessão terminada (palavra-passe ativa): volta ao login
      location.href = "/login?next=" + encodeURIComponent(location.pathname + location.search);
      throw new Error(data.error || "Sessão terminada.");
    }
    if (!res.ok) {
      const msg = data.error || (res.status === 403 ? "Sessão expirada: recarrega a página." : "Ocorreu um erro.");
      if (!opts.silent) pm.toast(msg, "danger");
      throw new Error(msg);
    }
    return data.message;
  };

  pm.toast = (msg, kind = "success") => {
    let box = document.getElementById("pm-toasts");
    if (!box) {
      box = document.createElement("div");
      box.id = "pm-toasts";
      box.className = "toast-container position-fixed bottom-0 end-0 p-3";
      document.body.appendChild(box);
    }
    const el = document.createElement("div");
    el.className = `toast align-items-center text-bg-${kind} border-0`;
    el.innerHTML = '<div class="d-flex"><div class="toast-body"></div><button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div>';
    el.querySelector(".toast-body").textContent = msg;
    box.appendChild(el);
    new bootstrap.Toast(el, { delay: 4000 }).show();
  };

  // depois de gravar sem recarregar, os valores gravados passam a ser os de origem do formulário
  // (form.reset() repunha os valores antigos e parecia que nada tinha sido gravado)
  const keepValues = (form) => {
    form.querySelectorAll("input, textarea").forEach((el) => {
      if (el.type === "checkbox" || el.type === "radio") el.defaultChecked = el.checked;
      else el.defaultValue = el.value;
    });
    form.querySelectorAll("option").forEach((o) => { o.defaultSelected = o.selected; });
  };

  // formulários com data-pm-method="nome" → chamam a API e recarregam a página
  document.addEventListener("submit", async (e) => {
    const form = e.target.closest("form[data-pm-method]");
    if (!form) return;
    e.preventDefault();
    const btn = form.querySelector("[type=submit]");
    if (btn) btn.disabled = true;
    try {
      const args = Object.fromEntries(new FormData(form).entries());
      await pm.call(form.dataset.pmMethod, args);
      if (form.dataset.pmSuccess) pm.toast(form.dataset.pmSuccess);
      if (form.dataset.pmReload !== "false") setTimeout(() => location.reload(), form.dataset.pmSuccess ? 600 : 0);
      else keepValues(form);
    } catch (err) { /* já mostrado */ } finally { if (btn) btn.disabled = false; }
  });

  // botões com data-pm-action="metodo" data-args='{"name": "..."}'
  document.addEventListener("click", async (e) => {
    const el = e.target.closest("[data-pm-action]");
    if (!el) return;
    e.preventDefault();
    if (el.dataset.confirm && !confirm(el.dataset.confirm)) return;
    if (el.dataset.pmAction === "logout") pm.offline.clear();  // ao sair, a cópia offline é apagada
    await pm.call(el.dataset.pmAction, JSON.parse(el.dataset.args || "{}"));
    if (el.dataset.reload !== "false") location.reload();
  });

  // botão "Atualizar cotações agora": a atualização corre no servidor em segundo plano,
  // por isso consulta o estado até terminar e só então avisa e recarrega a página
  const refreshButtons = () => document.querySelectorAll("[data-pm-refresh]");
  const setRefreshing = (on, progress) => refreshButtons().forEach((b) => {
    if (!b.dataset.label) b.dataset.label = b.innerHTML;
    b.disabled = on;
    // com o ativo em curso: "A atualizar cotações… 12/280 · VWCE.DE"
    const where = on && progress && progress.total ? ` ${progress.done + 1}/${progress.total} · ${progress.current}` : "";
    b.textContent = "";
    b.innerHTML = on ? '<span class="spinner-border spinner-border-sm me-1"></span> A atualizar cotações…' : b.dataset.label;
    if (where) b.append(document.createTextNode(where));  // texto (não HTML): o ticker vem dos dados
  });
  pm.watchRefresh = async () => {
    setRefreshing(true);
    let st;
    try {
      do {
        await new Promise((r) => setTimeout(r, 3000));
        st = await pm.call("refresh_status", {}, { silent: true });
        if (st.running) setRefreshing(true, st.progress);
      } while (st.running);
    } catch (err) {
      setRefreshing(false);
      pm.toast("Não foi possível saber o estado da atualização. Recarrega a página.", "warning");
      return;
    }
    setRefreshing(false);
    if (st.error) {
      pm.toast("A atualização de cotações falhou: " + st.error, "danger");
      return;
    }
    pm.toast(`Cotações atualizadas (${st.updated} ${st.updated === 1 ? "ativo" : "ativos"}).`);
    if (st.missing.length) pm.toast("Sem cotações para: " + st.missing.join(", "), "warning");
    setTimeout(() => location.reload(), 2500);
  };
  document.addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-pm-refresh]");
    if (!btn) return;
    e.preventDefault();
    try {
      pm.toast(await pm.call("refresh_market", { only_open: btn.dataset.onlyOpen || "" }), "info");
    } catch (err) { return; /* já mostrado */ }
    pm.watchRefresh();
  });

  // avisos: ao fechar um, lembra-o (só os 50 mais recentes, para a lista não crescer sem fim)
  document.addEventListener("close.bs.alert", (e) => {
    const text = e.target.dataset?.pmWarning;
    if (!text) return;
    let closed = [];
    try { closed = JSON.parse(pm.store.get("pm-closed-warnings") || "[]"); } catch (err) { /* vazio */ }
    closed = closed.filter((t) => t !== text).concat(text).slice(-50);
    pm.store.set("pm-closed-warnings", JSON.stringify(closed));
  });

  // ---------------------------------------------------------------- modo offline (PWA)
  // Com "Disponível offline" ligado (Definições), o service worker guarda as páginas de consulta; se a
  // aplicação estiver parada, a página vem dessa cópia: mostra-se uma faixa e as ações ficam bloqueadas.
  const OFFLINE_PAGES = ["/", "/carteira", "/desempenho", "/dividendos", "/fiscal", "/radar", "/noticias", "/transacoes"];
  const BLOCKED = "[data-pm-action],[data-pm-refresh],[data-pm-broker],[data-p],#fileInput,#drop,form[data-pm-method] [type=submit]";
  const toSW = (msg) => {
    if (!("serviceWorker" in navigator)) return;
    navigator.serviceWorker.ready.then((reg) => reg.active && reg.active.postMessage(msg)).catch(() => {});
  };
  pm.offline = {
    clear: () => toSW({ type: "clear" }),
    save: () => {
      toSW({ type: "warm", urls: OFFLINE_PAGES });
      store.set("pm-offline-saved", String(Date.now()));
      document.dispatchEvent(new CustomEvent("pm:offline-saved"));
    },
    lastSaved: () => Number(store.get("pm-offline-saved")) || null,
  };
  const enabled = () => document.body.dataset.offline === "1";
  const enterOffline = () => {
    if (document.body.classList.contains("pm-offline")) return;
    document.body.classList.add("pm-offline");
    const when = document.body.dataset.generated ? new Date(document.body.dataset.generated) : null;
    const bar = document.createElement("div");
    bar.className = "alert alert-secondary rounded-0 border-0 border-bottom mb-0 py-2 small d-flex align-items-center gap-2 pm-offline-bar";
    bar.innerHTML = '<i class="bi bi-cloud-slash"></i><span></span>';
    bar.querySelector("span").textContent = "Modo offline · dados de " +
      (when ? when.toLocaleString("pt-PT", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }) : "—") +
      " (só consulta). Inicia a aplicação para atualizar e fazer alterações.";
    document.querySelector(".pm-main")?.prepend(bar);
    // volta a tentar e recarrega quando a aplicação responder
    const retry = setInterval(() => fetch("/ping", { cache: "no-store" })
      .then((r) => { if (r.ok) { clearInterval(retry); location.reload(); } }).catch(() => {}), 15000);
  };
  // em modo offline, as ações ficam bloqueadas com uma explicação (em vez de falharem sem resposta)
  const blockOffline = (e) => {
    if (!document.body.classList.contains("pm-offline") || !e.target.closest(BLOCKED)) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    pm.toast("Modo offline: só consulta. Inicia a aplicação para fazer alterações.", "secondary");
  };
  document.addEventListener("click", blockOffline, true);
  document.addEventListener("submit", (e) => {
    if (!document.body.classList.contains("pm-offline") || !e.target.matches("form[data-pm-method]")) return;
    e.preventDefault();
    e.stopImmediatePropagation();
    pm.toast("Modo offline: só consulta. Inicia a aplicação para fazer alterações.", "secondary");
  }, true);
  document.addEventListener("DOMContentLoaded", () => {
    if (!document.querySelector(".pm-main")) return;  // login e páginas sem menu
    fetch("/ping", { cache: "no-store" }).then((r) => {
      if (!r.ok) throw new Error("sem resposta");
      // aplicação a correr: mantém a cópia offline em dia (de 30 em 30 minutos) ou apaga-a se o modo estiver desligado
      if (!enabled()) pm.offline.clear();
      else if (!pm.offline.lastSaved() || Date.now() - pm.offline.lastSaved() > 30 * 60 * 1000) pm.offline.save();
    }).catch(enterOffline);
  });

  // ---------------------------------------------------------------- preferências
  const store = {
    get: (k) => { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set: (k, v) => { try { localStorage.setItem(k, v); } catch (e) { /* sem armazenamento */ } },
  };
  pm.store = store;

  // modos de cor nativos do Bootstrap: light | dark | auto
  const prefersDark = window.matchMedia("(prefers-color-scheme: dark)");
  pm.applyTheme = () => {
    const pref = store.get("pm-theme") || "auto";
    const dark = pref === "dark" || (pref === "auto" && prefersDark.matches);
    document.documentElement.setAttribute("data-bs-theme", dark ? "dark" : "light");
    document.querySelectorAll("[data-pm-theme]").forEach((b) => b.classList.toggle("active", b.dataset.pmTheme === pref));
    document.dispatchEvent(new CustomEvent("pm:theme"));
  };
  pm.setTheme = (t) => { store.set("pm-theme", t); pm.applyTheme(); };
  prefersDark.addEventListener("change", () => { if ((store.get("pm-theme") || "auto") === "auto") pm.applyTheme(); });

  document.addEventListener("DOMContentLoaded", () => {
    if (store.get("pm-private") === "1") document.body.classList.add("pm-private");
    if (store.get("pm-collapsed") === "1") document.body.classList.add("pm-collapsed");

    document.querySelectorAll("[data-pm-toggle=private]").forEach((b) => b.addEventListener("click", () => {
      document.body.classList.toggle("pm-private");
      store.set("pm-private", document.body.classList.contains("pm-private") ? "1" : "0");
    }));
    document.querySelectorAll("[data-pm-theme]").forEach((b) => b.addEventListener("click", () => pm.setTheme(b.dataset.pmTheme)));
    pm.applyTheme();
    document.querySelectorAll("[data-pm-toggle=collapse]").forEach((b) => b.addEventListener("click", () => {
      document.body.classList.toggle("pm-collapsed");
      store.set("pm-collapsed", document.body.classList.contains("pm-collapsed") ? "1" : "0");
    }));
    document.querySelectorAll("[data-pm-toggle=menu]").forEach((b) => b.addEventListener("click", () => {
      document.body.classList.toggle("pm-menu-open");
    }));
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape") document.body.classList.remove("pm-menu-open");
    });
    document.querySelectorAll("[data-pm-broker]").forEach((a) => a.addEventListener("click", async (e) => {
      e.preventDefault();
      await pm.call("set_broker", { broker: a.dataset.pmBroker || "" });
      location.reload();
    }));
    document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach((el) => new bootstrap.Tooltip(el));
    pm.drawSparklines();
    // aplicação instalável (PWA): o browser só a oferece com um service worker registado
    if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
    // se a página abrir com uma atualização em curso, continua a acompanhá-la
    if (refreshButtons().length) {
      pm.call("refresh_status", {}, { silent: true }).then((st) => { if (st.running) pm.watchRefresh(); }).catch(() => {});
    }
  });

  // ---------------------------------------------------------------- gráficos
  pm.charts = {};
  pm.chartDefaults = () => {
    if (!window.Chart) return;
    Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
    Chart.defaults.color = pm.css("--pm-muted");
    Chart.defaults.borderColor = pm.css("--pm-grid");
    Chart.defaults.plugins.legend.labels.boxWidth = 10;
    Chart.defaults.plugins.legend.labels.boxHeight = 10;
    Chart.defaults.animation.duration = 300;
  };

  pm.chart = (id, config) => {
    pm.chartDefaults();
    const el = document.getElementById(id);
    if (!el) return null;
    if (pm.charts[id]) pm.charts[id].destroy();
    pm.charts[id] = new Chart(el, config);
    return pm.charts[id];
  };

  pm.gradient = (ctx, color) => {
    const g = ctx.createLinearGradient(0, 0, 0, ctx.canvas.height || 300);
    g.addColorStop(0, color + "55");
    g.addColorStop(1, color + "00");
    return g;
  };

  pm.yearTicks = (labels) => (value, index) => {
    const d = labels[index];
    const prev = labels[index - 1];
    return !prev || d.slice(0, 4) !== prev.slice(0, 4) ? d.slice(0, 4) : null;
  };

  pm.drawSparklines = () => {
    document.querySelectorAll("canvas[data-spark]").forEach((c) => {
      const values = JSON.parse(c.dataset.spark || "[]");
      if (values.length < 2) return;
      const up = values[values.length - 1] >= values[0];
      const color = up ? pm.css("--pm-up") : pm.css("--pm-down");
      new Chart(c, {
        type: "line",
        data: { labels: values.map((_, i) => i), datasets: [{ data: values, borderColor: color, borderWidth: 1.5, pointRadius: 0, fill: true, backgroundColor: color + "22", tension: .25 }] },
        options: { responsive: false, animation: false, plugins: { legend: { display: false }, tooltip: { enabled: false } }, scales: { x: { display: false }, y: { display: false } } },
      });
    });
  };

  // ordenação de tabelas: <th data-sort="num|text">
  document.addEventListener("click", (e) => {
    const th = e.target.closest("th[data-sort]");
    if (!th) return;
    const table = th.closest("table");
    const idx = [...th.parentNode.children].indexOf(th);
    const asc = th.dataset.dir !== "asc";
    th.parentNode.querySelectorAll("th").forEach((x) => delete x.dataset.dir);
    th.dataset.dir = asc ? "asc" : "desc";
    const rows = [...table.tBodies[0].rows];
    const val = (r) => {
      const cell = r.cells[idx];
      const raw = cell?.dataset.v ?? cell?.textContent.trim() ?? "";
      return th.dataset.sort === "num" ? parseFloat(raw) || 0 : raw.toLowerCase();
    };
    rows.sort((a, b) => (val(a) > val(b) ? 1 : val(a) < val(b) ? -1 : 0) * (asc ? 1 : -1));
    rows.forEach((r) => table.tBodies[0].appendChild(r));
  });
})();
