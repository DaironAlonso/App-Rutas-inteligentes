# Phase 1 Backend - Deployment Guide

## Pre-Deployment Checklist

- [ ] All requirements.txt dependencies installed
- [ ] Environment variables configured (.env file created)
- [ ] Testing completed successfully (test_phase1.py passes)
- [ ] Backward compatibility verified with existing frontend
- [ ] CORS origins configured for your domain
- [ ] Rate limits adjusted for expected traffic
- [ ] Logging output location configured

## Installation

### 1. Install Dependencies
```bash
cd optimizer-service
pip install -r requirements.txt
```

**Expected output:**
- fastapi 0.111.0
- uvicorn 0.29.0
- ortools 9.10.4067
- pydantic >=2.0
- pandas >=2.0.0
- openpyxl >=3.1.0
- httpx >=0.27.0
- slowapi >=0.1.9 (NEW)

### 2. Create Environment Configuration

Create `.env` file in project root or set environment variables:

```bash
# Development Configuration
export CORS_ORIGINS="http://localhost:3000,http://localhost:5173"
export MAX_FILE_SIZE_MB="50"
export RATE_LIMIT_REQUESTS="100"
export OSRM_MAX_RETRIES="3"
export OSRM_RETRY_BACKOFF_BASE="1.0"
export OSRM_FAILURE_CACHE_MINUTES="5"
export LOG_LEVEL="INFO"
```

### 3. Verify Installation

```bash
cd optimizer-service
python -c "from exceptions import InvalidPDVData; from config import config; print('✓ Phase 1 modules loaded successfully')"
```

Expected output:
```
✓ Phase 1 modules loaded successfully
```

## Running the Service

### Development Mode (with auto-reload)
```bash
cd optimizer-service
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

**Expected startup output:**
```
[CONFIG] Initializing CORS with origins: ['http://localhost:3000', 'http://localhost:5173']
INFO:     Uvicorn running on http://0.0.0.0:8000
INFO:     Application startup complete
```

### Production Mode
```bash
cd optimizer-service
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --workers 4
```

### Using Gunicorn (Recommended)
```bash
pip install gunicorn

cd optimizer-service
gunicorn -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000 main:app
```

## Verification Tests

### 1. Health Check
```bash
curl http://localhost:8000/health
```

Expected response:
```json
{"status": "ok"}
```

### 2. CORS Headers
```bash
curl -i -X OPTIONS http://localhost:8000/api/process \
  -H "Origin: http://localhost:3000" \
  -H "Access-Control-Request-Method: POST"
```

Expected headers:
```
Access-Control-Allow-Origin: http://localhost:3000
Access-Control-Allow-Methods: *
```

### 3. Rate Limiting
```bash
# First 100 requests should succeed
for i in {1..100}; do
  curl -X POST http://localhost:8000/api/process \
    -H "Content-Type: application/json" \
    -d '{"fileContent":"","rules":{}}' 2>/dev/null
  echo "Request $i"
done

# 101st request should fail with 429
curl -X POST http://localhost:8000/api/process \
  -H "Content-Type: application/json" \
  -d '{"fileContent":"","rules":{}}'
```

Expected response (on 101st request):
```json
{
  "error": "Rate limit exceeded",
  "detail": "Too many requests. Maximum 100 requests per minute per IP."
}
```

### 4. Validation Errors
```bash
curl -X POST http://localhost:8000/api/estimate-capacity \
  -H "Content-Type: application/json" \
  -d '{
    "data": [{"Latitud": 95, "Longitud": -74}],
    "rules": {},
    "groupBy": "ciudad"
  }'
```

Expected response (400):
```json
{"error": "PDV 0: Latitude must be between -90 and 90, got 95"}
```

## Production Deployment

### 1. AWS EC2 Deployment
```bash
# Install Python 3.10+
sudo yum install python3.10

# Clone repository
git clone <repo-url>
cd App\ Rutas\ inteligentes/optimizer-service

# Create virtual environment
python3.10 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt
pip install gunicorn

# Create .env file with production config
cat > .env << EOF
CORS_ORIGINS="https://app.example.com,https://api.example.com"
MAX_FILE_SIZE_MB="100"
RATE_LIMIT_REQUESTS="1000"
OSRM_MAX_RETRIES="5"
LOG_LEVEL="WARNING"
EOF

# Run with Gunicorn
gunicorn -w 4 -k uvicorn.workers.UvicornWorker \
  -b 0.0.0.0:8000 \
  --access-logfile /var/log/gunicorn_access.log \
  --error-logfile /var/log/gunicorn_error.log \
  main:app
```

### 2. Docker Deployment
```dockerfile
FROM python:3.10-slim

WORKDIR /app

COPY optimizer-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY optimizer-service/ .

ENV CORS_ORIGINS="https://app.example.com"
ENV LOG_LEVEL="INFO"

CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

Build and run:
```bash
docker build -t app-rutas-optimizer .
docker run -d \
  -p 8000:8000 \
  -e CORS_ORIGINS="https://app.example.com" \
  -e RATE_LIMIT_REQUESTS="1000" \
  app-rutas-optimizer
```

