# Enhancement 6: Change Detection & Diffs

## Overview

Enhancement 6 implements comprehensive policy change tracking and comparison functionality for the terms-analysis system. It provides:

1. **Policy Snapshots** - Historical versions of monitored policies stored with SHA-256 content hashing for deduplication
2. **Policy Watches** - Configurable monitoring of URLs with custom check frequencies  
3. **Token-Level Diffs** - Detailed token-by-token comparison with semantic severity classification
4. **Change Detection** - Automatic change tracking with historical versions and diffing

## Implementation Details

### Database Models

#### `PolicySnapshot`
Stores historical versions of policies with efficient deduplication:
- `id` (String, PK): Unique identifier
- `url` (String, indexed): Policy URL
- `content_hash` (String, indexed): SHA-256 hash of content for deduplication
- `captured_at` (DateTime, indexed): When the snapshot was taken
- `raw_text` (Text): Full policy content

Only new content (different hash) creates new snapshots, avoiding storage bloat.

#### `PolicyWatch`  
Configuration for watching specific policies:
- `id` (String, PK): Unique identifier
- `url` (String, unique, indexed): Policy URL to watch
- `user_id` (String, nullable): User who created the watch
- `check_frequency` (Integer): Seconds between checks (300-604800, default 86400)
- `last_check` (DateTime, nullable): Last time checked
- `enabled` (String): Watch enabled/disabled flag
- `created_at` (DateTime): When watch was created

### API Endpoints

#### Snapshots

**GET /snapshots?url={url}**
```
Get all historical snapshots for a policy URL
Query Parameters:
  - url (required): The policy URL

Response: List[PolicySnapshotListItem]
  - id: Snapshot ID
  - url: Policy URL
  - content_hash: SHA-256 hash
  - captured_at: Capture timestamp
```

**GET /snapshots/detail/{snapshot_id}**
```
Get full details of a specific snapshot including raw content
Path Parameters:
  - snapshot_id: Snapshot ID

Response: PolicySnapshotPayload (includes raw_text)
```

**POST /snapshots?url={url}**
```
Capture a new snapshot of a policy
Query Parameters:
  - url (required): Policy URL to snapshot

Response: PolicySnapshotPayload
- Returns existing snapshot if same content already captured
- Automatically fetches and hashes URL content
- Deduplicates by content_hash
```

#### Diffs

**GET /diff/{snapshot_id_1}/{snapshot_id_2}**
```
Compare two policy snapshots at token level
Path Parameters:
  - snapshot_id_1: First snapshot ID
  - snapshot_id_2: Second snapshot ID

Response: DiffResult
  - snapshot_1_id, snapshot_2_id: IDs being compared
  - url: Policy URL
  - created_at_1, created_at_2: Capture times
  - added: List[DiffToken] - New tokens
  - removed: List[DiffToken] - Removed tokens
  - unchanged: List[DiffToken] - Unchanged tokens
  - change_count: Total number of tokens that changed
  - severity_summary: {"high": N, "medium": N, "low": N}

DiffToken object:
  - token: The token string
  - type: "added" | "removed" | "unchanged"
  - line_number: Line where token appears
  - severity: "low" | "medium" | "high" (based on keyword analysis)
```

#### Policy Watches

**POST /policy-watch**
```
Create a new policy watch configuration
Request: PolicyWatchCreateRequest
  - url (required): Policy URL
  - user_id (optional): User ID
  - check_frequency (optional): Seconds between checks (default 86400)

Response: PolicyWatchPayload
- Fails with 409 if URL already being watched
```

**GET /policy-watch**
```
List all active policy watches
Response: List[PolicyWatchPayload]
```

**DELETE /policy-watch/{watch_id}**
```
Remove a policy watch
Path Parameters:
  - watch_id: Watch ID to delete

Response: {"status": "deleted", "id": watch_id}
```

**POST /policy-watch/{watch_id}/snapshot**
```
Manually capture a snapshot for a watched policy
Path Parameters:
  - watch_id: Watch ID

Response: PolicySnapshotPayload
- Updates watch's last_check timestamp
- Automatically deduplicates content
```

