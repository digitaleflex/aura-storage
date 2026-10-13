# Architecture Decisions

## ADR-001 — Independent storage service (Accepted)

AURA is operated independently from OpenBooks, Axiom and Azure. Applications consume an S3-compatible interface; ordinary file access does not require the control plane.

## ADR-002 — Single VPS first (Accepted for MVP)

Begin with one VPS to control complexity. This is not high availability. Independent backups and a tested restore are mandatory before importing production data.

## ADR-003 — SeaweedFS candidate (Proposed; verify)

Validate release maturity, S3 API compatibility, data layout, security, upgrades and resource use before committing production content.

## ADR-004 — Separate data and control planes (Accepted)

Normal object requests use the S3 interface. Future management integration can observe health/capacity and perform restricted operations, but Axiom must not be required for normal data access.