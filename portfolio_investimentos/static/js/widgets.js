// Mudar a ordem dos widgets: carregar 2 segundos no fundo de um cartão (rato ou dedo) e arrastar.
// A grelha tem data-pm-widgets="<página>" e cada widget data-widget="<nome>"; a ordem fica guardada na aplicação.
(function () {
  const HOLD_MS = 2000, SLOP = 6;
  const INTERACTIVE = "a, button, input, select, textarea, label, summary, canvas, svg, [role=button], .pm-treemap, .pm-seg, .pm-periods, .modal, .dropdown-menu";

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

  document.querySelectorAll("[data-pm-widgets]").forEach((grid) => {
    const page = grid.dataset.pmWidgets;
    let arm = null, drag = null;

    const cancelArm = () => {
      if (!arm) return;
      clearTimeout(arm.timer);
      arm.card.classList.remove("pm-widget-arming");
      arm = null;
    };

    grid.addEventListener("pointerdown", (e) => {
      if (drag || (e.pointerType === "mouse" && e.button !== 0)) return;
      const widget = e.target.closest("[data-widget]");
      if (!widget || widget.parentElement !== grid || e.target.closest(INTERACTIVE) || onText(e.clientX, e.clientY)) return;
      const card = widget.querySelector(".pm-card") || widget;
      if (e.pointerType === "mouse") e.preventDefault();  // no fundo do cartão: sem começar a selecionar texto
      arm = { widget, card, x: e.clientX, y: e.clientY, id: e.pointerId, type: e.pointerType };
      card.classList.add("pm-widget-arming");
      arm.timer = setTimeout(start, HOLD_MS);
    });

    const start = () => {
      const { widget, card, x, y, id } = arm;
      card.classList.remove("pm-widget-arming");
      arm = null;
      const rect = widget.getBoundingClientRect();
      const ph = document.createElement("div");
      ph.className = widget.className;
      ph.removeAttribute("data-widget");
      // um cartão mais alto do que 40% do ecrã encolhe enquanto se arrasta (e o marcador também), para se ver onde cai
      const tall = rect.height > window.innerHeight * 0.4;
      const h = card.getBoundingClientRect().height;
      ph.innerHTML = `<div class="pm-widget-placeholder" style="height:${tall ? Math.min(h, Math.max(96, window.innerHeight * 0.18)) : h}px"></div>`;
      widget.after(ph);
      drag = { widget, ph, id, dx: x - rect.left, dy: y - rect.top, next: ph.nextSibling, lastX: x, lastY: y };
      drag.raf = requestAnimationFrame(autoScroll);
      Object.assign(widget.style, { position: "fixed", left: `${rect.left}px`, top: `${rect.top}px`, width: `${rect.width}px`,
                                     zIndex: 1080, pointerEvents: "none",
                                     transform: tall ? `scale(${Math.max(0.35, (window.innerHeight * 0.3) / rect.height).toFixed(2)})` : "",
                                     transformOrigin: `${x - rect.left}px ${y - rect.top}px` });
      widget.classList.add("pm-widget-dragging");
      document.body.classList.add("pm-widget-drag-on");
      try { window.getSelection().removeAllRanges(); } catch (err) { /* sem seleção */ }
      if (navigator.vibrate) try { navigator.vibrate(30); } catch (err) { /* sem vibração */ }
    };

    const place = (x, y) => {
      const { widget, ph } = drag;
      widget.style.left = `${x - drag.dx}px`;
      widget.style.top = `${y - drag.dy}px`;
      const over = document.elementFromPoint(x, y);
      const target = over && over.closest("[data-widget]");
      if (!target || target === widget || target.parentElement !== grid) return;
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
    grid.addEventListener("contextmenu", (e) => { if (arm || drag) e.preventDefault(); });
    window.addEventListener("scroll", () => { if (arm && arm.type !== "mouse") cancelArm(); }, { passive: true });

    const finish = (save) => {
      const { widget, ph, next } = drag;
      cancelAnimationFrame(drag.raf);
      widget.removeAttribute("style");
      widget.classList.remove("pm-widget-dragging");
      document.body.classList.remove("pm-widget-drag-on");
      if (save) ph.replaceWith(widget);
      else { ph.remove(); grid.insertBefore(widget, next && next.parentElement === grid ? next : null); }
      drag = null;
      window.dispatchEvent(new Event("resize"));  // os gráficos ajustam-se à largura nova
      if (!save) return;
      const order = [...grid.querySelectorAll(":scope > [data-widget]")].map((w) => w.dataset.widget);
      pm.call("save_widget_order", { page, order: order.join(",") }, { silent: true })
        .then(() => pm.toast("Ordem dos widgets guardada."))
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
  });
})();
