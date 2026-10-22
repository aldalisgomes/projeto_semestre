USE PizzaSales;
GO
-- ============================================================
-- PROJECT: Pizza Place Sales - Advanced SQL Study
-- CONTENTS: Complex WHERE, LIKE, IN, BETWEEN, 
--           JOINS (INNER, LEFT, RIGHT, FULL), GROUP BY, 
--           Subqueries, and Set Operators.
-- ============================================================

---------------------------------------------------------------
-- 1. COMPLEX CONDITIONS, LIKE, IN, AND BETWEEN
---------------------------------------------------------------

-- 1.1. Extract pizzas that cost between $15 and $20 and are size L or XL
-- (Usage of BETWEEN and IN)
SELECT 
    pizza_id,
    pizza_type_id,
    size,
    price
FROM pizzas
WHERE price BETWEEN 15.00 AND 20.00
  AND size IN ('L', 'XL');


-- 1.2. Find pizzas that have 'Chicken' in their name, BUT ARE NOT size 'S'
-- (Usage of LIKE, AND, and NOT)
SELECT 
    p.pizza_id,
    pt.name,
    p.size,
    p.price
FROM pizzas p
JOIN pizza_types pt ON p.pizza_type_id = pt.pizza_type_id
WHERE pt.name LIKE '%Chicken%' 
  AND NOT p.size = 'S';


---------------------------------------------------------------
-- 2. WORKING WITH MULTIPLE TABLES (JOINS)
---------------------------------------------------------------

-- 2.1. INNER JOIN (Returns only matching records from both tables)
-- Ex: Order details alongside pizza name and category
SELECT TOP 100
    od.order_id,
    pt.name AS Pizza_Name,
    c.category_name,
    od.quantity
FROM order_details od
INNER JOIN pizzas p ON od.pizza_id = p.pizza_id
INNER JOIN pizza_types pt ON p.pizza_type_id = pt.pizza_type_id
INNER JOIN categories c ON pt.category_id = c.category_id;


-- 2.2. LEFT JOIN (Returns ALL from left table and matching from right table)
-- Ex: Ensure all pizza types appear, even if they had no sales (hypothetical)
SELECT 
    pt.name AS Pizza,
    SUM(od.quantity) AS Total_Sold
FROM pizza_types pt
LEFT JOIN pizzas p ON pt.pizza_type_id = p.pizza_type_id
LEFT JOIN order_details od ON p.pizza_id = od.pizza_id
GROUP BY pt.name
ORDER BY Total_Sold ASC;


-- 2.3. RIGHT JOIN (Returns ALL from right table and matching from left table)
-- Ex: List all categories and find their pizzas (inverse of previous)
SELECT 
    pt.name AS Pizza,
    c.category_name
FROM pizza_types pt
RIGHT JOIN categories c ON pt.category_id = c.category_id;


-- 2.4. FULL OUTER JOIN (Returns all records from both tables, joining on match)
-- Useful in audits to find "orphans" (e.g., a pizza with no type or a type with no pizza)
SELECT 
    p.pizza_id,
    pt.name
FROM pizzas p
FULL OUTER JOIN pizza_types pt ON p.pizza_type_id = pt.pizza_type_id
WHERE p.pizza_id IS NULL OR pt.pizza_type_id IS NULL; -- Filters only issues


---------------------------------------------------------------
-- 3. SIMPLE REPORTS (GROUP BY AND AGGREGATE FUNCTIONS)
---------------------------------------------------------------

-- 3.1. Total orders, total pizzas sold, and average pizzas per daily order
SELECT 
    o.date AS Order_Date,
    COUNT(DISTINCT o.order_id) AS Total_Orders,
    SUM(od.quantity) AS Total_Pizzas_Sold,
    CAST(SUM(od.quantity) AS DECIMAL(10,2))
        / NULLIF(COUNT(DISTINCT o.order_id), 0) AS Avg_Pizzas_Per_Order
FROM orders o
JOIN order_details od ON o.order_id = od.order_id
GROUP BY o.date
ORDER BY Total_Pizzas_Sold DESC;


---------------------------------------------------------------
-- 4. SUBQUERIES
---------------------------------------------------------------

-- 4.1. Subquery in WHERE clause: 
-- What are the details of orders that included the MOST EXPENSIVE pizza on the menu?
SELECT 
    order_id,
    pizza_id,
    quantity
FROM order_details
WHERE pizza_id IN (
    -- Subquery: Finds the ID of the pizza(s) with the highest price
    SELECT pizza_id 
    FROM pizzas 
    WHERE price = (SELECT MAX(price) FROM pizzas)
);


-- 4.2. Subquery in SELECT clause:
-- Calculate revenue for each pizza and show its % share of total overall revenue
SELECT 
    pt.name AS Pizza_Name,
    SUM(od.quantity * p.price) AS Pizza_Revenue,
    (SUM(od.quantity * p.price) / 
        (SELECT SUM(quantity * price) FROM order_details od2 JOIN pizzas p2 ON od2.pizza_id = p2.pizza_id)
    ) * 100 AS Percentage_Of_Total
