// Mudar a ordem dos cartões em todas as páginas: carregar 2 segundos no fundo de um cartão (rato ou dedo) e arrastar.
//
// Os cartões encontram-se sozinhos: cada .pm-card de topo (fora de outro cartão e de janelas) sobe até ao maior
// elemento que só o contém a ele; o pai desse elemento é a «grelha». Uma grelha com 2 ou mais cartões permite
// mudar a ordem (só dentro dela). Um elemento com data-widget="nome" conta como um cartão com esse nome, e o que
// estiver dentro dele não se arrasta à parte. A ordem de cada grelha fica guardada na aplicação, por página
// (window.PM_WIDGET_ORDER, vindo do servidor), e aplica-se antes de a página desenhar os gráficos.
(function () {
  const HOLD_MS = 2000, SLOP = 6;
  const INTERACTIVE = "a, button, input, select, textarea, label, summary, canvas, svg, img, [role=button], [contenteditable], .pm-treemap, .pm-seg, .pm-periods, .modal, .dropdown-menu, .btn-group, .nav, .table-responsive, table";
  const main = document.querySelector(".pm-content");
  if (!main) return;
  const page = location.pathname;
  const saved = window.PM_WIDGET_ORDER || {};

  const slug = (t) => (t || "").toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z\s-]/g, " ").trim().split(/\s+/).filter(Boolean).slice(0, 4).join("-").slice(0, 40);

  // ---------------------------------------------------------------- encontrar as grelhas e os cartões
  const explicit = [...main.querySelectorAll("[data-widget]")];
  const tops = [...main.querySelectorAll(".pm-card")].filter((c) =>
    !c.parentElement.closest(".pm-card, .modal, [data-widget]") && !c.closest("[hidden]"));
  const cardsIn = (el) => tops.filter((c) => el.contains(c)).length + explicit.filter((w) => el.contains(w)).length;
  const items = new Set(explicit);
  for (const card of tops) {
    let w = card;
    while (w.parentElement && w.parentElement !== main && cardsIn(w.parentElement) === 1) w = w.parentElement;
    items.add(w);
  }
  const grids = new Map();
  for (const w of items) {
    const g = w.parentElement;
    if (!grids.has(g)) grids.set(g, []);
    grids.get(g).push(w);
  }
  const named = [], gridNames = {};
  for (const [grid, list] of grids) {
    if (list.length < 2) continue;
    const used = {};
    for (const w of list) {
      const card = w.matches(".pm-card") ? w : w.querySelector(".pm-card");
      const title = card && card.querySelector(".pm-label, .pm-section-title, h1, h2, h3, h4, h5, h6");
      let name = w.dataset.widget || w.id || (card && card.id) || slug(title && title.textContent) || "cartao";
      name = slug(name) || "cartao";
      used[name] = (used[name] || 0) + 1;
      if (used[name] > 1) name = `${name}-${used[name]}`;
      w.dataset.pmItem = name;
    }
    // a grelha tem o id dela ou o nome do primeiro cartão (na ordem de omissão): não muda com outras grelhas
    let key = grid.id || `g-${list[0].dataset.pmItem}`.slice(0, 48);
    gridNames[key] = (gridNames[key] || 0) + 1;
    if (gridNames[key] > 1) key = `${key.slice(0, 44)}-${gridNames[key]}`;
    grid.dataset.pmGrid = key;
    named.push(grid);
  }
  const itemsOf = (grid) => [...grid.children].filter((el) => el.dataset.pmItem);

  // ---------------------------------------------------------------- aplicar a ordem guardada
  // os cartões trocam de lugar entre si; o resto da grelha (títulos, avisos) fica onde está
  for (const grid of named) {
    const order = saved[grid.dataset.pmGrid];
    if (!order || !order.length) continue;
    const list = itemsOf(grid);
    const rank = (el, i) => { const k = order.indexOf(el.dataset.pmItem); return k < 0 ? order.length + i : k; };
    const sorted = list.map((el, i) => [rank(el, i), el]).sort((a, b) => a[0] - b[0]).map((x) => x[1]);
    const slots = list.map((el) => { const m = document.createComment(""); el.before(m); return m; });
    list.forEach((el) => el.remove());
    slots.forEach((m, i) => m.replaceWith(sorted[i]));
  }

  // ---------------------------------------------------------------- clique longo e arrastar
  // o ponto está sobre texto? (o arrastar só começa no fundo do cartão)
  const onText = (x, y) => {
    let node = null, offset = 0;
    if (document.caretPositionFromPoint) {
      const pos = document.caretPositionFromPoint(x, y);
      if (pos) { node = pos.offsetNode; offset = pos.offset; }
    } else if (document.caretRangeFromPoint) {
      const r = document.caretRangeFromPoint(x, y);
      if (r) { node = r.startContainer; offset = r.startOffset; }
    }
    if (!node || node.nodeType !== Node.TEXT_NODE || !node.textContent.trim()) return false;
    const range = document.createRange();
    for (const k of [offset - 1, offset]) {
      if (k < 0 || k >= node.textContent.length) continue;
      range.setStart(node, k); range.setEnd(node, k + 1);
      for (const rect of range.getClientRects()) {
        if (x >= rect.left - 1 && x <= rect.right + 1 && y >= rect.top - 1 && y <= rect.bottom + 1) return true;
      }
    }
    return false;
  };

  let arm = null, drag = null;
  const cancelArm = () => {
    if (!arm) return;
    clearTimeout(arm.timer);
    arm.card.classList.remove("pm-widget-arming");
    arm = null;
  };

  main.addEventListener("pointerdown", (e) => {
    if (drag || (e.pointerType === "mouse" && e.button !== 0)) return;
    const widget = e.target.closest("[data-pm-item]");  // o mais próximo: um cartão dentro de outro conta o de dentro
    if (!widget || !widget.parentElement.dataset.pmGrid || e.target.closest(INTERACTIVE) || onText(e.clientX, e.clientY)) return;
    const card = widget.matches(".pm-card") ? widget : (widget.querySelector(".pm-card") || widget);
    if (e.pointerType === "mouse") e.preventDefault();  // no fundo do cartão: sem começar a selecionar texto
    arm = { widget, card, x: e.clientX, y: e.clientY, id: e.pointerId, type: e.pointerType };
    card.classList.add("pm-widget-arming");
    arm.timer = setTimeout(start, HOLD_MS);
  });

  const start = () => {
    const { widget, card, x, y, id } = arm;
    card.classList.remove("pm-widget-arming");
    arm = null;
    const grid = widget.parentElement;
    const rect = widget.getBoundingClientRect();
    // um cartão mais alto do que 40% do ecrã encolhe enquanto se arrasta (e o marcador também), para se ver onde cai
    const tall = rect.height > window.innerHeight * 0.4;
    const h = card.getBoundingClientRect().height;
    const ph = document.createElement("div");
    ph.className = widget.className;
    ph.classList.remove("pm-card", "pm-widget-arming");
    ph.innerHTML = `<div class="pm-widget-placeholder" style="height:${tall ? Math.min(h, Math.max(96, window.innerHeight * 0.18)) : h}px"></div>`;
    widget.after(ph);
    drag = { widget, grid, ph, id, dx: x - rect.left, dy: y - rect.top, next: ph.nextSibling, lastX: x, lastY: y };
    Object.assign(widget.style, { position: "fixed", left: `${rect.left}px`, top: `${rect.top}px`, width: `${rect.width}px`,
                                   margin: 0, zIndex: 1080, pointerEvents: "none",
                                   transform: tall ? `scale(${Math.max(0.35, (window.innerHeight * 0.3) / rect.height).toFixed(2)})` : "",
                                   transformOrigin: `${x - rect.left}px ${y - rect.top}px` });
    widget.classList.add("pm-widget-dragging");
    document.body.classList.add("pm-widget-drag-on");
    try { window.getSelection().removeAllRanges(); } catch (err) { /* sem seleção */ }
    if (navigator.vibrate) try { navigator.vibrate(30); } catch (err) { /* sem vibração */ }
    drag.raf = requestAnimationFrame(autoScroll);
  };

  const place = (x, y) => {
    const { widget, ph, grid } = drag;
    widget.style.left = `${x - drag.dx}px`;
    widget.style.top = `${y - drag.dy}px`;
    const over = document.elementFromPoint(x, y);
    let target = over && over.closest("[data-pm-item]");
    while (target && target.parentElement !== grid) target = target.parentElement && target.parentElement.closest("[data-pm-item]");
    if (!target || target === widget) return;
    const r = target.getBoundingClientRect();
    const fullRow = r.width > grid.getBoundingClientRect().width * 0.9;
    const before = fullRow ? y < r.top + r.height / 2 : x < r.left + r.width / 2;
    if (before && target.previousElementSibling !== ph) target.before(ph);
    else if (!before && target.nextElementSibling !== ph) target.after(ph);
  };

  // perto das margens, a página desliza (também com o cursor parado), mais depressa quanto mais perto
  const autoScroll = () => {
    if (!drag) return;
    const edge = 80, y = drag.lastY;
    const speed = y < edge ? -(edge - y) / 3 : (y > window.innerHeight - edge ? (y - window.innerHeight + edge) / 3 : 0);
    if (speed) { window.scrollBy(0, speed); place(drag.lastX, drag.lastY); }
    drag.raf = requestAnimationFrame(autoScroll);
  };

  document.addEventListener("pointermove", (e) => {
    if (arm && e.pointerId === arm.id && Math.hypot(e.clientX - arm.x, e.clientY - arm.y) > SLOP) cancelArm();
    if (drag && e.pointerId === drag.id) { e.preventDefault(); drag.lastX = e.clientX; drag.lastY = e.clientY; place(e.clientX, e.clientY); }
  }, { passive: false });
  // no telemóvel, enquanto se arrasta, o dedo não desliza a página
  document.addEventListener("touchmove", (e) => { if (drag) e.preventDefault(); }, { passive: false });
  main.addEventListener("contextmenu", (e) => { if (arm || drag) e.preventDefault(); });
  window.addEventListener("scroll", () => { if (arm && arm.type !== "mouse") cancelArm(); }, { passive: true });

  const finish = (save) => {
    const { widget, ph, next, grid } = drag;
    cancelAnimationFrame(drag.raf);
    widget.removeAttribute("style");
    widget.classList.remove("pm-widget-dragging");
    document.body.classList.remove("pm-widget-drag-on");
    if (save) ph.replaceWith(widget);
    else { ph.remove(); grid.insertBefore(widget, next && next.parentElement === grid ? next : null); }
    drag = null;
    window.dispatchEvent(new Event("resize"));  // os gráficos ajustam-se à largura nova
    if (!save) return;
    const order = itemsOf(grid).map((w) => w.dataset.pmItem);
    pm.call("save_widget_order", { page, grid: grid.dataset.pmGrid, order: order.join(",") }, { silent: true })
      .then(() => pm.toast("Ordem dos cartões guardada."))
      .catch(() => pm.toast("Não foi possível guardar a ordem.", "danger"));
  };

  document.addEventListener("pointerup", (e) => {
    if (arm && e.pointerId === arm.id) cancelArm();
    if (drag && e.pointerId === drag.id) finish(true);
  });
  document.addEventListener("pointercancel", (e) => {
    if (arm && e.pointerId === arm.id) cancelArm();
    if (drag && e.pointerId === drag.id) finish(false);
  });
  document.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    cancelArm();
    if (drag) finish(false);
  });
})();
