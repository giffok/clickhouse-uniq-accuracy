-- Этап 1: одиночный замер uniq() для каждого N
-- Запускать каждый запрос отдельно, чтобы получить чистое elapsed time.
-- truth = N (мы генерируем 1..N последовательно)

SELECT uniq(number) AS estimated FROM numbers_mt(100000)       FORMAT JSON;  -- 1e5
SELECT uniq(number) AS estimated FROM numbers_mt(1000000)      FORMAT JSON;  -- 1e6
SELECT uniq(number) AS estimated FROM numbers_mt(10000000)     FORMAT JSON;  -- 1e7
SELECT uniq(number) AS estimated FROM numbers_mt(100000000)    FORMAT JSON;  -- 1e8
SELECT uniq(number) AS estimated FROM numbers_mt(1000000000)   FORMAT JSON;  -- 1e9
SELECT uniq(number) AS estimated FROM numbers_mt(10000000000)  FORMAT JSON;  -- 1e10
SELECT uniq(number) AS estimated FROM numbers_mt(100000000000) FORMAT JSON;  -- 1e11

-- Этап 2 (потенциальный): распределение ошибок при разных хеш-сидах
-- Используем cityHash64(number, salt) — каждый salt даёт независимую HLL-оценку
SELECT uniq(cityHash64(number, 1)) FROM numbers_mt(1000000000) FORMAT JSON;
SELECT uniq(cityHash64(number, 2)) FROM numbers_mt(1000000000) FORMAT JSON;
-- ... salt = 1..m
