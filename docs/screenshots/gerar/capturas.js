// Capturas do README (1900×950): node docs/screenshots/gerar/capturas.js <url> <pasta> [claro|escuro|ambos] [filtro]
// Ex.: node docs/screenshots/gerar/capturas.js http://localhost:5089 docs/screenshots ambos
// O filtro tira só as capturas cujo nome o contém (ex.: «17-prospecao»). Precisa do Playwright (npm i playwright).
const { chromium } = require('playwright');
const [,, BASE, OUT, MODE = 'ambos', ONLY = ''] = process.argv;
const fs = require('fs');

// para: o elemento a pôr perto do topo (y = 110 px, logo abaixo da barra de cima); antes: o que fazer antes
const S = [
  { id: '01-visao-geral', url: '/' },
  { id: '02-visao-geral-evolucao', url: '/', to: '#modeSeg', y: 160 },
  { id: '03-visao-geral-peso-alocacao', url: '/', to: 'text=/^Peso vs retorno/', y: 330 },
  { id: '04-perfil-investidor', url: '/', to: 'text=/^Peso vs retorno/', y: 700, then: async (p) => { await p.locator('[data-bs-target="#profileModal"]').first().click({ force: true }); await p.waitForTimeout(600); } },
  { id: '05-carteira', url: '/carteira' },
  { id: '06-carteira-alocacao', url: '/carteira', to: 'text=/^Alocação · /', y: 120 },
  { id: '07-desempenho', url: '/desempenho' },
  { id: '08-desempenho-jornada', url: '/desempenho', to: 'text=2 · Como foi a jornada?' },
  { id: '09-desempenho-mensal', url: '/desempenho', to: 'text=3 · Quando ganhaste e perdeste?' },
  { id: '10-desempenho-merito', url: '/desempenho', to: 'text=4 · É sorte ou mérito?' },
  { id: '11-desempenho-risco', url: '/desempenho', to: 'text=5 · Qual é o risco real?' },
  { id: '12-dividendos', url: '/dividendos' },
  { id: '13-dividendos-mapa', url: '/dividendos', to: 'text=Mapa de rendimento: dividendos por mês' },
  { id: '14-fiscal', url: '/fiscal' },
  { id: '15-planeamento', url: '/planeamento' },
  { id: '16-planeamento-projecao', url: '/planeamento', to: 'text=/Já dá para|Ainda não dá/', y: 130 },
  { id: '17-prospecao-lista', url: '/radar/acompanhamento' },
  { id: '18-importar', url: '/importar' },
  { id: '19-transacoes', url: '/transacoes' },
  { id: '20-definicoes', url: '/definicoes' },
  { id: '21-patrimonio', url: '/patrimonio' },
  { id: '22-carteira-crises-custos', url: '/carteira', to: '#crisisCard' },
  { id: '23-patrimonio-crescimento', url: '/patrimonio', to: 'text=/^Evolução mensal/' },
  { id: '24-carteira-valor-acoes', url: '/carteira', to: '#valuationCard' },
  { id: '25-carteira-alerta', url: '/carteira', then: async (p) => { await p.click('button[title="Alerta da carteira"]'); await p.waitForTimeout(500); } },
  { id: '26-carteira-indices', url: '/carteira', then: async (p) => { await p.click('button[title="Gerir índices"]'); await p.waitForTimeout(500); } },
  { id: '27-noticias', url: '/noticias' },
  { id: '28-noticias-radar', url: '/noticias', then: async (p) => { await p.click('button[data-bs-target="#tab-radar"]'); await p.waitForTimeout(500); } },
  { id: '29-desempenho-indice', url: '/desempenho', to: '#shadowCard' },
  { id: '30-carteira-raio-x', url: '/carteira', to: '#xrayCard' },
  { id: '31-definicoes-dados-mercado', url: '/definicoes', to: 'text=/^Dados de mercado/' },
  { id: '32-fiscal-simulador', url: '/fiscal', to: 'text=/^Simular uma venda/', y: 130 },
  { id: '33-fiscal-vender-recomprar', url: '/fiscal', to: 'text=/^Vender e recomprar posições/', y: 130 },
  { id: '34-relatorio-anual', url: '/relatorio' },
  { id: '35-prospecao-triagem', url: '/radar', then: async (p) => {
      await p.click('[data-lens="buffett"]'); await p.waitForTimeout(400);
      await p.locator('#triageBody tr[data-ticker]').first().click();
      await p.waitForSelector('#triagePanelBody .pm-ficha', { timeout: 120000 }); await p.waitForTimeout(800); } },
  { id: '36-prospecao-ficha', url: '/radar', then: async (p) => {
      await p.click('[data-lens="buffett"]'); await p.fill('#fSearch', 'Shell plc'); await p.waitForTimeout(500);
      if (!(await p.locator('#triageBody tr[data-ticker]').count())) { await p.click('#fOnly'); await p.waitForTimeout(500); }
      await p.locator('#triageBody tr[data-ticker]').first().click();
      await p.waitForSelector('#triagePanelBody .pm-ficha', { timeout: 120000 }); await p.waitForTimeout(800);
      await p.evaluate(() => { const b = document.getElementById('triagePanelBody'); const v = b.querySelector('.pm-valuation, [data-valuation], #valueCard') || [...b.querySelectorAll('.pm-label')].find((e) => /O valor da ação/.test(e.textContent)); if (v) b.scrollTop = v.getBoundingClientRect().top - b.getBoundingClientRect().top - 20; }); await p.waitForTimeout(400); } },
  // novas
  { id: '37-carteira-ficha', url: '/carteira', then: async (p) => {
      await p.locator('tr[data-ficha]').first().click();
      await p.waitForSelector('#fichaPanelBody .pm-ficha', { timeout: 120000 }); await p.waitForTimeout(800); } },
  { id: '38-noticias-analise-ia', url: '/noticias' },
  { id: '39-definicoes-ia', url: '/definicoes', to: '#aiSettings', y: 110 },
];

