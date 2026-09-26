SELECT flag, old_variant, new_variant, changed_at
FROM flag_changes
WHERE changed_at >= :'since'::timestamptz
ORDER BY changed_at;
