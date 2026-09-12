# Deployment and activation

No VPS has been accessed or deployed during this build. Docker Compose definitions parse as YAML, but Docker execution and TLS issuance are unverified here. Inventory CPU/RAM/disk, existing services, available ports, domain, admin access and off-server backups before deployment. The configured container memory ceilings total about 5.6 GiB before OS headroom. These are limits, not measured reservations or a hardware recommendation; measure actual load and size the host or lower concurrency before activation.

## Local setup

Use README commands. Root `.env` is passed by Compose. Bare Python launched in `backend/` reads `backend/.env` or explicit environment variables. Keep local/staging/production values separate. Optional missing credentials produce NOT_CONFIGURED. Nonlocal startup requires HTTPS, explicit Google owner/client configuration and a valid token encryption key; DEMO_MODE is forbidden.

## Production secrets

Create `.secrets/postgres_admin_password`, `.secrets/owner_password`, `.secrets/app_password` outside Git. Generate independent strong values locally. The initialization script reads files and uses psql's literal quoting; it creates `staffer_owner` for migrations and `staffer_app` for runtime DML. The database administration role remains private. Existing volumes do not rerun initialization; migrate existing role ownership deliberately.

Create `.env.production` based on `.env.example` with APP_ENV=production, DEMO_MODE=false and HTTPS PUBLIC_BASE_URL. DATABASE_URL must use `staffer_app` and hostname postgres; REDIS_URL uses redis. Keep the matching migration DSN separately as MIGRATION_DATABASE_URL. Set Google credentials and TOKEN_ENCRYPTION_KEY (generate with `Fernet.generate_key()` in a secure local terminal). FCM service credentials can be mounted under `/run/staffer-secrets`; grant only the container service UID10001 the required read permission. Do not paste keys into chat or Git.

Set DOMAIN for Compose interpolation. Deploy commands from root, after authorization and backup:

```bash
docker compose -f deployment/compose.production.yml build
docker compose -f deployment/compose.production.yml up -d postgres redis
docker compose -f deployment/compose.production.yml run --rm -e DATABASE_URL="$MIGRATION_DATABASE_URL" api alembic upgrade head
docker compose -f deployment/compose.production.yml up -d
```

Caddy's default certificate validation requires ports80 and443 with DNS pointing at the host. Do not claim a443-only deployment with HTTP validation. Restrict SSH separately, account for Docker firewall behavior, and keep worker/DB/broker ports unpublished. Health readiness requires the exact shipped migration head and a responsive Redis; Google live grant checks are separate.

## Post-deployment gates

Check `/api/v1/health/ready`, allowed-owner login, one public configured source run, evidence withholding, save/apply/undo, exact notification routes, client restart and off-server restore. Do not execute demo reset on production. Record observed performance, source coverage and failures in BUILD_STATUS. A source label is not an implemented/global source guarantee.

## Updating and rollback

Pin previous backend image, native installer/APK and migration head. Back up first, apply migrations once with the owner role, then upgrade backend/clients. Verify checksums and signing identity outside the app before native installation; never auto-run an arbitrary downloaded binary. Downgrades that destroy immutable history are intentionally blocked in the history guard migration. Prefer restoring into a clean database or rolling code back compatibly; never delete user history to make a downgrade pass.

Source limits, Gmail consent/reconnection, People provider costs, FCM settings and signing are independent activation items. See their dedicated runbooks.
