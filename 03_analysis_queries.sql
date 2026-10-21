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
    AVG(CAST(od.quantity AS DECIMAL(5,2))) AS Avg_Pizzas_Per_Order
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
-- Ex: Which ingredients exist in 'Veggie' category that NEVER appear in 'Meat'?
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
WHERE c.category_name = 'Meat';

