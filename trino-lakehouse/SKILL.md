# Trino Lakehouse (CLI)

Query the Cruise production Trino cluster against Iceberg lakehouse tables (interactive / analytical SQL).

## Pre-flight: Authentication (two-tier)

**Tier 1** (try first — usually instant, no browser MFA):

```bash
authcli refresh
authcli app get spidercat -out stdout | head -c 30
```

**Tier 2** (if Tier 1 fails or Trino still returns auth errors): follow `~/.cursor/skills/cruise-auth-refresh/SKILL.md` for the full SSO flow.

Re-fetch the spidercat token after any refresh.

## CLI invocation

The Trino CLI ships as a local JAR (typically `$HOME/trino.jar`). Prefer `$HOME` over `~` inside nested command substitutions — tilde expansion is unreliable there.

```bash
"$HOME/trino.jar" \
  --server https://trino.prd.paasapps.robot.car \
  --access-token "$(authcli app get spidercat -out stdout)" \
  --execute "YOUR SQL HERE" 2>&1
```

## Catalog / schema

- A common NVIDIA workspace is `lakehouse.nvidia_prod`. Other catalogs and schemas exist — use `SHOW SCHEMAS FROM lakehouse` (or equivalent) to discover.

## Struct / nested fields

Use dotted paths for struct columns, e.g. `row_key.label_class_id` (exact paths depend on the table DDL).

## Gotchas

- **Stderr noise**: Java “illegal reflective access” / module warnings are usually harmless; focus on the query result or Trino error text.
- **Runtime**: Wide scans or large joins can take minutes; add `LIMIT` while exploring.
- **Auth expiry**: On 401 / access denied, run Tier 1 auth again, then Tier 2 if needed.

## When to use this skill

Use when you need ad-hoc SQL across VINs or global aggregates where the Polars client is too constrained, or for quick validation counts against Iceberg tables.