### Diff Algorithm

The diff algorithm provides token-level comparison:

1. **Tokenization**: Splits text into words and punctuation tokens
2. **Line Tracking**: Records line number for each token
3. **Severity Classification**: Assigns severity based on keywords:
   - **High**: critical keywords (personal, data, liability, consent, etc.)
   - **Medium**: change keywords (use, store, share, delete, etc.)
   - **Low**: other tokens
4. **Comparison**: Uses Python's `difflib.SequenceMatcher` for efficient token comparison
5. **Output**: Returns added, removed, and unchanged tokens with line numbers and severity

### Content Hashing

- Uses SHA-256 for deterministic content deduplication
- Prevents storing duplicate versions of unchanged policies
- Enables efficient change detection

## Usage Examples

### Creating a Policy Watch

```bash
curl -X POST http://localhost:9000/policy-watch \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com/privacy-policy",
    "user_id": "user123",
    "check_frequency": 86400
  }'
```

### Capturing a Snapshot

```bash
curl -X POST "http://localhost:9000/snapshots?url=https://example.com/privacy-policy"
```

### Comparing Two Versions

```bash
# Get snapshots for a URL
curl http://localhost:9000/snapshots?url=https://example.com/privacy-policy

# Compare two snapshots
curl http://localhost:9000/diff/snapshot-id-1/snapshot-id-2
```

### Using Automatic Snapshots

```bash
# Create watch
watch_resp=$(curl -X POST http://localhost:9000/policy-watch \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com/tos"}')

watch_id=$(echo $watch_resp | jq -r '.id')

# Capture snapshot
curl -X POST "http://localhost:9000/policy-watch/$watch_id/snapshot"
```

## Test Coverage

Comprehensive test suite with 32 tests covering:

- **Content Hashing**: Consistency, differentiation, edge cases
- **Tokenization**: Simple text, multiline, punctuation, empty input
- **Diff Tokens**: Identical texts, additions, removals, replacements, severity classification, large texts
- **Database Models**: Creation, deduplication, constraints
- **API Endpoints**: All CRUD operations, error cases, edge cases
- **Integration**: Full workflow from watch creation to diff comparison

All tests pass with 100% success rate.

## Performance Considerations

1. **Deduplication**: Only stores unique content (by hash), reducing storage requirements
2. **Indexing**: Database indexes on url, content_hash, and captured_at for fast queries
3. **Token-Level Diffs**: Uses Python's efficient difflib for comparison
4. **Severity Classification**: Simple keyword lookup O(1) operation
5. **Background Jobs**: Existing async watchlist refresh mechanism in place

## Security Considerations

1. **URL Handling**: Query parameters used for URLs to avoid path injection
2. **Access Control**: No user-level restrictions (can be added with auth middleware)
3. **Data Retention**: No automatic deletion (can be configured per deployment)
4. **Content Hashing**: SHA-256 suitable for change detection (not security-critical)

## Future Enhancements

1. **Scheduled Scanning**: APScheduler integration for automatic periodic snapshots
2. **Change Notifications**: Email/Slack alerts on detected policy changes
3. **Version Comparison**: Multi-version diff views
4. **Change History**: Timeline visualization of policy evolution
5. **Semantic Diffing**: ML-based semantic change detection
6. **Data Retention Policies**: Automatic cleanup of old snapshots
7. **Batch Comparisons**: Compare multiple policies simultaneously

## Files Modified/Created

- `app/models.py` - Added PolicySnapshot and PolicyWatch models
- `app/schemas.py` - Added Pydantic schemas for new endpoints
- `app/services/diffing.py` - Enhanced with token-level diff algorithm
- `app/main.py` - Added 8 new API endpoints (3 snapshot + 1 diff + 4 policy-watch)
- `tests/test_snapshots_and_diffs.py` - New comprehensive test suite (32 tests)

## Dependencies

No new external dependencies required. Uses:
- SQLAlchemy (existing)
- FastAPI (existing)
- Python standard library (hashlib, difflib, re)
