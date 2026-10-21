# A8 — PostgreSQL parity réellement exécutée

Pour exécuter la suite avec PostgreSQL réel :

```
AURA_TEST_PG_DSN="postgresql://user:pass@host:5432/db" \
  AURA_API_ADMIN_PASSWORD=ci AURA_S3_ACCESS_KEY=ci AURA_S3_SECRET_KEY=ci AURA_S3_ENDPOINT=https://127.0.0.1:9 \
  .venv/bin/python -m pytest tests/ -q
```

Sans cette variable, les tests utilisent SQLite (:memory:).
