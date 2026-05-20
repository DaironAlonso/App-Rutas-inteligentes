# Phase 1 Implementation - Quick Reference Guide

## Quick Start

### Installation
```bash
cd optimizer-service
pip install -r requirements.txt
```

### Configuration
Create a `.env` file or set environment variables:
```bash
export CORS_ORIGINS="http://localhost:3000,http://localhost:5173"
export MAX_FILE_SIZE_MB="50"
export RATE_LIMIT_REQUESTS="100"
export OSRM_MAX_RETRIES="3"
export OSRM_RETRY_BACKOFF_BASE="1.0"
export OSRM_FAILURE_CACHE_MINUTES="5"
export LOG_LEVEL="INFO"
```

### Running
```bash
cd optimizer-service
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

## Architecture Overview

```
Frontend (Vue)
      ↓
   [CORS Check]
      ↓
  FastAPI + Slowapi
      ↓
   [Rate Limit: 100/min per IP]
      ↓
  Pydantic Validators
      ├─ File size (50MB max)
      ├─ Excel format
      ├─ Required fields
      └─ Data types
      ↓
  Exception Handlers
      ├─ Return proper HTTP status
      ├─ No stack traces
      └─ Clear error messages
      ↓
  RouteOptimizer
      ├─ Data validation (coordinates, frequency)
      ├─ OR-Tools optimization
      └─ OSRM with Circuit Breaker
           ├─ Exponential backoff (1s, 2s, 4s)
           ├─ 5-minute failure cache
           └─ Haversine fallback
```

## Key Features

### 1. Input Validation
- **File Size**: Max 50MB (configurable)
- **File Format**: Must be valid Excel
- **Coordinates**: -90 to 90 (lat), -180 to 180 (lon)
- **Frequency**: 1 to 6
- **Required Fields**: Latitud/latitud, Longitud/longitud

### 2. Exception Handling
| Exception | Status | Meaning |
|-----------|--------|---------|
| InvalidPDVData | 400 | Invalid data in PDV records |
| InvalidCoordinates | 400 | Lat/lon out of range |
| FileSizeExceeded | 413 | File > 50MB |
| RouteOptimizationError | 500 | Optimization failed |
| RateLimitExceeded | 429 | Too many requests |

### 3. OSRM Circuit Breaker
```
Request → Check cache → Return cached
       ↓
       Check failures cache (5 min) → If cached, return None
       ↓
       Attempt 1 (immediate)
       ↓ (if fails)
       Wait 1s → Attempt 2
       ↓ (if fails)
       Wait 2s → Attempt 3
       ↓ (if fails)
       Wait 4s → Attempt 4 (optional)
       ↓ (all fail)
       Cache failure for 5 min → Return None (Haversine fallback)
```

### 4. Rate Limiting
- **Limit**: 100 requests per minute per IP
- **Key**: Client IP address
- **Response**: 429 status with error message
- **Protected Endpoints**:
  - POST `/api/process`
  - POST `/api/estimate-capacity`

### 5. CORS Security
- **Default**: localhost only (secure by default)
- **Production**: Set `CORS_ORIGINS` environment variable
- **Format**: Comma-separated URLs
- **Example**: `"https://app.example.com,https://api.example.com"`

### 6. Logging
All operations logged with prefixes:
```
[CONFIG]   - Startup configuration
[API]      - API requests with client IP
[PROCESS]  - /api/process operations
[CAPACITY] - /api/estimate-capacity operations
[OSRM]     - Route service calls
[OPTIMIZER] - Optimization engine
```

## API Responses

### Successful Response (Processing)
```json
{
  "sessionId": "550e8400-e29b-41d4-a716-446655440000",
  "status": "queued"
}
```

### Successful Response (Results)
```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": "2024-01-15T10:30:45.123456Z",
  "status": "completed",
  "rutas": [...],
  "omitidos": [...],
  "summary": {...}
}
```

### Error Response (Validation)
```json
{
  "error": "PDV 0: Latitude must be between -90 and 90, got 95"
}
```

### Error Response (Rate Limited)
```json
{
  "error": "Rate limit exceeded",
  "detail": "Too many requests. Maximum 100 requests per minute per IP."
}
```

## Testing

### Unit Tests
```bash
cd optimizer-service
python test_phase1.py
```

### Manual Testing with curl
```bash
# Test health endpoint
curl http://localhost:8000/health

