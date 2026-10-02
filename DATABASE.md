# Database model

PhoneBench uses SQLAlchemy models and a relational schema. SQLite is the default. Models avoid SQLite-only column types; the optional backup implementation and monthly SQL aggregation aside, the application uses ORM relations intended to support another SQLAlchemy database URL and driver.

## Main relationships

```text
Customer 1 ── * Device
Customer 1 ── * Repair * ── 1 Device
Repair 1 ── * Diagnosis
Repair 1 ── * RepairAttempt
RepairAttempt 1 ── 0..1 Solution
Repair 1 ── * InventoryMovement * ── 1 InventoryItem
Repair 1 ── * Invoice 1 ── * InvoiceItem
Invoice 1 ── * Payment ── 1 linked Transaction
Repair 1 ── * PortalToken (only token hash stored)
Device 1 ── * DeviceIdentifier
Device 1 ── * DeviceProperty (raw source properties)
```

## Data tables

- `users`: hashed login credentials, active state, and role.
- `customers`, `devices`: customer profiles and reusable device master records.
- `device_identifiers`, `device_properties`: multiple identity values and captured raw ADB properties. Identifier values should be handled as sensitive personal/device data.
- `repairs`, `diagnoses`, `repair_attempts`, `solutions`: ticket lifecycle and searchable technical history. Attempts are numbered uniquely per repair. Solution verification is a separate technician action.
- `inventory_items`, `inventory_movements`: current quantity plus immutable movement history; repair use movements reference their ticket.
- `invoices`, `invoice_items`, `payments`, `transactions`: invoice totals, collected amounts, refunds, and cash-basis accounting. Each payment emits a single transaction with a `PAYMENT:<id>` reference.
- `portal_tokens`: SHA-256 token digest and revocation state; cleartext links are shown only when issued.
- `attachments`: entity ownership metadata; file bytes live under the configured upload directory.
- `audit_logs`: action/entity changes without password/API-key payloads.
- `app_settings`, `notification_templates`, `pending_device_scans`: non-secret operational settings, message templates, and server-side short-lived scanner properties.

Branch scoping is not exposed in V1. Branch-aware ownership can be introduced using nullable `branch_id` foreign keys and backfill/default policy without changing customer-device-repair relationships.

## Initialize and evolve

For a fresh local database:

```powershell
flask --app run.py init-db
```

Before changing a deployed schema, create and validate a backup. Flask-Migrate is registered; the project has no initial migration history yet, so initialize the migration repository on the deployment branch before the first migration:

```powershell
flask --app run.py db init
flask --app run.py db migrate -m "Initial schema"
flask --app run.py db upgrade
```

Do not run `db init` a second time after a migrations directory exists. For a future migration-controlled installation, use migrations rather than `init-db` to evolve tables.

## Amounts, time, identifiers

Money is stored as fixed-precision `Numeric(12,2)` and validated as non-negative at the form boundary. Repair and audit timestamps are UTC-naive values for local deployments; date-only accounting periods use SQL `Date`. Ticket and invoice identifiers are derived from inserted row IDs to avoid count-based collisions. Passwords are one-way Werkzeug hashes; portal bearer tokens are hashed before persistence.
