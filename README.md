# clickhouse-uniq-accuracy

Эмпирический замер точности и времени трёх оценщиков мощности множества в ClickHouse — `uniq()`, `uniqCombined64()`, `uniqExact()` / `count(DISTINCT)` — на N от 10⁵ до 10¹¹.

- **Лендинг**: [docs/index.html](docs/index.html) (опубликован через GitHub Pages на https://giffok.github.io/clickhouse-uniq-accuracy/)
- **Полный разбор**: [results/analysis.md](results/analysis.md)
- **Сырые данные**: [results/raw.csv](results/raw.csv) — одна строка на каждый запрос, все хеш-сиды
- **Лог стоимости / времени**: [results/cost-log.md](results/cost-log.md)

## Конфигурация эксперимента

- Yandex Managed ClickHouse 25.8.22.28-yc.2, 1 хост `c3-c4-m8` (4 vCPU, 8 GB RAM), network-ssd 10 GB
- Истинная мощность задаётся `numbers_mt(N)` — генерирует ровно N различных целых на лету
- Распределение ошибки получаем через `cityHash64(number, salt)` с m разных солей на каждое N

## Воспроизведение

```bash
# 1. Поднять кластер в YC (см. cost-log.md)
yc managed-clickhouse cluster create --name clickhouse-uniq-experiment \
    --environment production --network-name default \
    --clickhouse-resource-preset c3-c4-m8 \
    --host type=clickhouse,zone-id=ru-central1-a,subnet-name=default-ru-central1-a,assign-public-ip=true \
    --clickhouse-disk-size 10G --clickhouse-disk-type network-ssd \
    --user name=expuser,password=<PASSWORD> --database name=experiment

# 2. Записать CH_EXPERIMENT_HOST/USER/PASSWORD в окружение
#    (см. шапку scripts/run-experiment.py — путь к .env)

# 3. Установить клиент и запустить
pip install clickhouse-driver
python scripts/run-experiment.py

# 4. Снести кластер
yc managed-clickhouse cluster delete <CLUSTER_ID>
```

Прогон занимает ~3 часа на одном хосте `c3-c4-m8` (большая часть времени — `uniqCombined64` на 10¹¹).

## Структура

```
scripts/
  run-experiment.py        # главный скрипт: все три среза в одном проходе
  run-precision-sweep.py   # бонус: uniqCombined64(p) для p=12..20
  summarize.py             # агрегаты по raw.csv в TSV для вставки
  debug-parallel.py        # диагностика TLS-handshake-проблем YC public IP
  queries.sql              # эталонные SQL для ручного прогона
results/
  raw.csv                  # одна строка на запрос — все экспери­менты
  analysis.md              # long-form разбор
  cost-log.md              # хронология аренды и стоимость
docs/
  index.html               # лендинг с ключевыми таблицами (GitHub Pages source)
YandexInternalRootCA.crt   # CA-сертификат для TLS YC (публичный)
```

## Главные находки (TL;DR)

- На N ≤ 10¹⁰: `uniq()` несмещён, std ≈ 0.33–0.51% (теория: ~0.39%). `uniqCombined64()` несмещён, std ≈ 0.24–0.36% (теория: ~0.29%) — стабильно точнее `uniq` в 1.3–1.7×.
- На N = 10¹¹ `uniq()` детерминированно ломается: возвращает 2⁶⁴ − 95 265 423 098 ≈ 1.84×10¹⁹ для любого входа.
- `uniqCombined64()` остаётся корректным на 10¹¹ (rel err ≈ +0.1%), но в 1–4× медленнее `uniq`.
- `uniqHLL12` / `uniqCombined` (32-бит хеш) на 10¹¹ выходят на плато ~6.2 млрд — потолок 2³²-пространства хешей.
- Точный `uniqExact` / `count(DISTINCT)` упирается в OOM при N ≥ 10⁹ на 8 GB хосте.
