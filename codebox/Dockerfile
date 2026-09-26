# The codebase analyst's workspace (phase 5). mini-swe-agent runs every action as a shell command
# in this container. Run it with the deployed tag's and the previous tag's worktrees mounted
# read-only, a read-only root filesystem, and no network except an internal network to the
# agent's Postgres (for the code index):
#
#   docker run -d --read-only --tmpfs /tmp --network codebox-internal \
#     -v ../shop@v1.4.0:/repo:ro -v ../shop@v1.3.0:/prev:ro \
#     -e INDEX_URL=postgresql://index_ro:...@db:5432/triage -e GIT_SHA=<sha> sandbox/codebox
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
      git ripgrep universal-ctags postgresql-client ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY bin/ /usr/local/bin/
RUN chmod +x /usr/local/bin/* && useradd -m analyst \
    && git config --system --add safe.directory '*'
USER analyst
WORKDIR /repo
CMD ["sleep", "infinity"]
