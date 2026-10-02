# Architecture

PhoneBench is a modular Flask application with a server-rendered HTML/CSS/JavaScript interface. It defaults to SQLite and does not require a frontend build tool or remote UI assets.

```text
Flask app factory
  ├─ extensions.py: SQLAlchemy, Flask-Migrate, LoginManager, CSRF
  ├─ models.py: relational records and explicit relationships
  ├─ routes/: auth, core, repairs/knowledge, finance, operations, portal, JSON API
  ├─ services/: ADB, AI provider, WhatsApp provider, database backup
  ├─ templates/: desktop-first responsive views
  └─ static/: local styles and small interaction helpers
```

## Request and service boundaries

- `create_app()` loads local configuration, installs security extensions, registers route modules and CLI commands, and keeps persistent runtime data under `instance\`.
- Route handlers validate user input and permissions, perform transactional model updates, and record audit events.
- `services/adb.py` is read-only device identification and can later be joined by Fastboot or other transport modules.
- `services/ai.py` is an OpenAI-compatible adapter. The assistant retrieves relevant local solution/attempt evidence before making a provider call.
- `services/whatsapp.py` defines a provider interface and Cloud API implementation. No secret or provider-specific automation is hard-coded into repair logic.
- Invoice payment creates one linked `Transaction`; invoice totals and paid/balance values remain separate.
- The public portal accepts an unguessable ticket token, stores only its SHA-256 digest, supports revocation, and renders a separate restricted view.

## Security boundaries

Authentication is required for staff views and JSON business endpoints. Role checks gate repair, customer, inventory, accounting, and administration surfaces; technician ticket access is additionally scoped to assigned repairs on ticket-detail/API endpoints. CSRF applies to mutating browser forms. Upload names are sanitized and replaced with random disk names, with a size limit and extension allowlist. Portal pages do not render technician notes, repair attempts, attachments, or identifiers.

External AI/WhatsApp API credentials are provided via local environment configuration and never stored in the repository. The AI prompt explicitly distinguishes database evidence from interpretation. A technician must independently mark an article verified.

## Extension points

- Add provider classes behind `AIProvider` and `WhatsAppProvider`.
- Add scanner implementations behind the device service boundary without making ADB mandatory.
- Add PostgreSQL/MySQL with a SQLAlchemy URL and matching driver; evolve schema via reviewed migrations.
- Introduce `branch_id` foreign keys in a future multi-branch release; V1 intentionally has no branch UI.
- Expand user permissions into persisted permission grants as the role matrix grows.
- Add asynchronous notifications, event delivery, and retry queues when a deployment has a persistent worker.

## Product scope and limitations

This version implements local ticketing, knowledge capture/search, inventory, basic invoice/payment workflows, operational reports, the optional local scanner, secure token status pages, and explicit integrations. It is not formal accounting software, not a customer identity provider, and does not claim external providers are usable until configured. Scheduled backup execution is delegated to Windows Task Scheduler rather than an in-process scheduler.
