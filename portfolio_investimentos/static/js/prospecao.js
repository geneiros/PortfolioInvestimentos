/* Prospeção: as listas de acompanhamento (criar uma lista, guardar uma ação numa lista). */
(() => {
  const newForm = document.getElementById("newListForm");
  if (newForm) newForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    const out = await pm.call("create_watch_list", { title: newForm.title.value });
    location.href = `/radar/acompanhamento?lista=${out.id}`;
  });

  // «Guardar»: escolher a lista (os botões com data-save-ticker, na tabela e na ficha)
  const modalEl = document.getElementById("saveListModal");
  let current = null;
  const watched = () => (window.pmTriage && window.pmTriage.watched) || {};
  const mark = () => {
    const inLists = (current && (current.lists || watched()[current.ticker])) || [];
    modalEl.querySelectorAll("[data-save-list]").forEach((b) => {
      const on = inLists.includes(Number(b.dataset.saveList));
      b.querySelector("[data-in-list]").classList.toggle("d-none", !on);
      b.disabled = on;
    });
  };
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-save-ticker]");
    if (!b || !modalEl) return;
    e.preventDefault();
    e.stopPropagation();
    current = { ticker: b.dataset.saveTicker, name: b.dataset.saveName, currency: b.dataset.saveCurrency || "USD",
      lens: b.dataset.saveLens || "", lists: b.dataset.saveLists ? JSON.parse(b.dataset.saveLists) : null };
    document.getElementById("saveListTicker").textContent = current.ticker;
    const lens = (window.pmLenses || []).find((l) => l.key === current.lens);
    document.getElementById("saveListLens").textContent = lens ? `Fica a acompanhar os critérios da lente ${lens.name}.` : "";
    mark();
    bootstrap.Modal.getOrCreateInstance(modalEl).show();
  });
  const save = async (listId) => {
    const msg = await pm.call("add_watch", { instrument: current.ticker, instrument_name: current.name,
      currency: current.currency, method: current.lens, list_id: listId });
    pm.toast(msg);
    const w = watched();
    (w[current.ticker] = w[current.ticker] || []).push(Number(listId));
    if (current.lists) current.lists.push(Number(listId));
    bootstrap.Modal.getOrCreateInstance(modalEl).hide();
    document.dispatchEvent(new CustomEvent("pm:saved", { detail: { ticker: current.ticker } }));
  };
  if (modalEl) {
    modalEl.addEventListener("click", (e) => {
      const b = e.target.closest("[data-save-list]");
      if (b && current) save(b.dataset.saveList).catch(() => {});
    });
    document.getElementById("saveListNew").addEventListener("submit", async (e) => {
      e.preventDefault();
      const f = e.currentTarget;
      const out = await pm.call("create_watch_list", { title: f.title.value });
      await save(out.id);
      setTimeout(() => location.reload(), 700);  // os separadores mostram a lista nova
    });
  }
})();
