USE PizzaSales;
GO
-- ============================================================
-- PROJETO: Vendas da Pizzaria - Estudo avançado de SQL
-- CONTEÚDO: Condições WHERE, LIKE, IN e BETWEEN,
--           junções (INNER, LEFT, RIGHT, FULL), GROUP BY,
--           subconsultas e operações de conjuntos.
-- ============================================================

---------------------------------------------------------------
-- 1. CONDIÇÕES COMPLEXAS, LIKE, IN E BETWEEN
---------------------------------------------------------------

-- 1.1. Selecionar pizzas com preço entre US$ 15 e US$ 20 e tamanho L ou XL
-- (Uso de BETWEEN e IN)
SELECT 
    pizza_id AS Id_Pizza,
    pizza_type_id AS Id_Tipo_Pizza,
    size AS Tamanho,
    price AS Preco
FROM pizzas
WHERE price BETWEEN 15.00 AND 20.00
  AND size IN ('L', 'XL');


-- 1.2. Selecionar pizzas cujo nome contém 'Chicken', mas que não são tamanho S
-- (Uso de LIKE, AND e NOT)
SELECT 
    p.pizza_id AS Id_Pizza,
    pt.name AS Nome_da_Pizza,
    p.size AS Tamanho,
    p.price AS Preco
FROM pizzas p
JOIN pizza_types pt ON p.pizza_type_id = pt.pizza_type_id
WHERE pt.name LIKE '%Chicken%' 
  AND NOT p.size = 'S';


---------------------------------------------------------------
-- 2. CONSULTAS COM MÚLTIPLAS TABELAS (JOINS)
---------------------------------------------------------------

-- 2.1. INNER JOIN (retorna somente registros correspondentes nas duas tabelas)
-- Exemplo: itens de pedidos com o nome da pizza e sua categoria
SELECT TOP 100
    od.order_id AS Id_Pedido,
    pt.name AS Nome_da_Pizza,
    c.category_name AS Categoria,
    od.quantity AS Quantidade
FROM order_details od
INNER JOIN pizzas p ON od.pizza_id = p.pizza_id
INNER JOIN pizza_types pt ON p.pizza_type_id = pt.pizza_type_id
INNER JOIN categories c ON pt.category_id = c.category_id;


-- 2.2. LEFT JOIN (retorna todos os registros da tabela à esquerda e as correspondências da direita)
-- Exemplo: exibir todos os tipos de pizza, mesmo sem vendas (hipoteticamente)
SELECT 
    pt.name AS Sabor,
    SUM(od.quantity) AS Unidades_Vendidas
FROM pizza_types pt
LEFT JOIN pizzas p ON pt.pizza_type_id = p.pizza_type_id
LEFT JOIN order_details od ON p.pizza_id = od.pizza_id
GROUP BY pt.name
ORDER BY Unidades_Vendidas ASC;


-- 2.3. RIGHT JOIN (retorna todos os registros da tabela à direita e as correspondências da esquerda)
-- Exemplo: listar todas as categorias e encontrar suas pizzas (inverso da consulta anterior)
SELECT 
    pt.name AS Sabor,
    c.category_name AS Categoria
FROM pizza_types pt
RIGHT JOIN categories c ON pt.category_id = c.category_id;


-- 2.4. FULL OUTER JOIN (retorna todos os registros das duas tabelas, combinando os correspondentes)
-- Útil para auditorias de registros órfãos (por exemplo, pizza sem tipo ou tipo sem pizza)
SELECT 
    p.pizza_id AS Id_Pizza,
    pt.name AS Nome_da_Pizza
FROM pizzas p
FULL OUTER JOIN pizza_types pt ON p.pizza_type_id = pt.pizza_type_id
WHERE p.pizza_id IS NULL OR pt.pizza_type_id IS NULL; -- Exibe somente inconsistências


---------------------------------------------------------------
-- 3. RELATÓRIOS BÁSICOS (GROUP BY E FUNÇÕES DE AGREGAÇÃO)
---------------------------------------------------------------

-- 3.1. Total de pedidos, total de pizzas vendidas e média de pizzas por pedido diário
SELECT 
    o.date AS Data_do_Pedido,
    COUNT(DISTINCT o.order_id) AS Total_de_Pedidos,
    SUM(od.quantity) AS Total_de_Pizzas_Vendidas,
    CAST(SUM(od.quantity) AS DECIMAL(10,2))
        / NULLIF(COUNT(DISTINCT o.order_id), 0) AS Media_de_Pizzas_por_Pedido
FROM orders o
JOIN order_details od ON o.order_id = od.order_id
GROUP BY o.date
ORDER BY Total_de_Pizzas_Vendidas DESC;


