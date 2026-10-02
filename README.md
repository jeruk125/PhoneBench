# PhoneBench

PhoneBench is a local-first smartphone service desk and technical repair knowledge system. It connects customers, independent device records, service tickets, diagnoses, repair attempts, reusable historical solutions, inventory, invoices, payments, and audit records. A repair is evidence—not just a status—so technicians can later search the actual tools, firmware, methods, outcomes, and errors recorded by the shop.

## Run locally (Windows)

1. Install Python 3.11 or newer.
2. In PowerShell from this folder:

   ```powershell
   py -3 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install -r requirements.txt
   flask --app run.py init-db
   flask --app run.py create-admin
   python run.py
   ```

3. Open `http://127.0.0.1:5000`. The local SQLite file is created at `instance\phonebench.sqlite`; private uploads, generated backups, and the local session secret are stored below `instance\`.

For a local production-style WSGI server (rather than Flask's development server), run:

```powershell
waitress-serve --listen=127.0.0.1:5000 run:app
```

Keep the service bound to loopback unless it is behind a correctly configured HTTPS reverse proxy and an appropriate firewall. The first owner account is created interactively; PhoneBench does not ship demo login credentials.

## Try demo data

Run `flask --app run.py seed-demo` after database initialization. It adds clearly marked fictional customers, six device brands/models, repairs, diagnoses, attempts, knowledge, stock, and invoices/payments. It creates no login account and is idempotent. Do not mistake seeded records for real shop data.

## Main workflows

- Create customers, then independent device records and a repair ticket with an assigned technician.
- Add multiple diagnoses and individually numbered attempts. Failed errors and successful outcomes remain searchable.
- Promote a successful attempt into an **unverified historical** knowledge article. A technician may separately mark evidence verified.
- Record stock movements; repair consumption immediately reduces stock and is included on the repair invoice.
- Issue invoices and record partial/full payments or refunds. Each payment creates exactly one linked accounting transaction; invoice creation is not treated as cash received.
- Generate a per-repair customer portal token. The raw link is shown once, stored only as a hash, and can be revoked.
- Use optional local ADB property scanning, or continue entering device details manually.
- Configure provider credentials with local environment variables. WhatsApp/AI are clearly marked unconfigured when credentials are absent; no unofficial WhatsApp automation is used.

## Security and privacy

Passwords are hashed. Flask-WTF CSRF protection, role checks, secure session cookie defaults, bounded uploads, extension allowlisting, randomized upload names, masked device identifiers, and audit records are included. Do not enter customer/device passwords, account credentials, FRP secrets, or authentication tokens into repair notes. Local data and backups require OS-level access controls and a protected backup destination. See [SETUP.md](./SETUP.md) and [ARCHITECTURE.md](./ARCHITECTURE.md).

## Documentation

- [SETUP.md](./SETUP.md) — environment, account, integration, and backup setup
- [DATABASE.md](./DATABASE.md) — data relationships and migration notes
- [ARCHITECTURE.md](./ARCHITECTURE.md) — modules, security boundaries, and extension points
- [API.md](./API.md) — initial JSON API endpoints

## Tests

```powershell
python -m unittest discover -s tests -v
```

## Operational limitations

PhoneBench provides shop-workflow and cash-basis estimates, not formal tax, statutory, or enterprise accounting. The customer portal is a per-ticket token link, not a full customer identity system. The AI and WhatsApp providers need shop-owned credentials; ADB requires Android Platform Tools and an authorized device. Database schema changes in a deployed installation should be applied with Flask-Migrate, with a backup taken first.
