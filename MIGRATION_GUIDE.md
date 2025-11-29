# Migration Guide - Fix Duplicate Deep Research Requests

## Problem

When using the Deep Research feature on the web interface, you may encounter:

1. **Duplicate research requests**: The same query triggers two separate deep research sessions
2. **Database error**: `relation "hyper_research_events" does not exist`

## Root Cause

1. **Missing database table**: The `hyper_research_events` table was not created because migration `002_add_deep_research_events.sql` was not run
2. **Frontend race condition**: Multiple simultaneous submissions could bypass the loading state check

## Solution

### Step 1: Apply Database Migration

The `hyper_research_events` table is required for real-time progress tracking during deep research.

**Run the following command:**

```bash
psql -U postgres -d neos --port 5432 --host localhost -f db/migrations/002_add_deep_research_events.sql
```

**Expected output:**
```
CREATE TABLE
CREATE INDEX
CREATE INDEX
CREATE INDEX
COMMENT
COMMENT
COMMENT
COMMENT
COMMENT
```

### Step 2: Verify Table Creation

```bash
psql -U postgres -d neos --port 5432 --host localhost
```

Then run:
```sql
\dt hyper_research_events
```

You should see:
```
                   List of relations
 Schema |          Name           | Type  |  Owner
--------+-------------------------+-------+----------
 public | hyper_research_events   | table | postgres
```

### Step 3: Update Your Code

The frontend code has been updated to prevent duplicate submissions:

1. **InputBox component** (`web/components/chat/InputBox.tsx`):
   - Added `isSubmittingRef` to block concurrent submissions
   - 500ms cooldown after each submission

2. **Chat store** (`web/lib/stores/chat-store.ts`):
   - Immediate `isLoading` state update at the start of `sendDeepResearchMessage`
   - Proper `isStreaming` state management throughout the deep research flow

### Step 4: Restart the Application

After applying the migration, restart your NEOS backend:

```bash
# Stop the current server (Ctrl+C)

# Restart
python3 -m neos.main
```

## Testing

1. Open the web interface
2. Select "Deep Research" mode
3. Submit a query (e.g., "요즈음 개발자를 위한 AI 설계 대세에 대해서 조사해줘")
4. Verify:
   - Only ONE "Initiating deep research..." message appears
   - No database errors in the server logs
   - Real-time progress updates display correctly

## Technical Details

### Database Schema

The `hyper_research_events` table structure:

```sql
CREATE TABLE hyper_research_events (
    event_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_id VARCHAR(255) NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    event_category VARCHAR(30) NOT NULL,
    sequence_number INTEGER NOT NULL,
    event_data JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (report_id) REFERENCES hyper_research_reports(report_id) ON DELETE CASCADE
);
```

### Frontend Fixes

**Before:**
```typescript
const handleSubmit = async () => {
  if (!input.trim() || isLoading || isStreaming) return;
  // ... validation ...
  await sendMessage(message); // Could be called twice
};
```

**After:**
```typescript
const handleSubmit = async () => {
  if (!input.trim() || isLoading || isStreaming) return;

  // Guard against concurrent calls
  if (isSubmittingRef.current) {
    logger.debug("Submission already in progress, ignoring duplicate call");
    return;
  }

  // ... validation ...

  isSubmittingRef.current = true;
  try {
    await sendMessage(message);
  } finally {
    setTimeout(() => {
      isSubmittingRef.current = false;
    }, 500);
  }
};
```

**Store State Management:**
```typescript
sendDeepResearchMessage: async (content: string) => {
  get().cleanupEventSource();

  // Set loading immediately to prevent duplicates
  set({ isLoading: true });

  // ... create conversation ...

  // Set streaming when research begins
  set({ isStreaming: true, isLoading: false });

  // ... SSE event handling ...

  // Reset streaming on completion/failure
  set({ isStreaming: false });
}
```

## Rollback (if needed)

If you need to remove the events table:

```sql
DROP TABLE IF EXISTS hyper_research_events CASCADE;
```

## Support

If you continue to experience issues:

1. Check server logs for errors
2. Verify the database connection settings in `.env`
3. Ensure PostgreSQL is running
4. Check browser console for frontend errors

## References

- Migration file: `db/migrations/002_add_deep_research_events.sql`
- Frontend fix commit: "fix: Prevent duplicate deep research requests"
- Database schema: `db/hyper_deep_research.sql`
