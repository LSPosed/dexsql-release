SELECT DISTINCT m.descriptor, m.class_descriptor
FROM methods AS m
WHERE EXISTS (
        SELECT 1 FROM method_strings AS s
        WHERE s.file_id = m.file_id AND s.method_idx = m.method_idx
          AND s.value = 'gifFilePath gifPath:'
      )
  AND EXISTS (
        SELECT 1 FROM method_calls AS c
        WHERE c.file_id = m.file_id AND c.method_idx = m.method_idx
          AND c.callee = 'Landroid/graphics/Bitmap;->getWidth()I'
      )
  AND EXISTS (
        SELECT 1 FROM method_field_accesses AS f
        WHERE f.file_id = m.file_id AND f.method_idx = m.method_idx
          AND f.field_class = 'Landroid/graphics/Point;'
          AND f.field_name = 'x'
          AND f.field_type = 'I'
      )
  AND EXISTS (
        SELECT 1 FROM method_using_numbers AS n
        WHERE n.file_id = m.file_id AND n.method_idx = m.method_idx
          AND n.long_value = 99
      )
ORDER BY m.descriptor;