# Test rate limiting (will get 429 after 100 requests/minute)
for i in {1..101}; do
  curl -X POST http://localhost:8000/api/process \
    -H "Content-Type: application/json" \
    -d '{"fileContent":"base64data...","rules":{}}'
done

# Test validation (invalid frequency)
curl -X POST http://localhost:8000/api/estimate-capacity \
  -H "Content-Type: application/json" \
  -d '{
    "data": [{"Latitud": 4.6, "Longitud": -74, "Frecuencia": 10}],
    "rules": {},
    "groupBy": "ciudad"
  }'
```

## Configuration Examples

### Development (Default)
```bash
CORS_ORIGINS="http://localhost:3000,http://localhost:5173"
MAX_FILE_SIZE_MB="50"
RATE_LIMIT_REQUESTS="100"
OSRM_MAX_RETRIES="3"
```

### Production (Secure)
```bash
CORS_ORIGINS="https://app.example.com,https://admin.example.com"
MAX_FILE_SIZE_MB="100"
RATE_LIMIT_REQUESTS="1000"
OSRM_MAX_RETRIES="5"
LOG_LEVEL="WARNING"
```

### Testing (Relaxed)
```bash
CORS_ORIGINS="*"
MAX_FILE_SIZE_MB="500"
RATE_LIMIT_REQUESTS="10000"
OSRM_MAX_RETRIES="1"
OSRM_FAILURE_CACHE_MINUTES="1"
```

## Troubleshooting

### "File size exceeds 50MB limit"
- Check file size: `ls -lh file.xlsx`
- Increase `MAX_FILE_SIZE_MB` environment variable
- Remove unnecessary rows/columns

### "Rate limit exceeded"
- Normal operation when > 100 requests/minute per IP
- Increase `RATE_LIMIT_REQUESTS` if needed
- Implement request queuing on client side

### "Invalid Excel file format"
- Verify file is .xlsx (not .xls, .csv, .json, etc.)
- Check Excel file isn't corrupted: `file file.xlsx`
- Try opening in Excel or LibreOffice to verify

### "Latitude must be between -90 and 90"
- Check coordinate values in Excel
- Verify Latitud/latitud column name
- Coordinates should be in decimal format (not DMS)

### "OSRM circuit breaker active"
- OSRM service may be down or unreachable
- Check network connectivity: `ping router.project-osrm.org`
- Wait 5 minutes for cache to expire
- Fallback to Haversine distance (less accurate)

## File Structure
```
optimizer-service/
├── main.py                 # FastAPI app, models, endpoints
├── optimizer_engine.py     # Route optimization logic
├── exceptions.py           # Custom exceptions
├── config.py              # Configuration management
├── test_phase1.py         # Test suite
├── requirements.txt       # Python dependencies
└── venv/                  # Virtual environment
```

## Key Differences from Phase 0

| Aspect | Phase 0 | Phase 1 |
|--------|---------|---------|
| Validation | Basic type checking | Comprehensive with validators |
| Errors | Stack traces exposed | Clean error messages |
| CORS | Allow all origins | Localhost only by default |
| Rate Limiting | None | 100 req/min per IP |
| OSRM Failures | Hangs/errors | Exponential backoff + cache |
| Logging | Minimal | Structured with prefixes |
| Configuration | Hardcoded | Environment variables |
| File Size | Unlimited | 50MB limit |
| Coordinates | No validation | -90~90 lat, -180~180 lon |
| Frequency | No validation | 1-6 only |

## Performance Notes

### Caching
- OSRM responses cached in-memory (per RouteOptimizer instance)
- Failed requests cached for 5 minutes (prevents retry storms)
- Session results cached in-memory (until server restart)

### Optimization
- Exponential backoff reduces load on OSRM (1s, 2s, 4s delays)
- Rate limiting prevents resource exhaustion
- File size limit prevents DOS attacks

### Scalability
- Single-server architecture (in-memory storage)
- Consider Redis for multi-server deployment
- Consider database for persistence

## Future Improvements (Phase 2+)

- [ ] Loguru for structured logging
- [ ] Database persistence (PostgreSQL)
- [ ] Task queue (Celery + Redis)
- [ ] Metrics/monitoring (Prometheus)
- [ ] API documentation (OpenAPI)
- [ ] Batch file processing
- [ ] Webhook notifications
- [ ] Advanced rate limiting strategies
- [ ] Request signing
- [ ] Multi-tenancy support
