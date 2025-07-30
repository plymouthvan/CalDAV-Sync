# CalDAV Sync Microservice - Deployment Guide

## Quick Start

The CalDAV Sync Microservice is fully containerized and ready for deployment. Follow these steps to get it running:

### Prerequisites

- Docker and Docker Compose installed
- Google OAuth credentials (for Google Calendar integration)
- CalDAV server credentials (Daylite, iCloud, etc.)

### 1. Clone and Configure

```bash
git clone <repository-url>
cd CalDAV-Sync-Microservice
cp .env.example .env
```

### 2. Configure Environment Variables

Edit the `.env` file with your settings:

```bash
# Required: Google OAuth Credentials
GOOGLE_CLIENT_ID=your-google-client-id
GOOGLE_CLIENT_SECRET=your-google-client-secret

# Required: Security Keys (CHANGE THESE!)
SECRET_KEY=your-secret-key-change-this-in-production
ENCRYPTION_KEY=your-32-character-encryption-key-here
API_KEY=your-api-key-for-external-access

# Optional: Customize other settings
BASE_URL=https://your-domain.com
DEFAULT_SYNC_INTERVAL_MINUTES=5
```

### 3. Deploy with Docker Compose

```bash
docker compose up -d
```

### 4. Access the Web Interface

Open your browser and navigate to:
- Local: `http://localhost:8000`
- Production: `https://your-domain.com`

### 5. Configure Sync

1. **Add CalDAV Account**: Enter your CalDAV server details
2. **Authenticate Google**: Complete OAuth flow for Google Calendar
3. **Create Mappings**: Map CalDAV calendars to Google calendars
4. **Start Sync**: Enable automatic synchronization

## Production Deployment

### Reverse Proxy Setup

For production, use a reverse proxy like NGINX or Traefik:

#### NGINX Example

```nginx
server {
    listen 443 ssl;
    server_name calendar-sync.example.com;
    
    ssl_certificate /path/to/cert.pem;
    ssl_certificate_key /path/to/key.pem;
    
    location / {
        proxy_pass http://localhost:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

#### Traefik Labels

The docker-compose.yml includes Traefik labels:

```yaml
labels:
  - "traefik.enable=true"
  - "traefik.http.routers.caldav-sync.rule=Host(`calendar-sync.example.com`)"
  - "traefik.http.routers.caldav-sync.tls=true"
```

### Security Considerations

1. **Change Default Keys**: Update all security keys in production
2. **Use HTTPS**: Always deploy behind HTTPS in production
3. **Restrict Access**: Consider IP whitelisting or VPN access
4. **Regular Backups**: Backup the SQLite database regularly

### Monitoring

The service provides several monitoring endpoints:

- **Health Check**: `GET /status`
- **Metrics**: Available through the web dashboard
- **Logs**: Docker logs via `docker compose logs -f`

### Backup and Recovery

#### Backup Database

```bash
docker compose exec caldav-sync cp /app/data/caldav_sync.db /app/data/backup.db
docker cp caldav-sync-microservice:/app/data/backup.db ./backup.db
```

#### Restore Database

```bash
docker cp ./backup.db caldav-sync-microservice:/app/data/caldav_sync.db
docker compose restart caldav-sync
```

## Troubleshooting

### Common Issues

1. **Google OAuth Not Working**
   - Verify client ID and secret are correct
   - Check redirect URI in Google Console: `https://your-domain.com/oauth/callback`

2. **CalDAV Connection Failed**
   - Verify server URL, username, and password
   - Check if server supports CalDAV discovery

3. **Sync Not Running**
   - Check logs: `docker compose logs caldav-sync`
   - Verify mappings are enabled
   - Check sync interval settings

### Logs and Debugging

```bash
# View all logs
docker compose logs caldav-sync

# Follow logs in real-time
docker compose logs -f caldav-sync

# View specific component logs
docker compose logs caldav-sync | grep "sync_engine"
```

### Performance Tuning

For high-volume deployments:

1. **Adjust Sync Intervals**: Increase interval for less frequent syncing
2. **Limit Concurrent Mappings**: Set `MAX_CONCURRENT_MAPPINGS`
3. **Database Optimization**: Consider PostgreSQL for large deployments
4. **Rate Limiting**: Adjust Google API rate limits

## API Usage

The service exposes a REST API for automation:

```bash
# Check status
curl -H "X-API-Key: your-api-key" http://localhost:8000/status

# Trigger manual sync
curl -X POST -H "X-API-Key: your-api-key" http://localhost:8000/sync

# List mappings
curl -H "X-API-Key: your-api-key" http://localhost:8000/mappings
```

## Support

For issues and questions:

1. Check the engineering journal: `engineering-journal.md`
2. Review application logs
3. Verify configuration settings
4. Test individual components (CalDAV connection, Google OAuth)

The CalDAV Sync Microservice is designed to be robust and self-healing. Most issues can be resolved by checking configuration and credentials.
