#!/usr/bin/env python3
"""
Call Vertex AI Search (Discovery Engine) and ask for a built-in summary
with citations, then render it nicely.

Prereqs:
    pip install google-cloud-discoveryengine

Auth:
    gcloud auth application-default login
"""

import os
from typing import Optional
from google.cloud import discoveryengine_v1beta as discovery
from google.api_core.client_options import ClientOptions

# ---------------------------------------------------------------------
# CONFIG — loads from environment
# ---------------------------------------------------------------------
PROJECT_ID = os.environ.get("PROJECT_ID", "sylvan-faculty-476113-c9")
PROJECT_NUMBER = os.environ.get("PROJECT_NUMBER", "51695993895")
LOCATION = os.environ.get("VERTEX_SEARCH_LOCATION", "global")

# Use DISCOVERY_SERVING_CONFIG from .env (two-tier Search App)
SERVING_CONFIG = os.environ.get(
    "DISCOVERY_SERVING_CONFIG",
    f"projects/{PROJECT_NUMBER}/locations/{LOCATION}/collections/default_collection/"
    f"engines/centef-two-tier-search-app/servingConfigs/default_config"
)

PAGE_SIZE = 10  # how many search results to fetch
SUMMARY_RESULT_COUNT = 5  # how many results to base the summary on


def make_client(location: str):
    # global discovery uses this endpoint:
    endpoint = f"{location}-discoveryengine.googleapis.com"
    return discovery.SearchServiceClient(
        client_options=ClientOptions(api_endpoint=endpoint)
    )


def search_with_summary(query: str):
    client = make_client(LOCATION)

    # Try with enterprise features first, fall back to basic if needed
    use_enterprise = os.environ.get("USE_ENTERPRISE_FEATURES", "true").lower() == "true"
    
    if use_enterprise:
        request = discovery.SearchRequest(
            serving_config=SERVING_CONFIG,
            query=query,
            page_size=PAGE_SIZE,
            content_search_spec=discovery.SearchRequest.ContentSearchSpec(
                summary_spec=discovery.SearchRequest.ContentSearchSpec.SummarySpec(
                    summary_result_count=SUMMARY_RESULT_COUNT,
                    include_citations=True,
                    ignore_adversarial_query=True,
                    ignore_non_summary_seeking_query=False,
                    use_semantic_chunks=True,
                ),
                extractive_content_spec=discovery.SearchRequest.ContentSearchSpec.ExtractiveContentSpec(
                    max_extractive_segment_count=3,
                ),
            ),
        )
    else:
        # Basic search without enterprise features
        request = discovery.SearchRequest(
            serving_config=SERVING_CONFIG,
            query=query,
            page_size=PAGE_SIZE,
        )

    response = client.search(request=request)

    # -----------------------------------------------------------------
    # 1. print raw results
    # -----------------------------------------------------------------
    print("=== RESULTS ===")
    for r in response.results:
        src = r.document.struct_data.get("source_uri") if r.document.struct_data else None
        print(f"- {r.document.id}  src={src}")

    # -----------------------------------------------------------------
    # 2. summary
    # -----------------------------------------------------------------
    summary = response.summary
    print("\n=== SUMMARY (raw) ===")
    print(summary.summary_text or "[no summary returned]")

    # If no summary, tell user why
    if hasattr(summary, 'summary_skipped_reasons') and summary.summary_skipped_reasons:
        print("\n[summary skipped reasons:]")
        for reason in summary.summary_skipped_reasons:
            print(" -", reason)

    # -----------------------------------------------------------------
    # 3. Show references with anchors (timestamps or page numbers)
    # -----------------------------------------------------------------
    if hasattr(summary, 'summary_with_metadata') and summary.summary_with_metadata:
        metadata = summary.summary_with_metadata
        if hasattr(metadata, 'references') and metadata.references:
            print("\n=== REFERENCES ===")
            
            # We need to fetch the actual documents to get their metadata
            # For now, let's look them up from the search results
            results_by_id = {r.document.id: r.document for r in response.results}
            
            for i, ref in enumerate(metadata.references, 1):
                # Extract document ID from the full path
                doc_path = ref.document
                doc_id = doc_path.split('/')[-1] if '/' in doc_path else doc_path
                
                # Try to get the document from results to access structData
                doc = results_by_id.get(doc_id)
                anchor_info = ""
                
                if doc and doc.struct_data:
                    struct_dict = dict(doc.struct_data)
                    
                    # Check if it's a video/audio chunk (has start_sec)
                    if 'start_sec' in struct_dict:
                        start_sec = struct_dict.get('start_sec', 0)
                        end_sec = struct_dict.get('end_sec', 0)
                        # Format as MM:SS
                        start_min = int(start_sec // 60)
                        start_s = int(start_sec % 60)
                        end_min = int(end_sec // 60)
                        end_s = int(end_sec % 60)
                        anchor_info = f" [{start_min:02d}:{start_s:02d} - {end_min:02d}:{end_s:02d}]"
                    
                    # Check if it's a document page (has page)
                    elif 'page' in struct_dict:
                        page = int(struct_dict.get('page', 0))
                        anchor_info = f" [Page {page}]"
                
                print(f"[{i}] {doc_id}{anchor_info}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        q = " ".join(sys.argv[1:])
    else:
        # default test query — change as you wish
        q = "how AI and social media enable financial fraud in Israel"

    print(f"QUERY: {q}\n")
    search_with_summary(q)
