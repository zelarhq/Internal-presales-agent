# API Standardisation (Frontend Contract)

This backend generates/refines report sections asynchronously.
The frontend starts a job and receives a `job_id`, then **polls the status endpoint** to check completion.

> **Important:** Job state storage:
> - **Development:** In-memory only. If the backend restarts, all job state is lost.
> - **Production:** Redis-backed (if `REDIS_URL` is configured). Jobs persist across restarts.

---

## Base URL
Provided per environment (dev/staging/prod).

---

## Common Response Envelope

All responses follow:

```json
{
  "status": "ok|processing|ready|busy|error",
  "message": "human readable message",
  "data": {}
}
```

### Status meanings
- `processing`: queued or in progress
- `busy`: currently executing (same as processing but explicitly “running”)
- `ready`: completed successfully
- `error`: failed

---

## Required Headers

Every request must include:

1) `X-API-Key`  
   Auth token for the API.

2) `Session-Id`  
   A frontend-generated session identifier.  
   - Must be included even on the *first* request.
   - Same value should be reused for all section calls in the same report workflow.

**Note:** `Request-Id` header is **no longer required**. The backend automatically generates a unique `job_id` (UUID) for each job.

Example:

```
X-API-Key: <key>
Session-Id: session_123
```

---

## Error Format

Errors are returned as:
- HTTP 4xx/5xx
- `status="error"`
- `data.error_code` included

Example:

```json
{
  "status": "error",
  "message": "Session-Id is required",
  "data": {
    "error_code": "BAD_REQUEST",
    "path": "/generate"
  }
}
```

Validation errors (HTTP 422) include `data.details` (Pydantic error list).

---

## Report Sections (Allowed Values)

`section_title` MUST be one of the allowed section titles for the given report `type`.
Backend validates this even if the frontend enforces it.

### Feasibility_report
Allowed `section_title` values (canonical):

- `Executive Summary`
- `Project Overview`
- `Business Requirements`
- `Technical Assessment`
- `Resource Assessment`
- `Cost-Benefit Analysis`
- `Risk Assessment`
- `Alternative Solutions`
- `Timeline Feasibility`
- `Stakeholder Analysis`
- `Recommendations`
- `Appendix`

### Technical_scope
Allowed `section_title` values (canonical):

- `Executive Summary`
- `Company Background`
- `Current State Analysis`
- `Requirements Overview`
- `Proposed Solution`
- `Technology Stack`
- `Integration Points`
- `Security & Compliance`
- `Implementation Timeline`
- `Resource Requirements`
- `Risks & Mitigations`
- `Assumptions & Dependencies`

### Commercial_proposal
Allowed `section_title` values:
- (TBD)

---

## Endpoints

### 1) POST `/generate`

Starts generation of a report section. Returns immediately with a `job_id` for polling.

**Headers**
- `X-API-Key` (required)
- `Session-Id` (required)

**Body**
```json
{
  "type": "Feasibility_report|Technical_scope|Commercial_proposal",
  "customer_id": "string",
  "opportunity_id": "string",
  "section_title": "string (must be allowed for type)"
}
```

**Response**
HTTP 202 Accepted

```json
{
  "status": "processing",
  "message": "Job queued",
  "data": {
    "job_id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "pending"
  }
}
```

**Polling:** Use `GET /status/{job_id}` to check job status (see Status Endpoint below).

**Busy**
```json
{
  "status": "busy",
  "message": "Request is busy",
  "data": { "ready": false, "request_id": "req_001" }
}
```

**Processing**
```json
{
  "status": "processing",
  "message": "Generating...",
  "data": { "ready": false, "request_id": "req_001" }
}
```

**Ready**
```json
{
  "status": "ready",
  "message": "Draft ready",
  "data": {
    "ready": true,
    "request_id": "string",
    "customer_id": "string",
    "opportunity_id": "string",
    "section_title": "string",
    "generated_section_b64": "string"
  }
  }

```

**Error**
```json
{
  "status": "error",
  "message": "Error message",
  "data": {
    "ready": false,
    "request_id": "req_001",
    "error_code": "INTERNAL_ERROR"
  }
}
```

---

### 2) POST `/refine`

Starts refinement of an existing section. Returns immediately with a `job_id` for polling.

**Headers**
- `X-API-Key` (required)
- `Session-Id` (required)

