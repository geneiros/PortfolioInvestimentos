# Portfolio Investimentos

Gestor de carteira de investimentos local: desempenho, dividendos, fiscalidade (PT) e importação de extratos da Trading 212, XTB e Trade Republic. **Corre no teu computador**, com alertas de preço e lista de observação.

- **Sem servidor e sem base de dados para instalar.** Os dados ficam num único ficheiro SQLite no teu computador.
- **Abre-se com um duplo clique.** O script de arranque prepara tudo na primeira vez e abre o browser.
- **Interface Bootstrap 5.3 nativa**, com modo claro, escuro ou automático (segue o sistema operativo).

## Como usar

Precisas apenas do **Python 3.10 ou superior** ([python.org/downloads](https://www.python.org/downloads/); no Windows marca a opção *Add Python to PATH*).

1. Descarrega o projeto: botão **Code → Download ZIP** no GitHub, ou `git clone https://github.com/geneiros/PortfolioInvestimentos`.
2. Abre a pasta e inicia a aplicação:
   - **Windows:** duplo clique em `iniciar.bat`
   - **macOS:** duplo clique em `iniciar.command`
   - **Linux:** `./iniciar.sh`
3. O browser abre em `http://127.0.0.1:5000`. Para terminar, fecha a janela do terminal.

Na primeira vez, o script cria um ambiente Python (`.venv`) na pasta do projeto e instala as dependências. Isto demora um ou dois minutos. Nas vezes seguintes arranca de imediato.

Para experimentar sem os teus dados, clica em **Ver demonstração**. São carregadas empresas fictícias com preços sintéticos, e depois podes apagá-las em Definições.

### Instalar como aplicação (PWA)

No **Chrome** ou no **Edge**, com a aplicação aberta em `http://127.0.0.1:5000`, carrega no ícone de instalar na barra de endereço (ou **Menu → Instalar Portfolio Investimentos**). A aplicação passa a abrir na sua própria janela, com ícone no menu Iniciar, na barra de tarefas ou na Dock, e atalhos para Carteira, Desempenho e Importar.

- A janela instalada é uma porta para a aplicação local, por isso o servidor tem de estar a correr (`iniciar.bat`, `iniciar.command` ou `./iniciar.sh`). Se não estiver, a janela mostra como o iniciar e volta sozinha quando ele arrancar.
- Para o servidor não abrir também um separador no browser, arranca com `python -m portfolio_investimentos --no-browser`.
- Usa sempre a mesma porta: a aplicação instalada fica associada a `127.0.0.1:5000`.
- Só os ficheiros estáticos (Bootstrap, ícones) ficam em cache. Os teus dados financeiros nunca ficam guardados pelo browser.
- Noutros dispositivos da rede (`--host 0.0.0.0`), o browser só permite instalar através de HTTPS.

### Android (Termux)

A aplicação também corre no telemóvel, dentro do [Termux](https://f-droid.org/packages/com.termux/). Instala-o a partir do F-Droid ou do GitHub: a versão da Play Store está desatualizada.

```bash
pkg install git
git clone https://github.com/geneiros/PortfolioInvestimentos
cd PortfolioInvestimentos
bash iniciar-android.sh               # na primeira vez instala o Python e as dependências
bash iniciar-android.sh --atualizar   # descarrega a versão mais recente e arranca
```

**Importar extratos no telemóvel:** o seletor de ficheiros do browser pode levar o Android a suspender o Termux (o que aparece como "Sem ligação à aplicação"). Em alternativa, importa diretamente no Termux. Descarrega os extratos para as Transferências e corre:

```bash
termux-setup-storage                                   # só na primeira vez: dá acesso às Transferências
bash iniciar-android.sh --importar ~/storage/downloads/EUR_*.xlsx ~/storage/downloads/from_*.csv
```

A corretora é detetada pelo conteúdo do ficheiro (XTB, Trading 212, Trade Republic ou CSV genérico). Também funciona no computador: `python -m portfolio_investimentos --importar ficheiro.csv`.

O script abre a aplicação no browser do telemóvel. No Chrome, **menu ⋮ → Adicionar ao ecrã principal** para a abrires como uma aplicação. Enquanto está aberta, o Termux fica acordado (`termux-wake-lock`). Para terminar, carrega em Ctrl+C no Termux.

- O `yfinance` não instala no Android (a dependência `curl_cffi` não suporta estes processadores). Sem ele, **Definições → Atualizar cotações agora** vai buscar as cotações, os câmbios e as notícias diretamente ao Yahoo Finance, só com a biblioteca padrão do Python. Os eventos (datas de resultados e de dividendos) e o setor dos ativos só vêm com o `yfinance`.
- Se aparecer "Sem cotações do Yahoo Finance", vê o motivo em **Definições → Resultado por ativo**, ou testa a ligação no Termux com `bash iniciar-android.sh --testar-yahoo`.
- Os dados do telemóvel e do computador são independentes. Se preferires uma só cópia, corre a aplicação no computador com `--host 0.0.0.0` e palavra-passe, e abre-a no telemóvel.

### Onde ficam os dados

| Sistema | Pasta |
| --- | --- |
| Windows | `%APPDATA%\PortfolioInvestimentos\portfolio.db` (a pasta `PortfolioManager` das versões anteriores muda de nome sozinha) |
| macOS / Linux | `~/.portfolio-investimentos/portfolio.db` (a pasta `~/.portfolio-manager` das versões anteriores muda de nome sozinha) |

Podes escolher outra pasta com a variável `PORTFOLIO_DATA_DIR` (por exemplo, uma pasta sincronizada com a cloud). Em **Definições** há botões para descarregar uma cópia de segurança (`.db`), exportar as transações em CSV e apagar todos os dados.

A aplicação só aceita ligações do próprio computador (`127.0.0.1`), e as ações estão protegidas contra pedidos de outros sites abertos no browser.

### Palavra-passe e acesso a partir de outros dispositivos

Em **Definições → Segurança** podes definir uma palavra-passe. A partir daí, a aplicação pede-a para entrar, e o botão **Sair** fica no fundo da barra lateral. A sessão dura 30 dias.

- **Sem palavra-passe**, a aplicação só abre no computador onde corre. Qualquer acesso de outro dispositivo, ou através de um proxy, mostra uma página a pedir que definas a palavra-passe primeiro.
- **Para abrir na rede local** (ex.: no telemóvel): define a palavra-passe e arranca com `python -m portfolio_investimentos --host 0.0.0.0`.
- **Num servidor ou na cloud**: usa `wsgi.py` (ex.: `gunicorn wsgi:app`) e define a palavra-passe na variável de ambiente `PORTFOLIO_PASSWORD`. Se o site usar HTTPS, define também `PORTFOLIO_HTTPS=1`, para o cookie de sessão só seguir por ligações cifradas.
- Ao mudar a palavra-passe, as sessões abertas noutros dispositivos terminam. Depois de 5 tentativas erradas, o login fica bloqueado durante 5 minutos.

### Opções da linha de comandos

```bash
python -m portfolio_investimentos              # inicia e abre o browser
python -m portfolio_investimentos --port 8080  # usa outra porta
python -m portfolio_investimentos --host 0.0.0.0 # abre na rede local (exige palavra-passe)
python -m portfolio_investimentos --no-browser # não abre o browser
python -m portfolio_investimentos --demo       # carrega os dados de demonstração e sai
python -m portfolio_investimentos --refresh    # atualiza as cotações e sai
python -m portfolio_investimentos --importar extrato.xlsx  # importa extratos (corretora detetada) e sai
python -m portfolio_investimentos --testar-yahoo  # testa a ligação ao Yahoo Finance e sai
```

## Capturas de ecrã

As capturas usam os dados de demonstração.

### Modo claro

| Visão Geral | Evolução e próximos eventos |
| --- | --- |
| ![Visão Geral](docs/screenshots/01-visao-geral.png) | ![Evolução](docs/screenshots/02-visao-geral-evolucao.png) |
| **Carteira** | **Alocação** |
| ![Carteira](docs/screenshots/03-carteira.png) | ![Alocação](docs/screenshots/04-carteira-alocacao.png) |
| **Desempenho** | **Como foi a jornada** |
| ![Desempenho](docs/screenshots/05-desempenho.png) | ![Jornada](docs/screenshots/06-desempenho-jornada.png) |
| **Retornos mensais** | **Mérito vs mercado** |
| ![Retornos mensais](docs/screenshots/07-desempenho-mensal.png) | ![Mérito](docs/screenshots/08-desempenho-merito.png) |
| **Risco e análise avançada** | **Dividendos** |
| ![Risco](docs/screenshots/09-desempenho-risco.png) | ![Dividendos](docs/screenshots/10-dividendos.png) |
| **Mapa de rendimento** | **Fiscal** |
| ![Mapa de dividendos](docs/screenshots/11-dividendos-mapa.png) | ![Fiscal](docs/screenshots/12-fiscal.png) |
| **Radar e alertas** | **Importar extrato** |
| ![Radar](docs/screenshots/13-radar.png) | ![Importar](docs/screenshots/14-importar.png) |
| **Transações** | **Definições** |
| ![Transações](docs/screenshots/15-transacoes.png) | ![Definições](docs/screenshots/16-definicoes.png) |

### Modo escuro

| Visão Geral | Carteira |
| --- | --- |
| ![Visão Geral (escuro)](docs/screenshots/escuro/01-visao-geral.png) | ![Carteira (escuro)](docs/screenshots/escuro/02-carteira.png) |
| **Desempenho** | **Retornos mensais** |
| ![Desempenho (escuro)](docs/screenshots/escuro/03-desempenho.png) | ![Retornos mensais (escuro)](docs/screenshots/escuro/04-desempenho-mensal.png) |
| **Dividendos** | **Importar extrato** |
| ![Dividendos (escuro)](docs/screenshots/escuro/05-dividendos.png) | ![Importar (escuro)](docs/screenshots/escuro/06-importar.png) |

O tema escolhe-se no botão **Tema**, no fundo da barra lateral: Claro, Escuro ou Automático.

## Funcionalidades

| Página | O que mostra |
| --- | --- |
| **Visão Geral** | Valor da carteira, variação diária, retorno total e do ano corrente; máximo histórico (carteira ou retorno); principais movers com notícias; resultados (não realizado, realizado, dividendos, comissões) e conta (custo base, depositado, caixa, juros); gráfico de evolução com períodos (1M a Máx) e comparação com S&P 500, Nasdaq 100 e MSCI World; próximos eventos (resultados, ex-dividendo, pagamentos estimados). |
| **Carteira** | Posições abertas/fechadas, carteira vs mercado no dia, filtros por setor, pesquisa, tabela ordenável (preço, 1D, preço médio, investido, valor, não realizado, dividendos, efeito cambial, comissões, ROI, peso) e alocação por ativo, setor e moeda. |
| **Desempenho** | Retorno total e IRR, TWR e CAGR vs índice, melhor/pior ano e mês, sequência atual; TWR anual e acumulado; drawdown; mapa de retornos mensais; mérito vs mercado (captura em alta/baixa, beta, % de meses acima do mercado); risco (Sharpe, Sortino, Calmar, volatilidade, max drawdown); alfa de Jensen e distribuição mensal ordenada. |
| **Dividendos** | Recebido líquido/bruto e retenção na fonte, maior pagador, meses com dividendos, rendimento anualizado, projeção do ano e dos próximos 12 meses, crescimento anual, dividendos por ano, decomposição do crescimento, mapa mensal, yield on cost e histórico. |
| **Fiscal** | Por ano: mais-valias pelo método FIFO (linha a linha, exportáveis em CSV), dividendos, juros e estimativa de imposto a 28% (Portugal). |
| **Radar e alertas** | Alertas de preço (acima, abaixo, variação diária) e lista de observação com preço-alvo. |
| **Notícias** | Notícias dos ativos em carteira. |
| **Importar** | Extratos da Trading 212 (CSV), XTB (XLSX), Trade Republic (CSV) e CSV genérico, com deduplicação (podes carregar o mesmo ficheiro várias vezes) e histórico de extratos. |
| **Transações** | Lista filtrável, inserção manual e exportação CSV. |
| **Definições** | Corretoras, ativos (setor, símbolo de dados, cor), atualização de cotações, cópia de segurança, demonstração e limpeza de dados. |

Também há um seletor de corretora (todas ou uma conta específica) e um botão com um olho que esconde os valores.

### Cotações e notícias

As cotações, câmbios, notícias e eventos vêm do Yahoo Finance através do pacote `yfinance`, instalado pelos scripts de arranque. Onde o `yfinance` não pode ser instalado (ex.: Android), a aplicação vai buscar as cotações, os câmbios e as notícias diretamente ao Yahoo. Para atualizar, usa **Definições → Atualizar cotações agora**, que precisa de internet. Confirma em **Definições → Ativos** o *símbolo de dados* de cada ativo (código do Yahoo Finance, ex.: `VWCE.DE`, `IWDA.AS`, `AAPL`).

O símbolo é escolhido automaticamente pelo ISIN e pelo ticker. Só é aceite um símbolo cotado na moeda do ativo e com preços perto dos das transações. Assim, uma ação americana comprada em euros (ex.: Apple na Xetra, `APC.DE`) não fica com a cotação em dólares, e as cotações de Londres em pence são convertidas para libras.

## Importação: Trading 212

Na Trading 212: **Histórico → Exportar**, com todos os tipos de dados ligados. A Trading 212 só exporta um ano de cada vez, por isso exporta cada ano desde a primeira transação e carrega todos os ficheiros de uma vez. As linhas repetidas são ignoradas.

O importador trata:

- compras/vendas (mercado e limite), com todas as comissões e impostos de bolsa convertidos para a moeda do ativo;
- dividendos (valor líquido e retenção na fonte), juros da conta e juros de empréstimo de ações;
- depósitos, levantamentos e pagamentos com o cartão;
- transferências de ações para outra corretora (saem sem gerar mais-valia), spin-offs, comissões ADR e de conversão de moeda;
- ações em GBX (convertidas para GBP), USD, CAD e EUR, e a subconta em USD.

O próprio extrato serve para obter câmbios e preços. Assim os gráficos funcionam sem internet, e a atualização de cotações substitui esses valores pelos fechos reais.

Se o extrato não incluir os anos anteriores, as vendas de ações compradas antes desse período usam o resultado indicado pela Trading 212 para estimar o custo. A aplicação mostra um aviso a pedir os extratos em falta. As mais-valias são calculadas pelo método FIFO (o usado no IRS), por isso podem diferir ligeiramente do "Result" da Trading 212, que usa o custo médio.

## Importação: XTB

Na XTB (xStation): **Histórico da conta → Exportar** para Excel (`.xlsx`). O importador lê as folhas de posições fechadas, posições abertas e operações de caixa:

- compras e vendas com o preço efetivo e as comissões;
- dividendos com retenção, juros, comissões e transferências entre subcontas (ignoradas, por não serem fluxos externos);
- ações recebidas de outra corretora (entram ao preço indicado, sem gerar depósito);
- o preço atual das posições abertas serve de cotação na data do relatório;
- os símbolos da XTB (ex.: `VUAA.UK` → `VUAA.L`, `AAPL.US` → `AAPL`) são convertidos para o símbolo do Yahoo Finance.

## Importação: Trade Republic

Na Trade Republic: **Perfil → Atividade → Exportar** para CSV. O importador trata compras, vendas, dividendos (com retenção), juros, depósitos, levantamentos, pagamentos com o cartão e comissões. As restantes linhas são ignoradas e contadas no resumo da importação.

A Trade Republic identifica os ativos pelo ISIN. Se o mesmo ISIN já existir noutra corretora, a aplicação usa o mesmo ativo, de modo que a carteira consolidada soma as posições. Os ativos que só existem na Trade Republic ficam com o ISIN como símbolo. Ao atualizar as cotações, a aplicação procura o símbolo do Yahoo Finance pelo ISIN; se não o encontrar, podes defini-lo em **Definições → Ativos**.

## Valores comparados com as corretoras

O valor da carteira usa o último fecho disponível de cada ativo. Sem internet, é o preço da última transação ou do extrato, por isso o total fica próximo, mas não igual, ao que a corretora mostra. **Definições → Atualizar cotações agora** aproxima os valores.

## Importação: formato CSV genérico

```
date,type,ticker,quantity,price,amount,fees,tax,currency,name
2024-01-02,DEPOSIT,,,,1000,,,EUR,
2024-01-03,BUY,VWCE.DE,5,110.20,,1.00,,EUR,Vanguard FTSE All-World
2024-03-20,DIVIDEND,VWCE.DE,5,,3.10,0.87,,EUR,
```

Tipos aceites: `BUY`, `SELL`, `DIVIDEND`, `DEPOSIT`, `WITHDRAWAL`, `FEE`, `INTEREST`, `TRANSFER_IN`, `TRANSFER_OUT`, `CONVERT_IN`, `CONVERT_OUT` (também em português: compra, venda, dividendo, depósito, levantamento, comissão, juros).

## Como são feitos os cálculos

- **Moeda base EUR.** Cada transação é convertida à taxa de câmbio do próprio dia.
- **Custo FIFO** com comissões incluídas; as vendas consomem os lotes mais antigos. É também o método usado no IRS.
- **Depósitos implícitos:** se uma compra não tiver dinheiro em caixa, o valor em falta conta como depósito. Assim, quem só importa compras e vendas continua a ter retornos corretos.
- **TWR** encadeia os retornos diários, descontando os fluxos externos. **IRR** é a XIRR dos depósitos e levantamentos mais o valor final.

## Estrutura

```
portfolio_investimentos/
├── engine/        # motor de cálculo em Python puro (FIFO, TWR, IRR, risco, dividendos, fiscal)
├── services/      # ligação à base de dados, importação, mercado (yfinance ou acesso direto ao Yahoo), demonstração
├── templates/     # páginas Jinja + Bootstrap 5.3
├── static/        # CSS/JS da app e bibliotecas (Bootstrap, Bootstrap Icons, Chart.js), sem CDN
├── models.py      # tabelas SQLite (SQLAlchemy)
├── views.py       # páginas
├── api.py         # ações chamadas pelas páginas
└── __main__.py    # arranque local
tests/             # testes do motor e da aplicação
iniciar.bat | iniciar.command | iniciar.sh
```

## Desenvolvimento

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt pytest
python -m pytest tests
python -m portfolio_investimentos
```

## Próximos passos

- Parsers para DEGIRO, IBKR, Revolut e eToro.
- Planeamento (objetivos, simulação de contribuições) e Análise (sobreposição de ETFs, exposição geográfica).
- Executável único (PyInstaller) para quem não quer instalar o Python.

## Licença

[Apache License 2.0](LICENSE) © 2026 Helder Meneses.

Podes usar, copiar, alterar e distribuir este software, incluindo para fins comerciais, desde que:

- mantenhas o nome do autor, os avisos de direitos de autor e o ficheiro [NOTICE](NOTICE) em todas as cópias e versões alteradas;
- incluas uma cópia da licença;
- assinales os ficheiros que alteraste.

O software é fornecido "tal como está", sem garantias.
