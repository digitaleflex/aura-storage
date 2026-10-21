# ENG-05 — Retry, backoff et contrôle de congestion

Implémenté dans `web/src/lib/transfer.ts` : `backoffDelay` (exponential backoff + jitter), classification des erreurs (retryable/expired/aborted/fatal).
