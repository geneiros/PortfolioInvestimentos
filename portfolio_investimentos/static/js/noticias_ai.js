/* Notícias: a análise com IA (pedida à plataforma escolhida em Definições). O resultado desenha-se aqui, sempre
   com textContent (o texto vem da IA e das notícias: nunca entra como HTML). */
(() => {
  const box = document.getElementById("aiResult");
  const scope = document.getElementById("aiScope");
  const run = document.getElementById("aiRun");
  const again = document.getElementById("aiAgain");
  if (!box || !scope) return;
  const saved = window.pmAiSaved || {};
  const TONE = { positivo: ["text-bg-success", "Positivo"], negativo: ["text-bg-danger", "Negativo"],
    misto: ["text-bg-warning", "Misto"], neutro: ["text-bg-secondary", "Neutro"] };
  const el = (tag, cls, text) => {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  };
  const list = (title, items) => {
    if (!items || !items.length) return null;
    const wrap = el("div", "small mt-1");
    wrap.appendChild(el("span", "text-secondary", title + ": "));
    const ul = el("ul", "mb-0 ps-3");
    items.forEach((t) => ul.appendChild(el("li", "", t)));
    wrap.appendChild(ul);
    return wrap;
  };
  const when = (iso) => { const d = new Date(iso); return isNaN(d) ? iso : d.toLocaleString("pt-PT", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }); };
  const render = (a) => {
    box.replaceChildren();
    if (!a || !a.result) {
      box.appendChild(el("p", "small text-secondary mb-0", "Ainda não há análise destas notícias. Carrega em «Analisar»."));
      return;
    }
    const r = a.result;
    box.appendChild(el("div", "small text-secondary mb-2",
      `${a.provider_name} · ${a.model} · ${when(a.at)} · ${a.count} ${a.count === 1 ? "notícia" : "notícias"}${a.reused ? " · sem notícias novas desde a última análise" : ""}`));
    if (r.resumo) box.appendChild(el("p", "mb-2", r.resumo));
    (r.ativos || []).forEach((x) => {
      const item = el("div", "border-top pt-2 mt-2");
      const head = el("div", "d-flex align-items-center gap-2 mb-1");
      head.appendChild(el("b", "", x.ticker || "—"));
      const [cls, label] = TONE[x.tom] || TONE.neutro;
      head.appendChild(el("span", `badge ${cls}`, label));
      item.appendChild(head);
      if (x.conclusao) item.appendChild(el("div", "", x.conclusao));
      [list("Riscos", x.riscos), list("A verificar", x.a_verificar)].forEach((n) => n && item.appendChild(n));
      if (x.noticias && x.noticias.length) {
        const src = el("div", "small mt-1 d-flex flex-wrap gap-2");
        src.appendChild(el("span", "text-secondary", "Notícias:"));
        x.noticias.forEach((n) => {
          const link = el("a", "text-truncate", n.titulo);
          if (/^https?:\/\//i.test(n.url || "")) link.href = n.url;
          link.target = "_blank"; link.rel = "noopener noreferrer"; link.style.maxWidth = "22rem";
          src.appendChild(link);
        });
        item.appendChild(src);
      }
      box.appendChild(item);
    });
    box.appendChild(el("p", "small text-secondary mt-2 mb-0", "Resumo automático: confirma sempre nas notícias de origem. Não é uma recomendação de investimento."));
  };
  const KEY = "pm-ai-scope";
  try { const s = localStorage.getItem(KEY); if (s && [...scope.options].some((o) => o.value === s)) scope.value = s; } catch (e) { /* sem armazenamento */ }
  const show = () => render(saved[scope.value]);
  scope.addEventListener("change", () => { try { localStorage.setItem(KEY, scope.value); } catch (e) { /* */ } show(); });
  const go = async (force) => {
    run.disabled = again.disabled = true;
    const old = run.innerHTML;
    run.innerHTML = '<span class="spinner-border spinner-border-sm"></span> A analisar…';
    try {
      const a = await pm.call("ai_analyse_news", { scope: scope.value, force: force ? "1" : "" });
      saved[scope.value] = a;
      render(a);
    } catch (e) { /* o erro já aparece no aviso */ } finally { run.disabled = again.disabled = false; run.innerHTML = old; }
  };
  run.addEventListener("click", () => go(false));
  again.addEventListener("click", () => go(true));
  show();
})();
