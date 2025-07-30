# CalDAV Sync Microservice

This microservice synchronizes one or more CalDAV-based calendar sources (such as Daylite, iCloud, or others) with Google Calendar. It supports full round-trip sync, allowing changes to propagate in either direction or both. This makes it suitable for merging multiple calendar sources into a unified Google Calendar, reflecting changes bidirectionally when needed, or acting as an aggregation layer for external tools like LatePoint or Calendly.

The sync process is efficient, fault-tolerant, and resilient to restarts. It uses UID-based deduplication and writes only the necessary changes to Google Calendar to stay within API rate limits.

---

## Features

- 🔁 Periodic polling of CalDAV calendars
- 🔍 Auto-discovery of available calendars per account
- ✅ Stable UID-based deduplication logic
- 🧠 Smart diffing to avoid unnecessary Google API calls
- 🔐 OAuth2 support for Google Calendar with token persistence
- ⚙️ Configuration via minimal, browser-based web UI
- 🐳 Fully dockerized, deployable via Docker Compose
- 🌐 Compatible with reverse proxy setups (e.g. NGINX or Traefik)

---

## Use Cases

This tool is ideal for:

- Keeping a team’s Google Calendar updated with shared iCloud calendars
- Pushing Daylite appointments into Google Calendar for use with external scheduling platforms like LatePoint or Calendly
- Merging multiple calendar sources into a single, read-only Google Calendar for simplified access
- Monitoring calendar state changes across disparate systems

---

## Installation

This service is fully Dockerized and distributed via GitHub Container Registry. The `:latest` image is updated automatically via GitHub Actions on each release.

### Quick Start

1. Create a new folder on your system to hold your config and Docker Compose file.

2. Inside that folder, create a file named `docker-compose.yml` using the example below or one provided in the release assets.

3. Launch the service:

```bash
docker compose up -d
```

That's it. Docker will automatically pull the latest image and launch the service.

Once running, visit the service in your browser at the hostname or IP you've configured via your reverse proxy.

All configuration, calendar mappings, and credentials will be managed through the web UI.

Persistent data, including the SQLite database and OAuth tokens, is stored inside the container at `/data`. To retain configuration between updates or container restarts, mount a volume to this path in your `docker-compose.yml`.

---


---

## Google OAuth Setup

To enable synchronization with Google Calendar, you must provide a Google OAuth Client ID and Secret.

### 1. Create OAuth Credentials

