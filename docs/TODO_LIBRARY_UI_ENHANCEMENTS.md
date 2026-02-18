# Library Detail Page UI Enhancements — COMPLETED

All items below have been implemented.

## What Was Done

### 1. Modern Drag-and-Drop Interface
- Full-page drag-and-drop zone on the library detail page with animated overlay
- Empty state replaced with inviting dropzone (gradient icon, click-to-browse)
- Files dropped on the page feed into the existing UploadModal flow
- **Folder support**: Dropping a folder recursively extracts all supported files using the `webkitGetAsEntry()` / FileSystemEntry API (with `readEntries` batch pattern)
- UploadModal's internal dropzone also supports folder drops via `extractFilesFromDataTransfer()`

### 2. Cascade Asset Deletion
- **Backend**: Added `POST /upload-libraries/{id}/assets/delete` bulk delete endpoint
  - For each asset: deletes search index chunks, artifact files from MinIO, extraction result files from MinIO, then deletes asset record (ORM cascades handle child DB rows)
  - Recomputes library stats after deletion
  - Added `DeleteAssetsRequest` schema to `schemas.py`
- **Backend**: Fixed existing `DELETE /assets/{asset_id}` to also clean up search chunks and extraction result files from MinIO
- **Frontend**: Per-row delete button (visible on hover via `group-hover:opacity-100`) with `ConfirmDeleteDialog`
- **Frontend**: Bulk "Delete Selected" button alongside existing "Move to..." action

### 3. Asset Detail Link
- Each asset filename is a clickable link to the full asset detail page (`/orgs/[orgSlug]/assets/[assetId]`)

### 4. Smart Status Polling
- Library detail page polls every 10 seconds while any asset has a non-terminal status (pending, processing)
- Polling automatically stops when all assets reach terminal status (ready, failed, inactive, deleted)
- No polling when all assets are already processed (zero overhead for idle libraries)
- Cleanup on unmount prevents leaked intervals

## Files Modified

| File | Change |
|------|--------|
| `curatore-backend/backend/app/api/v1/data/schemas.py` | Added `DeleteAssetsRequest` |
| `curatore-backend/backend/app/api/v1/data/routers/upload_libraries.py` | Added `POST /{id}/assets/delete` |
| `curatore-backend/backend/app/api/v1/data/routers/assets.py` | Fixed cascade in `DELETE /{asset_id}` |
| `curatore-frontend/lib/api.ts` | Added `deleteAssets` method to `uploadLibrariesApi` |
| `curatore-frontend/components/UploadModal.tsx` | Added `initialFiles` prop, folder drop support |
| `curatore-frontend/app/orgs/[orgSlug]/libraries/[libraryId]/page.tsx` | Drag-and-drop, delete UI, asset links, smart polling |