---------------------------------------------------------------
-- 4. SUBCONSULTAS
---------------------------------------------------------------

-- 4.1. Subconsulta na cláusula WHERE:
-- Quais são os detalhes dos pedidos que incluíram a pizza mais cara do cardápio?
SELECT 
    order_id AS Id_Pedido,
    pizza_id AS Id_Pizza,
    quantity AS Quantidade
FROM order_details
WHERE pizza_id IN (
    -- Subconsulta: encontra o identificador da(s) pizza(s) com o maior preço
    SELECT pizza_id 
    FROM pizzas 
    WHERE price = (SELECT MAX(price) FROM pizzas)
);


-- 4.2. Subconsulta na cláusula SELECT:
-- Calcula a receita de cada pizza e sua participação percentual na receita total
SELECT 
    pt.name AS Nome_da_Pizza,
    SUM(od.quantity * p.price) AS Receita_da_Pizza,
    (SUM(od.quantity * p.price) / 
        (SELECT SUM(quantity * price) FROM order_details od2 JOIN pizzas p2 ON od2.pizza_id = p2.pizza_id)
    ) * 100 AS Participacao_na_Receita_Total
FROM order_details od
JOIN pizzas p ON od.pizza_id = p.pizza_id
JOIN pizza_types pt ON p.pizza_type_id = pt.pizza_type_id
GROUP BY pt.name
ORDER BY Receita_da_Pizza DESC;


---------------------------------------------------------------
-- 5. OPERAÇÕES DE CONJUNTOS (UNION, INTERSECT, EXCEPT)
---------------------------------------------------------------

-- 5.1. UNION (combina os resultados e remove duplicatas)
-- Exemplo: nomes de ingredientes que contêm "Cheese" ou "Garlic"
SELECT ingredient_name AS Ingrediente FROM ingredients WHERE ingredient_name LIKE '%Cheese%'
UNION
SELECT ingredient_name AS Ingrediente FROM ingredients WHERE ingredient_name LIKE '%Garlic%';


-- 5.2. INTERSECT (retorna somente resultados presentes nas duas consultas)
-- Exemplo: ingredientes usados nas categorias 'Veggie' e 'Classic'
SELECT i.ingredient_name AS Ingrediente
FROM ingredients i
JOIN pizza_type_ingredients pti ON i.ingredient_id = pti.ingredient_id
JOIN pizza_types pt ON pti.pizza_type_id = pt.pizza_type_id
JOIN categories c ON pt.category_id = c.category_id
WHERE c.category_name = 'Veggie'

INTERSECT

SELECT i.ingredient_name AS Ingrediente
FROM ingredients i
JOIN pizza_type_ingredients pti ON i.ingredient_id = pti.ingredient_id
JOIN pizza_types pt ON pti.pizza_type_id = pt.pizza_type_id
JOIN categories c ON pt.category_id = c.category_id
WHERE c.category_name = 'Classic';


-- 5.3. EXCEPT (retorna resultados da primeira consulta que não aparecem na segunda)
-- Exemplo: ingredientes da categoria 'Veggie' que nunca aparecem em 'Chicken'
SELECT i.ingredient_name AS Ingrediente
FROM ingredients i
JOIN pizza_type_ingredients pti ON i.ingredient_id = pti.ingredient_id
JOIN pizza_types pt ON pti.pizza_type_id = pt.pizza_type_id
JOIN categories c ON pt.category_id = c.category_id
WHERE c.category_name = 'Veggie'

EXCEPT

SELECT i.ingredient_name AS Ingrediente
FROM ingredients i
JOIN pizza_type_ingredients pti ON i.ingredient_id = pti.ingredient_id
JOIN pizza_types pt ON pti.pizza_type_id = pt.pizza_type_id
JOIN categories c ON pt.category_id = c.category_id
WHERE c.category_name = 'Chicken';


---------------------------------------------------------------
-- 6. ANÁLISES AVANÇADAS (CTEs, FUNÇÕES DE JANELA, SELF JOIN E HAVING)
---------------------------------------------------------------

-- 6.1. Análise de produtos comprados em conjunto com CTE e junção da tabela consigo mesma
-- Os 10 pares de sabores mais comprados juntos no mesmo pedido.
-- DISTINCT na CTE evita contar mais de um tamanho do mesmo sabor como pares diferentes.
WITH OrderPizzaTypes AS (
    SELECT DISTINCT
        od.order_id,
        p.pizza_type_id
    FROM order_details od
    INNER JOIN pizzas p ON od.pizza_id = p.pizza_id
)
SELECT TOP 10
    pt1.name AS Sabor_1,
    pt2.name AS Sabor_2,
    COUNT(DISTINCT first_type.order_id) AS Pedidos_em_Comum
