package gui;

import java.io.File;
import javax.swing.JFrame;
import org.jdom.input.SAXBuilder;
import rts.Trace;

/**
 * Small command-line entrypoint for opening saved MicroRTS XML/ZIP traces.
 */
public class TraceViewerMain {
    public static void main(String[] args) throws Exception {
        if (args.length < 1) {
            System.err.println("Usage: java gui.TraceViewerMain <trace.xml|trace.zip>");
            System.exit(1);
        }

        String tracePath = args[0];
        Trace trace = tracePath.endsWith(".zip")
                ? Trace.fromZip(tracePath)
                : new Trace(new SAXBuilder().build(new File(tracePath)).getRootElement());
        JFrame window = TraceVisualizer.newWindow("MicroRTS Trace - " + tracePath, 900, 700, trace, -1);
        window.setVisible(true);
    }
}
