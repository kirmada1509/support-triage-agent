"""Retrieval (phase 3): hybrid search over help-center sections and past tickets.

Planned modules: embed.py (EmbeddingClient + local bge-small-en-v1.5), chunk.py (split help
articles at ## headings), index_help.py (re-embed changed sections by content hash), search.py
(top 20 vector + top 20 full-text, reciprocal rank fusion, kind/status/service filters),
memory.py (add tickets at the verdict as open, mark resolved later). Table: retrieval_docs.
"""
