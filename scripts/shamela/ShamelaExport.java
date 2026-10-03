import java.io.BufferedWriter;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import org.apache.lucene.document.Document;
import org.apache.lucene.index.DirectoryReader;
import org.apache.lucene.index.StoredFields;
import org.apache.lucene.store.FSDirectory;

/**
 * Exports one book's pages from an installed Shamela library (المكتبة الشاملة) as JSON lines:
 * {"page": <page id>, "body": "...", "foot": "..."}, one line per page, in no particular order.
 *
 * The desktop program keeps the books' text in a Lucene index (database/store/page) whose
 * documents are pages, identified as "<book id>-<page id>". Run by scripts/import_shamela.py,
 * with Shamela's own Lucene jars (app/lucene/2) on the class path:
 *
 *   java -cp <jars> ShamelaExport <shamela>/database/store/page <book id> <out.jsonl>
 */
public class ShamelaExport {
    public static void main(String[] args) throws Exception {
        Path index = Path.of(args[0]);
        String prefix = args[1] + "-";
        Path out = Path.of(args[2]);
        int written = 0;
        try (var dir = FSDirectory.open(index);
             var reader = DirectoryReader.open(dir);
             BufferedWriter w = Files.newBufferedWriter(out, StandardCharsets.UTF_8)) {
            StoredFields stored = reader.storedFields();
            for (int i = 0; i < reader.maxDoc(); i++) {
                Document d = stored.document(i);
                String id = d.get("id");
                if (id == null || !id.startsWith(prefix)) {
                    continue;
                }
                w.write("{\"page\":" + Long.parseLong(id.substring(prefix.length()))
                        + ",\"body\":" + json(d.get("body")) + ",\"foot\":" + json(d.get("foot")) + "}\n");
                written++;
            }
        }
        System.out.println(written);
    }

    private static String json(String s) {
        if (s == null) {
            return "\"\"";
        }
        StringBuilder sb = new StringBuilder(s.length() + 16).append('"');
        for (char c : s.toCharArray()) {
            switch (c) {
                case '"' -> sb.append("\\\"");
                case '\\' -> sb.append("\\\\");
                case '\n' -> sb.append("\\n");
                case '\r' -> sb.append("\\r");
                case '\t' -> sb.append("\\t");
                default -> {
                    if (c < 0x20) {
                        sb.append(String.format("\\u%04x", (int) c));
                    } else {
                        sb.append(c);
                    }
                }
            }
        }
        return sb.append('"').toString();
    }
}
