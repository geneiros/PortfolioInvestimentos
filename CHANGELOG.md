# Histórico de alterações

O que mudou em cada commit, do mais recente para o mais antigo (gerado a partir das mensagens dos commits). Os números entre parênteses são as issues do GitHub resolvidas.

## 2026-11-08

- **Notícias: sem Google Notícias, progresso no botão e diagnóstico do Yahoo Finance**  
  O Google Notícias deixa de ser fonte (as notícias já guardadas dele apagam-se). «Atualizar todas as fontes», em Definições, e «Atualizar notícias» atualizam ativo a ativo, com o progresso no botão («A atualizar notícias… 3/12 · ADB.DE»), que só volta ao normal quando acaba. O Yahoo Finance pede primeiro pelo símbolo dos EUA (o que o Finnhub encontra pelo ISIN, ex.: ADB.DE → ADBE), depois pelo símbolo de dados e pelo ticker, e, quando o yfinance não devolve nada, tenta a pesquisa do Yahoo; antes, um símbolo europeu ou um ETF dava uma lista vazia sem erro. Na tabela das fontes, em Definições, a coluna nova «Última atualização» diz quantas notícias cada fonte encontrou, em quantos pedidos, quantas eram novas e quantos pedidos falharam.
- **Notícias: Marketaux como quarta fonte**  
  Com a chave em Definições → Dados de mercado (ou na variável MARKETAUX_API_KEY), as notícias do Marketaux juntam-se às do Finnhub, do Yahoo Finance e do Google Notícias, pelo símbolo dos EUA quando existe (o mesmo que o Finnhub encontra pelo ISIN) ou pelo do Yahoo. O plano gratuito tem 100 pedidos por dia e 3 notícias por pedido: as do Marketaux reaproveitam-se durante 6 horas (as outras, 1 hora), com a validade agora contada por fonte. A API só aceita a chave no endereço, que a aplicação não mostra nem regista (os erros não o incluem).

- **Nova área Notícias (Finnhub, Yahoo Finance e Google Notícias)**  
  Página Notícias no menu, a seguir a Radar e alertas: as notícias dos últimos 7 dias dos ativos da carteira selecionada no topo (ou de todas), com filtro por ativo, e um separador «Mercado». Três fontes: o Finnhub (com a chave em Definições ou na variável FINNHUB_API_KEY, enviada num cabeçalho; no plano gratuito só empresas cotadas nos EUA e no Canadá, com o símbolo encontrado pelo ISIN e guardado), o Yahoo Finance (pelo yfinance) e o Google Notícias (RSS, pelo nome do ativo, em português). A mesma notícia em duas fontes (endereço ou título igual) só aparece uma vez. Obtêm-se ao abrir a página, com limite de tempo, e guardam-se 1 hora (as com mais de 30 dias apagam-se); os erros de cada fonte aparecem na página. Em Definições → Dados de mercado: a chave do Finnhub (escondida depois de guardada), a escolha das fontes com o número de notícias guardadas de cada uma e o botão «Atualizar todas as fontes». A página não carrega imagens de outros sites. Tabela nova news_item; «Apagar todos os dados» apaga também as notícias.

- **Atualizar cotações pela página aos bocados (funciona no PythonAnywhere)**  
  O botão de Definições (e o da faixa de cotações antigas) lançava a atualização numa thread no servidor. No PythonAnywhere a aplicação web não deixa correr threads: a atualização só avançava enquanto a página fazia pedidos (ficava muito tempo em «1/18 · ^GSPC») e morria quando o servidor reciclava o processo, sem guardar as cotações. Agora a página pede a atualização aos bocados: cada pedido faz alguns ativos (cerca de 10 s), o progresso fica guardado na base de dados e aparece no botão; se mudares de página ou recarregares, a página seguinte continua de onde ficou. A atualização pela consola (`atualizar-cotacoes.sh`) fica igual.

- **Visão Geral: MSCI World no gráfico de evolução**  
  O MSCI World junta-se aos índices de comparação do gráfico «Retorno total / Valor total»: S&P 500, MSCI World, FTSE All-World e STOXX Europe 600.

- **Visão Geral: comparar com S&P 500, FTSE All-World e STOXX Europe 600; posições por selecionar**  
  O gráfico «Retorno total / Valor total» passa a comparar só com o S&P 500, o FTSE All-World (cotações do ETF VWCE.DE, com o ticker próprio FTSE-AW para não se confundir com quem o tem na carteira) e o STOXX Europe 600 (^STOXX); os dois novos ficam também na lista de índices da «Carteira vs mercado» e recebem cotações na atualização. Por baixo do gráfico só a Carteira vem selecionada: as linhas das posições ficam na legenda, por selecionar (um clique mostra cada uma).

- **Visão Geral: o período do gráfico de evolução filtra também o cartão Carteira**  
  Os botões 1M, 3M, 6M, YTD, 1A, 3A, 5A e Máx do gráfico «Retorno total / Valor total» passam a mudar também o primeiro cartão: o gráfico de fundo mostra o valor das posições abertas nesse período, «Variação diária» passa a «Variação · período» (ganho sem depósitos, em € e %, como em Desempenho) e «Ano corrente» passa a «Rendimento · período» (TWR). Abre em YTD. O valor da carteira, o retorno total e os resultados e a conta não mudam.

## 2026-11-07

- **Património: na evolução mensal, por omissão só o disponível, a liquidez imediata e o curto prazo**  
  O total, o ilíquido e as dívidas continuam na legenda do gráfico, mas por selecionar; um clique mostra-os.

- **Património: % de ganho em «De onde veio o crescimento»**  
  Cada ano mostra o ganho sem a poupança (a variação do património menos o dinheiro novo posto nas corretoras), em € e em % do património no início do ano, e a % de cada parte sobre a sua própria base: a valorização do mercado pelo rendimento ponderado pelo tempo (TWR) das corretoras, como em Desempenho; os outros ativos financeiros e os imóveis sobre o valor no início do ano; a amortização sobre a dívida do início do ano. A poupança investida não tem % (não é rendimento). No ano corrente as % são até hoje, não anualizadas; no telemóvel a % aparece por baixo do valor.

