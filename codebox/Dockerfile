# The codebase analyst's workspace. mini-swe-agent runs every action as a shell command in this
# container, as user analyst, with the deployed tag's and the previous tag's worktrees mounted
# read-only, a read-only root filesystem, and no network. The fork's .git is mounted at /git and
# GIT_DIR points at the worktree's own metadata (its commondir is relative, so it resolves there;
# mounting .git at its host path doesn't work under Docker Desktop). bin/git switches to
# PREV_GIT_DIR in /prev. The code index of the deployed commit, exported as files
# (python -m app.indexer export v1.4.0 <dir>), is mounted at /index; without it the helper
# commands fall back to ctags and rg.
#
#   docker run -d --read-only --tmpfs /tmp --network none \
#     -v ../shop@v1.4.0:/repo:ro -v ../shop@v1.3.0:/prev:ro -v ../opentelemetry-demo/.git:/git:ro \
#     -v <index dir>:/index:ro -e GIT_WORK_TREE=/repo -e GIT_DIR=/git/worktrees/shop@v1.4.0 \
#     -e PREV_GIT_DIR=/git/worktrees/shop@v1.3.0 sandbox/codebox
FROM debian:bookworm-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
      git ripgrep universal-ctags ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY bin/ /usr/local/bin/
RUN chmod 0755 /usr/local/bin/* && chmod 0644 /usr/local/bin/_index && useradd -m analyst \
    && git config --system --add safe.directory '*'
USER analyst
WORKDIR /repo
CMD ["sleep", "infinity"]
