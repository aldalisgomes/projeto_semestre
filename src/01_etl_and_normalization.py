#%% 
import pandas as pd
from sqlalchemy import create_engine, text
import urllib

df_orders = pd.read_csv('data/orders.csv')
df_order_details = pd.read_csv('data/order_details.csv')
df_pizzas = pd.read_csv('data/pizzas.csv')
df_pizza_types = pd.read_csv('data/pizza_types.csv', encoding='latin1')

# %%
# --- TREATMENT AND NORMALIZATION ---

# 2. Create the 'categories' Table
categories_list = df_pizza_types['category'].unique()
df_categories = pd.DataFrame({'category_name': categories_list})
# Creating a sequential ID for categories
df_categories['category_id'] = range(1, len(df_categories) + 1) 
df_categories = df_categories[['category_id', 'category_name']] # Reordering columns

# %%
# 3. Update the 'pizza_types' Table (Replacing text with category_id)
df_pizza_types = df_pizza_types.merge(df_categories, left_on='category', right_on='category_name')
# Select only the relevant columns for the new table
df_pizza_types_clean = df_pizza_types[['pizza_type_id', 'name', 'category_id']]

# %%
# 4. Create the 'ingredients' Table and the Associative 'pizza_type_ingredients' Table
# First, we take the ingredients column and split the string by commas
df_ingredients_temp = df_pizza_types[['pizza_type_id', 'ingredients']].copy()
df_ingredients_temp['ingredients'] = df_ingredients_temp['ingredients'].str.split(',')

# %%
# 'explode' transforms the list of ingredients into multiple rows, repeating the pizza_type_id
df_exploded = df_ingredients_temp.explode('ingredients')
# Remove leading/trailing whitespaces after splitting by comma
df_exploded['ingredients'] = df_exploded['ingredients'].str.strip()
# Standardization:
df_exploded['ingredients'] = df_exploded['ingredients'].replace('Artichoke', 'Artichokes')

# %%
# --- APPLICATION OF BUSINESS RULES ---
# 4.1. Add Mozzarella Cheese to all pizzas that don't have it yet
mozzarella_pizzas = pd.DataFrame({
    'pizza_type_id': df_pizza_types['pizza_type_id'],
    'ingredients': 'Mozzarella Cheese'
})

# 4.2. Add Tomato Sauce only where no other "Sauce" is specified
# Filtering pizzas that DO NOT contain the word 'Sauce' in their original ingredients
pizzas_without_sauce = df_pizza_types[~df_pizza_types['ingredients'].str.contains('Sauce', case=False)]
tomato_pizzas = pd.DataFrame({
    'pizza_type_id': pizzas_without_sauce['pizza_type_id'],
    'ingredients': 'Tomato Sauce'
})

# Merge the original ingredients with the new rules and remove duplicates (in case cheese was already on the list)
df_exploded = pd.concat([df_exploded, mozzarella_pizzas, tomato_pizzas]).drop_duplicates()

#%%
# Extraction of unique ingredients for the final Ingredients table
unique_ingredients = df_exploded['ingredients'].unique()
df_ingredients = pd.DataFrame({'ingredient_name': unique_ingredients})
df_ingredients['ingredient_id'] = range(1, len(df_ingredients) + 1)
df_ingredients = df_ingredients[['ingredient_id', 'ingredient_name']]

# %%
# Create the associative table by crossing the exploded data with the generated IDs
df_pizza_type_ingredients = df_exploded.merge(df_ingredients, left_on='ingredients', right_on='ingredient_name')
df_pizza_type_ingredients = df_pizza_type_ingredients[['pizza_type_id', 'ingredient_id']]

#%%
print("--- STARTING DATA AUDIT ---")

# 1. Validation: orders
print("\n[1] Checking df_orders...")
# NOT NULL and UNIQUE for order_id
print(f" - order_id Nulls: {df_orders['order_id'].isnull().sum()}")
print(f" - order_id Duplicates: {df_orders['order_id'].duplicated().sum()}")
print(f" - date Nulls: {df_orders['date'].isnull().sum()}")
print(f" - time Nulls: {df_orders['time'].isnull().sum()}")

#%%
# CHECK (date >= '2015-01-01' AND date <= '2015-12-31')
# Converting to datetime temporarily to ensure checking
invalid_dates = pd.to_datetime(df_orders['date']).loc[
    ~pd.to_datetime(df_orders['date']).between('2015-01-01', '2015-12-31')
]
print(f" - Dates out of range (2015): {len(invalid_dates)}")

#%%
# 2. Validation: order_details
print("\n[2] Checking df_order_details...")
print(f" - order_details_id Nulls: {df_order_details['order_details_id'].isnull().sum()}")
print(f" - order_details_id Duplicates: {df_order_details['order_details_id'].duplicated().sum()}")
print(f" - order_id Nulls: {df_order_details['order_id'].isnull().sum()}")
print(f" - pizza_id Nulls: {df_order_details['pizza_id'].isnull().sum()}")
print(f" - quantity Nulls: {df_order_details['quantity'].isnull().sum()}")

# CHECK (quantity > 0)
invalid_qty = df_order_details[df_order_details['quantity'] <= 0]
print(f" - Quantities <= 0: {len(invalid_qty)}")

