#%% 
import pandas as pd
from sqlalchemy import create_engine, text
import urllib

df_orders = pd.read_csv('data/orders.csv')
df_order_details = pd.read_csv('data/order_details.csv')
df_pizzas = pd.read_csv('data/pizzas.csv')
df_pizza_types = pd.read_csv('data/pizza_types.csv', encoding='latin1')

# %%
# --- TRATAMENTO E NORMALIZAÇÃO ---

# 2. Criar a tabela categories
categories_list = df_pizza_types['category'].unique()
df_categories = pd.DataFrame({'category_name': categories_list})
# Criar identificadores sequenciais para as categorias
df_categories['category_id'] = range(1, len(df_categories) + 1) 
df_categories = df_categories[['category_id', 'category_name']] # Reordering columns

# %%
# 3. Atualizar a tabela pizza_types (substituir o texto por category_id)
df_pizza_types = df_pizza_types.merge(df_categories, left_on='category', right_on='category_name')
# Selecionar somente as colunas necessárias para a nova tabela
df_pizza_types_clean = df_pizza_types[['pizza_type_id', 'name', 'category_id']]

# %%
# 4. Criar a tabela ingredients e a tabela associativa pizza_type_ingredients
# Separar por vírgulas os valores da coluna ingredients
df_ingredients_temp = df_pizza_types[['pizza_type_id', 'ingredients']].copy()
df_ingredients_temp['ingredients'] = df_ingredients_temp['ingredients'].str.split(',')

# %%
# explode transforma a lista de ingredientes em várias linhas e repete o pizza_type_id
df_exploded = df_ingredients_temp.explode('ingredients')
# Remover espaços no início e no fim após separar os valores por vírgula
df_exploded['ingredients'] = df_exploded['ingredients'].str.strip()
# Padronização:
df_exploded['ingredients'] = df_exploded['ingredients'].replace('Artichoke', 'Artichokes')

# %%
# --- APLICAÇÃO DAS REGRAS DE NEGÓCIO ---
# 4.1. Adicionar Mozzarella Cheese às pizzas que ainda não o têm
mozzarella_pizzas = pd.DataFrame({
    'pizza_type_id': df_pizza_types['pizza_type_id'],
    'ingredients': 'Mozzarella Cheese'
})

# 4.2. Adicionar Tomato Sauce somente quando nenhum outro molho estiver especificado
# Selecionar pizzas cujos ingredientes originais não contêm a palavra Sauce
pizzas_without_sauce = df_pizza_types[~df_pizza_types['ingredients'].str.contains('Sauce', case=False)]
tomato_pizzas = pd.DataFrame({
    'pizza_type_id': pizzas_without_sauce['pizza_type_id'],
    'ingredients': 'Tomato Sauce'
})

# Combinar ingredientes originais e regras e remover duplicatas
df_exploded = pd.concat([df_exploded, mozzarella_pizzas, tomato_pizzas]).drop_duplicates()

#%%
# Extrair ingredientes únicos para a tabela final ingredients
unique_ingredients = df_exploded['ingredients'].unique()
df_ingredients = pd.DataFrame({'ingredient_name': unique_ingredients})
df_ingredients['ingredient_id'] = range(1, len(df_ingredients) + 1)
df_ingredients = df_ingredients[['ingredient_id', 'ingredient_name']]

# %%
# Criar a tabela associativa relacionando os ingredientes separados aos identificadores gerados
df_pizza_type_ingredients = df_exploded.merge(df_ingredients, left_on='ingredients', right_on='ingredient_name')
df_pizza_type_ingredients = df_pizza_type_ingredients[['pizza_type_id', 'ingredient_id']]

#%%
print("--- INICIANDO A AUDITORIA DOS DADOS ---")