FROM order_details od
JOIN pizzas p ON od.pizza_id = p.pizza_id
JOIN pizza_types pt ON p.pizza_type_id = pt.pizza_type_id
GROUP BY pt.name
ORDER BY Pizza_Revenue DESC;


---------------------------------------------------------------
-- 5. SET OPERATIONS (UNION, INTERSECT, EXCEPT)
---------------------------------------------------------------

-- 5.1. UNION (Combines results by stacking them, removing duplicates)
-- Ex: List of ingredient names containing "Cheese" OR "Garlic"
SELECT ingredient_name FROM ingredients WHERE ingredient_name LIKE '%Cheese%'
UNION
SELECT ingredient_name FROM ingredients WHERE ingredient_name LIKE '%Garlic%';


-- 5.2. INTERSECT (Returns only results present in BOTH queries)
-- Ex: Which ingredients are used in BOTH 'Veggie' AND 'Classic' categories?
SELECT i.ingredient_name
FROM ingredients i
JOIN pizza_type_ingredients pti ON i.ingredient_id = pti.ingredient_id
JOIN pizza_types pt ON pti.pizza_type_id = pt.pizza_type_id
JOIN categories c ON pt.category_id = c.category_id
WHERE c.category_name = 'Veggie'

INTERSECT

SELECT i.ingredient_name
FROM ingredients i
JOIN pizza_type_ingredients pti ON i.ingredient_id = pti.ingredient_id
JOIN pizza_types pt ON pti.pizza_type_id = pt.pizza_type_id
JOIN categories c ON pt.category_id = c.category_id
WHERE c.category_name = 'Classic';


-- 5.3. EXCEPT (Returns results from the first query MINUS those in the second)
-- Ex: Which ingredients exist in 'Veggie' category that NEVER appear in 'Chicken'?
SELECT i.ingredient_name
FROM ingredients i
JOIN pizza_type_ingredients pti ON i.ingredient_id = pti.ingredient_id
JOIN pizza_types pt ON pti.pizza_type_id = pt.pizza_type_id
JOIN categories c ON pt.category_id = c.category_id
WHERE c.category_name = 'Veggie'

EXCEPT

SELECT i.ingredient_name
FROM ingredients i
JOIN pizza_type_ingredients pti ON i.ingredient_id = pti.ingredient_id
JOIN pizza_types pt ON pti.pizza_type_id = pt.pizza_type_id
JOIN categories c ON pt.category_id = c.category_id
WHERE c.category_name = 'Chicken';


---------------------------------------------------------------
-- 6. ADVANCED ANALYTICS (CTEs, WINDOW FUNCTIONS, SELF JOIN, HAVING)
---------------------------------------------------------------

-- 6.1. Market Basket Analysis with CTE and Self Join
-- Top 10 pizza flavor pairs purchased together in the same order.
-- DISTINCT in the CTE prevents multiple sizes of a flavor from inflating pair counts.
WITH OrderPizzaTypes AS (
    SELECT DISTINCT
        od.order_id,
        p.pizza_type_id
    FROM order_details od
    INNER JOIN pizzas p ON od.pizza_id = p.pizza_id
)
SELECT TOP 10
    pt1.name AS Pizza_1,
    pt2.name AS Pizza_2,
    COUNT(DISTINCT first_type.order_id) AS Orders_Together
FROM OrderPizzaTypes first_type
INNER JOIN OrderPizzaTypes second_type
    ON first_type.order_id = second_type.order_id
   AND first_type.pizza_type_id < second_type.pizza_type_id
INNER JOIN pizza_types pt1 ON first_type.pizza_type_id = pt1.pizza_type_id
INNER JOIN pizza_types pt2 ON second_type.pizza_type_id = pt2.pizza_type_id
GROUP BY pt1.name, pt2.name
ORDER BY Orders_Together DESC, pt1.name, pt2.name;


-- 6.2. Top 2 menu pizzas by gross revenue within each category
-- DENSE_RANK keeps ties and restarts the ranking for every category.
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
    category_name,
    Pizza_Name,
    Gross_Revenue,
    Revenue_Rank
FROM RankedPizzaRevenue
WHERE Revenue_Rank <= 2
ORDER BY category_name, Revenue_Rank, Pizza_Name;


-- 6.3. Recipe complexity in 1NF with GROUP BY and HAVING
-- Recipes with at least 7 distinct ingredients and their average menu price.
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
    rc.Pizza_Name,
    rc.category_name,
    rc.Ingredient_Count,
    AVG(p.price) AS Average_Menu_Price
FROM RecipeComplexity rc
INNER JOIN pizzas p ON rc.pizza_type_id = p.pizza_type_id
GROUP BY rc.Pizza_Name, rc.category_name, rc.Ingredient_Count
ORDER BY rc.Ingredient_Count DESC, rc.Pizza_Name;


-- 6.4. Order segmentation with CTE and CASE WHEN
-- Average ticket is the average gross revenue per order in each profile.
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
    Order_Profile,
    COUNT(*) AS Total_Orders,
    SUM(Total_Pizzas) AS Total_Pizzas_Sold,
    AVG(Gross_Order_Revenue) AS Average_Ticket
FROM SegmentedOrders
GROUP BY Order_Profile
ORDER BY Order_Profile;

