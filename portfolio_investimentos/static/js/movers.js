/* Visão Geral · principais movers: gráfico de cada ação (último ano) face ao preço médio de aquisição.
   A linha e o preenchimento ficam verdes acima do preço médio e vermelhos abaixo; o preço médio é o tracejado. */
(function () {
  const ddmmyyyy = (iso) => `${iso.slice(8, 10)}/${iso.slice(5, 7)}/${iso.slice(0, 4)}`;
  const hidden = () => document.documentElement.classList.contains("pm-private");

  function draw(canvas) {
    const d = JSON.parse(canvas.dataset.mover || "{}");
    if (!d.v || d.v.length < 2) return;
    // datas: dias desde a primeira ("s" + "o") → "aaaa-mm-dd"
    const t0 = Date.parse(d.s + "T00:00:00Z");
    d.d = d.o.map((k) => new Date(t0 + k * 86400000).toISOString().slice(0, 10));
    const old = Chart.getChart(canvas);
    if (old) old.destroy();
    const up = pm.css("--pm-up"), down = pm.css("--pm-down"), muted = pm.css("--bs-secondary-color");
    const avg = d.avg;
    const ref = avg ?? d.v[0];  // sem preço médio: compara com o início do período
    const values = d.v.concat(avg ? [avg] : []);
    const min = Math.min(...values), max = Math.max(...values), pad = (max - min) * 0.1 || max * 0.01;
    const price = (v) => (hidden() ? "€ ••••" : pm.money(v, 2, false, d.cur));
    const datasets = [{
      data: d.v, borderWidth: 1.6, pointRadius: 0, pointHoverRadius: 3, tension: .25,
      segment: { borderColor: (c) => ((c.p0.parsed.y + c.p1.parsed.y) / 2 >= ref ? up : down) },
      borderColor: d.v[d.v.length - 1] >= ref ? up : down,
      fill: { target: { value: ref }, above: up + "26", below: down + "26" },
    }];
    if (avg) datasets.push({ data: d.v.map(() => avg), borderColor: muted, borderWidth: 1, borderDash: [3, 3],
      pointRadius: 0, pointHoverRadius: 0, fill: false, isAvg: true });
    new Chart(canvas, {
      type: "line",
      data: { labels: d.d, datasets },
      options: {
        responsive: true, maintainAspectRatio: false, animation: false,
        interaction: { mode: "index", intersect: false },
        layout: { padding: { top: 2, bottom: 2 } },
        scales: { x: { display: false }, y: { display: false, min: min - pad, max: max + pad } },
        plugins: {
          legend: { display: false },
          // tooltip em HTML por cima do gráfico (o do Chart.js ficava cortado num gráfico tão baixo)
          tooltip: { enabled: false, filter: (it) => !it.dataset.isAvg, external: (ctx) => tip(ctx, d, avg, price) },
        },
      },
    });
  }

  function tip({ chart, tooltip }, d, avg, price) {
    const box = chart.canvas.parentNode;
    let el = box.querySelector(".pm-mover-tip");
    if (!el) {
      el = document.createElement("div");
      el.className = "pm-mover-tip";
      box.appendChild(el);
    }
    if (!tooltip.opacity || !tooltip.dataPoints || !tooltip.dataPoints.length) {
      el.style.opacity = 0;
      return;
    }
    const point = tooltip.dataPoints[0], v = point.parsed.y;
    const diff = avg ? v / avg - 1 : null;
    el.replaceChildren();
    const head = document.createElement("div");
    head.innerHTML = "<b></b> · <span></span>";
    head.children[0].textContent = ddmmyyyy(point.label);
    head.children[1].textContent = price(v);
    el.appendChild(head);
    if (avg) {
      const line = document.createElement("div");
      line.className = diff >= 0 ? "text-up" : "text-down";
      line.textContent = `${pm.pct(diff, 1)} face ao preço médio ${price(avg)}`;
      el.appendChild(line);
    }
    const x = Math.min(Math.max(tooltip.caretX, el.offsetWidth / 2), box.clientWidth - el.offsetWidth / 2);
    el.style.left = `${x}px`;
    el.style.opacity = 1;
  }

  const drawAll = () => document.querySelectorAll("canvas[data-mover]").forEach(draw);
  document.addEventListener("DOMContentLoaded", drawAll);
  document.addEventListener("pm:theme", drawAll);
})();
