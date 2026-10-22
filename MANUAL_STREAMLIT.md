# Manual do painel Streamlit — Análises da Pizzaria

## O que o painel entrega

O painel do Projeto Integrador IV reúne métricas úteis para a gestão de uma pizzaria: receita bruta estimada, quantidade de pizzas, pedidos, valor médio por pedido, desempenho por categoria e tamanho, horários de maior movimento, indicadores de ingredientes associados às receitas vendidas e previsão de demanda para sete dias.

**O painel agora usa como fonte padrão as sete tabelas normalizadas pelo ETL:** `orders`, `order_details`, `pizzas`, `pizza_types`, `categories`, `ingredients` e `pizza_type_ingredients`. Elas são materializadas em `data/normalized/` e relacionadas pelas chaves e cardinalidades do modelo do grupo antes de formar os gráficos. O ETL, o esquema SQL e os CSVs originais foram preservados.

## Instalação e abertura

### Ambiente validado pelo grupo

O grupo executou o fluxo completo em Windows usando WSL2 Ubuntu, Docker Desktop com a integração WSL habilitada, GNU Make, VS Code e navegador. O VS Code é opcional: os comandos e o painel também podem ser usados pelo terminal e pelo navegador.

### Fluxo completo em Docker

No ambiente validado pelo grupo, abra um terminal WSL Ubuntu com Docker Desktop ativo e integrado, depois clone e inicie o projeto:

    git clone https://github.com/aldalisgomes/projeto_semestre
    cd projeto_semestre
    make all

O alvo inicia o SQL Server, executa o ETL, exporta as sete tabelas normalizadas e abre o Streamlit no navegador em http://localhost:8501. O primeiro uso pode demorar enquanto o Docker baixa as imagens e constrói a aplicação. O contêiner da aplicação já inclui Python, dependências do projeto e ODBC, então não é necessário instalar Python ou ODBC no WSL para esse fluxo.

O grupo também validou a conexão e a consulta 6.4 no SQL Server pelo Streamlit. No teste, o ETL auditou os dados, carregou as sete tabelas e exportou os CSVs normalizados. Esses resultados descrevem o teste feito em WSL; o grupo não testou uma instalação Linux nativa.

### Linux nativo

O Makefile também foi preparado para Linux nativo x86-64: use Git, GNU Make, Bash, Docker Engine e o complemento Docker Compose v2. Docker Desktop e VS Code não são obrigatórios nesse cenário. A imagem de SQL Server usada pelo projeto é destinada a computadores x86-64; ARM com emulação não faz parte do caminho suportado pela Microsoft. Em Linux sem interface gráfica, abra http://localhost:8501 manualmente depois que o servidor iniciar.

### Apenas abrir o painel localmente

Para usar os CSVs normalizados sem executar o ETL no SQL Server, instale as dependências Python locais e inicie o painel:

    make setup
    make dashboard

Esse caminho local exige Python. A conexão SQL Server local também exige o driver ODBC do sistema; se ele não estiver instalado, use a fonte Base normalizada do projeto ou rode o fluxo Docker acima.

## Comandos do Makefile

Use os comandos abaixo na raiz do repositório. Em WSL, o Docker Desktop precisa estar integrado à distribuição Ubuntu; em Linux nativo x86-64, use Docker Engine e Docker Compose v2. Para o fluxo completo validado pelo grupo, execute make all.

| Comando | O que faz |
| --- | --- |
| `make help` | Lista os alvos disponíveis. |
| `make setup` | Cria `.venv` e instala `requirements.txt`. |
| `make db-up` | Sobe o SQL Server e aguarda a mensagem de prontidão. |
| `make run` | Constrói a imagem e executa o ETL existente no SQL Server. |
| `make normalize` | Executa `src/04_exportar_base_normalizada.py` e atualiza as sete tabelas CSV. |
| `make dashboard` | Atualiza as tabelas, inicia o Streamlit local sem interface gráfica e abre o navegador quando a porta `8501` responde. |
| `make dashboard-docker` | Inicia/aguarda o SQL Server, exporta os CSVs com o contêiner da aplicação e executa o Streamlit sem interface gráfica no Docker; abre o navegador após a porta `8501` responder e não exige Python/ODBC no WSL. |
| `make all` | Executa em sequência: banco, ETL, exportação normalizada no contêiner e painel Docker. |
| `make db-down` | Para e remove o contêiner e a rede do SQL Server, preservando o volume nomeado com os dados. |
| `make clean` | Remove arquivos temporários de cache do Python. |

**Cuidado com `make run` e `make all`:** o ETL atual executa o DDL de referência, que recria o banco `PizzaSales`. Use-os em uma base de demonstração ou teste e proteja antes qualquer dado que precise ser mantido. Para abrir o painel com os CSVs normalizados, `make dashboard` é suficiente e não executa o ETL do SQL Server.

