/* Visão Geral: peso vs retorno (mapa e bolhas), alocação e escolha do perfil de investidor. */
(function () {
  const PALETTE = ["#3b82f6", "#f97316", "#22c55e", "#a855f7", "#ec4899", "#14b8a6", "#eab308", "#ef4444", "#64748b", "#06b6d4"];

  // cor do retorno: vermelho (≤ −25%) → cinzento (0) → verde (≥ +25%)
  const retColor = (r) => {
    const t = Math.max(-1, Math.min(1, r / 0.25));
    const mix = (a, b, k) => Math.round(a + (b - a) * k);
    const base = [71, 85, 105], up = [22, 163, 74], down = [220, 38, 38];
    const to = t >= 0 ? up : down, k = Math.abs(t);
    return `rgb(${mix(base[0], to[0], k)}, ${mix(base[1], to[1], k)}, ${mix(base[2], to[2], k)})`;
  };

  // treemap "quadrado" (Bruls et al.): retângulos com proporções próximas de 1
  function squarify(items, x, y, w, h) {
    const out = [];
    const total = items.reduce((s, it) => s + it.v, 0);
    if (!total) return out;
    const scale = (w * h) / total;
    let rest = items.map((it) => ({ ...it, a: it.v * scale }));
    while (rest.length) {
      const side = Math.min(w, h);
      let row = [rest[0]], best = worst(row, side), i = 1;
      while (i < rest.length) {
        const cand = row.concat(rest[i]), r = worst(cand, side);
        if (r > best) break;
        row = cand; best = r; i += 1;
      }
      const sum = row.reduce((s, it) => s + it.a, 0);
      if (w >= h) {  // coluna à esquerda
        const cw = sum / h; let cy = y;
        row.forEach((it) => { const ch = it.a / cw; out.push({ ...it, x, y: cy, w: cw, h: ch }); cy += ch; });
        x += cw; w -= cw;
      } else {       // linha em cima
        const rh = sum / w; let cx = x;
        row.forEach((it) => { const cw = it.a / rh; out.push({ ...it, x: cx, y, w: cw, h: rh }); cx += cw; });
        y += rh; h -= rh;
      }
      rest = rest.slice(row.length);
    }
    return out;
    function worst(row, side) {
      const s = row.reduce((t, it) => t + it.a, 0);
      const max = Math.max(...row.map((it) => it.a)), min = Math.min(...row.map((it) => it.a));
      return Math.max((side * side * max) / (s * s), (s * s) / (side * side * min));
    }
  }

  function drawMap(rows) {
    const box = document.getElementById("wrMap");
    box.replaceChildren();
    const W = box.clientWidth, H = box.clientHeight;
    const big = rows.filter((r) => r.weight >= 0.01);
    const small = rows.length - big.length;
    const badge = document.getElementById("wrSmall");
    badge.classList.toggle("d-none", !small);
    badge.textContent = `+${small} com peso <1%`;
    squarify(big.map((r) => ({ ...r, v: r.weight })), 0, 0, W, H).forEach((c) => {
      const el = document.createElement("div");
      el.className = "pm-tile";
      Object.assign(el.style, { left: `${c.x}px`, top: `${c.y}px`, width: `${c.w}px`, height: `${c.h}px`, background: retColor(c.ret) });
      el.title = `${c.ticker} · peso ${pm.pct(c.weight, 1, false)} · retorno ${pm.pct(c.ret, 1)} (${pm.money(c.gain, 0, true)})`;
      if (c.w > 46 && c.h > 30) {
        const t = document.createElement("b"); t.textContent = c.ticker;
        const r = document.createElement("span"); r.textContent = pm.pct(c.ret, 1);
        el.append(t, r);
      }
      box.append(el);
    });
  }

  function drawBubbles(rows) {
    const max = Math.max(...rows.map((r) => r.value), 1);
    pm.chart("wrChart", {
      type: "bubble",
      data: { datasets: [{ data: rows.map((r) => ({ x: r.weight * 100, y: r.ret * 100, r: 4 + 22 * Math.sqrt(r.value / max), t: r.ticker })),
        backgroundColor: rows.map((r) => retColor(r.ret)), borderColor: "rgba(255,255,255,.25)" }] },
      options: { maintainAspectRatio: false, plugins: { legend: { display: false },
        tooltip: { callbacks: { label: (it) => `${it.raw.t}: peso ${it.raw.x.toFixed(1)}% · retorno ${it.raw.y.toFixed(1)}%` } } },
        scales: { x: { title: { display: true, text: "peso (%)" } }, y: { title: { display: true, text: "retorno total (%)" } } } },
    });
  }

  function drawAlloc(alloc, view) {
    const rows = alloc[view] || [];
    const total = rows.reduce((s, r) => s + r.value, 0);
    document.getElementById("allocTotal").textContent = pm.money(total, 0);
    document.getElementById("allocCaption").textContent = view === "kind" ? "com caixa" : "em posições";
    pm.chart("allocChart", {
      type: "doughnut",
      data: { labels: rows.map((r) => r.name), datasets: [{ data: rows.map((r) => r.value), backgroundColor: rows.map((_, i) => PALETTE[i % PALETTE.length]), borderWidth: 0 }] },
      options: { maintainAspectRatio: false, cutout: "68%", plugins: { legend: { display: false },
        tooltip: { callbacks: { label: (it) => `${it.label}: ${pm.money(it.parsed, 0)} (${pm.pct(it.parsed / total, 1, false)})` } } } },
    });
    const list = document.getElementById("allocList");
    list.replaceChildren();
    rows.forEach((r, i) => {
      const line = document.createElement("div");
      line.className = "d-flex align-items-center gap-2 py-1 border-bottom";
      const sw = document.createElement("span");
      sw.className = "sw"; Object.assign(sw.style, { width: "9px", height: "9px", borderRadius: "2px", background: PALETTE[i % PALETTE.length], flex: "none" });
      const name = document.createElement("span"); name.className = "flex-grow-1 text-truncate"; name.textContent = r.name;
      const n = document.createElement("span"); n.className = "badge text-bg-secondary"; n.textContent = r.count || "";
      const v = document.createElement("span"); v.className = "money text-end"; v.style.minWidth = "5rem"; v.textContent = pm.money(r.value, 0);
      const p = document.createElement("b"); p.className = "text-end"; p.style.minWidth = "3.5rem"; p.textContent = pm.pct(total ? r.value / total : 0, 1, false);
      line.append(sw, name, n, v, p);
      list.append(line);
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    const src = document.getElementById("insightsData");
    if (src) {
      const d = JSON.parse(src.textContent);
      let wrMode = "map", view = "sector";
      const wr = () => {
        document.getElementById("wrMap").classList.toggle("d-none", wrMode !== "map");
        document.getElementById("wrBubbles").classList.toggle("d-none", wrMode !== "bubbles");
        wrMode === "map" ? drawMap(d.wr) : drawBubbles(d.wr);
      };
      document.querySelectorAll("#wrMode button").forEach((b) => b.addEventListener("click", () => {
        document.querySelectorAll("#wrMode button").forEach((x) => x.classList.toggle("active", x === b));
        wrMode = b.dataset.mode; wr();
      }));
      document.querySelectorAll("#allocTabs button").forEach((b) => b.addEventListener("click", () => {
        document.querySelectorAll("#allocTabs button").forEach((x) => x.classList.toggle("active", x === b));
        view = b.dataset.view; drawAlloc(d.alloc, view);
      }));
      let resize;
      window.addEventListener("resize", () => { clearTimeout(resize); resize = setTimeout(() => wrMode === "map" && drawMap(d.wr), 150); });
      document.addEventListener("pm:theme", () => { wr(); drawAlloc(d.alloc, view); });
      wr(); drawAlloc(d.alloc, view);
    }
    // perfis: a lista à esquerda mostra a explicação à direita
    document.querySelectorAll(".pm-profile").forEach((b) => b.addEventListener("click", () => {
      document.querySelectorAll(".pm-profile").forEach((x) => {
        x.classList.toggle("border-primary", x === b);
        const icon = x.querySelector(".bi");
        icon.className = "bi " + (x === b ? "bi-record-circle-fill text-primary" : "bi-circle");
      });
      document.querySelectorAll(".pm-profile-detail").forEach((x) => x.classList.toggle("d-none", x.dataset.profile !== b.dataset.profile));
    }));
  });
})();