### 3. Systemd Service
```ini
# /etc/systemd/system/app-rutas-optimizer.service
[Unit]
Description=App Rutas Inteligentes - Optimizer Service
After=network.target

[Service]
User=ubuntu
WorkingDirectory=/home/ubuntu/app/optimizer-service
Environment="PATH=/home/ubuntu/app/optimizer-service/venv/bin"
EnvironmentFile=/home/ubuntu/app/optimizer-service/.env
ExecStart=/home/ubuntu/app/optimizer-service/venv/bin/gunicorn \
  -w 4 \
  -k uvicorn.workers.UvicornWorker \
  -b 127.0.0.1:8000 \
  main:app

Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable app-rutas-optimizer
sudo systemctl start app-rutas-optimizer
sudo systemctl status app-rutas-optimizer
```

## Nginx Configuration

```nginx
upstream app_optimizer {
    server 127.0.0.1:8000;
}

server {
    listen 443 ssl http2;
    server_name api.example.com;

    ssl_certificate /etc/letsencrypt/live/api.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/api.example.com/privkey.pem;

    # Security headers
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;

    # Rate limiting at Nginx level (additional layer)
    limit_req_zone $binary_remote_addr zone=api_limit:10m rate=100r/m;
    limit_req zone=api_limit burst=200 nodelay;

    location / {
        proxy_pass http://app_optimizer;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 300s;
        proxy_connect_timeout 300s;
    }
}
```

## Monitoring and Logging

### 1. Log File Configuration
```bash
# Create log directory
mkdir -p /var/log/app-rutas

# Monitor logs in real-time
tail -f /var/log/app-rutas/gunicorn_access.log
tail -f /var/log/app-rutas/gunicorn_error.log
```

### 2. Key Metrics to Monitor
- Request latency (API response times)
- Rate limit hits (429 responses)
- OSRM circuit breaker triggers
- Validation errors
- Session completion time

### 3. Example: Monitor Rate Limiting
```bash
# Count rate limit errors per hour
grep "Rate limit exceeded" /var/log/app-rutas/gunicorn_access.log | \
  awk '{print $4}' | cut -d: -f1,2 | sort | uniq -c
```

### 4. Example: Monitor OSRM Failures
```bash
# Find OSRM circuit breaker activations
grep "\[OSRM\] Circuit breaker active" /var/log/app-rutas/*.log | \
  wc -l
```

## Troubleshooting

### Port 8000 Already in Use
```bash
# Find process using port
lsof -i :8000
# Kill process
kill -9 <PID>
```

### CORS Errors in Frontend
```bash
# Verify CORS configuration
curl -i -H "Origin: http://your-frontend.com" \
  http://localhost:8000/health

# Check logs for CORS configuration
grep "\[CONFIG\]" /var/log/app-rutas/*.log
```

### Rate Limiting Too Strict
```bash
# Increase rate limit
export RATE_LIMIT_REQUESTS="500"
# Or adjust in .env file
echo "RATE_LIMIT_REQUESTS=500" >> .env
```

### OSRM Service Unavailable
```bash
# Test OSRM connectivity
curl -v http://router.project-osrm.org/route/v1/foot/13.388860,52.517037;13.397634,52.529407

# If OSRM is down, service will use Haversine fallback
# Check logs for OSRM attempts
grep "\[OSRM\]" /var/log/app-rutas/*.log
```

## Performance Tuning

### 1. Gunicorn Workers
```bash
# For CPU-bound work (default)
workers = (2 * cpu_count) + 1

# For I/O-bound work (like API calls)
workers = (4 * cpu_count) + 1
```

### 2. Connection Pool Limits
In `config.py`:
```python
HTTPX_POOL_LIMITS = {
    "http": (10, 100),
    "https": (10, 100)
}
```

### 3. Cache Optimization
- OSRM cache grows per RouteOptimizer instance
- Consider implementing Redis for shared caching
- Monitor memory usage on long-running instances

## Rollback Plan

If issues occur after deployment:

```bash
# Quick rollback to previous version
cd optimizer-service
git checkout HEAD~1 .
pip install -r requirements.txt
systemctl restart app-rutas-optimizer
```

## Upgrade Path

To upgrade to Phase 2:

```bash
# Pull latest code
git pull origin main

# Update requirements (Phase 2 adds loguru, etc.)
pip install -r requirements.txt

# Run Phase 2 tests
python test_phase2.py

# Restart service
systemctl restart app-rutas-optimizer
```

## Support and Resources

- Documentation: See PHASE1_IMPLEMENTATION.md
- Quick Reference: See optimizer-service/QUICK_REFERENCE.md
- Troubleshooting: See QUICK_REFERENCE.md § Troubleshooting
- Configuration: See .env.example
- Tests: See optimizer-service/test_phase1.py

## Success Criteria

After deployment, verify:

- [x] Health endpoint returns 200 OK
- [x] CORS headers present for allowed origins
- [x] Rate limiting returns 429 after limit exceeded
- [x] Validation errors return proper error messages
- [x] OSRM circuit breaker works (check logs)
- [x] File uploads properly limited to 50MB
- [x] Coordinates validated (-90~90 lat, -180~180 lon)
- [x] Frequency validated (1-6)
- [x] Error messages don't expose stack traces
- [x] All requests logged with [PREFIX] format

All criteria met = Phase 1 successfully deployed! ✓
