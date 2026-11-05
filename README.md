# Portfolio Investimentos

[![Testes](https://github.com/geneiros/PortfolioInvestimentos/actions/workflows/testes.yml/badge.svg)](https://github.com/geneiros/PortfolioInvestimentos/actions/workflows/testes.yml) [![Buy Me a Coffee](https://img.shields.io/badge/Buy%20Me%20a%20Coffee-ffdd00?logo=buymeacoffee&logoColor=black)](https://buymeacoffee.com/geneiros)

Gestor de carteira de investimentos local: desempenho, dividendos, fiscalidade (PT) e importação de extratos da Trading 212, XTB e Trade Republic. **Corre no teu computador**, com alertas de preço e lista de observação.

- **Sem servidor e sem base de dados para instalar.** Os dados ficam num único ficheiro SQLite no teu computador.
- **Abre-se com um duplo clique.** O script de arranque prepara tudo na primeira vez e abre o browser.
- **Interface Bootstrap 5.3 nativa**, com modo claro, escuro ou automático (segue o sistema operativo).
- **Cartões à tua medida:** em todas as páginas, um clique longo (2 segundos no fundo de um cartão, com o rato ou o dedo) levanta o cartão para o arrastar para outro lugar; a ordem fica guardada na aplicação, igual em todos os dispositivos, e repõe-se em Definições.
- **Esconder valores** (botão do olho, no topo): cada valor em euros passa a «€ ••••», na cor do valor, em todas as páginas; o botão fica selecionado enquanto o modo está ligado e a escolha fica guardada no dispositivo.

## Como usar

Precisas apenas do **Python 3.10 ou superior** ([python.org/downloads](https://www.python.org/downloads/); no Windows marca a opção *Add Python to PATH*).

1. Descarrega o projeto: botão **Code → Download ZIP** no GitHub, ou `git clone https://github.com/geneiros/PortfolioInvestimentos`.
2. Abre a pasta e inicia a aplicação:
   - **Windows:** duplo clique em `iniciar.bat`
   - **macOS:** duplo clique em `iniciar.command`
   - **Linux:** `./iniciar.sh`
3. O browser abre em `http://127.0.0.1:5000`. Para terminar, fecha a janela do terminal.

Se instalaste com `git clone`, o `iniciar.bat` verifica a cada arranque se há uma versão nova e pergunta se queres atualizar. Sem resposta em 10 segundos atualiza (responde N para não atualizar); sem internet, arranca a versão atual. Os teus dados não são afetados, porque ficam fora da pasta do projeto.

Na primeira vez, o script cria um ambiente Python (`.venv`) na pasta do projeto e instala as dependências. Isto demora um ou dois minutos. Nas vezes seguintes arranca de imediato.

Para experimentar sem os teus dados, clica em **Ver demonstração**. São carregadas empresas fictícias com preços sintéticos, e depois podes apagá-las em Definições.

### Instalar como aplicação (PWA)

No **Chrome** ou no **Edge**, com a aplicação aberta em `http://127.0.0.1:5000`, carrega no ícone de instalar na barra de endereço (ou **Menu → Instalar Portfolio Investimentos**). A aplicação passa a abrir na sua própria janela, com ícone no menu Iniciar, na barra de tarefas ou na Dock, e atalhos para Carteira, Desempenho e Importar.

- A janela instalada é uma porta para a aplicação local, por isso o servidor tem de estar a correr (`iniciar.bat`, `iniciar.command` ou `./iniciar.sh`). Se não estiver, a janela mostra como o iniciar e volta sozinha quando ele arrancar (ver também **Disponível offline**, abaixo).
- Para o servidor não abrir também um separador no browser, arranca com `python -m portfolio_investimentos --no-browser`.
- Usa sempre a mesma porta: a aplicação instalada fica associada a `127.0.0.1:5000`.
- A barra do sistema em cima tem a cor do fundo da aplicação e acompanha o tema (claro ou escuro). No Android, a barra de navegação em baixo usa a cor do manifesto, gravada na instalação: escura (e, nas versões do Chrome que o suportam, clara com o telemóvel em modo claro). Depois de atualizar a aplicação, reinstala-a para a cor nova ser aplicada.
- Por omissão, só os ficheiros estáticos (Bootstrap, ícones) ficam em cache e os teus dados financeiros não ficam guardados pelo browser.
- Noutros dispositivos da rede (`--host 0.0.0.0`), o browser só permite instalar através de HTTPS.

#### Disponível offline

Para consultar os últimos dados com a aplicação parada (por exemplo, com o Termux ou o computador desligados), liga **Definições → Disponível offline**. A partir daí, as páginas de consulta (Visão Geral, Carteira, Desempenho, Dividendos, Fiscal, Radar e Transações) ficam guardadas no browser tal como estavam da última vez que as abriste. A cópia é renovada de 30 em 30 minutos enquanto a aplicação está aberta, ou quando carregas em **Guardar cópia agora**.

- Sem a aplicação a correr, aparece a faixa "Modo offline", com a data dos dados. A página recarrega sozinha quando a aplicação voltar.
- Funciona só para consulta. Importar, editar, atualizar cotações e mudar de corretora precisam da aplicação a correr.
- A cópia mostra a corretora que estava selecionada quando foi guardada.
- Privacidade: quem tiver acesso ao dispositivo pode ver os valores guardados, mesmo com palavra-passe. Desligar a opção ou sair (**Sair**) apaga a cópia.

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

- O `yfinance` não instala no Android (a dependência `curl_cffi` não suporta estes processadores). Sem ele, **Definições → Atualizar cotações agora** vai buscar as cotações e os câmbios diretamente ao Yahoo Finance, só com a biblioteca padrão do Python. Os eventos (datas de resultados e de dividendos) e o setor dos ativos só vêm com o `yfinance`.
- Se aparecer "Sem cotações do Yahoo Finance", vê o motivo em **Definições → Resultado por ativo**, ou testa a ligação no Termux com `bash iniciar-android.sh --testar-yahoo`.
- Os dados do telemóvel e do computador são independentes. Se preferires uma só cópia, corre a aplicação no computador com `--host 0.0.0.0` e palavra-passe, e abre-a no telemóvel.

### Onde ficam os dados

| Sistema | Pasta |
| --- | --- |
| Windows | `%APPDATA%\PortfolioInvestimentos\portfolio.db` (a pasta `PortfolioManager` das versões anteriores muda de nome sozinha) |
| macOS / Linux | `~/.portfolio-investimentos/portfolio.db` (a pasta `~/.portfolio-manager` das versões anteriores muda de nome sozinha) |

Podes escolher outra pasta com a variável `PORTFOLIO_DATA_DIR` (por exemplo, uma pasta sincronizada com a cloud). Em **Definições** há botões para descarregar uma cópia de segurança (`.db`), exportar as transações em CSV e apagar todos os dados.

**Cópias automáticas.** Antes de importar um extrato, apagar dados, carregar a demonstração, apagar uma importação ou atualizar a estrutura da base de dados (numa versão nova), a aplicação guarda uma cópia na pasta `copias`, ao lado da base de dados, e mantém só as últimas 2 (a mais antiga é apagada quando se faz uma nova). Em **Definições → Os teus dados → Cópias automáticas** vês a lista e podes **Restaurar** uma delas (antes de restaurar fica também uma cópia do estado atual, sem apagar a que restauras), **Eliminar** uma cópia ou criar uma cópia à hora. Não se fazem cópias quando só há dados de demonstração.

**Versão da estrutura da base de dados.** A base de dados guarda a versão da sua estrutura (`PRAGMA user_version`). Ao abrir uma versão nova da aplicação, os passos de migração pendentes (`portfolio_investimentos/migrations.py`) correm um a um, cada um numa transação; se um falhar, a base fica como estava e a mensagem diz onde está a cópia. Uma base de uma versão mais recente do que a aplicação não é aberta.

A aplicação só aceita ligações do próprio computador (`127.0.0.1`), e as ações estão protegidas contra pedidos de outros sites abertos no browser.

### Palavra-passe e acesso a partir de outros dispositivos

Em **Definições → Segurança** podes definir uma palavra-passe. A partir daí, a aplicação pede-a para entrar, e o botão **Sair** fica no fundo da barra lateral. A sessão dura 30 dias.

- **Sem palavra-passe**, a aplicação só abre no computador onde corre. Qualquer acesso de outro dispositivo, ou através de um proxy, mostra uma página a pedir que definas a palavra-passe primeiro.
- **Para abrir na rede local** (ex.: no telemóvel): define a palavra-passe e arranca com `python -m portfolio_investimentos --host 0.0.0.0`.
- **Num servidor ou na cloud**: usa `wsgi.py` (ex.: `gunicorn wsgi:app`) e define a palavra-passe na variável de ambiente `PORTFOLIO_PASSWORD`. Se o site usar HTTPS, define também `PORTFOLIO_HTTPS=1`, para o cookie de sessão só seguir por ligações cifradas.
- **Atrás de um proxy** (PythonAnywhere, nginx, Caddy…): define também `PORTFOLIO_PROXY=1` (o número de proxies à frente da aplicação). Assim o endereço de cada pedido é o do visitante e não o do proxy, e o limite de tentativas de login vale por visitante. Sem ela, todos os visitantes parecem vir do mesmo endereço, e as tentativas erradas de alguém bloqueiam também o teu acesso. Não a definas sem proxy: os cabeçalhos `X-Forwarded-For` podiam ser falsificados.
- Ao mudar a palavra-passe, as sessões abertas noutros dispositivos terminam. Depois de 5 tentativas erradas do mesmo endereço, o login (e a palavra-passe atual pedida em Definições) fica bloqueado para esse endereço durante 5 minutos. As tentativas ficam guardadas na base de dados, por isso valem entre processos e depois de reiniciar.

### Opções da linha de comandos

```bash
python -m portfolio_investimentos              # inicia e abre o browser
python -m portfolio_investimentos --port 8080  # usa outra porta
python -m portfolio_investimentos --host 0.0.0.0 # abre na rede local (exige palavra-passe)
python -m portfolio_investimentos --no-browser # não abre o browser
python -m portfolio_investimentos --demo       # carrega os dados de demonstração e sai
python -m portfolio_investimentos --refresh    # atualiza as cotações e sai
python -m portfolio_investimentos --importar extrato.xlsx  # importa extratos (corretora detetada) e sai
python -m portfolio_investimentos --testar-yahoo  # testa a ligação ao Yahoo Finance (cotações e dados fundamentais) e sai
```

O que mudou em cada versão está no [histórico de alterações](CHANGELOG.md).

## Capturas de ecrã

As capturas usam os dados de demonstração (empresas e preços fictícios).

### Modo claro

| Visão Geral | Evolução, as minhas posições e próximos eventos |
| --- | --- |
| ![Visão Geral](docs/screenshots/01-visao-geral.png) | ![Evolução](docs/screenshots/02-visao-geral-evolucao.png) |
| **Peso vs retorno e alocação** | **Perfil de investidor** |
| ![Peso vs retorno e alocação](docs/screenshots/03-visao-geral-peso-alocacao.png) | ![Perfil de investidor](docs/screenshots/04-perfil-investidor.png) |
| **Carteira** | **Alocação** |
| ![Carteira](docs/screenshots/05-carteira.png) | ![Alocação](docs/screenshots/06-carteira-alocacao.png) |
| **Desempenho** | **Como foi a jornada** |
| ![Desempenho](docs/screenshots/07-desempenho.png) | ![Jornada](docs/screenshots/08-desempenho-jornada.png) |
| **Retornos mensais** | **Mérito vs mercado** |
| ![Retornos mensais](docs/screenshots/09-desempenho-mensal.png) | ![Mérito](docs/screenshots/10-desempenho-merito.png) |
| **Risco e análise avançada** | **Dividendos** |
| ![Risco](docs/screenshots/11-desempenho-risco.png) | ![Dividendos](docs/screenshots/12-dividendos.png) |
| **Mapa de rendimento e datas ex-dividendo** | **Fiscal** |
| ![Mapa de dividendos](docs/screenshots/13-dividendos-mapa.png) | ![Fiscal](docs/screenshots/14-fiscal.png) |
| **Planeamento (FIRE)** | **Evolução e projeção** |
| ![Planeamento](docs/screenshots/15-planeamento.png) | ![Projeção](docs/screenshots/16-planeamento-projecao.png) |
| **Radar e alertas** | **Importar extrato** |
| ![Radar](docs/screenshots/17-radar.png) | ![Importar](docs/screenshots/18-importar.png) |
| **Transações** | **Definições** |
| ![Transações](docs/screenshots/19-transacoes.png) | ![Definições](docs/screenshots/20-definicoes.png) |
| **Património** | **Carteira: as crises e os custos** |
| ![Património](docs/screenshots/21-patrimonio.png) | ![Crises e custos](docs/screenshots/22-carteira-crises-custos.png) |
| **Património: de onde veio o crescimento** | **Carteira: o valor de cada ação** |
| ![Crescimento](docs/screenshots/23-patrimonio-crescimento.png) | ![Valor de cada ação](docs/screenshots/24-carteira-valor-acoes.png) |

### Modo escuro

| Visão Geral | Evolução, as minhas posições e próximos eventos |
| --- | --- |
| ![Visão Geral (escuro)](docs/screenshots/escuro/01-visao-geral.png) | ![Evolução (escuro)](docs/screenshots/escuro/02-visao-geral-evolucao.png) |
| **Peso vs retorno e alocação** | **Perfil de investidor** |
| ![Peso vs retorno e alocação (escuro)](docs/screenshots/escuro/03-visao-geral-peso-alocacao.png) | ![Perfil de investidor (escuro)](docs/screenshots/escuro/04-perfil-investidor.png) |
| **Carteira** | **Alocação** |
| ![Carteira (escuro)](docs/screenshots/escuro/05-carteira.png) | ![Alocação (escuro)](docs/screenshots/escuro/06-carteira-alocacao.png) |
| **Desempenho** | **Como foi a jornada** |
| ![Desempenho (escuro)](docs/screenshots/escuro/07-desempenho.png) | ![Jornada (escuro)](docs/screenshots/escuro/08-desempenho-jornada.png) |
| **Retornos mensais** | **Mérito vs mercado** |
| ![Retornos mensais (escuro)](docs/screenshots/escuro/09-desempenho-mensal.png) | ![Mérito (escuro)](docs/screenshots/escuro/10-desempenho-merito.png) |
| **Risco e análise avançada** | **Dividendos** |
| ![Risco (escuro)](docs/screenshots/escuro/11-desempenho-risco.png) | ![Dividendos (escuro)](docs/screenshots/escuro/12-dividendos.png) |
| **Mapa de rendimento e datas ex-dividendo** | **Fiscal** |
| ![Mapa de dividendos (escuro)](docs/screenshots/escuro/13-dividendos-mapa.png) | ![Fiscal (escuro)](docs/screenshots/escuro/14-fiscal.png) |
| **Planeamento (FIRE)** | **Evolução e projeção** |
| ![Planeamento (escuro)](docs/screenshots/escuro/15-planeamento.png) | ![Projeção (escuro)](docs/screenshots/escuro/16-planeamento-projecao.png) |
| **Radar e alertas** | **Importar extrato** |
| ![Radar (escuro)](docs/screenshots/escuro/17-radar.png) | ![Importar (escuro)](docs/screenshots/escuro/18-importar.png) |
| **Transações** | **Definições** |
| ![Transações (escuro)](docs/screenshots/escuro/19-transacoes.png) | ![Definições (escuro)](docs/screenshots/escuro/20-definicoes.png) |
| **Património** | **Carteira: as crises e os custos** |
| ![Património (escuro)](docs/screenshots/escuro/21-patrimonio.png) | ![Crises e custos (escuro)](docs/screenshots/escuro/22-carteira-crises-custos.png) |
| **Património: de onde veio o crescimento** | **Carteira: o valor de cada ação** |
| ![Crescimento (escuro)](docs/screenshots/escuro/23-patrimonio-crescimento.png) | ![Valor de cada ação (escuro)](docs/screenshots/escuro/24-carteira-valor-acoes.png) |

O tema escolhe-se no botão **Tema**, no fundo da barra lateral: Claro, Escuro ou Automático.

## Funcionalidades

| Página | O que mostra |
| --- | --- |
| **Visão Geral** | Valor da carteira, variação diária, retorno total e do ano corrente, e no mesmo cartão os resultados (não realizado, dividendos, realizado, comissões) e a conta (custo base, depositado, caixa, valor total, juros). **Perfil de investidor**: Investor Score e Portfolio Score (0-100, últimos 3 anos) com seis perfis (Passive Index, Concentrated Picker, Diversified Active, Income Focus, Growth/Tech, Active Trader), o perfil sugerido pela carteira e a fórmula de cada métrica no «?». Gráfico de evolução (retorno ou valor, 1M a Máx; abre no ano corrente) com comparação com S&P 500, Nasdaq 100 e MSCI World e **as minhas posições** (as 5 com maior ganho ou perda e as restantes somadas, ligado por omissão), a toda a largura. Principais movers do dia (até 8), com o nome, o preço e um gráfico do último ano que ocupa a largura da linha, verde acima do teu preço médio de aquisição (tracejado) e vermelho abaixo, com a data, o preço e a diferença para o preço médio ao passar o rato. Próximos eventos dos próximos 90 dias (resultados, com o intervalo quando ainda é estimado, ex-dividendo e pagamentos). **Peso vs retorno** (mapa e bolhas) e **alocação** por setor, geografia, classe e corretora. |
| **Carteira** | Posições abertas/fechadas, carteira vs mercado no dia, filtros por setor, pesquisa, tabela ordenável (preço, 1D, preço médio, investido, valor, não realizado, dividendos, efeito cambial, comissões, ROI, peso) e alocação por ativo, setor e moeda. «As crises»: quanto cairia a carteira de hoje se 2008, 2011, 2020 ou 2022 se repetissem (beta de cada posição face ao S&P 500) e quanto tempo levava a recuperar. «Os custos»: comissões, custo dos ETF (TER, indicado por ti) e retenções na fonte acima dos 15% da convenção, por ano e daqui a 20 anos. «O valor de cada ação»: por ordem de popularidade, DCF, Número de Graham, fórmula de crescimento de Graham (com o rendimento das obrigações AAA configurável) e modelo de Gordon, e em «Mais métodos» Owner Earnings (Buffett), Earnings Power Value (Greenwald), Bazin e o PEG de Peter Lynch, sempre em intervalo e com a fórmula e os números no «?», comparados com o preço, e o crescimento que o preço de hoje já assume; dados fundamentais do Yahoo (uma vez por semana, na atualização de cotações; se o pedido principal falhar, a partir das demonstrações financeiras, também da cotação principal pelo ISIN, convertidos para a moeda da cotação), que podes corrigir. «Carteira cerne»: três ETF com pesos alvo (por omissão ERNX 45% · FWIA 30% · XEON 25%); quando o ETF de crescimento cai face ao máximo, a mistura alvo passa ao escalão seguinte (40/35/25, 35/40/25, 30/50/20, 25/60/15, 20/70/10), a cada 10% de queda (configurável em Definições), e mantém-se quando ele recupera até voltares à base; com os pesos atuais, o desvio, as ordens em € e unidades (ou só a distribuição do dinheiro novo, sem vender), o retorno esperado, a volatilidade e o pior ano típico de cada escalão, e uma faixa no topo quando se chega a um escalão novo. |
| **Desempenho** | Retorno total e IRR, TWR e CAGR vs índice, melhor/pior ano e mês, sequência atual; TWR anual e acumulado; drawdown; mapa de retornos mensais; mérito vs mercado (captura em alta/baixa, beta, % de meses acima do mercado); risco (Sharpe, Sortino, Calmar, volatilidade, max drawdown); alfa de Jensen e distribuição mensal ordenada. |
| **Dividendos** | Recebido líquido/bruto e retenção na fonte, maior pagador, meses com dividendos, rendimento anualizado, crescimento anual. **Projeção** do ano e dos próximos 12 meses com os dividendos recebidos e, para posições recentes, os dividendos por ação do Yahoo, com a origem de cada valor. Dividendos por ano, decomposição do crescimento, **mapa mensal com a linha do próximo ano**, **datas ex-dividendo** (recebido, a receber, sem direito por ter comprado depois, previsto), yield on cost e histórico. |
| **Património** | A carteira das corretoras mais os outros ativos e dívidas que indicas à mão (contas à ordem, depósitos a prazo, certificados, PPR, imóveis, outros, créditos), separados por camadas de liquidez (imediata, curto prazo, ilíquido) e nunca somados num único total: património líquido total e património líquido disponível (só imediata e curto prazo); meses de reserva (liquidez imediata ÷ despesas mensais do Planeamento); imóveis pelo valor líquido de dívida (crédito ligado ao imóvel) com desconto opcional de 5% ou 10% para os custos de venda; casa de habitação própria fora do FIRE; alocação por camada e categoria com e sem a casa própria; evolução mensal por camada; «De onde veio o crescimento», ano a ano (poupança investida, valorização do mercado, outros ativos financeiros, imóveis e amortização da dívida); «Atualizar valores», um formulário mensal com todos os ativos e dívidas, com lembrete (também na Visão Geral) quando um valor passa um mês sem atualizar; aviso nos valores com mais de 90 dias; cada ativo pode somar-se à carteira no Planeamento (FIRE). Na Visão Geral, o património líquido total e o disponível aparecem por baixo do valor da carteira. |
| **Planeamento** | Independência financeira (FIRE): o número FIRE «para sempre» (regra dos 4%), «para sempre, com a pensão» e «até aos N anos, com a pensão», já depois do IRS dos levantamentos; a parte já feita; a idade e o ano a que corresponde cada capital necessário (com uma nota quando «investir até aos» adia a data FIRE: o capital pedido desce só porque faltam menos anos até à pensão); a data em três cenários (3%, 5% e 7% reais ao ano), a investir até à data FIRE (ou até uma idade) e a levantar daí em diante; o gráfico da vida inteira com os números FIRE a tracejado e quando cada cenário chega a cada um (tabela e pontos no gráfico); nota quando a pensão cobre as despesas; os outros ativos marcados em Património somam-se à carteira; até quando dura o dinheiro em cada cenário; acompanhamento mês a mês. |
| **Radar e alertas** | Alertas de preço (acima, abaixo, variação diária) e lista de observação com preço-alvo. |
| **Fiscal** | Por ano: mais-valias pelo método FIFO resumidas por ativo (as linhas de cada lote abrem a pedido e vão todas no CSV), dividendos com o crédito de imposto estrangeiro limitado a cada dividendo, juros e estimativa de imposto a 28% (Portugal). |
| **Importar** | Extratos da Trading 212 (CSV), XTB (XLSX), Trade Republic (CSV) e CSV genérico, com deduplicação (podes carregar o mesmo ficheiro várias vezes) e histórico de extratos. Antes de importar fica uma cópia automática da base de dados. |
| **Transações** | Lista filtrável, inserção manual (com validação da quantidade detida nas vendas) e exportação CSV. |
| **Definições** | Corretoras; ativos com filtro (posições abertas, sem cotações, todos), pesquisa, último fecho e «Juntar» para o mesmo título com dois tickers; atualização de cotações (todas ou só as posições abertas, com o progresso ativo a ativo); taxa sem risco; aviso de cotações antigas (os dias configuram-se; 5 por omissão, 0 desliga); disponível offline; cópias de segurança automáticas com «Restaurar» e «Eliminar»; demonstração e limpeza de dados. |

Também há um seletor de corretora (todas ou uma conta específica) e um botão com um olho que esconde os valores.

### Cotações

As cotações, os câmbios, os eventos (resultados e dividendos), o histórico de dividendos por ação e os dados fundamentais das ações vêm do Yahoo Finance através do pacote `yfinance`, instalado pelos scripts de arranque. Onde o `yfinance` não pode ser instalado (ex.: Android), a aplicação vai buscar esses dados diretamente ao Yahoo. Para atualizar, usa **Definições → Atualizar cotações agora** (ou `bash atualizar-cotacoes.sh`), que precisa de internet. Quando as posições abertas não são atualizadas há mais de 5 dias, aparece uma faixa no topo de todas as páginas com o botão «Atualizar posições abertas»; o número de dias muda-se em **Definições → Dados de mercado**.

Os dados fundamentais (lucro por ação, valor contabilístico, cash flow livre, crescimento, owner earnings, resultado operacional, dívida e caixa), usados em **Carteira → O valor de cada ação**, são pedidos no máximo uma vez por semana por ação. Vêm do resumo do Yahoo e, para o que faltar, das demonstrações financeiras, também da cotação principal da empresa (pelo ISIN), convertidos para a moeda da cotação. Podes corrigi-los à mão no próprio cartão; `python -m portfolio_investimentos --testar-yahoo` mostra o que cada fonte devolve. Confirma em **Definições → Ativos** o *símbolo de dados* de cada ativo (código do Yahoo Finance, ex.: `VWCE.DE`, `IWDA.AS`, `AAPL`).

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
- **Índices de referência** (S&P 500, Nasdaq 100, MSCI World) convertidos para euros ao câmbio de cada dia, como a carteira. Assim a variação do dólar não aparece como mérito ou demérito.
- **Volatilidade, Sharpe e Sortino** calculados só com dias úteis (os juros lançados ao fim de semana não contam como dias de bolsa), anualizados com 252 dias. O Sharpe e o Sortino usam o retorno médio diário anualizado (× 252), na mesma base da volatilidade e da taxa sem risco, por isso valem também para períodos curtos. O **Calmar** (CAGR ÷ maior queda) só aparece com pelo menos 1 ano, e o **beta**, as **capturas** e o **alfa** com pelo menos 6 meses; com menos de 1 ano, o CAGR é o retorno do período, sem anualizar.
- **Taxa sem risco** de 2% ao ano por omissão (perto da taxa de depósito do BCE) no Sharpe, no Sortino e no alfa; ajustável em **Definições → Dados de mercado**.
- **Melhor/pior mês e ano**, **sequência atual** e **médias anuais** só contam períodos completos: ficam de fora o mês e o ano em curso e o primeiro mês ou ano, se a carteira (ou o período escolhido) começou a meio.

## Estrutura

```
portfolio_investimentos/
├── engine/        # motor de cálculo em Python puro: carteira (FIFO, TWR, IRR, risco, dividendos, fiscal), FIRE,
│                  #   notas do perfil de investidor, crises, custos, valor de cada ação e carteira cerne
├── services/      # base de dados, importação, mercado (yfinance ou acesso direto ao Yahoo), património,
│                  #   cartões da Visão Geral, carteira cerne, cópias de segurança, demonstração
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
- Análise da sobreposição de ETFs (as mesmas empresas em vários fundos); no Planeamento, simulações com os anos reais dos mercados e o efeito de vender ou comprar.
- Executável único (PyInstaller) para quem não quer instalar o Python.

## Apoiar o projeto

Se a aplicação te é útil, podes pagar-me um café:

<a href="https://buymeacoffee.com/geneiros"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me a Coffee" height="45"></a>

## Licença

[Apache License 2.0](LICENSE) © 2026 Helder Meneses.

Podes usar, copiar, alterar e distribuir este software, incluindo para fins comerciais, desde que:

- mantenhas o nome do autor, os avisos de direitos de autor e o ficheiro [NOTICE](NOTICE) em todas as cópias e versões alteradas;
- incluas uma cópia da licença;
- assinales os ficheiros que alteraste.

O software é fornecido "tal como está", sem garantias.
