# PhoneBench JSON API

Base path: `/api/v1`. Business endpoints use the same logged-in staff session and role checks as the web application. Send the session cookie and a CSRF token for any future/mutating session-authenticated endpoints. The API does not accept API keys or customer portal tokens as staff credentials.

## Endpoints

### `GET /api/v1/health`

Unauthenticated liveness response:

```json
{"status":"ok","service":"PhoneBench"}
```

### `GET /api/v1/repairs`

Requires staff login. Returns up to 100 most recent tickets; technicians see only assigned tickets. Optional `status` filter.

### `GET /api/v1/repairs/{id}`

Requires staff login. Technicians cannot inspect a ticket assigned to another technician. Response includes customer-reported problem, device identity, diagnoses, and technical attempt outcomes. It excludes customer contact details, passwords, internal invoice data, and raw identifiers.

### `GET /api/v1/knowledge?q={term}`

Requires staff login and `knowledge.read`. Returns matching historical solution evidence, success/failure counts, source ticket, and a distinct verification label. A missing `q` returns HTTP 400.

## Portal status view

`GET /customer/{unguessable-token}` is a separate HTML customer surface, not a staff API. The random bearer token is shown only at creation, stored only as a digest, and can be revoked. Treat the URL as private.

## Errors and versioning

Standard HTTP status codes are used (`400` invalid input, `401` staff authentication required, `403` forbidden, `404` unknown/revoked portal token or record). API v1 is intentionally read-only; state changes use validated CSRF-protected staff forms until a token-based API authentication model is designed.