## Aba Consultas SQL

A aba **Consultas SQL** lê automaticamente `03_analysis_queries.sql` da raiz e separa as consultas numeradas, de `1.1` até `6.4`. A lista suspensa permite escolher uma delas; a interface exibe o SQL com realce de sintaxe e a tabela retornada.

- Com **Banco SQL Server normalizado** selecionado, a consulta é executada diretamente no banco `PizzaSales`.
- Com uma `PIZZA_DATABASE_URL` acessível e as sete tabelas do projeto disponíveis, o painel também usa o SQL Server.
- Sem SQL Server acessível, a interface carrega `categories`, `pizza_types`, `ingredients`, `pizza_type_ingredients`, `pizzas`, `orders` e `order_details` de `data/normalized/` em um SQLite temporário na memória. O `SELECT TOP N` do T-SQL é convertido para `LIMIT N` nessa execução local.

A alternativa local exige as sete tabelas exportadas. Execute `make normalize` caso estejam ausentes ou desatualizadas. A aba consulta a base do projeto e não aplica os filtros de período/categoria/tamanho da barra lateral nem os CSVs externos enviados.

## Usar dados de outra pizzaria com um CSV

Para uma pizzaria que ainda registra poucas informações, escolha **Enviar CSV único da pizzaria** no menu lateral. Basta exportar um arquivo CSV com duas colunas obrigatórias:

| Coluna | O que registrar |
| --- | --- |
| data ou date | Dia da venda, preferencialmente no formato AAAA-MM-DD (por exemplo, 2026-10-20). |
| quantidade ou quantity | Número de pizzas vendidas naquela linha; use zero para dia sem venda ou fechado. |

O painel também reconhece pedido_id/order_id, hora/time, produto/product, tamanho/size, preco_unitario/unit_price, categoria/category e ingredientes/ingredients. São opcionais: cada coluna habilita apenas as análises que ela sustenta. Sem preço não há receita; sem identificador de pedido não há total de pedidos nem valor médio por pedido; sem horário não há análise intradiária; sem produto, categoria ou tamanho não há detalhamento de cardápio. O arquivo é validado e usado em memória nesta sessão, sem alterar o banco ou os CSVs do projeto e sem aplicar regras inventadas de receita.

As linhas podem representar itens vendidos (um sabor por linha, com a quantidade daquela linha) ou totais diários. Registre corretamente a quantidade e não use um preço de linha inteira como se fosse preço unitário. O botão **Baixar modelo de CSV** no painel fornece um exemplo. Com apenas data e quantidade já é possível ver evolução diária.

Para habilitar a previsão, selecione um período com pelo menos 56 dias consecutivos registrados. Inclua uma linha para cada dia entre a primeira e a última data, usando quantidade zero nos dias sem venda ou em que a pizzaria ficou fechada. Se o CSV tiver lacunas, a previsão é suspensa para não confundir falta de registro com zero vendas. Um histórico menor ainda permite visualizar vendas, mas não sustenta a previsão com a validação atual.

Receita, pedidos, cardápio, horários e ingredientes ficam indisponíveis ou incompletos quando os campos correspondentes não são fornecidos. O painel não estima valores ausentes. Mesmo com preço, a métrica é receita bruta, não lucro; para medir lucro, estoque ou consumo real de ingredientes seriam necessários custos e quantidades por receita.

### Importação estruturada em quatro CSVs

Para exportações que já separem pedidos, itens e cardápio, escolha **Enviar quatro CSVs da pizzaria** e forneça:

| Arquivo | Campos obrigatórios |
| --- | --- |
| `orders.csv` | `order_id`, `date`, `time` |
| `order_details.csv` | `order_id`, `pizza_id`, `quantity` |
| `pizzas.csv` | `pizza_id`, `pizza_type_id`, `size`, `price` |
| `pizza_types.csv` | `pizza_type_id`, `name`, `category` |

O campo `ingredients` em `pizza_types.csv` é opcional; sem ele, o painel mostra as demais análises e informa que a aba de ingredientes não está disponível. Quando ele existe, o painel separa a lista por vírgulas, remove espaços extras e padroniza `Artichoke` como `Artichokes`. Também separa categorias em uma dimensão própria e representa ingredientes e receitas pela dimensão `ingredients` e pela tabela associativa `pizza_type_ingredients`.

No envio de CSVs, a opção **Aplicar regras de receita do ETL deste projeto** vem marcada para reproduzir o ETL da base usada pelo grupo: incluir `Mozzarella Cheese` em todas as receitas e `Tomato Sauce` nas receitas que não indicam outro molho. Como essas duas regras podem não representar a ficha técnica de outra pizzaria, desmarque a opção se não forem verdadeiras para o cardápio enviado. Na base de exemplo local, as regras do projeto são aplicadas automaticamente. A normalização é feita em memória e não grava alterações nos arquivos.