Visit [Google Cloud Console](https://console.cloud.google.com/) and do the following:

- Create a new project (or use an existing one)
- Enable the **Google Calendar API**
- Under "APIs & Services" → "Credentials", click "Create Credentials" → "OAuth client ID"
- Choose **Web application**
- Set the following:
  - **Authorized redirect URI**: `https://your-domain.com/oauth/callback`
    - (Replace with your actual external URL. This must match the BASE_URL you use.)  
    Ensure your reverse proxy passes traffic to /oauth/callback so the OAuth flow can complete.

After creation, copy the **Client ID** and **Client Secret**

### 2. Add to Your Environment

These credentials must be passed to the container either via `.env` file or directly in your `docker-compose.yml`.

#### Example `.env`:

```dotenv
GOOGLE_CLIENT_ID=your-client-id
GOOGLE_CLIENT_SECRET=your-client-secret
BASE_URL=https://calendar-sync.example.com
```

#### Example docker-compose.yml snippet:

```yaml
environment:
  GOOGLE_CLIENT_ID: your-client-id
  GOOGLE_CLIENT_SECRET: your-client-secret
  BASE_URL: https://calendar-sync.example.com
```

Once set, the service will guide you through authenticating with Google the first time you open the web UI.

---

## Configuration

All configuration is managed through a simple web interface.

Advanced users may optionally configure the system via a `config.yaml` file placed in the container’s data volume. When present, these settings will override UI defaults.

You will be prompted to:

1. Add one or more CalDAV accounts (username, password, base URL)
2. Authenticate with Google Calendar via OAuth
3. Select which source calendars to sync
4. Map each source calendar to a target Google Calendar
5. Set a sync interval (default: every 5 minutes)

An example .env file is included as .env.example.

All tokens and mappings are stored securely in SQLite.

---

## User Interface

The web UI is designed to be minimal and self-explanatory. Once the service is running, you can access the interface via your configured base URL.

### Main UI Sections

- **Accounts**: Add and manage CalDAV accounts. Upon entering credentials, the system auto-discovers available calendars from that account.
- **Calendar Mappings**: Map discovered CalDAV calendars to specific Google Calendars. Each mapping includes:
  - Source CalDAV calendar name and ID
  - Destination Google Calendar (selected via dropdown)
  - Sync toggle (on/off)
- **Google Account**: Authenticate with your Google Calendar account using OAuth 2.0. Tokens are securely stored and automatically refreshed.
- **Sync Settings**: Configure how often the sync runs (e.g. every 5 minutes, 15 minutes, hourly).
- **Manual Sync**: Run a sync immediately for all enabled mappings.
- **Status Dashboard**: Displays last sync timestamps, number of events synced, and any recent errors or warnings.

This dashboard also helps verify correct setup immediately after deployment. You can trigger a manual sync and confirm successful event processing here.

Changes made in the UI are saved immediately and applied during the next sync cycle (or when triggered manually).

---

## Sync Logic

This service performs full round-trip synchronization between CalDAV and Google Calendar, including support for recurring events, exception overrides, and deletions.

Each calendar mapping can be configured with one of three sync directions:

- **CalDAV → Google**: CalDAV is the source of truth. Changes flow into Google only.
- **Google → CalDAV**: Google is the source of truth. Changes flow into CalDAV only.
- **Bidirectional**: Changes flow in both directions. The system handles conflict resolution and deduplication.

New mappings default to one-way sync from CalDAV to Google, which can be changed at any time via the UI.

### Recurrence Handling

Recurring events are fully supported in both directions. Recurrence rules (RRULE) and exceptions (RECURRENCE-ID) are parsed, preserved, and mapped to native recurrence structures in both CalDAV and Google Calendar where possible. When needed, exceptions are expanded into discrete instance modifications.

Modifications to specific instances of a recurring event are tracked and synchronized correctly using parent/child logic and event override detection.

Note: Only core event attributes are synchronized — title, description, time, location, and recurrence structure. Attendees, reminders, and attachments are not currently supported.

### Change Detection and Mapping

All synchronized events are tracked using a metadata store that maps:

- Source calendar system (CalDAV or Google)
- Event UID and recurrence instance (if any)
- Destination calendar system event ID
- Last synced timestamp
- Normalized event hash

This mapping allows the system to:

- Detect and apply new or updated events
- Propagate deletions
- Resolve conflicting changes
- Prevent duplication

### Conflict Resolution

In bidirectional mode, when the same event has been changed on both sides since last sync, the system uses the following policy:

- By default, the most recently modified version wins
- All conflicts are logged and surfaced in the dashboard
- Future versions may allow user-defined conflict rules or manual intervention

### Sync Execution

The service performs the following during each scheduled run:

1. Fetches updated events from each CalDAV calendar (using sync windows and etags where supported). The default sync window is 30 days forward from the current time. This range is configurable per mapping.
2. Fetches updated events from each mapped Google Calendar
3. Applies change detection and determines direction of each change
4. Propagates inserts, updates, or deletions
5. Updates the event mapping registry accordingly

This logic ensures high-fidelity synchronization while minimizing redundant API calls.

If outbound webhooks are configured, the service will POST a JSON payload to the provided URL after each sync run. This payload includes metadata about the sync operation (status, timestamp, direction), as well as a summary of the events that were inserted, updated, or deleted.

Sync volume is throttled to avoid exceeding Google’s API limits (e.g., 10,000 writes/day). If limits are approached, sync operations may be deferred and logged with a warning.

### Example Webhook Payload

```json
{
  "mapping_id": "abc123",
  "direction": "CalDAV → Google",
  "status": "success",
  "timestamp": "2025-07-29T21:00:00Z",
  "inserted": 3,
  "updated": 1,
  "deleted": 2,
  "events": [
    {
      "uid": "event123",
      "summary": "Team Meeting",
      "action": "inserted"
    }
  ]
}
```

---

## Error Handling

If an event fails to sync due to a validation or API error, the failure is logged and the remaining events are processed as normal. The sync run will report a `partial_failure` status in outbound webhook payloads if any events fail. Fatal errors (e.g., invalid credentials) will abort the current mapping sync but not affect others.

---

## API

The service exposes the following API endpoints:

| Method | Path                   | Description                          |
|--------|------------------------|--------------------------------------|
| GET    | `/status`              | Health check and last sync timestamps |
| POST   | `/caldav/accounts`     | Add a new CalDAV source              |
| GET    | `/caldav/calendars`    | Discover calendars for a given account |
| POST   | `/mappings`            | Create or update calendar mappings   |
| GET    | `/mappings`            | View current mappings                |
| POST   | `/sync`                | Trigger manual sync                  |


API requests must include the header `Authorization: Bearer YOUR_API_KEY` to authenticate, unless originating from localhost.

The `/sync` endpoint may be called by external systems (e.g. webhooks) to immediately trigger a sync. This enables event-driven integrations with tools like Daylite, Make.com, or custom scheduling platforms.

To restrict access, set an API key in your .env file using API_KEY=yourkey. This key will be required for all non-local requests.

---

## Reverse Proxy Support

To run behind a reverse proxy:

- Set `BASE_URL` in `.env` to the external URL (e.g. `https://calendar-sync.example.com`)
- Proxy traffic using NGINX, Caddy, or Traefik
- Enable HTTPS and optionally restrict access

---

## Development

To run locally without Docker:

```bash
pip install -r requirements.txt
uvicorn main:app --reload
```

Tokens and mappings will be stored in `./caldav_sync.db`.

Logs are written to stdout and can be viewed with `docker logs <container-name>`. They include detailed information about sync runs, errors, and status updates.

---

## Version 1.0 Feature Overview

- ✅ UID-based event deduplication for efficient sync
- ✅ Auto-discovery of calendars from each CalDAV account
- ✅ Secure storage of CalDAV and Google credentials using SQLite
- ✅ Background sync process with configurable polling interval
- ✅ Web UI for adding accounts, selecting calendars, and managing mappings
- ✅ OAuth2 authentication for Google Calendar with token refresh and persistence
- ✅ Event normalization for all-day and time-zoned events
- ✅ Sync logic that inserts, updates, and deletes based on diffing
- ✅ Secure reverse-proxy-compatible deployment
- ✅ Manual sync trigger and health check API
- ✅ Outbound webhook support to notify external systems after sync success or failure

---

## Architecture

This application is built with long-term maintainability and clarity in mind. All functionality is broken into robust, testable modules, including separate layers for CalDAV ingestion, Google Calendar interaction, sync diff logic, UI configuration, and persistent storage.

### Key technologies

- Python 3.11+
- FastAPI for API and web UI
- APScheduler for timed sync jobs
- SQLite for lightweight persistent storage
- Docker for packaging and deployment
- Docker Compose for service orchestration
- Reverse proxy compatibility (NGINX, Caddy, Traefik)

### Deployment

Deployment is fully automated via Docker Compose. The container includes the app, all runtime dependencies, and a startup process that handles:

- Initialization of the SQLite database
- OAuth credential bootstrapping
- Web server launch
- Scheduler task startup

Once deployed, the service can be managed entirely from its web interface.

---

## License

MIT License. Use freely and responsibly.