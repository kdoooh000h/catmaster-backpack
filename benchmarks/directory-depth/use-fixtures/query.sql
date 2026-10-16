CREATE TABLE customers(id INTEGER PRIMARY KEY, name TEXT NOT NULL);
CREATE TABLE orders(id INTEGER PRIMARY KEY, customer_id INTEGER NOT NULL REFERENCES customers(id), amount_cents INTEGER NOT NULL, status TEXT NOT NULL);
INSERT INTO customers VALUES (1,'北星'),(2,'岚'),(3,'青叶');
INSERT INTO orders VALUES (101,1,1000,'paid'),(102,1,500,'paid'),(103,1,900,'pending'),(104,2,700,'paid'),(105,3,600,'cancelled');