FROM OrderPizzaTypes first_type
INNER JOIN OrderPizzaTypes second_type
    ON first_type.order_id = second_type.order_id
   AND first_type.pizza_type_id < second_type.pizza_type_id
INNER JOIN pizza_types pt1 ON first_type.pizza_type_id = pt1.pizza_type_id
INNER JOIN pizza_types pt2 ON second_type.pizza_type_id = pt2.pizza_type_id
GROUP BY pt1.name, pt2.name
ORDER BY Pedidos_em_Comum DESC, pt1.name, pt2.name;


-- 6.2. Duas pizzas de maior receita bruta em cada categoria
-- DENSE_RANK mantém empates e reinicia a classificação em cada categoria.
WITH PizzaRevenue AS (
    SELECT
        c.category_name,
        pt.name AS Pizza_Name,
        SUM(od.quantity * p.price) AS Gross_Revenue
    FROM order_details od
    INNER JOIN pizzas p ON od.pizza_id = p.pizza_id
    INNER JOIN pizza_types pt ON p.pizza_type_id = pt.pizza_type_id
    INNER JOIN categories c ON pt.category_id = c.category_id
    GROUP BY c.category_name, pt.name
), RankedPizzaRevenue AS (
    SELECT
        category_name,
        Pizza_Name,
        Gross_Revenue,
        DENSE_RANK() OVER (
            PARTITION BY category_name
            ORDER BY Gross_Revenue DESC
        ) AS Revenue_Rank
    FROM PizzaRevenue
)
SELECT
    category_name AS Categoria,
    Pizza_Name AS Nome_da_Pizza,
    Gross_Revenue AS Receita_Bruta,
    Revenue_Rank AS Posicao_na_Categoria
FROM RankedPizzaRevenue
WHERE Revenue_Rank <= 2
ORDER BY Categoria, Posicao_na_Categoria, Nome_da_Pizza;


-- 6.3. Complexidade das receitas na 1FN com GROUP BY e HAVING
-- Receitas com pelo menos 7 ingredientes distintos e seu preço médio no cardápio.
WITH RecipeComplexity AS (
    SELECT
        pt.pizza_type_id,
        pt.name AS Pizza_Name,
        c.category_name,
        COUNT(DISTINCT pti.ingredient_id) AS Ingredient_Count
    FROM pizza_types pt
    INNER JOIN categories c ON pt.category_id = c.category_id
    INNER JOIN pizza_type_ingredients pti ON pt.pizza_type_id = pti.pizza_type_id
    GROUP BY pt.pizza_type_id, pt.name, c.category_name
    HAVING COUNT(DISTINCT pti.ingredient_id) >= 7
)
SELECT
    rc.Pizza_Name AS Nome_da_Pizza,
    rc.category_name AS Categoria,
    rc.Ingredient_Count AS Quantidade_de_Ingredientes,
    AVG(p.price) AS Preco_Medio_no_Cardapio
FROM RecipeComplexity rc
INNER JOIN pizzas p ON rc.pizza_type_id = p.pizza_type_id
GROUP BY rc.Pizza_Name, rc.category_name, rc.Ingredient_Count
ORDER BY Quantidade_de_Ingredientes DESC, Nome_da_Pizza;


-- 6.4. Segmentação de pedidos com CTE e CASE WHEN
-- O valor médio por pedido é a receita bruta média em cada perfil.
WITH OrderTotals AS (
    SELECT
        o.order_id,
        SUM(od.quantity) AS Total_Pizzas,
        SUM(od.quantity * p.price) AS Gross_Order_Revenue
    FROM orders o
    INNER JOIN order_details od ON o.order_id = od.order_id
    INNER JOIN pizzas p ON od.pizza_id = p.pizza_id
    GROUP BY o.order_id
), SegmentedOrders AS (
    SELECT
        order_id,
        Total_Pizzas,
        Gross_Order_Revenue,
        CASE
            WHEN Total_Pizzas = 1 THEN '1. Individual (1 pizza)'
            WHEN Total_Pizzas BETWEEN 2 AND 3 THEN '2. Pequeno Grupo (2 a 3 pizzas)'
            ELSE '3. Família / Evento (4+ pizzas)'
        END AS Order_Profile
    FROM OrderTotals
)
SELECT
    Order_Profile AS Perfil_do_Pedido,
    COUNT(*) AS Total_de_Pedidos,
    SUM(Total_Pizzas) AS Total_de_Pizzas_Vendidas,
    AVG(Gross_Order_Revenue) AS Valor_Medio_por_Pedido
FROM SegmentedOrders
GROUP BY Order_Profile
ORDER BY Perfil_do_Pedido;

