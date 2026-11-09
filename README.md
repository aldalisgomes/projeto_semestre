# Painel de Análise de Dados para Pizzarias

Projeto Integrador IV da UNIVESP, desenvolvido em Python, SQL e Streamlit. O projeto começou com o conjunto público Pizza Place Sales, utilizado para desenvolver a modelagem relacional, o ETL, as consultas SQL e as análises. Depois, o painel foi ampliado para permitir que outras pizzarias analisem seus próprios arquivos CSV. O conjunto VENDAS_PIZZARIA_BAIRRO.csv é o estudo de caso dessa ampliação.

As fontes são independentes. Pizza Place Sales é uma base pública de demonstração, com registros de 2015. VENDAS_PIZZARIA_BAIRRO.csv contém os dados do estabelecimento usado no estudo de caso, com sua identidade comercial omitida. Um arquivo carregado pelo usuário constitui uma terceira fonte independente.

## Executar as consultas SQL no VS Code

Esta seção apresenta o caminho completo para clonar o projeto no Windows com WSL2/Ubuntu, iniciar o SQL Server pelo Docker, carregar a base pública e executar as consultas no VS Code. Os comandos de terminal devem ser executados no Ubuntu/WSL, na pasta do projeto. O VS Code é usado para editar e executar o arquivo SQL.

### 1. Pré-requisitos

- Windows 10/11 com WSL2 e uma distribuição Ubuntu.
- Docker Desktop configurado para usar containers Linux e com integração habilitada para Ubuntu em Settings > Resources > WSL Integration.
- Git, GNU Make e Bash disponíveis no Ubuntu.
- Visual Studio Code para Windows e a extensão WSL da Microsoft.
- Extensão SQL Server (mssql), da Microsoft, instalada no VS Code. Em uma janela conectada ao WSL, instale-a também no ambiente WSL, se o VS Code solicitar.

