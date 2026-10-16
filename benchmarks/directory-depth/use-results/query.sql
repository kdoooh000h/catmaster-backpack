SELECT c.id, c.name, COALESCE(SUM(o.amount_cents), 0) AS paid_total_cents
FROM customers AS c
LEFT JOIN orders AS o ON o.customer_id = c.id AND o.status = :status
GROUP BY c.id, c.name
ORDER BY paid_total_cents DESC, c.id ASC;
