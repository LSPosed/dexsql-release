import java.io.*;
import java.util.*;
import java.util.stream.*;
import com.google.gson.*;
import jadx.api.*;

/** Resident JADX 1.5.6 adapter for the goal-oriented APK audit replay. */
public class JadxAuditProbe {
    static final Gson JSON = new Gson();

    static Set<String> stringValues(jadx.core.dex.nodes.MethodNode method) {
        Set<String> values = new HashSet<>();
        var code = method.getCodeReader();
        if (code != null) code.visitInstructions(insn -> {
            if (insn.getOpcode() == jadx.api.plugins.input.insns.Opcode.CONST_STRING) {
                insn.decode();
                values.add(insn.getIndexAsString());
            }
        });
        return values;
    }

    static void emit(Object value) {
        System.out.println("AUDIT_JSON:" + JSON.toJson(value));
        System.out.flush();
    }

    public static void main(String[] args) throws Exception {
        long start = System.nanoTime();
        JadxArgs ja = new JadxArgs();
        ja.setInputFile(new File(args[0]));
        ja.setThreadsCount(Integer.parseInt(args[1]));
        ja.setRenameFlags(EnumSet.noneOf(JadxArgs.RenameEnum.class));
        ja.setUseSourceNameAsClassNameAlias(jadx.api.args.UseSourceNameAsClassNameAlias.NEVER);
        try (JadxDecompiler d = new JadxDecompiler(ja)) {
            d.load();
            emit(Map.of("ready", true, "load_ms", (System.nanoTime() - start) / 1e6,
                    "classes", d.getClassesWithInners().size()));
            BufferedReader in = new BufferedReader(new InputStreamReader(System.in));
            for (String line; (line = in.readLine()) != null;) {
                JsonObject request = JSON.fromJson(line, JsonObject.class);
                String kind = request.get("kind").getAsString();
                String needle = request.has("needle") ? request.get("needle").getAsString() : "";
                start = System.nanoTime();
                try {
                    Object result;
                    if (kind.equals("string")) {
                        result = d.getClassesWithInners().parallelStream()
                                .filter(c -> c.getClassNode().getMethods().stream()
                                        .anyMatch(m -> stringValues(m).stream().anyMatch(v -> v.contains(needle))))
                                .map(JavaClass::getRawName).distinct().sorted().toList();
                    } else if (kind.equals("method")) {
                        String lower = needle.toLowerCase(Locale.ROOT);
                        result = d.getClassesWithInners().parallelStream()
                                .filter(c -> c.getClassNode().getMethods().stream()
                                        .anyMatch(m -> m.getMethodInfo().getName().toLowerCase(Locale.ROOT).contains(lower)))
                                .map(JavaClass::getRawName).distinct().sorted().toList();
                    } else if (kind.equals("class")) {
                        JavaClass c = d.searchJavaClassByOrigFullName(needle);
                        result = c == null ? "" : c.getCode();
                    } else if (kind.equals("manifest")) {
                        result = d.getResources().stream()
                                .filter(r -> r.getOriginalName().equals("AndroidManifest.xml"))
                                .findFirst().map(r -> r.loadContent().getText().getCodeStr()).orElse("");
                    } else {
                        throw new IllegalArgumentException("unknown kind: " + kind);
                    }
                    emit(Map.of("result", result, "execute_ms", (System.nanoTime() - start) / 1e6));
                } catch (Throwable e) {
                    emit(Map.of("error", e.toString(), "execute_ms", (System.nanoTime() - start) / 1e6));
                }
            }
        }
    }
}