Documentação oficial: [instalar WSL](https://learn.microsoft.com/windows/wsl/install/), [desenvolver no WSL com VS Code](https://code.visualstudio.com/docs/remote/wsl), [integração WSL do Docker Desktop](https://docs.docker.com/desktop/features/wsl/) e [extensão MSSQL para VS Code](https://learn.microsoft.com/sql/tools/visual-studio-code-extensions/mssql/mssql-extension-visual-studio-code).

Abra Ubuntu e confira se as ferramentas estão disponíveis:

~~~bash
git --version
make --version
docker version
docker compose version
~~~

Em docker version, confira se aparecem informações do cliente e do servidor. Se docker não conseguir falar com o servidor, abra o Docker Desktop no Windows e habilite a integração com Ubuntu antes de continuar. Se make estiver ausente, instale-o no Ubuntu:

~~~bash
sudo apt update
sudo apt install -y git make
~~~

### 2. Clonar a branch de entrega e abrir no VS Code

Execute no terminal Ubuntu. O exemplo guarda o clone no sistema de arquivos Linux do WSL, em vez de uma pasta montada do Windows.

~~~bash
mkdir -p ~/projetos
cd ~/projetos
git clone --branch versao-final --single-branch https://github.com/aldalisgomes/projeto_semestre.git
cd projeto_semestre
code .
~~~

O VS Code deve abrir uma janela conectada ao WSL. Confirme o indicador WSL: Ubuntu no canto inferior esquerdo. O terminal integrado dessa janela também será Ubuntu; os comandos abaixo podem ser executados nele ou no terminal Ubuntu separado.

### 3. Configurar a senha local do SQL Server

Na raiz do clone (ainda no terminal do Ubuntu), crie a configuração local a partir do modelo:

~~~bash
cp .env.example .env
nano .env
~~~

#### Preencher as três referências à senha

No template deste projeto, a variável principal chama-se MSSQL_SA_PASSWORD. Localize-a com as setas do teclado no nano e substitua o valor de exemplo pela senha que deseja usar. Alguns projetos usam nomes como DB_PASSWORD, mas este projeto utiliza MSSQL_SA_PASSWORD.

O arquivo também contém duas URLs opcionais para conexão direta do Streamlit ao SQL Server. Se quiser usar essa conexão, coloque a mesma senha nas três configurações:

1. MSSQL_SA_PASSWORD.
2. PIZZA_DATABASE_URL.
3. PIZZA_DATABASE_URL_DOCKER.

Nas duas URLs, a senha fica entre sa: e @. Como esses campos são URLs, caracteres especiais precisam ser codificados. Por exemplo, o caractere ! deve aparecer como %21. Ao substituir o valor de exemplo, atualize ou remova o %21 conforme a senha escolhida; se a senha tiver outros caracteres especiais, codifique-os também. Assim, não deixe nas URLs uma senha diferente da variável MSSQL_SA_PASSWORD.

Para salvar no nano, pressione Ctrl+O, Enter para confirmar o nome do arquivo e Ctrl+X para sair. Para conferir as linhas localmente, execute:

~~~bash
cat .env
~~~

Confira se MSSQL_SA_PASSWORD contém a senha escolhida e se, nas URLs, ela aparece entre sa: e @. A saída mostra os valores locais do arquivo; não publique nem envie esse conteúdo.

#### Requisitos da senha

Por padrão, a senha do SQL Server deve ter entre 8 e 128 caracteres e incluir caracteres de pelo menos três destes quatro grupos:

- Letras maiúsculas (A a Z).
- Letras minúsculas (a a z).
- Números (0 a 9).
- Símbolos ou caracteres especiais, como _, - e !.

Se a senha não atender a essa política, o container pode não concluir a inicialização. Consulte a [política de senha para containers do SQL Server](https://learn.microsoft.com/sql/linux/containers/deploy?view=sql-server-ver16).

Anote a senha configurada: você precisará informá-la no perfil de conexão do VS Code. Não publique o arquivo .env nem reutilize uma senha de outro serviço. O arquivo .env é ignorado pelo Git.

Para executar as consultas no VS Code, basta a variável MSSQL_SA_PASSWORD. As variáveis PIZZA_DATABASE_URL e PIZZA_DATABASE_URL_DOCKER são opcionais e servem para o Streamlit se conectar diretamente ao SQL Server; não são usadas pelo perfil de conexão manual do VS Code. Se alterar a senha e quiser essa conexão direta no painel, atualize as URLs com a senha codificada para uso em URL. Para o painel com os CSVs normalizados, essas URLs podem ficar vazias.

### 4. Verificar se já há recursos com os nomes do projeto

O Compose e o Makefile usam o nome de projeto vesuvio, o container vesuvio_sql_server e o volume vesuvio_vesuvio_sqlserver_data. O volume persiste o banco entre inicializações. Em uma máquina sem uma execução anterior do projeto, não deve haver recursos existentes com esses nomes.

Antes de carregar o banco, confira:

~~~bash
docker ps -a --filter name=vesuvio_sql_server --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
docker volume ls --filter name=vesuvio_vesuvio_sqlserver_data
~~~

Se já existir esse container ou volume, verifique se é o ambiente descartável deste projeto antes de prosseguir. Não execute o carregamento abaixo sobre um SQL Server ou volume que contenha dados que você queira preservar.

Se você já tiver o container deste projeto e quiser apenas consultar o banco existente, não execute make run. Conecte-se ao SQL Server em localhost, porta 1433, usando a senha originalmente configurada. No VS Code, comece pelo banco master e consulte:

~~~sql
SELECT name
FROM sys.databases
ORDER BY name;
~~~

Se PizzaSales já existir e contiver as tabelas do projeto, siga diretamente para as etapas de conexão e execução das consultas. O alvo make run é necessário somente para criar/recarregar a base pública em uma instância descartável.

### 5. Iniciar o SQL Server e carregar a base pública

Na raiz do repositório, execute:

~~~bash
make help
make run
~~~

make run depende de make db-up: inicia o SQL Server pelo Docker Compose, aguarda o serviço ficar pronto, constrói a imagem do ETL e carrega os dados públicos. Na carga, o script executa 02_create_tables_reference.sql, que contém DROP DATABASE IF EXISTS PizzaSales. Portanto, make run apaga e recria somente o banco PizzaSales no SQL Server ao qual o container se conecta. Use-o apenas em uma instância local descartável ou quando aceitar substituir esse banco. Não execute esse alvo em um banco de produção ou em um volume com dados que queira manter.

Ao final, o ETL deve informar a conclusão da carga. A base contém 21.350 pedidos e 48.620 itens em order_details. O serviço SQL Server também fica acessível do Windows/WSL pela porta local 1433. Dentro da rede Docker, o nome do serviço é pizza_sql_server; no VS Code, use localhost e a porta publicada.

Se make run falhar porque a porta 1433 já está ocupada, confira os containers com docker ps -a. Não inicie dois SQL Servers que publiquem simultaneamente a mesma porta.

### 6. Conectar o VS Code ao banco

1. No VS Code aberto na janela WSL, instale SQL Server (mssql), da Microsoft. Abra a área de extensões e confira se aparece instalada em WSL: Ubuntu.
2. Abra a paleta de comandos com Ctrl+Shift+P e execute MS SQL: Connect.
3. Crie um perfil de conexão com estes valores:
   - Server name: localhost
   - Port: 1433
   - Authentication type: SQL Login
   - User name: sa
   - Password: o mesmo valor configurado em MSSQL_SA_PASSWORD no arquivo .env
   - Trust server certificate: habilitado
   - Database name: PizzaSales
4. Se o VS Code não conseguir carregar a lista de bancos, informe PizzaSales diretamente no campo Database name. Para testar a conexão antes de carregar a base, use master.
5. Use Test connection e, se aprovado, Connect.

Se a mensagem for Login failed for user 'sa', o servidor foi alcançado, mas a senha não corresponde à senha definida quando aquele SQL Server/volume foi inicializado. Alterar o .env não troca a senha de um volume já existente. Use a senha original desse volume ou configure uma instância de teste nova; não remova o volume para tentar corrigir a senha.

### 7. Executar as consultas

No VS Code, abra 03_analysis_queries.sql. O script começa selecionando PizzaSales e contém consultas analíticas de leitura da base pública. Ele utiliza a sintaxe T-SQL do SQL Server, incluindo separadores GO. Não execute 02_create_tables_reference.sql como se fosse um conjunto de consultas: esse arquivo recria o banco. A criação e a carga descritas acima são feitas pelo alvo make run.

Confirme que a conexão está selecionada para o editor. Clique dentro da área de texto do arquivo SQL e então:

- Pressione Ctrl+Shift+E; ou
- Abra Ctrl+Shift+P e execute MS SQL: Execute Query.

Se aparecer “A SQL editor must have focus before executing this command”, o foco está fora do editor SQL: clique dentro do texto de 03_analysis_queries.sql e execute novamente. Se executar uma consulta selecionada, somente a seleção será enviada; sem seleção, a extensão executa a instrução atual ou o conteúdo do editor conforme o comando utilizado.

Para conferir a carga, execute no editor:

~~~sql
USE PizzaSales;
GO

SELECT COUNT(*) AS total_pedidos
FROM dbo.orders;

SELECT COUNT(*) AS total_itens
FROM dbo.order_details;
~~~

Os resultados esperados são 21.350 em total_pedidos e 48.620 em total_itens. Depois, execute as consultas de 03_analysis_queries.sql individualmente ou em conjunto. Os resultados SQL referem-se à base pública Pizza Place Sales, não ao estudo de caso da pizzaria de bairro.

### Encerrar o ambiente Docker

Quando terminar, o comando abaixo para e remove o container e a rede do Compose, mas preserva o volume de dados:

~~~bash
make db-down
~~~

Não acrescente a opção -v ao comando Docker Compose down: ela remove o volume persistente. Manter o volume permite que o banco continue disponível na próxima inicialização.

## Visão geral do projeto

### Fontes de dados

| Fonte | Uso | Características |
| --- | --- | --- |
| Pizza Place Sales | Desenvolvimento original, ETL, modelagem e consultas SQL | Conjunto público de vendas de 2015; quatro arquivos brutos e 48.620 linhas de itens. A descrição do desafio caracteriza o estabelecimento como fictício. |
| VENDAS_PIZZARIA_BAIRRO.csv | Estudo de caso de análise personalizada | Dados do estabelecimento de bairro, com identidade comercial omitida; período registrado no arquivo de 01/08/2026 a 30/09/2026. |
| CSV enviado pelo usuário | Análise personalizada | Período, produtos, tamanhos, categorias e calendário dependem do arquivo enviado e das informações fornecidas pelo usuário. |

Referências consultadas para Pizza Place Sales: [Maven Pizza Challenge](https://mavenanalytics.io/challenges/maven-pizza-challenge) e [Pizza Place Sales no Maven Data Playground](https://status.mavenanalytics.io/data-playground/pizza-place-sales). A página do Data Playground informa a licença como Public Domain; confira os termos na fonte antes de redistribuir arquivos.

### Modelagem, ETL e SQL

O esquema relacional público contém sete tabelas: categories, pizza_types, ingredients, pizza_type_ingredients, pizzas, orders e order_details. A lista de ingredientes é decomposta em registros atômicos. O esquema inclui chaves primárias e estrangeiras e restrições próprias da fonte pública, incluindo tamanhos S, M, L, XL e XXL e datas de 2015. Essas regras não são aplicadas ao CSV externo da pizzaria.

O ETL lê os quatro CSVs públicos em data/, prepara categorias e ingredientes, audita valores e relacionamentos e carrega as tabelas no SQL Server. O exportador src/04_exportar_base_normalizada.py gera sete CSVs em data/normalized/. O painel usa esses dados para análises locais e pode executar consultas compatíveis por meio de SQLite em memória quando a conexão direta ao SQL Server não estiver disponível.

O arquivo 03_analysis_queries.sql reúne exemplos com WHERE, LIKE, IN, BETWEEN, JOINs, GROUP BY, agregações, subconsultas, operações de conjuntos, CTEs, função de janela, autojunção e HAVING. Essas consultas pertencem à base pública. Elas não utilizam o CSV da pizzaria de bairro.

### Indicadores e previsão

O painel apresenta agregações por pedido, produto, categoria, tamanho, data, dia da semana e horário. O faturamento bruto é calculado pela soma de quantidade multiplicada pelo preço unitário; não representa lucro. A análise de ingredientes associa itens vendidos às composições cadastradas, mas não estima gramagem, custo ou consumo físico.

A previsão diária usa regressão linear com variáveis de calendário e histórico: dia da semana, índice temporal, vendas defasadas em sete dias, média móvel dos sete dias anteriores, indicador do início do mês e componentes cíclicos mensais. A avaliação cronológica apresenta MAE, RMSE, R² e comparação com a referência da semana anterior. O painel requer 56 dias completos para treinamento e apresenta um horizonte de sete dias. A faixa previsão ± MAE é indicativa, não é intervalo de confiança.

### Aplicação Streamlit e estudo de caso

O painel separa a base pública, o estudo de caso e arquivos enviados pelo usuário. Inclui visão geral, cardápio, picos de demanda, ingredientes, previsão, avaliação do modelo, consultas analíticas e fontes de dados. Títulos e indicadores identificam a fonte usada. A receita calculada não é lucro; análises de ingredientes dependem dos dados disponíveis.

O CSV de referência para outros estabelecimentos está em docs/modelo_csv_vendas_pizzaria.csv. As orientações de preenchimento estão em docs/modelo_csv_vendas_pizzaria.md. O cabeçalho de referência contém:

~~~csv
data,quantidade,pedido_id,hora,produto,tamanho,preco_unitario,categoria,ingredientes
~~~

Datas no formato AAAA-MM-DD são preferidas; datas no formato DD/MM/AAAA também são aceitas quando identificáveis sem ambiguidade. Quantidades comerciais devem ser inteiras e positivas. Um pedido pode aparecer em várias linhas quando contém diferentes itens. O sistema sinaliza possíveis linhas repetidas para conferência e não exclui vendas automaticamente. Análises dependem das colunas disponíveis; o diagnóstico informa limitações e inconsistências. Dias fechados, dias abertos sem registros e dias com vendas zero devem ser distinguidos conforme o calendário configurado pelo usuário.

### Estrutura principal

~~~text
.
├── data/                         # CSVs públicos e tabelas normalizadas
├── docs/                         # Modelo de CSV e orientação de preenchimento
├── docker/docker-compose.yml     # Serviço SQL Server
├── src/                          # ETL, exportador, previsão, painel e importador
├── tests/                        # Testes do importador e da interface
├── 02_create_tables_reference.sql
├── 03_analysis_queries.sql
├── Dockerfile
├── Makefile
├── requirements.txt
└── README.md
~~~

O CSV do estudo de caso é armazenado em output/VENDAS_PIZZARIA_BAIRRO.csv e distribuído com autorização, com o nome comercial omitido. Esse arquivo não é necessário para executar as consultas SQL da base pública. Se não estiver presente, o painel mantém a base pública disponível e informa que o estudo de caso não pode ser carregado.

## Alvos do Makefile

Execute os alvos no Ubuntu/WSL, na raiz do repositório:

| Alvo | Função |
| --- | --- |
| make help | Exibe os alvos documentados. |
| make setup | Cria .venv local e instala requirements.txt. |
| make db-up | Inicia o SQL Server pelo Docker Compose e aguarda a disponibilidade. |
| make db-down | Para e remove o container e a rede Compose, preservando o volume. |
| make run | Inicia o SQL Server, constrói a imagem e executa o ETL; recria PizzaSales. |
| make normalize | Instala dependências locais, se necessário, e gera os sete CSVs normalizados. |
| make dashboard | Atualiza os CSVs e executa o painel localmente; requer dependências Python. |
| make dashboard-docker | Exporta os CSVs e executa o painel em container. |
| make all | Encadeia a carga do SQL Server e o painel Docker; inclui a recriação de PizzaSales. |
| make clean | Remove diretórios de cache __pycache__ do Python. |

Não é necessário executar make normalize antes de consultar o SQL Server: a carga SQL usa os quatro CSVs originais em data/. make normalize atualiza arquivos versionados em data/normalized/; por isso, confira git status depois de executá-lo.

## Executar o painel

Para executar o painel localmente em Ubuntu/WSL:

~~~bash
make setup
make dashboard
~~~

O alvo cria o ambiente virtual local, instala as dependências, atualiza os CSVs normalizados e inicia o Streamlit. A URL local aparece no terminal. A conexão direta do painel ao SQL Server é opcional; sem ela, as análises públicas usam data/normalized/ e SQLite em memória.

Para executar o painel em container:

~~~bash
make dashboard-docker
~~~

O alvo requer Docker Desktop/Engine ativo. Ele exporta as tabelas normalizadas e inicia o Streamlit em um container; abra a URL local informada ou http://localhost:8501.

## Testes

Na raiz do repositório, instale as dependências e execute:

~~~bash
make setup
.venv/bin/python -m unittest discover -s tests -v
~~~

## Limitações

- A previsão representa unidades vendidas, não receita, lucro ou consumo real de ingredientes.
- O modelo de previsão não incorpora feriados, promoções, custos, margens ou capacidade de produção.
- As análises personalizadas dependem dos campos presentes e da qualidade do CSV enviado.
- A execução do SQL Server requer Docker com containers Linux e a porta local 1433 disponível.
- O SQL Server guarda os dados no volume Compose. make db-down preserva esse volume; make run recria o banco PizzaSales dentro dele.

## Referências de uso

- [Maven Pizza Challenge](https://mavenanalytics.io/challenges/maven-pizza-challenge)
- [Pizza Place Sales — Maven Data Playground](https://status.mavenanalytics.io/data-playground/pizza-place-sales)
- [WSL — documentação Microsoft](https://learn.microsoft.com/windows/wsl/install/)
- [VS Code no WSL — documentação oficial](https://code.visualstudio.com/docs/remote/wsl)
- [Docker Desktop e WSL 2 — documentação Docker](https://docs.docker.com/desktop/features/wsl/)
- [MSSQL para VS Code — documentação Microsoft](https://learn.microsoft.com/sql/tools/visual-studio-code-extensions/mssql/mssql-extension-visual-studio-code)
