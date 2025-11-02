#!/usr/bin/env python3
"""
Call Vertex AI Search (Discovery Engine) and ask for a built-in summary
with citations, then render it nicely.

Prereqs:
    pip install google-cloud-discoveryengine

Auth:
    gcloud auth application-default login
"""

from typing import Optional
from google.cloud import discoveryengine_v1beta as discovery
from google.api_core.client_options import ClientOptions

# ---------------------------------------------------------------------
# CONFIG — this is all from your env / messages
# ---------------------------------------------------------------------
PROJECT_ID = "sylvan-faculty-476113-c9"
LOCATION = "global"  # your datastore is in global
DATASTORE = "centef-chunk-data-store_1761831236752_gcs_store"
SERVING_CONFIG = (
    f"projects/{PROJECT_ID}/locations/{LOCATION}/collections/default_collection/"
    f"dataStores/{DATASTORE}/servingConfigs/default_serving_config"
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
    # 3. Show references
    # -----------------------------------------------------------------
    if hasattr(summary, 'summary_with_metadata') and summary.summary_with_metadata:
        metadata = summary.summary_with_metadata
        if hasattr(metadata, 'references') and metadata.references:
            print("\n=== REFERENCES ===")
            for i, ref in enumerate(metadata.references, 1):
                # Extract document ID from the full path
                doc_path = ref.document
                doc_id = doc_path.split('/')[-1] if '/' in doc_path else doc_path
                print(f"[{i}] {doc_id}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        q = " ".join(sys.argv[1:])
    else:
        # default test query — change as you wish
        q = "how AI and social media enable financial fraud in Israel"

    print(f"QUERY: {q}\n")
    search_with_summary(q)
