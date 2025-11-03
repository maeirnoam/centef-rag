# Two-Tier Retrieval Setup - Quick Start

## Current Status

✅ **Completed**:
- 5 documents ingested and chunked (239 total chunks)
- Summaries generated with Gemini for all 5 documents
- Manifest populated with complete metadata
- Existing chunks datastore working

🔄 **Next**: Create summaries datastore and Search App

## Quick Setup (3 Steps)

### Option A: Via Console (Recommended - 15 minutes)

#### 1. Create Summaries Datastore
```
Console: https://console.cloud.google.com/gen-app-builder/engines
→ Create Data Store
→ Cloud Storage: gs://centef-rag-chunks/summaries/
→ Name: CENTEF Document Summaries
→ ID: centef-summaries-datastore
→ Region: global
→ Create
```

#### 2. Create Search App
```
Console: https://console.cloud.google.com/gen-app-builder/engines
→ Create App → Search
→ Name: CENTEF Two-Tier Search
→ Select BOTH datastores:
   ✅ centef-chunk-data-store_1761831236752_gcs_store
   ✅ centef-summaries-datastore
→ Create
→ Enable "Generative AI" features
```

#### 3. Update Configuration
```powershell
# Copy the serving config from your new Search App
# It should look like:
# projects/51695993895/locations/global/collections/default_collection/engines/centef-two-tier-search-app/servingConfigs/default_config

# Update .env file
notepad .env
# Add/update this line:
DISCOVERY_SERVING_CONFIG="projects/51695993895/locations/global/collections/default_collection/engines/centef-two-tier-search-app/servingConfigs/default_config"
```

### Option B: Via Script (if you have permissions)

```powershell
# Run all steps automatically
python tools/setup_two_tier_search.py --all

# Or step by step:
python tools/setup_two_tier_search.py --create-summaries-datastore
python tools/setup_two_tier_search.py --import-summaries
python tools/setup_two_tier_search.py --create-search-app
```

## Testing

Once setup is complete, test the two-tier search:

```powershell
# Test 1: Document discovery by metadata
python tools/search_with_summary.py "CENTEF reports about fraud"

# Test 2: Author/speaker search
python tools/search_with_summary.py "Matthew Levitt terrorism"

# Test 3: Content search with granular chunks
python tools/search_with_summary.py "terrorist financing methods"

# Test 4: Date/organization filtering
python tools/search_with_summary.py "Syria discussions 2025"
```

## What You'll Get

### Before (Single-Tier - Chunks Only)
- Search returns individual chunks
- Limited document-level context
- No metadata-based discovery
- Hard to find "all documents by X author"

### After (Two-Tier - Summaries + Chunks)
- **Summaries tier**: Document discovery by title, author, speaker, organization, date, tags
- **Chunks tier**: Precise content with page numbers and timestamps
- **Combined**: Find documents first, then drill down to specific passages
- **Better ranking**: Multi-datastore signals improve relevance

## Example Query Results

### Query: "What did Matthew Levitt say about Iran?"

**Tier 1 (Summaries) Returns**:
```
Document: youtube_iran_resistance
Title: "Matthew Levitt speaks on Iran's Axis of Resistance under Pressure"
Speaker: Matthew Levitt
Organization: CIDItv
Date: 2025-05-27
Tags: ["Iran", "resistance", "terrorism", "Middle East"]
Summary: On May 27, 2025, Matthew Levitt delivered a comprehensive presentation...
```

**Tier 2 (Chunks) Returns**:
```
Chunk [12:30 - 14:45]: "Iran's proxy network has been significantly weakened..."
Chunk [28:15 - 30:20]: "Hezbollah's financial infrastructure faces..."
Chunk [42:10 - 43:55]: "The resistance axis coordination mechanisms..."
```

**Combined Result**:
- Found the right document via speaker metadata
- Got document-level context from summary
- Retrieved specific passages with precise timestamps
- Can click timestamps to watch exact video moments

## Architecture Diagram

```
User Query: "CENTEF fraud reports from 2024"
         |
         v
┌─────────────────────────────────────────┐
│     Vertex AI Search App                │
│   (centef-two-tier-search-app)          │
└─────────────────────────────────────────┘
         |
         ├────────────────────┬────────────────────┐
         v                    v                    v
┌─────────────────┐  ┌─────────────────┐  ┌────────────────┐
│  Summaries DS   │  │   Chunks DS     │  │  LLM Summary   │
│  (5 documents)  │  │  (239 chunks)   │  │   Generator    │
└─────────────────┘  └─────────────────┘  └────────────────┘
         |                    |                    |
         v                    v                    v
   Document-level        Granular chunks      AI-generated
   with metadata         with anchors         summary with
   (author, date,        (page, timestamp)    citations
    tags, etc.)
```

## Resource Names Reference

Copy these for your configuration:

```bash
# Project
PROJECT_ID=sylvan-faculty-476113-c9
PROJECT_NUMBER=51695993895
LOCATION=global

# Chunks Datastore (existing)
CHUNKS_DATASTORE_ID=centef-chunk-data-store_1761831236752_gcs_store
CHUNKS_DATASTORE_PATH=projects/51695993895/locations/global/collections/default_collection/dataStores/centef-chunk-data-store_1761831236752_gcs_store

# Summaries Datastore (new)
SUMMARIES_DATASTORE_ID=centef-summaries-datastore
SUMMARIES_DATASTORE_PATH=projects/51695993895/locations/global/collections/default_collection/dataStores/centef-summaries-datastore
SUMMARIES_SOURCE=gs://centef-rag-chunks/summaries/*.jsonl

# Search App (new)
SEARCH_APP_ID=centef-two-tier-search-app
SEARCH_APP_PATH=projects/51695993895/locations/global/collections/default_collection/engines/centef-two-tier-search-app
SERVING_CONFIG=projects/51695993895/locations/global/collections/default_collection/engines/centef-two-tier-search-app/servingConfigs/default_config
```

## Checklist

- [ ] Navigate to Vertex AI Search console
- [ ] Create summaries datastore pointing to `gs://centef-rag-chunks/summaries/`
- [ ] Wait for datastore creation (5-10 min)
- [ ] Trigger import (or wait for automatic import)
- [ ] Wait for import completion (10-15 min)
- [ ] Create Search App combining both datastores
- [ ] Enable "Generative AI" features
- [ ] Copy serving config path
- [ ] Update `.env` file with new serving config
- [ ] Test searches with `search_with_summary.py`
- [ ] Verify results show both summaries and chunks
- [ ] Update agent API configuration
- [ ] Deploy to Cloud Run with new config

## Files Reference

- `TWO_TIER_SETUP.md` - Detailed setup guide with console screenshots
- `tools/setup_two_tier_search.py` - Automation script (if you have API permissions)
- `tools/search_with_summary.py` - Test search script
- `manifest.jsonl` - Document registry with metadata
- `.env` - Environment configuration (update DISCOVERY_SERVING_CONFIG here)

## Support

If you encounter issues:
1. Check TWO_TIER_SETUP.md for detailed troubleshooting
2. Verify both datastores show "Active" status in console
3. Ensure imports completed successfully
4. Test each datastore individually before combining
5. Check serving config path is copied exactly

## Next After Setup

Once two-tier search is working:
1. Update agent API to use new serving config
2. Test advanced queries combining metadata + content
3. Experiment with date/tag filtering
4. Add more documents to see improved discovery
5. Deploy updated agent to Cloud Run
