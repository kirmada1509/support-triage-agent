SELECT service, previous_version, version, git_sha, deployed_at,
       array_to_string(commit_titles, '; ') AS commits
FROM deploys
WHERE deployed_at >= :'since'::timestamptz
  AND (:'service' = '' OR service = :'service')
ORDER BY deployed_at;
