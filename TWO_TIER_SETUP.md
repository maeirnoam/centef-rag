# Two-Tier Retrieval Setup Guide

This guide walks you through setting up a two-tier retrieval system with Vertex AI Search.

## Overview

**Tier 1 (Summaries)**: Document-level search with rich metadata (author, date, tags, organization)
**Tier 2 (Chunks)**: Granular chunk search with precise anchors (page numbers, timestamps)

## Prerequisites

✅ You already have:
- Summaries generated in `gs://centef-rag-chunks/summaries/*.jsonl` (5 documents)
- Manifest populated with metadata in `manifest.jsonl`
- Existing chunks datastore: `centef-chunk-data-store_1761831236752_gcs_store`

## Step-by-Step Setup

### Step 1: Create Summaries Datastore (Console)

Since the API may require additional permissions, it's easier to create this via the console:

1. **Navigate to Vertex AI Search**
   - Go to: https://console.cloud.google.com/gen-app-builder/engines
   - Project: `sylvan-faculty-476113-c9`

2. **Create New Data Store**
   - Click "**Create Data Store**"
   - Choose: **Cloud Storage**
   - Click "Continue"

3. **Configure Data Source**
   - Select folder with structured data: `gs://centef-rag-chunks/summaries/`
   - Data type: **Structured data (JSONL)**
   - Click "Continue"

4. **Configure Data Store**
   - Data store name: `CENTEF Document Summaries`
   - Data store ID: `centef-summaries-datastore`
   - Region: **global**
   - Click "**Create**"

5. **Wait for Creation**
   - This takes 5-10 minutes
   - You'll see status "Data store created"

### Step 2: Trigger Summaries Import (Script)

Once the datastore is created, import the summaries:

```powershell
python tools/setup_two_tier_search.py --import-summaries
```

OR use the console:
- Go to your new datastore
- Click "**Import**" → "Cloud Storage"
- Path: `gs://centef-rag-chunks/summaries/*.jsonl`
- Click "Import"

**Wait**: Import takes 10-15 minutes for 5 documents.

### Step 3: Create Search App (Console)

Now combine both datastores into a single Search App:

1. **Navigate to Apps**
   - Go to: https://console.cloud.google.com/gen-app-builder/engines
   - Click "**Create App**"

2. **Choose App Type**
   - Select: **Search**
   - Give it a name: `CENTEF Two-Tier Search`
   - Company name: `CENTEF`
   - Click "Continue"

3. **Select Content**
   - Select BOTH data stores:
     - ✅ `centef-chunk-data-store_1761831236752_gcs_store` (chunks)
     - ✅ `centef-summaries-datastore` (summaries)
   - Click "Create"

4. **Enable Advanced Features**
   - Go to your new app's configuration
   - Under "Search features":
     - ✅ Enable "Generative AI" (for summaries)
     - ✅ Enable "Advanced LLM features"
   - Click "Save"

### Step 4: Get the Serving Config Path

1. **In your Search App**, go to "Configurations" → "API"
2. Copy the **Serving Config** path, it should look like:
   ```
   projects/51695993895/locations/global/collections/default_collection/engines/centef-two-tier-search-app/servingConfigs/default_config
   ```

3. **Update your `.env` file**:
   ```
   DISCOVERY_SERVING_CONFIG="projects/51695993895/locations/global/collections/default_collection/engines/centef-two-tier-search-app/servingConfigs/default_config"
   ```

### Step 5: Test the Two-Tier Search

Test with queries that benefit from both tiers:

```powershell
# Document-level discovery (uses summaries tier)
python tools/search_with_summary.py "CENTEF reports about fraud"

# Author/speaker search (uses summaries metadata)
python tools/search_with_summary.py "Matthew Levitt"

# Granular content search (uses chunks tier)
python tools/search_with_summary.py "terrorist financing methods"

# Combined search
python tools/search_with_summary.py "Syria finance discussions in 2025"
```

## Configuration Reference

### Current Setup
- **Project**: sylvan-faculty-476113-c9 (51695993895)
- **Location**: global

### Chunks Datastore (Existing)
- **ID**: `centef-chunk-data-store_1761831236752_gcs_store`
- **Source**: `gs://centef-rag-chunks/data/**/*.jsonl`
- **Content**: 239 chunks (27 PDF, 134 SRT, 76 YouTube, 1 image, 1 video)
- **Schema**: page/timestamp anchors, text content

### Summaries Datastore (New)
- **ID**: `centef-summaries-datastore`
- **Source**: `gs://centef-rag-chunks/summaries/*.jsonl`
- **Content**: 5 document summaries
- **Schema**: title, author, speaker, organization, date, tags, summary text

### Search App (New)
- **ID**: `centef-two-tier-search-app`
- **Combines**: Both chunks and summaries datastores
- **Features**: Multi-datastore search, LLM-powered summaries, citations

## How Two-Tier Retrieval Works

### Query: "CENTEF fraud reports"

**Tier 1 (Summaries)**:
1. Searches summaries by:
   - Title: "Algorithmic Scams..."
   - Tags: ["fraud", "AI", "social media"]
   - Organization: "CENTEF"
2. Returns document-level match with metadata
3. Provides high-level context

**Tier 2 (Chunks)**:
1. Searches chunks within matched documents
2. Returns specific passages with anchors:
   - [Page 5]: "Social media platforms facilitate..."
   - [Page 12]: "AI-powered fraud detection..."
3. Provides precise citations

**Combined Result**:
- Document discovery from summaries
- Precise content from chunks
- Rich context from metadata
- Anchored citations for verification

## Benefits

✅ **Better Discovery**: Find documents by metadata (author, date, tags)
✅ **Precise Navigation**: Jump to exact page/timestamp in source
✅ **Rich Context**: Summaries provide document-level understanding
✅ **Improved Ranking**: Multi-datastore signals improve relevance
✅ **Metadata Filtering**: Search by organization, speaker, date range

## Troubleshooting

### Summaries not appearing in search
- Check import completed successfully in console
- Verify JSONL format in `gs://centef-rag-chunks/summaries/`
- Wait 5-10 minutes after import for indexing

### Search App not finding results
- Verify both datastores are selected in App configuration
- Check serving config path is correct in .env
- Test each datastore individually first

### Citations missing
- Enable "Generative AI" features in App configuration
- Ensure structData includes proper anchor fields (page, start_sec)
- Check content_search_spec includes citations in request

## Next Steps

1. ✅ Create summaries datastore in console
2. ✅ Import summaries (wait for completion)
3. ✅ Create Search App combining both datastores
4. ✅ Update .env with new serving config
5. ✅ Test searches
6. 🔄 Update agent API to use new serving config
7. 🔄 Deploy to Cloud Run with updated config
