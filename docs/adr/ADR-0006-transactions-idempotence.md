# ADR-0006 — Transactions, idempotence et cohérence distribuée

- Statut: Proposé
- Date: 2026-11-26
- Issue: #333

## Règles

- **Transaction locale DB**: préférée pour invariants domaine.
- **S3+DB**: pas de transaction distribuée; utiliser ordre sûr, idempotence, réconciliation.
- **Idempotence**: commit/abort/upload intent, share redeem, jobs, webhooks futurs doivent supporter retry.
- **États explicites**: transitions objet/transfer/job documentées et testées.
- **Réconciliation**: workers reconcile/verifier/scrubber restent la sécurité ultime.
- **Observabilité**: correlation/request id dans logs/audit/jobs.
