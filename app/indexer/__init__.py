"""Code indexer (phase 5), run by scenarios/deploy.sh once per deployed (service, git_sha).

universal-ctags -> code_symbols; ast-grep patterns -> error_strings and flag_reads; protoc over
the shared gRPC definitions -> rpc_map; git log/diff --stat -> change summary; one Pydantic AI
call (role "indexer") -> service_cards. New rows per version, never edits.
"""
