WITH
string_groups AS (
    SELECT file_id, class_idx, method_idx, method,
           COUNT(DISTINCT value) AS invariant_count
    FROM method_strings
    WHERE value IN ('ByteUnitConvertUtils', 'GB', 'KB', 'MB')
    GROUP BY file_id, class_idx, method_idx, method
    HAVING COUNT(DISTINCT value) = 4
),
signature_pool AS (
    SELECT DISTINCT file_id, class_idx, method_idx, descriptor AS method
    FROM methods
    WHERE access_flags IS NOT NULL
      AND return_descriptor = 'Ljava/lang/String;'
      AND param_count = 2
      AND param_descriptors = 'J,Z'
),
set_candidates AS (
    SELECT file_id, class_idx, method_idx, method FROM string_groups
    INTERSECT
    SELECT file_id, class_idx, method_idx, method FROM signature_pool
    EXCEPT
    SELECT file_id, class_idx, method_idx, method
    FROM method_strings
    WHERE value = '__round13_impossible_bad_marker__'
),
shared AS (
    SELECT c.file_id, c.class_idx, c.method_idx, c.method
    FROM set_candidates c
    WHERE EXISTS (
        SELECT 1
        FROM method_calls mc
        WHERE mc.file_id = c.file_id
          AND mc.class_idx = c.class_idx
          AND mc.method_idx = c.method_idx
          AND mc.callee = 'Ljava/lang/Math;->round(D)J'
    )
),
field_consumer AS (
    SELECT s.file_id, s.class_idx, s.method_idx, s.method
    FROM shared s
    WHERE (s.file_id, s.class_idx, s.method_idx) IN (
        SELECT fa.file_id, fa.class_idx, fa.method_idx
        FROM method_field_accesses fa
        WHERE fa.field = 'Ljava/math/RoundingMode;->HALF_UP:Ljava/math/RoundingMode;'
        GROUP BY fa.file_id, fa.class_idx, fa.method_idx
        HAVING COUNT(*) >= 1
    )
),
call_consumer AS (
    SELECT s.file_id, s.class_idx, s.method_idx, s.method
    FROM shared s
    WHERE (
        SELECT COUNT(*)
        FROM method_calls mc
        WHERE mc.file_id = s.file_id
          AND mc.class_idx = s.class_idx
          AND mc.method_idx = s.method_idx
          AND mc.callee IN (
              'Ljava/lang/Math;->round(D)J',
              'Ljava/text/DecimalFormat;->format(J)Ljava/lang/String;'
          )
    ) >= 2
      AND NOT EXISTS (
          SELECT 1
          FROM method_strings bad
          WHERE bad.file_id = s.file_id
            AND bad.class_idx = s.class_idx
            AND bad.method_idx = s.method_idx
            AND bad.value = '__round13_excluded__'
      )
),
merged AS (
    SELECT file_id, class_idx, method_idx, method FROM field_consumer
    UNION
    SELECT file_id, class_idx, method_idx, method FROM call_consumer
)
SELECT DISTINCT m.method
FROM merged m
WHERE EXISTS (
    SELECT 1 FROM field_consumer f
    WHERE f.file_id = m.file_id
      AND f.class_idx = m.class_idx
      AND f.method_idx = m.method_idx
)
AND EXISTS (
    SELECT 1 FROM call_consumer c
    WHERE c.file_id = m.file_id
      AND c.class_idx = m.class_idx
      AND c.method_idx = m.method_idx
)
ORDER BY m.method
