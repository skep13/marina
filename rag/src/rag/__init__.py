"""Local RAG for the Marina / Songbird assistants.

Retrieve vetted cybersecurity reference material at query time instead of
fine-tuning. No model weights live here; the vector store and the ingestion
pipeline are self-contained so the whole thing can run on lab3 (where the
models are served) or on a Mac for development.
"""

__version__ = "0.1.0"
