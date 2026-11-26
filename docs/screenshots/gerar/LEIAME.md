# Gerar as capturas do README

As capturas de `docs/screenshots` (e de `docs/screenshots/escuro`) geram-se com estes três ficheiros. Os dados
ficam numa pasta à parte, por isso os teus dados não são tocados.

| Ficheiro | O que faz |
| --- | --- |
| `preparar.py` | Prepara os dados: a demonstração, a triagem com dados reais do Yahoo Finance, as listas de acompanhamento com empresas reais e as notícias e a análise com IA de exemplo (fictícias, como as empresas). |
| `servir.py` | Arranca a aplicação com esses dados, numa porta à escolha. |
| `capturas.js` | Abre cada página no Chromium (Playwright), com 1900×950, desloca-a até à secção certa, abre o que for preciso (modais, menus, a ficha) e guarda a imagem, em claro e em escuro. |

Precisas do Python com as dependências da aplicação, do Node.js e do Playwright (`npm i playwright` e
`npx playwright install chromium`).

```bash
python docs/screenshots/gerar/preparar.py ~/capturas-dados              # demo, triagem, dados das ações e listas
python docs/screenshots/gerar/preparar.py ~/capturas-dados enrich       # se a triagem ainda tiver ações por completar
python docs/screenshots/gerar/preparar.py ~/capturas-dados extras       # notícias e análise com IA de exemplo
python docs/screenshots/gerar/preparar.py ~/capturas-dados fresh        # antes de cada série de capturas
python docs/screenshots/gerar/servir.py ~/capturas-dados 5089 &         # a aplicação, em http://localhost:5089
node docs/screenshots/gerar/capturas.js http://localhost:5089 docs/screenshots ambos
```

- A triagem demora: as pesquisas levam uns minutos e os dados de cada ação (cerca de 2700) uns 20 minutos, com
  pausas quando o Yahoo limita os pedidos. `enrich` continua de onde ficou.
- Para refazer só algumas capturas, junta um filtro no fim: `... docs/screenshots claro 17-prospecao`.
- Para juntar uma captura nova, acrescenta-a à lista `S` de `capturas.js` (o endereço, o elemento a pôr no topo e o
  que fazer antes) e ao README, nas duas tabelas.
- O `fresh` marca as notícias como pedidas há pouco, para a página Notícias não as pedir à rede durante as capturas
  (vale 1 hora).