- **Performance: contar posições sem calcular carteiras, faixa da carteira cerne em cache e cache que já não se perde sem razão (#45, #46, #49)**  
  Medido com dados do tamanho de uma carteira real (5 corretoras, 2 100 transações, 293 ativos, 416 mil cotações): o seletor de corretoras deixa de calcular a carteira de cada corretora só para contar as posições (`brokers()` de ~800 ms para ~6 ms; a primeira Definições depois de uma mudança de ~1,4 s para ~0,9 s); a faixa da carteira cerne passa de 12–20 ms em todas as páginas para ~1 ms (lê só o máximo e o último fecho e fica em cache); operações noutras tabelas (ex.: cada login) já não deitam fora as carteiras calculadas (a página seguinte de ~1,4 s para ~0,1 s); e o pré-aquecimento em segundo plano calcula também as carteiras de cada corretora, por isso depois de uma atualização a Visão Geral e a Carteira abrem em ~45–80 ms.

- **Segurança: o cookie de sessão deixa de levar um hash da palavra-passe (#42)**  
  Com a palavra-passe em `PORTFOLIO_PASSWORD`, o cookie de sessão (assinado, mas legível) guardava parte de um SHA-256 sem sal da palavra-passe, que permitia testá-la offline a quem tivesse o cookie. Passa a guardar um HMAC com a chave secreta do servidor. As sessões abertas terminam uma vez: é preciso voltar a entrar.

- **Importação: o ativo do ISIN passa ao ticker real sem perder dados; carteira cerne volta à base ao mudar o ETF de crescimento (#36, #37)**  
  Quando um ativo criado com o ISIN (ex.: Trade Republic) passa ao ticker real, ou quando se juntam dois tickers do mesmo título, passam também o logótipo, os dados fundamentais (ao juntar, só as correções à mão, porque os do Yahoo estão na moeda da outra cotação), o TER e o setor, sem apagar o que o ativo novo já tiver. Na carteira cerne, escolher outro ETF para o papel «Crescimento» volta ao alvo base: o escalão atingido era do ETF anterior.

- **Desempenho: o IRR deixa de ser anualizado em períodos de menos de 1 ano (#38)**  
  Em 1M, 3M, 6M ou YTD no início do ano, o XIRR aparecia anualizado (+2% num mês davam ~+27% «por ano»). Com menos de 1 ano, o cartão passa a dizer «No período» e mostra o retorno ponderado pelo dinheiro do período, com a nota «não anualizado» e o valor anualizado no «?»; com 1 ano ou mais fica como estava («Por ano»).

- **Números com separador de milhares e definições que sobravam depois de «Apagar tudo» (#34, #35)**  
  Os formulários passam a ler os números à portuguesa: «1.000» é mil (era 1), «1.000,50» e «1 000» também funcionam, e continuam a aceitar-se «1000,5», «1000.5» e «1,000.50»; os grupos de milhares têm de ter 3 algarismos. Os campos numéricos do browser seguem com vírgula decimal, para «2.125» não ser lido como milhares. Vale para todas as ações da API e para o «Dinheiro novo a investir» da carteira cerne. «Apagar todos os dados» passa a limpar o escalão atingido e o aviso da carteira cerne, os ativos escolhidos para cada papel e o perfil de investidor de cada corretora; apagar uma corretora apaga o perfil dela. Ficam as preferências: o intervalo dos escalões, o perfil de «todas as corretoras», a ordem dos cartões e os índices escolhidos.

## 2026-11-05

- **README e capturas de ecrã atualizados**  
  Todas as capturas (claro e escuro) refeitas com os logótipos e as iniciais de 36 px e o gráfico da Visão Geral em YTD; README com os logótipos só à mão.
- **Logótipos maiores e mais arredondados**  
  Os logótipos e as iniciais dos ativos passam de 28 para 36 px, com cantos de 10 px, como nas apps das corretoras.
- **Logótipos a preencher o quadrado**  
  A imagem do logótipo passa a ocupar o quadrado todo, sem margem nem borda, com os cantos arredondados como as iniciais.
- **Logótipos só à mão**  
  A atualização de cotações deixa de procurar logótipos (no PythonAnywhere quase todos os serviços de ícones estão bloqueados e o Yahoo limita os pedidos). Em Definições → Ativos, clicar nas iniciais de um ativo permite carregar uma imagem, procurar o ícone pelo site indicado ou tirar o logótipo; os já guardados ficam.
- **Logótipos: variantes do site e servidores bloqueados**  
  No PythonAnywhere só o DuckDuckGo responde (o Google, o gstatic e os sites das empresas estão fora da lista de sites permitidos). Quando o DuckDuckGo não tem o ícone do site, tenta-se também com «www.» e os outros sites do emitente (ex.: Xtrackers → dws.com); um servidor que falha por rede salta-se no resto da atualização. Os marcados como «sem ícone» voltam a procurar-se já.
- **Logótipos: nome do ETF pelo cliente da atualização e mais serviços de ícones, com o motivo no resumo**  
  No PythonAnywhere o Yahoo limita (HTTP 429) os pedidos diretos, mas não os do yfinance: o nome longo do ETF passa a vir do mesmo cliente que obtém as cotações (deixa de se usar a pesquisa, que demorava ~20 s por ETF a falhar). Os ícones procuram-se no Google (128 e 64 px), no gstatic, no DuckDuckGo e no próprio site; quando nenhum tem, a linha do resumo diz a resposta de cada serviço.
- **Logótipos: nome do ETF pelas cotações, domínio principal e ícones mais pequenos**  
  Na atualização no PythonAnywhere, a pesquisa do Yahoo respondia 429 (pedidos limitados) para os ETF; o nome longo (ex.: «Xtrackers II EUR Overnight Rate Swap UCITS ETF 1C») passa a vir primeiro do pedido das cotações, que já funciona. Um site num subdomínio sem ícone (ex.: ir.finvgroup.com) tenta também o domínio principal (finvgroup.com), e ao serviço de ícones pedem-se também 64 e 32 px quando não tem 128 px. Os marcados como «sem ícone» até agora voltam a procurar-se já.
- **Logótipos: mais fontes e erros que já não contam como «não há»**  
  Só aparecia o logótipo quando o Yahoo devolvia o site da empresa, e esse pedido falha muitas vezes (ex.: no PythonAnywhere); nos ETF, o nome da corretora («EUR Overnight Rate Swap») não diz o emitente. Agora o site da empresa vem também do Wikidata pelo ISIN, e o emitente do ETF também do nome longo do Yahoo (a pesquisa, ex.: «Xtrackers II EUR Overnight Rate Swap…») ou do Wikidata. Uma fonte que não responde já não grava «sem logótipo»: tenta-se na atualização seguinte (os marcados assim antes voltam a procurar-se já); um não encontrado repete-se ao fim de 7 dias. O resumo da atualização tem uma linha «logótipo» por ativo com o site e a origem, ou o motivo.
- **Logótipos das empresas e dos ETF**  
  Na atualização de cotações, cada posição aberta sem logótipo recebe o ícone do site da empresa (o site vem dos dados da empresa no Yahoo) ou, num ETF, o do emitente reconhecido pelo nome (iShares, Vanguard, Xtrackers, Invesco, Amundi/Lyxor, SPDR, WisdomTree, VanEck, …). A imagem fica guardada na base de dados (tabela nova Logo) e é servida pela própria aplicação, por isso as páginas não fazem pedidos a outros sites e funcionam offline; sem logótipo ficam as iniciais, e um não encontrado volta a procurar-se ao fim de 30 dias. Em Definições → Ativos, clicar no logótipo abre o editor: procurar por um site, carregar uma imagem (até 200 KB), ficar com as iniciais ou voltar à procura automática.
- **README e capturas de ecrã atualizados**  
  Todas as capturas (claro e escuro) refeitas com a versão atual; novas capturas 25 (alerta da carteira) e 26 (gerir índices) da Carteira; README com os alertas da carteira, os índices à escolha, a ordem dos cartões e o intervalo da carteira cerne em Definições.
- **Radar e alertas: os alertas da carteira**  
  Os alertas criados na Carteira («Carteira vs mercado» → sino) aparecem também em Radar e alertas, numa secção «Alertas da carteira» por baixo dos alertas de preço: carteira ou conta, condição, estado (ativo ou pausado e o último disparo) e botões para pausar, reativar e apagar. O aviso de um alerta disparado aparece também nesta página.
- **Carteira: escolher os índices da «Carteira vs mercado» e alertas da variação da carteira**  
  Dois botões no cartão «Carteira vs mercado». «Gerir índices» escolhe até 5 índices (Global: MSCI World; EUA: S&P 500, Dow Jones, Nasdaq 100, Russell 2000, Bitcoin; Europa: FTSE 100, CAC 40, DAX, Euro STOXX 50, AEX, Euronext 100); um índice novo recebe as cotações na atualização seguinte. «Alerta da carteira» cria alertas da variação do dia de toda a carteira ou de uma corretora (1, 2, 3 ou 5%; a subir, a descer ou os dois), com a variação de hoje à vista; disparam no máximo uma vez por dia e por sentido, sem contar depósitos e levantamentos, e o aviso aparece no topo da Visão Geral e da Carteira.
- **Visão Geral: perfil de investidor por corretora**  
  Cada corretora tem o seu perfil de investidor, e «Todas as corretoras» também (o perfil escolhido antes passa a ser o de todas). As notas usam a carteira da corretora selecionada e o perfil dela; o aviso aparece quando o perfil escolhido (ou, sem escolha, o sugerido) não é o que a carteira dessa corretora sugere, e o link e a janela do perfil dizem a que corretora se referem.
- **Mudar a ordem dos cartões em todas as páginas; gráfico da Visão Geral abre em YTD**  
  O clique longo e arrastar passa da Visão Geral a todos os cartões de todas as páginas: os cartões e as grelhas encontram-se sozinhos (cada cartão muda de lugar dentro da sua grelha; títulos e avisos ficam onde estão) e a ordem fica guardada por página na aplicação, aplicada antes de a página desenhar os gráficos. Em Definições → Ordem dos cartões, repor a ordem de cada página ou de todas. O gráfico «Retorno total / Valor total» da Visão Geral abre com o período YTD.
- **Visão Geral: mudar a ordem dos widgets arrastando**  
  Carregar 2 segundos no fundo de um cartão (rato ou toque; não conta em texto, botões, links ou gráficos, e mexer antes cancela) levanta o widget, que se arrasta para outro lugar; um marcador tracejado mostra onde cai, a página desliza perto das margens e Esc cancela. Os cartões altos encolhem enquanto se arrastam. A ordem fica guardada na aplicação (igual em todos os dispositivos) e repõe-se em Definições → Ordem dos widgets.
- **Visão Geral: Investor Score e Portfolio Score a seguir ao gráfico**  
  As notas do perfil de investidor passam para baixo do gráfico «Retorno total / Valor total».
- **README: link para o Buy Me a Coffee**  
  Badge no topo e botão na secção nova «Apoiar o projeto», a ligar a buymeacoffee.com/geneiros.
- **Visão Geral: o gráfico de fundo do cartão Carteira mostra o último ano**  
  Mostrava os últimos 120 dias úteis (cerca de 6 meses); passa a mostrar o valor das posições abertas no último ano, e o «?» do cartão diz o período.
- **Visão Geral: sem o cartão «Máximo histórico»**  
  O cartão sai e o cartão Carteira passa a ocupar a largura toda; os resultados e a conta ficam em 5 colunas alinhadas. A queda face ao máximo (drawdown) continua em Desempenho.
- **Visão Geral: resultados e conta no cartão Carteira**  
  Os valores do cartão «Resultados / Conta» (não realizado, dividendos, realizado, comissões, custo base, depositado, caixa, valor total e juros da conta) passam para uma faixa por baixo dos valores do primeiro cartão, Carteira. O cartão antigo sai e o gráfico de evolução passa a ocupar a largura toda.
- **Carteira: carteira cerne (ERNX · FWIA · XEON) com escalões quando o FWIA cai**  
  Um cartão novo na Carteira com os pesos alvo de 3 ETF (reserva, crescimento e estável; por omissão ERNX 45% · FWIA 30% · XEON 25%). Quando o FWIA cai face ao máximo, a mistura alvo passa ao escalão seguinte da tabela (40/35/25, 35/40/25, 30/50/20, 25/60/15, 20/70/10), por omissão a cada 10% de queda; o intervalo muda-se em Definições → Dados de mercado (ex.: 5% → −5/−10/−15/−20/−25%), sem mudar as misturas. O escalão atingido mantém-se quando o FWIA recupera; «Voltar ao alvo base» é manual. O cartão mostra a queda, os pesos atuais e alvo, o desvio, as ordens para chegar ao alvo em € e unidades, ou, com dinheiro novo a investir, só as compras (sem vender nem pagar IRS), e o retorno esperado, a volatilidade e o pior ano típico de cada escalão. Ao chegar a um escalão novo, aparece uma faixa no topo de todas as páginas, até carregares em «Já vi».
- **Desempenho: Sharpe, Sortino e alfa corretos em períodos curtos; médias só com anos completos**  
  Verificados o TWR, o CAGR, a IRR, a volatilidade, o drawdown e o beta com um cálculo independente. Corrigido: o Sharpe e o Sortino comparavam o retorno do período (ex.: 1 mês) com a taxa sem risco anual e a volatilidade anualizada (1M com +0,45% dava Sharpe −0,15); passam a usar o retorno médio diário anualizado. Com menos de 1 ano, o Calmar fica «—», o CAGR diz «no período, não anualizado» e o alfa usa a taxa sem risco do período; o beta, as capturas e o alfa precisam de 6 meses. A média anual, o melhor/pior ano e o mérito anual deixam de contar o primeiro ano (se começou a meio) e o ano a decorrer.
- **Visão Geral verificada; posição de abertura estimada por corretora** `53d8851`  
  Confirmados os cartões da Visão Geral (carteira, retorno total = soma das partes, variação diária, ano corrente, máximo histórico, resultados, conta, peso vs retorno, alocação). A alocação por corretora não batia com o total: uma venda numa corretora sem o histórico completo consumia as ações de outra corretora na vista consolidada. A posição de abertura estimada passa a ser por corretora e ativo, por isso o consolidado é a soma das corretoras. A demonstração deixa de vender numa corretora ações que só existiam na outra.
- **Carteira: ROI % do total com a mesma base das linhas; «?» no 1D** `c1da696`  
  Confirmados os totais da tabela (cada coluna é a soma das linhas). O ROI % do total passava a dividir pelo investido só nas posições abertas, enquanto as linhas dividem por tudo o que se investiu no ativo (incluindo partes já vendidas, de onde vem o realizado); o total passa a usar a mesma base. A coluna 1D ganha um «?»: a % é a do preço na moeda do ativo e o valor em euros inclui o câmbio.
- **Cópias de segurança: no máximo 2** `6da949b`  
  Cada cópia nova (automática, manual ou antes de restaurar ou de atualizar a base de dados) apaga as mais antigas, para ficarem só as últimas 2 (eram 10). A cópia feita antes de restaurar nunca apaga a que se está a restaurar.
- **Aviso de cotações antigas e eliminar cópias de segurança** `3f7cb2a`  
  Quando as cotações das posições abertas não são atualizadas há mais de 5 dias (configurável em Definições → Dados de mercado; 0 desliga), aparece uma faixa no topo de todas as páginas com o botão «Atualizar posições abertas»; fechada, fica escondida até ao fim da sessão do browser. Em Definições, cada cópia automática tem um botão «Eliminar» a seguir a «Restaurar».

## 2026-11-01

- **Planeamento: o capital necessário com a idade e o ano, e nota sobre «investir até aos»** `e7635a3`  
  As contas estavam certas: nos blocos «com a pensão» e «até aos N anos», o capital necessário é o da data FIRE e desce com a idade (menos anos até à pensão), por isso investir menos tempo, que adia a data, mostrava um valor mais baixo. A página passa a pôr em destaque a idade e o ano a que corresponde cada valor, a explicá-lo no «?» e, com «Investir até aos» preenchido, a mostrar uma nota: investir menos tempo não reduz o que precisas, adia a data.
- **Esconder valores: botão também no telemóvel** `64fa0c3`  
  No telemóvel (menos de 768 px) o grupo do meio da barra de topo esconde-se e o botão do olho ia com ele. Passa a haver um botão do olho à direita da barra de topo nos ecrãs pequenos; o seletor de corretora encolhe (texto truncado) para caberem os dois.
- **README: revisão e capturas da Visão Geral** `7e37762`  
  Capturas 02, 03 e 04 (claro e escuro) refeitas com os gráficos novos dos principais movers. Tabela de funcionalidades pela ordem do menu; secção «Cotações» com o histórico de dividendos, os eventos e os dados fundamentais (fontes, frequência e correção manual); «Próximos passos» sem a exposição geográfica, que já existe; «Estrutura» com os módulos novos.
- **Visão Geral: gráfico dos movers com o último ano** `2323566`  
  O gráfico de cada ação dos «Principais movers» passa a mostrar o último ano (eram os últimos 30 dias), e a data no valor ao passar o rato inclui o ano.
- **Visão Geral: gráfico dos movers face ao preço médio, com o valor ao passar o rato** `e8f089e`  
  O gráfico de cada ação dos «Principais movers» ocupa a largura livre da linha e mostra o preço médio de aquisição a tracejado: a linha e o preenchimento ficam verdes acima dele e vermelhos abaixo. Ao passar o rato aparece a data, o preço e a diferença para o preço médio (com «€ ••••» se os valores estiverem escondidos). No telemóvel, o gráfico passa para uma segunda linha, com a largura toda.
- **Visão Geral: mini-gráfico em cada ação dos principais movers** `edf0424`  
  Cada ação dos «Principais movers» mostra o nome, um mini-gráfico dos últimos 30 dias (verde se subiu, vermelho se desceu) e o preço; o cartão passa a mostrar até 8 ações. Os mini-gráficos (também os da Carteira) redesenham-se com as cores do tema ao mudar de tema.
- **Visão Geral: gráfico de evolução no lugar dos principais movers** `9c6f67e`  
  O gráfico «Retorno total / Valor total» sobe para logo a seguir às notas (ao lado de «Resultados / Conta») e os «Principais movers» passam para o lugar dele (ao lado de «Próximos eventos»). Os restantes cartões ficam onde estavam.
- **Menu: Radar e alertas antes de Fiscal** `b7d3544`  
  Nova ordem: Visão Geral, Carteira, Desempenho, Dividendos, Património, Planeamento, Radar e alertas, Fiscal.
- **Valor de cada ação: mais quatro métodos e o PEG; «?» com círculo** `431b57a`  
  Por ordem de popularidade: DCF, Número de Graham, fórmula de crescimento de Graham (LPA × (8,5 + 2g) × 4,4 ÷ Y, com Y, o rendimento das obrigações AAA, configurável no cartão; 5% por omissão) e modelo de Gordon (D₁ ÷ (Ke − g), com o crescimento dos dividendos do histórico, no máximo 6%, e Ke de 8% a 10%) sempre visíveis; em «Mais métodos», Owner Earnings de Buffett (lucro líquido + amortizações − CAPEX de manutenção ± fundo de maneio, descontados como no DCF), Earnings Power Value de Greenwald (NOPAT normalizado ÷ WACC de 8% a 10% + caixa − dívida), Bazin e o PEG de Peter Lynch (com o preço de PEG 1). Owner earnings, NOPAT e caixa líquida vêm das demonstrações financeiras do Yahoo e podem ser corrigidos à mão (migração 6). O «?» das explicações passa a ser um círculo, mais escuro, em toda a aplicação.
- **Valor de cada ação: a fórmula de cada método no «?»** `5cdc387`  
  A seguir ao nome de cada método (DCF, Graham, Bazin) há um «?» com a fórmula e os números usados nessa ação.
- **Valor de cada ação: dados fundamentais mais robustos** `26c13b5`  
  O pedido de dados fundamentais do yfinance (quoteSummary) falha muitas vezes e devolvia quase nada sem dar erro, e a aplicação gravava esse vazio como atualizado. Agora: sem dados, tenta as séries das demonstrações financeiras do Yahoo (lucro por ação dos últimos 12 meses, cash flow livre, capital próprio, nº de ações e histórico do lucro por ação para o crescimento), do símbolo da cotação ou de outra cotação da mesma empresa pelo ISIN, tudo convertido para a moeda da cotação; sem nenhum dado não grava e tenta de novo na próxima atualização (também as tentativas vazias já gravadas). `--testar-yahoo` mostra o que cada fonte devolve.
- **Carteira: o valor de cada ação** `62de5b3`  
  Para cada ação aberta, três métodos sempre em intervalo, numa barra com o preço como traço: DCF (cash flow livre por ação, ou o lucro, a crescer 10 anos e depois 2,5%, desconto de 8% a 10%, crescimento ±2,5 p.p.), número de Graham (lucro atual e previsto) e Bazin (dividendo médio de 3 anos ÷ 6% a 8%); e o crescimento que o preço de hoje já assume (desconto de 9%). Os dados fundamentais vêm do Yahoo na atualização de cotações (uma vez por semana; também sem o yfinance, pelo quoteSummary), convertidos para a moeda da cotação, e podem ser corrigidos à mão. Captura 24.
- **README: capturas atualizadas e novas** `df711f9`  
  As 21 capturas (claro e escuro) refeitas com o menu na ordem nova e as funcionalidades recentes, mais duas novas: «Carteira: as crises e os custos» (22) e «Património: de onde veio o crescimento» (23). O README passa a descrever o «Esconder valores» e a cor das barras do sistema na aplicação instalada.
- **Carteira: as crises e os custos** `3c1ff98`  
  Dois cartões novos na Carteira. «As crises»: a queda estimada da carteira de hoje se a crise financeira (2008), a dívida do euro (2011), a pandemia (2020) ou a inflação e juros (2022) se repetissem, = Σ peso × beta × queda do S&P 500 (beta de cada posição pelos retornos semanais dos últimos 3 anos, em euros; beta 1 sem histórico; a caixa não cai), em % e em euros, e o tempo do S&P 500 até recuperar o pico. «Os custos»: comissões dos últimos 12 meses (e nº de operações), custo dos ETF (valor × TER, que indicas no próprio cartão; migração 5) e retenções na fonte acima dos 15% da convenção (sem Portugal nem país desconhecido), por ano e o que representam em 20 anos.
- **Menu: nova ordem** `eeaddd9`  
  Visão Geral, Carteira, Radar e alertas, Desempenho, Dividendos, Património, Planeamento, Fiscal.
- **Aplicação instalada: cores do manifesto para o modo claro e escuro do sistema (experimental)**  
  O manifesto ganha user_preferences.color_scheme com uma cor para o modo claro (#ffffff) e outra para o escuro (#212529), um campo experimental que algumas versões do Chrome usam para seguir o modo claro ou escuro do telemóvel. Sem suporte, fica a cor base, escura.
- **Aplicação instalada: barra de navegação do Android da cor do topo (modo escuro)**  
  No Android, a barra de navegação (em baixo) da aplicação instalada usa a cor do manifesto, gravada na instalação, e ficava azul. O manifesto passa a usar #212529 (o fundo do modo escuro) em theme_color e background_color.
- **Aplicação instalada: barra do sistema da cor do fundo**  
  A cor da barra do sistema (theme-color) deixa de ser o azul fixo e acompanha o tema: branca no modo claro e #212529 no escuro, desde o início de cada página e ao mudar de tema (também na página «Aplicação parada»). O manifesto deixa o azul e a cache do service worker passa a pi-v4.

## 2026-10-31

- **Esconder valores: «€ ••••» na cor do valor e botão selecionado**  
  O texto que substitui cada valor mantém a cor do valor (verde nos ganhos, vermelho nas perdas…) em vez de ficar cinzento. Enquanto o modo está ligado, o botão fica selecionado, com o olho riscado e o título «Mostrar valores», logo desde o início de cada página.
- **Património: atualizar todos os valores de uma vez, com lembrete mensal** `af5a3eb`  
  Botão «Atualizar valores» que abre um formulário com todos os ativos e dívidas (o valor de hoje editável e o do mês anterior como referência). «Guardar tudo» regista o valor do mês de todos (ação save_other_asset_values: aceita espaços como separador de milhares, deixa como está um campo vazio e recusa nan e negativos). Quando um valor passa um mês sem atualizar, aparece um lembrete no Património e um aviso «N por atualizar» na Visão Geral. Com «Esconder valores», os números do formulário só se veem ao editar.
- **Património: de onde veio o crescimento, ano a ano** `501757d`  
  A variação do património líquido total em cada ano dividida em poupança investida, valorização do mercado, contas/depósitos/certificados/PPR, imóveis e amortização da dívida (a soma dá a variação; registar um ativo não conta como crescimento), com seletor de ano e gráfico de barras empilhadas.
- **Património por camadas de liquidez** `6ac5b9c`  
  O património deixa de ser somado num único total: cada ativo tem um nível de liquidez (imediata, curto prazo, ilíquido; por omissão o da categoria, e muda-se no modal) e a página mostra: - património líquido total e património líquido disponível (só imediata e curto prazo, menos as dívidas sem imóvel), em cartões separados; - meses de reserva = liquidez imediata ÷ despesas mensais do Planeamento (vermelho abaixo de 3, amarelo de 3 a 6, verde acima de 6); - imóveis pelo valor líquido de dívida: um crédito pode ligar-se ao imóvel que financia e abate ao valor dele, com desconto opcional de 5% ou 10% para os custos de venda; - casa de habitação própria, que nunca conta no FIRE (nem o crédito dela); - tabela agrupada por camada com subtotais (o crédito por baixo do imóvel) e alocação por camada e categoria, com e sem a casa própria; - evolução mensal por camada, com as linhas do total e do disponível. Categoria nova "Contas à ordem e poupança à vista" (imediata); "Depósitos" passa a "Depósitos a prazo". Migração 4 (colunas liquidity, home e linked); ação set_sale_discount; a demonstração tem conta à ordem, casa própria com crédito ligado e despesas de exemplo (apagadas com ela).
- **Património: outros ativos e património líquido** `675e0d4`  
  Nova página Património (menu lateral): a carteira das corretoras mais os ativos e as dívidas fora delas, indicados à mão (PPR, certificados de aforro/tesouro, depósitos, imóveis, outros e créditos), com: - património líquido, corretoras, outros ativos, dívidas e o que conta no FIRE; - composição com o peso de cada um, editar/apagar e um interruptor "FIRE" por ativo (por omissão ligado nos ativos financeiros, desligado em imóveis e créditos); - donut por categoria e evolução mensal (fica um registo por mês sempre que atualizas um valor); - aviso nos valores sem atualizar há mais de 90 dias. No Planeamento, os ativos marcados somam-se ao valor da carteira (com a nota "Inclui € X de outros ativos"); na Visão Geral, o património líquido aparece por baixo do valor da carteira. Tabelas novas OtherAsset e OtherAssetValue (criadas sozinhas), ações save_other_asset, set_other_asset_fire e delete_other_asset, e exemplos na demonstração.
- **Esconder valores: espaço fino entre o € e os pontos** `7ef5674`  
  Volta a haver um espaço fino entre o € e os pontos («€ ••••»), sem espaçamento extra entre os pontos.
- **Esconder valores: pontos juntos ao €** `7bf7486`  
  O texto que substitui cada valor passa de «€ ••••» a «€••••».
- **Esconder valores: «€ ••••» em vez do desfoque** `168095c`  
  Cada valor em euros passa a aparecer como «€ ••••», com os pontos à altura do meio do €. O texto real fica transparente e sem largura, por isso também não se adivinha o número de algarismos.
- **Esconder valores: sem mostrar os valores por instantes ao mudar de página** `8a49a9d`  
  A opção passa a ser aplicada logo no início da página (na tag html, como o tema), antes de qualquer valor aparecer.
- **Esconder valores: desfoque proporcional ao tamanho da letra** `176785d`  
  Os números grandes, como o valor da carteira, deixavam-se ler com o desfoque fixo de 7 px.
- **Planeamento: quando cada cenário chega a cada número FIRE** `f59da8e`  
  Tabela «Quando chegas a cada número FIRE» (mês, idade e capital por número FIRE e cenário) e, no gráfico, um ponto da cor de cada número onde cada cenário lá chega, com a curva pontilhada "se continuasses a investir".
- **Planeamento: nota quando a pensão cobre as despesas** `dfcf5bb`  
  Quando a pensão (× 14 meses) paga as despesas, só é preciso capital até à pensão e os números «para sempre, com a pensão» e «até aos N anos» ficam iguais; a página passa a explicá-lo.
- **Visão Geral: Investor Score e Portfolio Score cabem no ecrã do telemóvel** `d2ff44f`  
  Os cartões das notas deixam de ficar cortados no telemóvel.
- **Login: limite de tentativas por visitante atrás de um proxy e guardado na base de dados** `8f3091e`  
  Com PORTFOLIO_PROXY, o endereço é o do visitante; as tentativas falhadas ficam na base de dados (valem para todos os processos) e a palavra-passe atual é pedida para a mudar ou remover (#28).
- **Planeamento: cor da linha do gráfico no título de cada número FIRE** `fc31f3d`  
  Os títulos "Para sempre", "Para sempre, com a pensão" e "Até aos N anos" passam a ter a cor e uma amostra da linha tracejada correspondente no gráfico (laranja, roxa e rosa).
- **Planeamento: números FIRE como linhas tracejadas no gráfico** `cbdbdff`  
  O gráfico Evolução e projeção mostra os números FIRE como linhas horizontais tracejadas, cada uma com a sua cor e o valor na legenda: laranja "para sempre", roxa "para sempre, com a pensão aos 67" e rosa "até aos N anos, com a pensão aos 67" (estes dois na data FIRE do cenário base). Substitui a curva do capital necessário até ao fim.
- **Planeamento: número FIRE "para sempre" com a pensão** `082dc56`  
  Novo bloco "Para sempre, com a pensão" (engine/fire.py, pension_plan): o capital necessário tem duas partes, calculadas mês a mês para trás desde a idade da pensão: - até à pensão, a carteira paga as despesas todas (com o IRS dos levantamentos), a render a taxa real do cenário; - a partir da pensão, o que ela não cobre, pela regra da taxa de levantamento: (despesas − pensão) ÷ (1 − imposto) ÷ taxa. O número depende da idade em que se chega lá; a página mostra-o na data FIRE do cenário base, a parte "depois da pensão", quanto seria preciso hoje e a data nos três cenários. O número "para sempre" de sempre passa a dizer "sem contar com a pensão".
- **Planeamento: depois da data FIRE deixa de investir e passa a levantar; investir até uma idade** `2d23f9a`  
  Cada cenário tem agora duas fases (engine/fire.py, simulate): - até à data FIRE junta o investimento mensal, ou só até à idade indicada em "Investir até aos" (novo campo opcional); - a partir da data FIRE deixa de investir e levanta o que as despesas pedem, já com o IRS dos levantamentos, menos a pensão a partir da idade dela. Com a idade preenchida, o gráfico vai até à idade "durar até" e marca a data FIRE de cada cenário; a tabela dos cenários diz a idade na data FIRE e até quando dura o dinheiro (ou o ano em que acaba).
- **Planeamento: capital necessário até uma idade, com a pensão** `16c3e29`  
  Além do número FIRE "para sempre" (regra dos 4%), com a idade indicada a página calcula o capital que paga as despesas desde a data FIRE até uma idade (90 anos por omissão) e pode acabar perto de zero: - necessário(mês) = levantamento do mês (despesas menos a pensão, a partir da idade indicada, já com o IRS dos levantamentos) + necessário do mês seguinte descontado à taxa real do cenário; - a data FIRE é o primeiro mês em que a carteira projetada chega ao necessário nesse mês (o último ano não conta); - mostra o capital na data FIRE e a idade, a parte já feita se te reformasses hoje, a data nos três cenários e a curva no gráfico. A pensão líquida mensal conta 14 vezes por ano.
- **README: Planeamento já existe** `7748e9c`  
  Atualiza a lista do que falta fazer.
- **Planeamento: independência financeira (FIRE)** `4f7fd20`  
  Nova página Planeamento (menu lateral), com o motor em engine/fire.py: - número FIRE = despesas anuais ÷ (1 − imposto efetivo sobre os levantamentos) ÷ taxa de levantamento (4% por omissão); - já feito = valor atual da carteira ÷ número FIRE; - data FIRE em três cenários (3%, 5% e 7% reais ao ano, em euros de hoje), mês a mês com o investimento mensal; - gráfico com o valor real até hoje, as três projeções e o número FIRE; - acompanhamento dos últimos 12 meses (valor, variação e parte feita). Os parâmetros guardam-se (ação save_fire); por omissão, o investimento mensal é a média dos depósitos líquidos dos últimos 12 meses e o imposto é 28% × a parte de ganho da carteira (pelo menos metade). A página também fica disponível offline.
- **Visão Geral: perfil de investidor com notas, peso vs retorno e alocação** `d090322`  
  Investor Score e Portfolio Score (0-100, últimos 3 anos), num módulo novo (engine/scores.py): - seis perfis (Passive Index, Concentrated Picker, Diversified Active, Income Focus, Growth/Tech, Active Trader), cada um com as métricas e os pesos do Investor Score; o perfil sugerido sai do comportamento (rotação da carteira) e da composição (ETF, dividendos, tecnologia, nº de ações); o escolhido fica guardado (ação set_profile); - métricas: superação do S&P 500 / MSCI World / Nasdaq 100, fidelidade ao índice, disciplina, paciência, Sharpe, coerência, grandes vencedores, assimetria, acerto, fator de lucro e corte das perdas; - Portfolio Score: concentração, diversificação (setores e países), volatilidade, custos e proximidade ao MSCI World. Cada métrica tem a fórmula e o valor atual no "?"; sem dados suficientes fica "—" e não conta.
- **Próximos eventos: data de resultados alterada substitui a antiga, e intervalo estimado à vista** `d046a7d`  
  - Quando o Yahoo muda a data de um evento (ex.: resultados estimados para 12/11 e depois anunciados para 13/11), a data nova substitui a antiga em vez de aparecerem as duas. - Se o Yahoo só tiver um intervalo (duas datas), o evento mostra "estimado: 12/11–17/11" ao lado; com uma só data, é a anunciada. - Os resultados deixam de mostrar "Resultados" duas vezes.
- **Visão Geral: próximos eventos dos próximos 90 dias** `b621aa1`  
  A secção Próximos eventos passa de 60 para 90 dias e o grupo "Mais tarde" mostra até 10 eventos (antes 4).
- **Visão Geral: "As minhas posições" ligado por omissão** `d46bf1f`  
  O gráfico abre já com as linhas das posições (carregadas logo a seguir à da carteira). Se o desligares, a escolha fica guardada neste dispositivo (localStorage) e a página passa a abrir sem elas.
- **Visão Geral: "As minhas posições" no gráfico de evolução** `b3f8e89`  
  Novo botão no gráfico Retorno total / Valor total que acrescenta uma linha por posição: as 5 com maior ganho ou perda no período (em valor absoluto) e as restantes somadas em "Outras (N)". Em Retorno total, a linha é o ganho da posição no período (valor + vendas + dividendos líquidos − compras); em Valor total, o valor de mercado. Por baixo, uma legenda com o ganho em euros e em % de cada uma (e da carteira); um clique esconde ou mostra a linha. As linhas carregam-se a pedido (ação positions) e seguem o período escolhido.
- **Dividendos: datas ex-dividendo e quem tem direito a cada dividendo** `dc0fe8e`  
  Nova tabela "Datas ex-dividendo" na página Dividendos (últimos 3 meses e próximos 12), a partir das datas ex e valores por ação do Yahoo: - recebido / a receber: tinhas ações antes da data ex (a quantidade é a que tinhas na véspera); a receber se o pagamento ainda não entrou; - sem direito: compraste depois da data ex; - previsto: data ex do ano anterior + 1 ano (ou a data anunciada pelo calendário do yfinance, se houver), com as ações de hoje. Inclui posições vendidas depois de uma data ex recente, cujo dividendo ainda é teu.
- **Dividendos: projeção com os dividendos por ação do Yahoo para posições recentes** `bd617de`  
  A projeção só usava os dividendos recebidos nos últimos 12 meses, por isso posições compradas há pouco (ou que ainda não pagaram desde a compra) ficavam de fora, e podia não haver projeção nenhuma. - Ao atualizar as cotações, guardam-se os dividendos por ação dos últimos ~13 meses de cada posição aberta segundo o Yahoo (eventos "div" do gráfico, também no acesso direto), numa tabela nova. - Na página Dividendos, para cada posição aberta com esses dados, a projeção usa os dividendos por ação do Yahoo × a quantidade atual, nos meses em que foram pagos; as restantes continuam pelos recebidos. A origem aparece ao lado ("(Yahoo)"). - O resumo da atualização diz quantas posições abertas pagam dividendos.
- **Dividendos: projeção do próximo ano no mapa mensal e explicação da projeção** `a934541`  
  - O mapa de rendimento por mês tem uma linha para o próximo ano (ex.: 2027*), com cada posição aberta a pagar nos mesmos meses dos últimos 12, com as quantidades atuais. - Por baixo do gráfico Dividendos por ano, a página diz de que posições vem a projeção, ou porque não há projeção (nenhuma posição aberta pagou dividendos nos últimos 12 meses), em vez de mostrar a barra de 2027 vazia sem explicação.
- **Atualizar cotações: ao voltar à página, o spinner fica no botão que a lançou** `6b23b46`  
  Ao sair das Definições a meio de uma atualização "Só posições abertas" e voltar, o spinner passava para o botão "Atualizar cotações agora" (a página não sabia qual tinha sido usado) e o progresso só aparecia se o pedido calhasse no mesmo processo do servidor. Agora o estado guardado leva também o modo e o progresso (ativo em curso, n/total), e a página escolhe o botão certo e mostra o progresso ao voltar.
- **Definições → Ativos: por omissão só as posições abertas, com filtro à parte para as sem cotações** `c723425`  
  O filtro misturava as posições abertas com os ativos vendidos sem nenhuma cotação, por isso mostrava mais do que as posições abertas (ex.: 18 em vez de 10). Agora há três filtros: Posições abertas (por omissão), Sem cotações (abertas ou vendidas) e Todos, cada um com a sua contagem.
- **Definições → Ativos: o filtro já não inclui vendidos que têm cotações** `cc84f95`  
  O filtro "Posições abertas e sem cotações" usava a lista de ativos sem cotações da última atualização, que pode estar desatualizada e levava ativos vendidos, com cotações, para a lista. Agora um ativo vendido só entra se não tiver nenhuma cotação guardada; as posições abertas entram sempre. Cada linha diz porquê ("· aberta" ou "vendido · sem cotações") e o botão explica a contagem.
- **README: sem as notícias** `75c286c`  
  Atualiza a descrição das páginas e das cotações depois de as notícias terem sido retiradas.
- **Retira as notícias da aplicação e corrige o botão de atualizar a rodar para sempre** `a4023b9`  
  Notícias (a pedido): retiradas da atualização de cotações e do interface (página Notícias, menu, Visão Geral, modo offline). Fica só a atualização de cotações, câmbios, eventos e setor. Saem também o acesso às notícias do Yahoo e do Google Notícias, e a tabela news é apagada por uma migração (versão 3 do esquema, com cópia automática antes). O resumo da atualização mostra agora a fase dos eventos ("[eventos 3/10]").
- **Notícias: não esperar pelo 429 do Yahoo e usar o Google Notícias como alternativa** `8b63064`  
  Do PythonAnywhere o Yahoo responde 429 às notícias (as cotações funcionam), e cada ativo esperava cerca de 15 s por tentativas inúteis. - As notícias do acesso direto tentam só 2 vezes (em vez de 4, com esperas) por ativo. - Depois de 2 ativos seguidos com 429, a fase das notícias pára e o resumo diz que o Yahoo está a limitar os pedidos a partir do servidor. - Se o Yahoo não deu notícias, tenta o feed RSS do Google Notícias pesquisando pelo nome do ativo (a fonte aparece como o jornal).
- **Notícias: RSS da página do ativo como alternativa, e diagnóstico do que cada via devolve** `683c0e5`  
  O Yahoo Finance mostra notícias para ativos como o FINV, mas a atualização trazia 0: nem o yfinance nem a pesquisa do acesso direto as devolviam. - O acesso direto passa a usar também o feed RSS da página do ativo (feeds.finance.yahoo.com) quando a pesquisa vem vazia. - O resumo da atualização diz o que cada via devolveu nos primeiros ativos sem notícias ("yfinance 0; direto 0 (RSS: HTTP 403)"), e cada ativo da fase das notícias mostra o resultado e o tempo. - --testar-yahoo testa também as notícias do AAPL e do FINV.
- **Atualização: contador só dos ativos a atualizar, tempo por ativo e spinner no botão certo** `cba9d96`  
  - Só posições abertas: o contador [n/total] conta apenas essas (e os índices de comparação), não todos os ativos da base de dados. - Cada linha do progresso leva o tempo que o ativo demorou, para se ver qual é o lento (ex.: o Yahoo a limitar os pedidos). - A fase das notícias, eventos e setor, que pede 2 a 3 ligações por posição aberta, também aparece ("[notícias 3/10] VWCE.DE"). - O spinner e o texto de progresso aparecem só no botão em que se carregou; o outro fica apenas desativado.
- **Corrige o teste da atualização em segundo plano para o novo argumento** `51665c3`  
  A função simulada de refresh_all passa a aceitar only_open.
- **Atualizar cotações só das posições abertas** `b2519ca`  
  Nova opção para atualizar apenas os ativos que estão na carteira (e os índices de comparação), sem pedir as posições já vendidas nem os seus câmbios: botão "Só posições abertas" em Definições, --abertas na consola e atualizar-cotacoes.sh --abertas. O botão de sempre continua a atualizar tudo.
- **Cala o aviso de obsolescência do pandas vindo do yfinance** `3416ee2`  
  O yfinance 1.x com o pandas 3.1 emite um Pandas4Warning a cada pedido ("The inplace keyword in DataFrame.sort_index is deprecated"), que o pandas volta a ativar mesmo com PYTHONWARNINGS=ignore. Passa a ignorar-se só os avisos atribuídos ao módulo yfinance, ao carregá-lo.
- **Atualização de cotações mostra cada ativo e o último fecho, em direto** `105d579`  
  refresh_all aceita uma função de progresso, chamada a cada ativo com "[n/total] SÍMBOLO: N cotações · último fecho 227.10 EUR (23/10/2026)". Na consola (--refresh) as linhas aparecem à medida que a atualização avança, em vez de só no fim. O resumo guardado em Definições também passa a incluir o último fecho. O botão Atualizar cotações agora mostra o ativo em curso ("12/280 · VWCE.DE") enquanto corre.
- **Script atualizar-cotacoes.sh para consola e tarefas agendadas** `34d3e1e`  
  Corre a atualização de cotações (--refresh) com o virtualenv e a pasta de dados certos (por omissão ~/.virtualenvs/pi e ~/dados, configuráveis com VENV e PORTFOLIO_DATA_DIR), para usar numa consola Bash ou numa tarefa agendada do PythonAnywhere.

## 2026-10-30

- **Fiscal: resumo por ativo, com as linhas FIFO a pedido e no CSV** (#13) `59edd75`  
  A página gerava uma linha por lote FIFO vendido (mais de 1 100 linhas e 499 KB com um histórico real). Agora mostra uma linha por ativo (linhas, quantidade, realização, aquisição, mais/menos-valia); o botão Lotes abre uma janela com as linhas desse ativo, carregadas a pedido (/fiscal/lotes). O CSV passa a ser gerado no servidor (/fiscal.csv) com todas as linhas FIFO do ano, pela ordem do formulário. Com os dados de teste (900 compras fracionadas) a página passa de centenas de KB para 14 KB.
- **Visão Geral: gráfico de evolução de 314 KB para cerca de 16 KB** (#12) `6ef6199`  
  A página embutia todo o resultado do desempenho (métricas de risco, rendimentos mensais, drawdown…) quando o gráfico só desenha datas, ganho, valor e a variação dos índices. Agora o payload tem só isso, com os valores arredondados (cêntimos nos euros, 5 casas nas variações) e, de 3 anos para cima, só o último dia de cada semana (mais o primeiro e o último pontos). A ação performance, usada pelos botões de período, devolve o mesmo formato. Na página Desempenho, o JSON dos gráficos também é arredondado.

## 2026-10-29

- **Teste do iniciar.bat no Windows: saída visível e limites de tempo** `86564b9`  
  Os passos passam a correr em PowerShell com a saída à vista (Tee-Object) e com limite de tempo, para se perceber onde falha em vez de ficar pendente.
- **iniciar.bat: volta a abrir-se depois de atualizar, e teste no Windows** `e36506d`  
  O cmd lê os .bat por posição no ficheiro; quando a atualização muda o próprio iniciar.bat, continuar a ler o ficheiro trocado podia executar lixo. Agora, depois do git pull, o iniciar.bat abre a versão nova e sai. Também: PORTFOLIO_ATUALIZAR=S atualiza sem perguntar e =N nunca atualiza, e a verificação passa a ser feita fora de blocos para o NOVAS ser lido sempre atualizado.
- **Versão do esquema da base de dados com migrações, e cópias automáticas** (#23, #24) `0ca6115`  
  Migrações (#23): a base de dados guarda a versão do esquema (PRAGMA user_version) e os passos pendentes de migrations.py correm por ordem, cada um numa transação (BEGIN explícito, porque o sqlite3 não abre uma para o DDL). Antes de migrar faz-se uma cópia; se um passo falhar, a base fica como estava e a mensagem diz onde está a cópia. Uma base nova nasce na versão mais recente e uma base de uma versão futura não é aberta. Os dois passos existentes (result, last_quote) são idempotentes, por isso as bases antigas, sem versão, migram sem perdas. Substitui models.migrate().
- **Estado do mercado com feriados e com as bolsas dos EUA** (#26) `1a7049e`  
  O indicador usava só o horário fixo da Euronext, sem feriados, e dava "Fechado" quando a Nasdaq ainda estava aberta. Agora: - calcula os feriados da Euronext/Xetra e da NYSE/Nasdaq (Páscoa, feriados móveis e a regra do fim de semana), com sessões reduzidas nos EUA a 24 de dezembro e na sexta a seguir ao Dia de Ação de Graças; - o horário dos EUA vem de Nova Iorque (9:30-16:00), por isso acompanha as semanas em que as horas de verão não coincidem; - mostra as bolsas onde há posições abertas (sufixo .US, sem sufixo ou em USD = EUA; as restantes = Europa), por exemplo "Europa: fechado · EUA: aberto até às 21:00".
- **Definições → Ativos: filtro, pesquisa e estado das cotações** (#15) `865c439`  
  Com um histórico real eram cerca de 280 formulários numa só página. Agora, por omissão, só se mostram as posições abertas e os ativos sem cotações, com um botão "Todos" e uma caixa de pesquisa (ticker, nome ou ISIN; ?ativo=XXX abre a pesquisa já preenchida). Cada linha mostra o último fecho e a data, ou "sem cotações".
- **Remove importação sem uso nos testes** `c060074`  
  Apanhado pelo ruff na integração contínua.
- **Atualização de cotações incremental (só os dias em falta)** (#11) `9cc064a`  
  Cada atualização pedia o histórico completo de todos os ativos. Agora: - guarda-se o último fecho obtido com o símbolo validado (last_quote) e pedem-se só os últimos dias (com 5 dias de folga para correções); - posições fechadas cujas cotações já cobrem a última transação não se pedem; - a pesquisa completa de símbolos só corre para ativos por validar, com o símbolo alterado, com transações mais antigas do que as cotações guardadas ou depois de um desdobramento; - os câmbios também pedem só os dias novos. O resumo da atualização indica quantos ativos foram incrementais.
- **Remove uv.lock criado por engano** `56e74d0`  
  Ficheiro gerado ao testar com uv; não faz parte do projeto.
- **Integração contínua: testes e ruff no GitHub Actions** (#16) `0ff813b`  
  Workflow que corre o pytest em Python 3.10 e 3.13, em Linux e Windows, e o ruff (erros de sintaxe, importações e nomes por usar) em cada push e pull request. Configuração do ruff no pyproject.toml, distintivo no README e correção dos 5 avisos que o ruff apontou (variável l, importação sem uso).
- **Substitui datetime.utcnow e utcfromtimestamp, obsoletos desde o Python 3.12** (#19) `133236c`  
  Usa datetime.now(timezone.utc) e datetime.fromtimestamp(ts, timezone.utc), guardando as datas sem fuso para manter a compatibilidade com os dados já gravados no SQLite.
- **Unificar o mesmo título com dois tickers (XTB e Trade Republic)** (#3) `59e77db`  
  Os ativos da XTB não têm ISIN e a Trade Republic usa o ISIN como ticker, por isso o mesmo ETF aparecia como dois ativos, um deles sem cotações. Agora: - ao atualizar as cotações, se um ativo com o ISIN como ticker se resolve para o símbolo de outro ativo na mesma moeda, os dois são juntados (transações e alertas passam para o ativo da bolsa, que fica com o ISIN; as novas importações da Trade Republic já caem nele); - em Definições → Ativos há também "Juntar X em Y" para o fazer à mão.
- **Cópia de segurança gerada com a API de backup do SQLite** (#10) `6327ad0`  
  O botão enviava o ficheiro da base de dados em uso; com uma atualização de cotações ou importação a escrever, a cópia podia ficar a meio. Agora a cópia é gerada com sqlite3.Connection.backup, consistente mesmo com escritas em curso, e enviada a partir de um ficheiro temporário.
- **Venda manual acima da quantidade detida é recusada** (#9) `7ae12c9`  
  add_transaction só validava quantity > 0. Uma venda (ou transferência/ conversão de saída) acima do que se tem na data era aceite e o motor tratava a diferença como posição anterior ao histórico, com um aviso enganador. Agora responde "Só tens X unidades de ATIVO em dd/mm/aaaa." As importações continuam a aceitar o caso (posições anteriores ao histórico).
- **Apagar tudo limpa também o estado da atualização de cotações** (#8) `60aefab`  
  reset_data só limpava as definições broker e demo; ficavam last_refresh, refresh_* e hide_banner, e o aviso "Ainda não atualizaste as cotações" deixava de aparecer depois de apagar todas as cotações.
- **API: mensagens em vez de erro 500 em entradas inválidas** (#7) `cf4f524`  
  Renomear uma corretora para um nome existente e pedir o desempenho com índices que não são JSON válido davam erro 500. Agora respondem com uma mensagem. A conversão de TypeError em "Faltam dados no pedido." passa a ser só a verificação dos argumentos antes de chamar a ação, para não esconder erros de programação.
- **Scripts de arranque reinstalam as dependências em falta** (#6) `2e09db9`  
  iniciar.sh e iniciar.bat só instalavam quando a pasta .venv não existia: uma instalação interrompida, ou uma dependência nova numa versão nova, deixava a aplicação sem arrancar (ModuleNotFoundError). Agora um marcador (cópia de requirements.txt, criada só no fim da instalação) faz reinstalar se faltar ou se a lista mudar. O iniciar.bat deixa de reinstalar à parte depois da atualização.
- **Fiscal: o crédito de imposto estrangeiro é limitado a cada dividendo** (#4) `354e031`  
  O crédito por dupla tributação era calculado sobre os totais do ano, por isso a retenção acima de 28% num dividendo (ex.: 30% nos EUA) abatia o imposto de outros dividendos e a estimativa ficava abaixo do devido. Agora soma-se, dividendo a dividendo, max(bruto x 28% - retenção, 0).
- **Seletor de corretoras conta as posições abertas como a Carteira** (#5) `b063c9d`  
  O seletor só somava compras e vendas, por isso ações transferidas, conversões e desdobramentos contavam como posições abertas. Agora usa as posições abertas do próprio motor (já em cache entre pedidos).
- **Importação: linhas iguais no mesmo dia já não são descartadas** (#2) `392ec11`  
  Sem identificador, duas ordens iguais no mesmo ficheiro (planos de investimento, ordens em partes) ficavam com a mesma impressão digital e a segunda era descartada como duplicada. Agora as repetidas juntam o nº de ordem; a primeira mantém a impressão de sempre, por isso reimportar o mesmo ficheiro continua a ser detetado como duplicado.
- **Transferências e conversões manuais já têm ativo** (#1) `e950cd6`  
  O formulário só associava o ativo a compras, vendas e dividendos; uma transferência ou conversão gravada sem ativo dava erro 500 em todas as páginas. Agora a API associa o ativo (e exige ticker e quantidade) nos sete tipos que o precisam, e o motor ignora, com aviso, transações de ativo sem ativo já gravadas.

## 2026-10-27

- **iniciar.bat: atualiza por omissão passados 10 segundos** `22bff42`  
  Antes, sem resposta à pergunta, assumia N e a atualização nunca acontecia num duplo clique. Agora só a resposta N a salta.

## 2026-10-26

- **XTB: extrato de um período curto já não duplica as posições** `3d978be`  
  As posições abertas (ou vendidas) cuja compra é anterior ao início do extrato ("Date from (UTC)") eram tratadas como ações recebidas de outra corretora, somando-se às compras já importadas. Agora ficam ignoradas quando a corretora já tem histórico; na primeira importação continuam a entrar como transferências.

## 2026-10-25

- **iniciar.bat: verifica atualizações ao arrancar (git clone)** `691313c`  
  Com a pasta instalada por git clone, faz git fetch e, se houver versão nova, pergunta se deve atualizar (S/N; sem resposta em 10 s arranca a versão atual). Atualiza com git pull --ff-only e reinstala as dependências. Sem git, sem internet ou com ficheiros alterados, arranca na mesma. .gitattributes mantém os .bat com fins de linha CRLF.
- **PWA: consulta offline das últimas páginas (Disponível offline)** `b21981f`  
  - Nova opção em Definições, desligada por omissão: as páginas de consulta ficam guardadas pelo service worker (cabeçalho X-PM-Offline) e podem ser vistas com a aplicação parada, só para leitura. - Faixa "Modo offline" com a data dos dados; ações bloqueadas com aviso; recarrega sozinha quando a aplicação volta (/ping). - Desligar a opção ou sair apaga a cópia. - offline.html lista as páginas guardadas. - Arranque: SO_REUSEADDR na deteção de porta ocupada (evita falsos "porta ocupada" logo após reiniciar).
- **Desempenho: taxa sem risco, períodos completos e aviso sem cotações** `e6b8171`  
  - Taxa sem risco de 2% ao ano por omissão (era 0%, o que inflacionava o Sharpe, o Sortino e o alfa), ajustável em Definições → Dados de mercado (ação set_risk_free, 0 a 20%). A ajuda do Sharpe mostra a taxa usada. - O mês e o ano em curso deixam de contar para o melhor/pior mês e ano e para a sequência atual (só períodos completos). - Sem cotações de mercado, o aviso na página Desempenho explica que a volatilidade, o drawdown, o Sharpe e a comparação com o mercado ficam distorcidos. - Testes e README.
- **Desempenho: índices em euros e volatilidade só com dias úteis** `bfd622e`  
  - Os índices de referência (S&P 500, Nasdaq 100, MSCI World) eram comparados na moeda deles (dólares) com a carteira em euros. Uma carteira igual ao S&P 500 aparecia 20 pontos abaixo do índice num ano em que o dólar caiu 20%. Passam a ser convertidos para euros ao câmbio de cada dia: gráfico, TWR e CAGR dos índices, mérito (alfa, beta, captura, meses acima do mercado) e "Carteira vs mercado". - A volatilidade (e com ela Sharpe e Sortino) contava os pontos do fim de semana, que existem quando há juros diários, como dias de bolsa com variação nula. Com 365 pontos por ano anualizados com 252, ficava ~16% abaixo do real. Passa a usar só dias úteis. - Testes das duas correções; README e ajuda de "Carteira vs mercado".
- **Logótipo da Trade Republic e contorno nos logótipos** `12963be`  
  - Logótipo da Trade Republic (fica completo o conjunto: Trading 212, XTB e Trade Republic). - Contorno subtil à volta dos logótipos, para os de fundo branco não se confundirem com os cartões no modo claro.
- **Logótipo da XTB** `bc11018`
- **Logótipos das corretoras (Trading 212)** `65b00ac`  
  - O seletor de corretoras e os cartões da página Importar mostram o logótipo da corretora quando existe em static/icons/brokers/<chave>.svg ou .png (trading212, xtb, traderepublic); as outras continuam com a letra inicial. - A corretora é reconhecida pelo nome, para o logótipo aparecer também em corretoras criadas na importação com um nome próprio. - Primeiro logótipo: Trading 212.
- **Yahoo sem yfinance: tentativas, autorização e motivo das falhas** `bdafabc`  
  Sem o yfinance (Android), nenhum ativo recebia cotações e o resumo só dizia "sem cotações", porque os erros de cada pedido eram descartados.
- **Cotações sem yfinance: acesso direto ao Yahoo Finance (Android)** `1da3caf`  
  No Android/Termux o yfinance não instala (a dependência curl_cffi não suporta o processador: "Unsupported arch ... armv8l"), por isso não havia forma de atualizar cotações e os valores usavam os preços das transações.
- **Arranque: escolhe uma porta livre quando a 5000 está ocupada** `caf5ca6`  
  Mesmo depois de parar a aplicação, a porta 5000 pode continuar ocupada por outro processo (ex.: uma sessão da versão anterior ou outra aplicação do Android), e o arranque falhava.
- **Arranque: não falha quando a aplicação já está a correr** `034e4ad`  
  Arrancar uma segunda vez (ex.: no Termux, com uma sessão anterior ainda em segundo plano) terminava com "OSError: [Errno 98] Address already in use".
- **Corrige os botões para esconder e mostrar a barra lateral** `3c983e1`  
  - Com a barra recolhida (76 px), os botões do fundo ficavam lado a lado e o de expandir ficava fora da barra, sem forma de a voltar a abrir (pior ainda com o botão Sair, quando há palavra-passe). Passam a ficar em coluna, só com o ícone. - No telemóvel, a barra aberta tapava o botão ☰ e não havia forma de a fechar sem escolher uma opção. Agora fecha com o botão ✕ no topo da barra, tocando fora dela (fundo escurecido) ou com a tecla Esc.
- **Importar extratos pela linha de comandos (--importar)** `db44fec`  
  No Android, escolher o ficheiro no browser pode levar o sistema a suspender o Termux, e a importação falha sem ligação à aplicação.
- **Importar: lê o ficheiro antes de enviar e explica falhas de ligação** `78161af`  
  No Android, escolher um extrato e importar podia acabar só com "Failed to fetch", sem explicação. Acontece quando o Termux é suspenso ou fechado enquanto o seletor de ficheiros está aberto, ou quando o browser não consegue ler o ficheiro (ex.: ficheiro do Google Drive que não está no telemóvel, ou alterado depois de escolhido).
- **Corrige o arranque sem base de dados de fusos horários (Android/Termux)** `0a8fa87`  
  No Termux (e no Windows, quando o yfinance não é instalado) não existe a base de dados de fusos horários do sistema, e ZoneInfo("Europe/Lisbon") fazia a aplicação falhar logo ao arrancar com ZoneInfoNotFoundError.
- **Muda o nome da aplicação para Portfolio Investimentos** `7f0cb2a`  
  - Nome mostrado (títulos, login, aplicação instalável, README, NOTICE e scripts de arranque): Portfolio Investimentos. Na barra lateral fica em duas linhas, para caber. - Pacote Python portfolio_manager → portfolio_investimentos; comando python -m portfolio_investimentos e portfolio-investimentos. Os scripts iniciar.* continuam a funcionar da mesma forma. - Pasta de dados no macOS/Linux: ~/.portfolio-investimentos. A pasta ~/.portfolio-manager das versões anteriores muda de nome sozinha, como já acontecia no Windows. - Service worker com versão nova, para os browsers largarem a cache antiga. - Capturas de ecrã do README geradas de novo com o nome novo.
- **Muda a pasta de dados no Windows para PortfolioInvestimentos** `ebe6328`  
  - Os dados passam a ficar em %APPDATA%\PortfolioInvestimentos. - Na primeira execução, a pasta PortfolioManager das versões anteriores muda de nome automaticamente; se não for possível (ex.: ficheiro aberto noutro programa), continua a ser usada, para não se perderem dados. - README atualizado e teste da mudança de nome.
- **Portfolio Manager** `1164a8e`  
  Gestor de carteira de investimentos local: desempenho, dividendos, fiscalidade (PT) e importação de extratos da Trading 212, XTB e Trade Republic. Corre no próprio computador (Flask + SQLite), com interface Bootstrap em modo claro e escuro, login opcional com palavra-passe, instalação como PWA e script para Android (Termux).
- **Initial commit** `6e09c29`