**Body**
```json
{
  "type": "Feasibility_report|Technical_scope|Commercial_proposal",
  "customer_id": "string",
  "opportunity_id": "string",
  "section_title": "string (must be allowed for type)",
  "original_text": "string (base64-encoded markdown/text)",
  "prompt": "string"
}
```

**Response**
HTTP 202 Accepted

```json
{
  "status": "processing",
  "message": "Job queued",
  "data": {
    "job_id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "pending"
  }
}
```

**Polling:** Use `GET /status/{job_id}` to check job status (see Status Endpoint below).

### 3) GET `/status/{job_id}`

Get the status of a background job. Use this endpoint to poll for job completion.

**Headers**
- `X-API-Key` (required)

**Path Parameters**
- `job_id` (required) - The job ID returned from `/generate` or `/refine`

**Response - Pending/Processing**
HTTP 200 OK

```json
{
  "status": "processing",
  "message": "Job processing",
  "data": {
    "job_id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "processing"
  }
}
```

**Response - Completed**
HTTP 200 OK

```json
{
  "status": "ready",
  "message": "Job completed",
  "data": {
    "job_id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "completed",
    "result": {
      "customer_id": "string",
      "opportunity_id": "string",
      "section_title": "string",
      "generated_section_b64": "string"
    }
  }
}
```

For `/refine` jobs, the result contains `refined_section_b64` instead of `generated_section_b64`.

**Response - Failed**
HTTP 200 OK

```json
{
  "status": "error",
  "message": "Job failed",
  "data": {
    "job_id": "550e8400-e29b-41d4-a716-446655440000",
    "status": "failed",
    "error": {
      "error_code": "INTERNAL_ERROR",
      "message": "Error details"
    }
  }
}
```

**Response - Not Found**
HTTP 404 Not Found

```json
{
  "status": "error",
  "message": "Job 550e8400-e29b-41d4-a716-446655440000 not found",
  "data": {
    "error_code": "JOB_NOT_FOUND",
    "path": "/status/550e8400-e29b-41d4-a716-446655440000"
  }
}
```

---

## Polling Guidance (Frontend)

### Polling Flow

1. **Start a job:** Call `POST /generate` or `POST /refine`
2. **Extract `job_id`:** From the response `data.job_id`
3. **Poll status:** Call `GET /status/{job_id}` repeatedly until status is `completed` or `failed`

### Polling Strategy

- **Initial delay:** Wait 1 second before first poll
- **Backoff strategy:** 
  - Start at 1s intervals
  - Increase to 2s, 3s, 5s as time progresses
  - Cap at 10s maximum interval
- **Timeout:** 
  - 3–10 minutes depending on model / workload
  - If timeout reached, treat job as failed
- **Error handling:**
  - If `GET /status/{job_id}` returns 404, the job was lost (backend restart or expiration)
  - Treat as expired and re-submit using a new request

### Example Polling Code (Pseudocode)

```javascript
async function pollJobStatus(jobId, maxWaitTime = 600000) {
  const startTime = Date.now();
  let delay = 1000; // Start with 1 second
  
  while (Date.now() - startTime < maxWaitTime) {
    await sleep(delay);
    
    const response = await fetch(`/status/${jobId}`, {
      headers: { "X-API-Key": apiKey }
    });
    
    const data = await response.json();
    
    if (data.status === "ready") {
      return data.data.result; // Job completed
    }
    
    if (data.status === "error" && data.data.status === "failed") {
      throw new Error(data.data.error.message);
    }
    
    if (response.status === 404) {
      throw new Error("Job not found - may have expired");
    }
    
    // Exponential backoff, capped at 10s
    delay = Math.min(delay * 1.5, 10000);
  }
  
  throw new Error("Job polling timeout");
}
```

---

## Notes / Gotchas

1) **Job persistence:**
   - **Development:** In-memory only. Backend restart wipes all job state.
   - **Production:** If `REDIS_URL` is configured, jobs persist across restarts (24-hour TTL).

2) **Job IDs:** Backend generates UUIDs automatically. No need to provide `Request-Id` header.

3) **Session-Id required always:** Must be included in every request to `/generate` and `/refine`.

4) **Report type values:** Use exactly:
   - `Feasibility_report`
   - `Technical_scope`
   - `Commercial_proposal`

5) **Job expiration:** Jobs expire after 24 hours (Redis) or on server restart (in-memory).

6) **Status endpoint:** Always use `GET /status/{job_id}` for polling. Do not resend POST requests.