# 1. Validar orders
print("\n[1] Verificando df_orders...")
# order_id deve ser NOT NULL e UNIQUE
print(f" - Valores nulos em order_id: {df_orders['order_id'].isnull().sum()}")
print(f" - Duplicatas em order_id: {df_orders['order_id'].duplicated().sum()}")
print(f" - Valores nulos em date: {df_orders['date'].isnull().sum()}")
print(f" - Valores nulos em time: {df_orders['time'].isnull().sum()}")

#%%
# CHECK (date >= '2015-01-01' AND date <= '2015-12-31')
# Converter temporariamente para data e validar o intervalo
invalid_dates = pd.to_datetime(df_orders['date']).loc[
    ~pd.to_datetime(df_orders['date']).between('2015-01-01', '2015-12-31')
]
print(f" - Datas fora do intervalo de 2015: {len(invalid_dates)}")

#%%
# 2. Validar order_details
print("\n[2] Verificando df_order_details...")
print(f" - Valores nulos em order_details_id: {df_order_details['order_details_id'].isnull().sum()}")
print(f" - Duplicatas em order_details_id: {df_order_details['order_details_id'].duplicated().sum()}")
print(f" - Valores nulos em order_id: {df_order_details['order_id'].isnull().sum()}")
print(f" - Valores nulos em pizza_id: {df_order_details['pizza_id'].isnull().sum()}")
print(f" - Valores nulos em quantity: {df_order_details['quantity'].isnull().sum()}")

# CHECK (quantity > 0)
invalid_qty = df_order_details[df_order_details['quantity'] <= 0]
print(f" - Quantidades menores ou iguais a zero: {len(invalid_qty)}")

#%%
# 3. Validar pizzas
print("\n[3] Verificando df_pizzas...")
print(f" - Valores nulos em pizza_id: {df_pizzas['pizza_id'].isnull().sum()}")
print(f" - Duplicatas em pizza_id: {df_pizzas['pizza_id'].duplicated().sum()}")
print(f" - Valores nulos em pizza_type_id: {df_pizzas['pizza_type_id'].isnull().sum()}")
print(f" - Valores nulos em size: {df_pizzas['size'].isnull().sum()}")
print(f" - Valores nulos em price: {df_pizzas['price'].isnull().sum()}")

# CHECK (size IN ('S', 'M', 'L', 'XL', 'XXL'))
valid_sizes = ['S', 'M', 'L', 'XL', 'XXL']
invalid_size = df_pizzas[~df_pizzas['size'].isin(valid_sizes)]
print(f" - Tamanhos fora do padrão: {len(invalid_size)}")

# CHECK (price > 0)
invalid_price = df_pizzas[df_pizzas['price'] <= 0]
print(f" - Preços menores ou iguais a zero: {len(invalid_price)}")

#%%
# 4. Validar pizza_types (usando o DataFrame tratado)
print("\n[4] Verificando df_pizza_types_clean...")
print(f" - Valores nulos em pizza_type_id: {df_pizza_types_clean['pizza_type_id'].isnull().sum()}")
print(f" - Duplicatas em pizza_type_id: {df_pizza_types_clean['pizza_type_id'].duplicated().sum()}")
print(f" - Valores nulos em name: {df_pizza_types_clean['name'].isnull().sum()}")
print(f" - Duplicatas em name: {df_pizza_types_clean['name'].duplicated().sum()}")
print(f" - Valores nulos em category_id: {df_pizza_types_clean['category_id'].isnull().sum()}")

#%%
# 5. Validar categories
print("\n[5] Verificando df_categories...")
print(f" - Valores nulos em category_id: {df_categories['category_id'].isnull().sum()}")
print(f" - Duplicatas em category_id: {df_categories['category_id'].duplicated().sum()}")
print(f" - Valores nulos em category_name: {df_categories['category_name'].isnull().sum()}")
print(f" - Duplicatas em category_name: {df_categories['category_name'].duplicated().sum()}")

