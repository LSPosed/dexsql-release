SELECT DISTINCT m.descriptor
FROM methods AS m
WHERE EXISTS (
        SELECT 1 FROM method_strings AS s
        WHERE s.file_id = m.file_id AND s.method_idx = m.method_idx
          AND s.value = 'gifFilePath gifPath:'
      )
  AND EXISTS (
        SELECT 1 FROM method_calls AS c
        WHERE c.file_id = m.file_id AND c.method_idx = m.method_idx
          AND c.callee_class = 'Landroid/graphics/Bitmap;'
          AND c.callee_name = 'getWidth'
          AND c.callee = 'Landroid/graphics/Bitmap;->getWidth()I'
      )
ORDER BY m.descriptor;
