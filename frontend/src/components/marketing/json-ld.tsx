/**
 * Structured data for search engines (schema.org JSON-LD).
 *
 * `<` is escaped so a string containing `</script>` cannot close the tag early.
 * Everything passed in is our own copy, but the escape costs nothing.
 */
export function JsonLd({ data }: { data: Record<string, unknown> }) {
  return (
    <script
      type="application/ld+json"
      dangerouslySetInnerHTML={{ __html: JSON.stringify(data).replace(/</g, "\\u003c") }}
    />
  );
}