Essas transformações não alteram os CSVs enviados nem gravam dados no banco. As chaves precisam corresponder entre os arquivos. O painel valida chaves, quantidades, preços, datas e horários; sinaliza linhas órfãs e exclui dos gráficos aquelas que não podem ser relacionadas. Datas fora de 2015 e tamanhos fora do padrão do esquema de referência são contabilizados, mas não bloqueiam a análise, para permitir históricos atuais e cardápios de outras pizzarias. Abra **Qualidade dos dados e interpretação** no painel para ver a contagem de categorias, tipos, ingredientes, relações tipo-ingrediente e as regras aplicadas. `order_details_id` é verificado quando o CSV o fornece.

A previsão de demanda agrega a quantidade diária de pizzas. Na importação simples, ela exige pelo menos 56 dias consecutivos registrados e não roda se houver datas ausentes; inclua todos os dias e use quantidade zero para dias sem venda ou fechamento. Ingredientes não são variáveis de entrada: o alvo é quantidade, e não receita, lucro ou consumo físico. O algoritmo independente em src/02_regressao_linear_vendas_diarias.py também aceita somente date,quantity, como descrito em MANUAL_REGRESSAO_LINEAR.md.

## Conectar ao SQL Server

O painel também oferece a opção **Banco SQL Server**. Essa conexão faz somente consultas `SELECT` ao esquema normalizado `PizzaSales`; o painel não grava nem altera dados.

Configure `PIZZA_DATABASE_URL` antes de iniciar o Streamlit. Exemplo no PowerShell, substituindo os marcadores pelos dados locais:

```powershell
$env:PIZZA_DATABASE_URL = "mssql+pyodbc://USUARIO:SENHA@localhost:1433/PizzaSales?driver=ODBC+Driver+17+for+SQL+Server&TrustServerCertificate=yes"
streamlit run src/03_streamlit_dashboard.py
```

Se a senha tiver caracteres reservados em uma URL, codifique-os para URL. O driver ODBC do SQL Server precisa estar instalado na máquina. Não coloque senhas no código nem em arquivos versionados.

Se selecionar essa fonte em WSL e aparecer erro de libodbc.so.2, a conexão local não encontrou unixODBC. Quando data/normalized/ está disponível, o painel avisa e continua com os CSVs normalizados do projeto; isso não significa que o SQL Server conectou. Para usar SQL Server sem instalar ODBC no WSL, rode make all e abra o painel Docker, com Docker Desktop integrado ao WSL e o banco de demonstração preparado pelo ETL.

## Como ler os resultados

- **Receita bruta** usa preço de venda multiplicado pela quantidade. O seletor de moeda altera apenas o símbolo; não converte valores. A base pública de exemplo tem preços em dólares.
- **Valor médio por pedido** é a receita bruta dividida pelo número de pedidos distintos no período.
- **Picos de demanda** usa a data e a hora registradas no pedido. Ajuda a visualizar períodos movimentados, mas não mede tempo de preparo ou capacidade real da cozinha.
- **Ingredientes** conta pizzas vendidas cujas receitas listam cada ingrediente. Um mesmo ingrediente pode aparecer em receitas de muitas pizzas; esse indicador não equivale a gramas, estoque ou custo consumido.
- **Previsão** usa o modelo de regressão existente, requer pelo menos 56 dias no intervalo selecionado e compara o erro com repetir a venda do mesmo dia da semana anterior (`lag_7d`). A previsão começa no dia seguinte ao fim do intervalo.

## Por que os gráficos podem continuar com números parecidos

A normalização reorganiza os dados em sete tabelas relacionadas e reduz repetição e inconsistências de cadastro. Ela não deveria alterar a quantidade de pizzas vendidas nem a receita quando as chaves e os valores estão corretos. Por isso, indicadores agregados como vendas por dia, receita ou pizzas por categoria podem manter os mesmos resultados: o painel reconstrói essas métricas por meio dos relacionamentos entre as tabelas normalizadas. A diferença principal está na estrutura, na integridade e na possibilidade de analisar categorias e ingredientes com relacionamentos consistentes; não em mudar artificialmente os números da operação. A aba **ETL e modelo** evidencia as tabelas, seus volumes e os relacionamentos usados.

## Limites para apresentar o projeto

A base do projeto é uma amostra histórica de 2015. Ela serve para demonstrar o pipeline e o painel, não para orientar compras atuais. Cada pizzaria precisa carregar seus próprios dados recentes.

A base contém preços e vendas, mas não contém custo por ingrediente, quantidade de ingrediente por receita, desperdício, descontos detalhados ou custo de mão de obra. Portanto, o painel calcula **receita bruta**, não lucro ou margem de contribuição. Para responder à pergunta de rentabilidade real levantada na conversa com a pizzaria, seria necessário cadastrar fichas técnicas com gramagem, custo atualizado dos insumos e outros custos operacionais.
