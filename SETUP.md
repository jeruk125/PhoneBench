# Setup and operations

## Windows installation

Use Python 3.11+ and run in PowerShell:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
flask --app run.py init-db
flask --app run.py create-admin
python run.py
```

Use `waitress-serve --listen=127.0.0.1:5000 run:app` for a local WSGI server. Do not expose the development server directly to a network. Set `PHONEBENCH_SECRET_KEY` to a long, randomly generated value when deploying; local installations otherwise create a persistent random secret in `instance\secret.key`. Never commit `.env`, `instance\`, or backups.

## Database and file locations

- Default database: `instance\phonebench.sqlite`
- Attachments: `instance\uploads\`
- Backups: `instance\backups\`
- Local generated secret: `instance\secret.key`

Override the database with `PHONEBENCH_DATABASE_URL`, for example `postgresql+psycopg://...` after installing a suitable database driver. Keep uploads and SQLite files on a local, access-controlled disk. An HTTPS reverse proxy is required before exposing the customer portal to a network.

## Accounts and roles

`flask --app run.py create-admin` prompts for a username, display name, and password. Passwords must contain at least 12 characters. Owner/Admin have full access; technicians can work assigned tickets and knowledge; Receptionists handle customer/device/intake tasks; Accounting manages invoices, payments, and financial views. Create further staff from **Technicians / Users**. There are no preset passwords.

## Demo records

`flask --app run.py seed-demo` creates fictional `Demo ...` records without demo users. Seeded notes, repairs, solutions, inventory, and invoice values are explicitly marked as demo content.

## Optional AI provider

Set environment variables in the service environment or a local, ignored `.env` file:

```text
PHONEBENCH_AI_BASE_URL=https://your-openai-compatible-host/v1
PHONEBENCH_AI_API_KEY=your-private-key
PHONEBENCH_AI_MODEL=your-model
```

The base URL should include the provider's API prefix where required. The assistant retrieves PhoneBench history first, supplies that evidence as context, and labels generated text as AI interpretation. Credentials are not shown in Settings or recorded in audit data. Review privacy terms before sending repair records to a remote provider; use a local endpoint for offline/private operation.

## Optional WhatsApp Cloud API

Configure a business-owned Cloud API number:

```text
PHONEBENCH_WHATSAPP_TOKEN=your-private-access-token
PHONEBENCH_WHATSAPP_PHONE_NUMBER_ID=your-phone-number-id
PHONEBENCH_WHATSAPP_API_VERSION=v22.0
```

Edit message templates in **Settings**. Sending is available only when provider credentials, customer phone number, and an enabled template are present. The application does not automate WhatsApp Web, scan QR codes, or bypass Meta's provider controls. Test with an approved number before sending customer notifications.

## Optional Android scanner

Install Android SDK Platform Tools and add `adb.exe` to the Windows `PATH`. Connect an Android phone, authorize USB debugging on the phone, and use **Device Scanner**. PhoneBench calls `adb devices` and read-only `adb shell getprop`. If ADB is missing or the device is unauthorized, manual device entry remains available.

## Backups and restore

Use **Backup / Restore → Create backup now** for a consistent SQLite snapshot. Attachments are backed up to a paired ZIP archive. Download and move both files to access-controlled external storage. A SQLite restore makes a timestamped copy of the current database before replacement; attachment archives should be restored separately into the uploads directory after checking their contents.

For a daily/weekly scheduled backup, set `PHONEBENCH_BACKUP_FREQUENCY=daily` or `weekly` and schedule this command in Windows Task Scheduler from the project directory, using the virtual environment's Python/Flask command:

```powershell
.\.venv\Scripts\flask.exe --app run.py backup-if-due
```

Use `manual` to disable scheduled runs. Test restores against a copy before relying on them. Keep backup media encrypted and offline where practical. JSON export is available from the backup page; it contains the database records and should be treated as sensitive.

## Production hardening checklist

- Use an HTTPS reverse proxy and set `PHONEBENCH_COOKIE_SECURE=true` in the deployment configuration.
- Keep database, upload, secret, and backup paths writable only by the service account.
- Use unique staff accounts, remove access promptly, and verify backup restore regularly.
- Restrict network access and configure the host firewall.
- Use a production database driver and migration workflow before changing away from SQLite.
- Confirm the AI provider's data handling before transmitting any customer information.
