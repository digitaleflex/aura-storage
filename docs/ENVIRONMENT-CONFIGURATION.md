# Environment Configuration

## Principle

Environment-specific values belong in the local `.env`. Keep service topology and security rules versioned in `docker-compose.yml`; do not make security-sensitive ports or network isolation casually configurable.

## Values controlled by `.env`

- `AURA_INSTANCE_ID`: local container name prefix, e.g. `aura-001`.
- `TZ`: container timezone.
- `TRAEFIK_IMAGE`, `SEAWEEDFS_IMAGE`: reviewed image references.
- `S3_DOMAIN`: public hostname routed to the S3 gateway.
- `ACME_EMAIL`: certificate notifications.
- `AURA_DATA_DIR`: persistent data root. Prefer an absolute path on the intended filesystem.
- `SEAWEED_VOLUME_SIZE_LIMIT_MB`, `SEAWEED_VOLUME_MAX`: SeaweedFS capacity controls.
- `S3_ACCESS_KEY`, `S3_SECRET_KEY`: initial S3 credentials injected into generated local config.

## First setup

```bash
cp .env.example .env
chmod 600 .env
# Edit .env locally; use strong random S3 credentials and real domain/email.
bash ./scripts/generate-config.sh
chmod 600 config/seaweedfs/s3.json
docker compose config --quiet
```

The generator creates `config/seaweedfs/s3.json` from the tracked example and local environment values. The generated file is ignored by Git. It does not change or erase storage data.

The generator currently injects the configured credentials into the placeholder credential fields in the example identity. Review the example's permissions and confirm policy/action syntax for the exact SeaweedFS release. Do not use a broad Admin identity for routine application access; create least-privilege identities as the service evolves.

## Domain migration

To move from an initial endpoint to a dedicated domain:

1. Create DNS records for the new S3 hostname pointing to the VPS.
2. Set `S3_DOMAIN` in `.env` to the new hostname.
3. Confirm ports 80/443 are reachable and the old endpoint can remain available during migration if desired.
4. Run `docker compose config --quiet` and inspect the rendered configuration locally.
5. Deploy with the reviewed procedure and verify the new HTTPS certificate and authenticated S3 upload/download.
6. Update client endpoint configuration separately where clients currently hard-code the old endpoint.
7. Retire the old DNS name only after client migration and validation.

Changing `S3_DOMAIN` does not automatically update DNS, clients, external firewall rules, or application configuration outside this repository.

## Change classes

Usually environment-only: hostname, ACME email, image reference, data root, instance name, supported capacity settings and credentials.

May require code/config changes: service topology, adding a database/API, changing network boundaries, changing exposed ports, changing SeaweedFS command semantics, adding new application behavior, or altering policy schema.

## Safety

- Never commit `.env` or generated `config/seaweedfs/s3.json`.
- Do not print secrets or the fully rendered Compose configuration into public issues/logs.
- Back up persistent data before upgrades or changing storage paths.
- Changing `AURA_DATA_DIR` points services at a different directory; it does not move existing files. Copy/verify data separately before changing it.
- Rotating S3 credentials requires updating the generated config and any clients using those credentials.