#%%
# 3. Validation: pizzas
print("\n[3] Checking df_pizzas...")
print(f" - pizza_id Nulls: {df_pizzas['pizza_id'].isnull().sum()}")
print(f" - pizza_id Duplicates: {df_pizzas['pizza_id'].duplicated().sum()}")
print(f" - pizza_type_id Nulls: {df_pizzas['pizza_type_id'].isnull().sum()}")
print(f" - size Nulls: {df_pizzas['size'].isnull().sum()}")
print(f" - price Nulls: {df_pizzas['price'].isnull().sum()}")

# CHECK (size IN ('S', 'M', 'L', 'XL', 'XXL'))
valid_sizes = ['S', 'M', 'L', 'XL', 'XXL']
invalid_size = df_pizzas[~df_pizzas['size'].isin(valid_sizes)]
print(f" - Non-standard sizes: {len(invalid_size)}")

# CHECK (price > 0)
invalid_price = df_pizzas[df_pizzas['price'] <= 0]
print(f" - Prices <= 0: {len(invalid_price)}")

#%%
# 4. Validation: pizza_types (using clean df)
print("\n[4] Checking df_pizza_types_clean...")
print(f" - pizza_type_id Nulls: {df_pizza_types_clean['pizza_type_id'].isnull().sum()}")
print(f" - pizza_type_id Duplicates: {df_pizza_types_clean['pizza_type_id'].duplicated().sum()}")
print(f" - name Nulls: {df_pizza_types_clean['name'].isnull().sum()}")
print(f" - name Duplicates: {df_pizza_types_clean['name'].duplicated().sum()}")
print(f" - category_id Nulls: {df_pizza_types_clean['category_id'].isnull().sum()}")

#%%
# 5. Validation: categories
print("\n[5] Checking df_categories...")
print(f" - category_id Nulls: {df_categories['category_id'].isnull().sum()}")
print(f" - category_id Duplicates: {df_categories['category_id'].duplicated().sum()}")
print(f" - category_name Nulls: {df_categories['category_name'].isnull().sum()}")
print(f" - category_name Duplicates: {df_categories['category_name'].duplicated().sum()}")

#%%
# 6. Validation: ingredients
print("\n[6] Checking df_ingredients...")
print(f" - ingredient_id Nulls: {df_ingredients['ingredient_id'].isnull().sum()}")
# If the original ingredients table was assembled by 'unique()', it already has no duplicates, but we validate:
print(f" - ingredient_id Duplicates: {df_ingredients['ingredient_id'].duplicated().sum()}")
print(f" - ingredient_name Nulls: {df_ingredients['ingredient_name'].isnull().sum()}")

#%%
# 7. Validation: pizza_type_ingredients (Associative Table)
print("\n[7] Checking df_pizza_type_ingredients...")
print(f" - pizza_type_id Nulls: {df_pizza_type_ingredients['pizza_type_id'].isnull().sum()}")
print(f" - ingredient_id Nulls: {df_pizza_type_ingredients['ingredient_id'].isnull().sum()}")

# Composite UNIQUE: Checks if the same pizza and ingredient combination exists more than once
composite_duplicates = df_pizza_type_ingredients.duplicated(subset=['pizza_type_id', 'ingredient_id']).sum()
print(f" - Duplicate Pizza+Ingredient combinations: {composite_duplicates}")

print("\n--- END ---")

#%% 
# --- SQL SERVER INGESTION (DOCKER) ---

# Ensures that special characters in the password don't break the connection
password_encoded = urllib.parse.quote_plus("SenhaForte@2026!")

# 1. Initial engine connected to 'master' (required to run the database creation script)
connection_string_master = (
    f"mssql+pyodbc://sa:{password_encoded}@pizza_sql_server:1433/master"
    "?driver=ODBC+Driver+17+for+SQL+Server&TrustServerCertificate=yes"
)
engine_master = create_engine(connection_string_master)

# Dictionary mapping database tables to DataFrames
# THE ORDER IS MANDATORY to respect FKs (Foreign Keys)
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
# Database structure creation
print("--- CREATING DATABASE STRUCTURE ---")
# Ensure the SQL file name here matches your actual file
with open('02_create_tables_reference.sql', 'r', encoding='utf-8') as file:
    sql_script = file.read()

sql_commands = sql_script.split('GO')

# Execute database and table creation using the 'master' connection (with AUTOCOMMIT)
with engine_master.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
    for command in sql_commands:
        if command.strip():
            conn.execute(text(command))
print("[OK] Tables, keys, and constraints created successfully!")
# =====================================================================

# 2. Engine now pointing to the newly created 'PizzaSales' database to insert the data
connection_string_sales = (
    f"mssql+pyodbc://sa:{password_encoded}@pizza_sql_server:1433/PizzaSales"
    "?driver=ODBC+Driver+17+for+SQL+Server&TrustServerCertificate=yes"
)
engine_sales = create_engine(connection_string_sales)

print("--- STARTING SQL SERVER LOAD ---")

for table_name, df in dataframes_to_load.items():
    try:
        print(f"Uploading {table_name} ({len(df)} records)...")
        df.to_sql(table_name, con=engine_sales, if_exists='append', index=False)
        print(f"[OK] {table_name} loaded successfully")
    except Exception as e:
        print(f"Error loading {table_name}: {e}")

print("\n[OK] Load successfully finished! The data now resides in SQL Server.")