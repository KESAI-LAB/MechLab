import com.comsol.model.*;
import com.comsol.model.util.*;

/**
 * Remote time-series extractor (comsolbatch).
 *
 * All inputs are baked into this source by remote_extract.sh, so the class does
 * no direct file IO (COMSOL's file-system security preference blocks java.io
 * access).  Results are printed to stdout as lines:
 *
 *     TSV <t_d> <label>_min <label>_max <label>_mean ...
 *
 * Each expression carries its own domain group, so one solve can serve every
 * probe (defects, IPyC, SiC, ...).  comsolbatch keeps stdout in its batch log,
 * which is downloaded and parsed locally into a small CSV.
 */
public class ExtractGen {
    public static void main(String[] args) throws Exception {
        String modelPath = "__MODEL__";
        int[][] domGroups = new int[][] { __DOMAINS__ };
        int[] geomDims = new int[] { __DIMS__ };
        String[] labels = new String[] { __LABELS__ };
        String[] exprs = new String[] { __EXPRS__ };

        Model model = ModelUtil.load("M", modelPath);
        ModelUtil.showProgress(false);
        var num = model.result().numerical();
        int n = exprs.length;
        double[][][] data = new double[n][][];
        for (int i = 0; i < n; i++) {
            String tag = "ev" + i;
            num.create(tag, "Eval");
            var ev = num.get(tag);
            ev.selection().geom(geomDims[i]).set(domGroups[i]);
            ev.set("expr", exprs[i]);
            data[i] = ev.getData()[0];
        }
        num.create("evt", "Eval");
        var te = num.get("evt");
        te.selection().geom(geomDims[0]).set(domGroups[0]);
        te.set("expr", "t");
        te.set("unit", "d");
        double[][] times = te.getData()[0];

        for (int k = 0; k < times.length; k++) {
            StringBuilder sb = new StringBuilder("TSV ");
            sb.append(times[k][0]);
            for (int i = 0; i < n; i++) {
                double[] vals = data[i][k];
                double mn = Double.POSITIVE_INFINITY, mx = Double.NEGATIVE_INFINITY, sm = 0.0;
                for (double v : vals) { if (v < mn) mn = v; if (v > mx) mx = v; sm += v; }
                sb.append(" ").append(mn).append(" ").append(mx).append(" ").append(sm / vals.length);
            }
            System.out.println(sb.toString());
        }
        System.out.println("EXTRACT_DONE times=" + times.length);
        ModelUtil.disconnect();
    }
}