(async () => {
  const b = await chromium.launch();
  const themes = MODE === 'ambos' ? ['claro', 'escuro'] : [MODE];
  for (const theme of themes) {
    const ctx = await b.newContext({ viewport: { width: 1900, height: 950 }, deviceScaleFactor: 1, locale: 'pt-PT', timezoneId: 'Europe/Lisbon' });
    await ctx.addInitScript((t) => { try { localStorage.setItem('pm-theme', t); localStorage.setItem('pm-collapsed', '0'); localStorage.removeItem('pm-ai-scope'); } catch (e) {} }, theme === 'escuro' ? 'dark' : 'light');
    await ctx.addCookies([{ name: 'pm_theme', value: theme === 'escuro' ? 'dark' : 'light', url: BASE }]);
    const p = await ctx.newPage();
    p.on('pageerror', (e) => console.log('  erro na página:', e.message));
    const dir = theme === 'escuro' ? `${OUT}/escuro` : OUT;
    fs.mkdirSync(dir, { recursive: true });
    for (const s of S) {
      if (ONLY && !s.id.includes(ONLY)) continue;
      await p.goto(BASE + s.url, { waitUntil: 'load' });
      await p.waitForTimeout(1500);  // gráficos (Chart.js) e dados vindos depois
      await p.addStyleTag({ content: '*, *::before, *::after { transition: none !important; animation: none !important; } .toast-container, #pmProgress { display: none !important; }' });
      if (s.to) {
        const el = s.to.startsWith('text=') ? p.locator(s.to).first() : p.locator(s.to).first();
        await el.evaluate((e, y) => window.scrollTo(0, window.scrollY + e.getBoundingClientRect().top - y), s.y ?? 110);
        await p.waitForTimeout(700);
      }
      if (s.then) await s.then(p);
      await p.mouse.move(1899, 949);
      await p.waitForTimeout(300);
      await p.screenshot({ path: `${dir}/${s.id}.png` });
      console.log(theme, s.id);
    }
    await ctx.close();
  }
  await b.close();
})();