#%%
# 6. Validar ingredients
print("\n[6] Verificando df_ingredients...")
print(f" - Valores nulos em ingredient_id: {df_ingredients['ingredient_id'].isnull().sum()}")
# Mesmo que unique() já remova valores repetidos, a auditoria confirma a ausência de duplicatas.
print(f" - Duplicatas em ingredient_id: {df_ingredients['ingredient_id'].duplicated().sum()}")
print(f" - Valores nulos em ingredient_name: {df_ingredients['ingredient_name'].isnull().sum()}")

#%%
# 7. Validar pizza_type_ingredients (tabela associativa)
print("\n[7] Verificando df_pizza_type_ingredients...")
print(f" - Valores nulos em pizza_type_id: {df_pizza_type_ingredients['pizza_type_id'].isnull().sum()}")
print(f" - Valores nulos em ingredient_id: {df_pizza_type_ingredients['ingredient_id'].isnull().sum()}")

# UNIQUE composto: verifica se a mesma combinação de pizza e ingrediente aparece mais de uma vez
composite_duplicates = df_pizza_type_ingredients.duplicated(subset=['pizza_type_id', 'ingredient_id']).sum()
print(f" - Combinações duplicadas de pizza e ingrediente: {composite_duplicates}")

print("\n--- FIM DA AUDITORIA ---")

#%% 
# --- CARGA NO SQL SERVER (DOCKER) ---

# Codificar caracteres especiais da senha para formar uma URL válida
password_encoded = urllib.parse.quote_plus("SenhaForte@2026!")

# 1. Conexão inicial com master, necessária para executar o arquivo SQL de criação do banco
connection_string_master = (
    f"mssql+pyodbc://sa:{password_encoded}@pizza_sql_server:1433/master"
    "?driver=ODBC+Driver+17+for+SQL+Server&TrustServerCertificate=yes"
)
engine_master = create_engine(connection_string_master)

# Dicionário que relaciona as tabelas do banco aos DataFrames
# A ordem é obrigatória para respeitar as chaves estrangeiras (FKs)
dataframes_to_load = {
    'categories': df_categories,                         # 1st (Base)
    'pizza_types': df_pizza_types_clean,                 # 2nd (Depends on Categories)
    'ingredients': df_ingredients,                       # 3rd (Base)
    'pizza_type_ingredients': df_pizza_type_ingredients, # 4th (Depends on PizzaTypes and Ingredients)
    'pizzas': df_pizzas,                                 # 5th (Depends on PizzaTypes)
    'orders': df_orders,                                 # 6th (Independent)
    'order_details': df_order_details                    # 7th (Depends on Orders and Pizzas)
}

# =====================================================================
# Criação da estrutura do banco de dados
print("--- CRIANDO A ESTRUTURA DO BANCO DE DADOS ---")
# O nome do arquivo SQL deve corresponder ao arquivo existente no projeto
with open('02_create_tables_reference.sql', 'r', encoding='utf-8') as file:
    sql_script = file.read()

sql_commands = sql_script.split('GO')

# Criar o banco e as tabelas pela conexão master, usando AUTOCOMMIT
with engine_master.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
    for command in sql_commands:
        if command.strip():
            conn.execute(text(command))
print("[OK] Tabelas, chaves e restrições criadas.")
# =====================================================================

# 2. Conexão com o banco PizzaSales recém-criado para inserir os dados
connection_string_sales = (
    f"mssql+pyodbc://sa:{password_encoded}@pizza_sql_server:1433/PizzaSales"
    "?driver=ODBC+Driver+17+for+SQL+Server&TrustServerCertificate=yes"
)
engine_sales = create_engine(connection_string_sales)

print("--- INICIANDO A CARGA NO SQL SERVER ---")

for table_name, df in dataframes_to_load.items():
    try:
        print(f"Carregando {table_name} ({len(df)} registros)...")
        df.to_sql(table_name, con=engine_sales, if_exists='append', index=False)
        print(f"[OK] {table_name} carregada.")
    except Exception as e:
        print(f"Erro ao carregar {table_name}: {e}")

print("\nCarga finalizada. Confira as mensagens acima para verificar se houve erros.")
