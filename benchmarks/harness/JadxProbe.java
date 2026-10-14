import java.io.*;
import java.nio.file.*;
import java.util.*;
import java.util.stream.*;
import javax.swing.*;
import com.google.gson.*;
import jadx.api.*;
import jadx.cli.JadxCLIArgs;
import jadx.gui.settings.*;
import jadx.gui.ui.MainWindow;
import jadx.gui.utils.*;

// Benchmark adapter; does not modify the JADX engine or the MCP plugin.
public class JadxProbe {
    static String target="Liu3/a;->a(JZ)Ljava/lang/String;";
    static String methodId(jadx.core.dex.nodes.MethodNode m) {
        var i=m.getMethodInfo();
        return "L"+i.getDeclClass().getRawName().replace('.','/')+";->"+i.getShortId();
    }
    static Set<String> stringValues(jadx.core.dex.nodes.MethodNode m) {
        Set<String> values=new HashSet<>(); var code=m.getCodeReader();
        if(code!=null)code.visitInstructions(i->{if(i.getOpcode()==jadx.api.plugins.input.insns.Opcode.CONST_STRING){i.decode();values.add(i.getIndexAsString());}});
        return values;
    }
    static List<String> calls(jadx.core.dex.nodes.MethodNode m) {
        List<String> values=new ArrayList<>(); var code=m.getCodeReader();
        if(code!=null)code.visitInstructions(i->{if(i.getIndexType()==jadx.api.plugins.input.insns.InsnIndexType.METHOD_REF){i.decode();var r=i.getIndexAsMethod();r.load();values.add(r.getParentClassType()+"->"+r.getName()+"("+String.join("",r.getArgTypes())+")"+r.getReturnType());}});
        return values;
    }
    static List<String> callers(JadxDecompiler d,Set<String> targets) {
        return d.getClassesWithInners().parallelStream().flatMap(c->c.getClassNode().getMethods().stream()).filter(m->calls(m).stream().anyMatch(targets::contains)).map(JadxProbe::methodId).distinct().sorted().toList();
    }
    static List<String> compound(JadxDecompiler d,String kind) {
        return d.getClassesWithInners().parallelStream().flatMap(c->c.getClassNode().getMethods().stream()).filter(m->{
            if(kind.equals("complex")&&!m.getMethodInfo().getShortId().endsWith("(JZ)Ljava/lang/String;"))return false;
            var strings=stringValues(m);
            if(kind.equals("complex")) {
                if(!strings.containsAll(Set.of("ByteUnitConvertUtils","GB","KB","MB"))||strings.contains("__round13_impossible_bad_marker__")||strings.contains("__round13_excluded__"))return false;
            }else if(!strings.contains("gifFilePath gifPath:"))return false;
            var calls=calls(m);
            if(kind.equals("complex")) {
                if(!calls.contains("Ljava/lang/Math;->round(D)J")||calls.stream().filter(x->x.equals("Ljava/lang/Math;->round(D)J")||x.equals("Ljava/text/DecimalFormat;->format(J)Ljava/lang/String;")).count()<2)return false;
            }else if(!calls.contains("Landroid/graphics/Bitmap;->getWidth()I"))return false;
            if(kind.equals("string_call"))return true;
            boolean[] found={false,false};
            m.getCodeReader().visitInstructions(i->{
                if(i.getIndexType()==jadx.api.plugins.input.insns.InsnIndexType.FIELD_REF){i.decode();var f=i.getIndexAsField();String s=f.getParentClassType()+"->"+f.getName()+":"+f.getType();if(s.equals(kind.equals("complex")?"Ljava/math/RoundingMode;->HALF_UP:Ljava/math/RoundingMode;":"Landroid/graphics/Point;->x:I"))found[0]=true;}
                if(i.getOpcode().name().equals("CONST")||i.getOpcode().name().equals("CONST_WIDE")){i.decode();if(i.getLiteral()==99)found[1]=true;}
            });
            return found[0]&&(kind.equals("complex")||found[1]);
        }).map(JadxProbe::methodId).distinct().sorted().toList();
    }
    static final Gson JSON = new Gson();
    static void emit(Object value) { System.out.println("BENCH_JSON:" + JSON.toJson(value)); System.out.flush(); }
    public static void main(String[] args) throws Exception {
        if (args[0].equals("gui")) {
            var adapter = JadxSettings.buildConfigAdapter();
            var data = JadxCLIArgs.processArgs(new String[]{"-j", args[2], "--rename-flags", "none", "--use-source-name-as-class-name-alias", "never", "--deobf-cfg-file-mode", "ignore", args[1]}, new JadxSettingsData(), adapter);
            var settings = new JadxSettings(adapter);
            settings.loadSettingsData(data);
            settings.setCheckForUpdates(false);
            settings.setAutoStartJobs(false);
            NLS.setLocale(settings.getLangLocale());
            SwingUtilities.invokeLater(() -> {
                LafManager.init(settings);
                settings.getFontSettings().updateDefaultFont();
                MainWindow window = new MainWindow(settings) {
                    @Override public void setVisible(boolean ignored) { super.setVisible(false); }
                };
                window.addLoadListener(loaded -> {
                    if (loaded) emit(Map.of("ready",true,"classes",window.getWrapper().getIncludedClassesWithInners().size()));
                    return loaded;
                });
                window.init();
            });
            return;
        }
        long start = System.nanoTime();
        JadxArgs ja = new JadxArgs();
        ja.setInputFile(new File(args[1]));
        ja.setThreadsCount(Integer.parseInt(args[2]));
        ja.setRenameFlags(EnumSet.noneOf(JadxArgs.RenameEnum.class));
        ja.setUseSourceNameAsClassNameAlias(jadx.api.args.UseSourceNameAsClassNameAlias.NEVER);
        try (JadxDecompiler decompiler = new JadxDecompiler(ja)) {
            decompiler.load();
            emit(Map.of("ready", true, "load_ms", (System.nanoTime()-start)/1e6));
            BufferedReader input = new BufferedReader(new InputStreamReader(System.in));
            for (String line; (line=input.readLine()) != null;) {
                JsonObject request = JSON.fromJson(line, JsonObject.class);
                String kind=request.get("kind").getAsString();
                String needle=request.get("needle").getAsString();
                start=System.nanoTime();
                try {
                    Stream<JavaClass> stream=kind.equals("class") ? Stream.empty() : decompiler.getClassesWithInners().parallelStream();
                    List<String> rows;
                    if (kind.equals("class")) {
                        JavaClass found=decompiler.searchJavaClassByOrigFullName(needle);
                        rows=found==null ? List.of() : List.of(found.getRawName());
                    } else if (kind.equals("method")) {
                        String lower=needle.toLowerCase(Locale.ROOT);
                        rows=stream.filter(c -> c.getClassNode().getMethods().stream().anyMatch(m -> m.getMethodInfo().getName().toLowerCase(Locale.ROOT).contains(lower)))
                            .map(JavaClass::getRawName).distinct().sorted().toList();
                    } else if (kind.equals("string")) {
                        rows=stream.filter(c -> {
                            for (var method : c.getClassNode().getMethods()) {
                                var code=method.getCodeReader();
                                if(code==null) continue;
                                boolean[] found={false};
                                code.visitInstructions(insn -> {
                                    if(insn.getOpcode()==jadx.api.plugins.input.insns.Opcode.CONST_STRING) {
                                        insn.decode();
                                        if(needle.equals(insn.getIndexAsString())) found[0]=true;
                                    }
                                });
                                if(found[0]) return true;
                            }
                            return false;
                        }).map(JavaClass::getRawName).distinct().sorted().toList();
                    } else if(kind.equals("callers")) { rows=callers(decompiler,Set.of(target));
                    } else if(kind.equals("twohop")) { rows=callers(decompiler,new HashSet<>(callers(decompiler,Set.of(target))));
                    } else if(Set.of("string_call","four_fact","complex").contains(kind)) { rows=compound(decompiler,kind);
                    } else { throw new IllegalArgumentException(kind); }
                    emit(Map.of("rows",rows,"execute_ms",(System.nanoTime()-start)/1e6));
                } catch(Throwable e) { emit(Map.of("error",e.toString())); }
            }
        }
    }
}
