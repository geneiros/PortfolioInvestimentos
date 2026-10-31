# Histórico de alterações

O que mudou em cada commit, do mais recente para o mais antigo (gerado a partir das mensagens dos commits). Os números entre parênteses são as issues do GitHub resolvidas.

## 2026-10-31

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
