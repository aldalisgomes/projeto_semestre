-- 1. Reset and create the database
USE master;
GO

DROP DATABASE IF EXISTS PizzaSales;
GO

CREATE DATABASE PizzaSales;
GO

USE PizzaSales;
GO

-- 2. Categories Table
CREATE TABLE categories (
    category_id INT PRIMARY KEY,
    category_name VARCHAR(50) NOT NULL UNIQUE
);

-- 3. Pizza Types Table
CREATE TABLE pizza_types (
    pizza_type_id VARCHAR(50) PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    category_id INT NOT NULL,
    FOREIGN KEY (category_id) REFERENCES categories(category_id)
);

-- 4. Ingredients Table
CREATE TABLE ingredients (
    ingredient_id INT PRIMARY KEY,
    ingredient_name VARCHAR(100) NOT NULL UNIQUE
);

-- 5. Associative Table (Pizza Types <-> Ingredients)
CREATE TABLE pizza_type_ingredients (
    pizza_type_id VARCHAR(50) NOT NULL,
    ingredient_id INT NOT NULL,
    PRIMARY KEY (pizza_type_id, ingredient_id),
    FOREIGN KEY (pizza_type_id) REFERENCES pizza_types(pizza_type_id),
    FOREIGN KEY (ingredient_id) REFERENCES ingredients(ingredient_id)
);

-- 6. Pizzas Table (Price and Size)
CREATE TABLE pizzas (
    pizza_id VARCHAR(50) PRIMARY KEY,
    pizza_type_id VARCHAR(50) NOT NULL,
    size VARCHAR(5) NOT NULL CHECK (size IN ('S', 'M', 'L', 'XL', 'XXL')),
    price DECIMAL(5,2) NOT NULL CHECK (price > 0),
    FOREIGN KEY (pizza_type_id) REFERENCES pizza_types(pizza_type_id)
);

-- 7. Orders Table
CREATE TABLE orders (
    order_id INT PRIMARY KEY,
    date DATE NOT NULL CHECK (date >= '2015-01-01' AND date <= '2015-12-31'),
    time TIME NOT NULL
);

-- 8. Order Details Table
CREATE TABLE order_details (
    order_details_id INT PRIMARY KEY,
    order_id INT NOT NULL,
    pizza_id VARCHAR(50) NOT NULL,
    quantity INT NOT NULL CHECK (quantity > 0),
    FOREIGN KEY (order_id) REFERENCES orders(order_id),
    FOREIGN KEY (pizza_id) REFERENCES pizzas(pizza_id)
);