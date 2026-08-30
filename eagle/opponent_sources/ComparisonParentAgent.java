package ai.eagle;

import ai.core.AI;
import ai.core.ParameterSpecification;
import java.io.File;
import java.lang.reflect.Constructor;
import java.net.URL;
import java.net.URLClassLoader;
import java.util.List;
import rts.GameState;
import rts.PlayerAction;
import rts.units.UnitTypeTable;

/**
 * Loads a comparison parent's already-compiled CandidateAgent in an isolated
 * class loader, while sharing the MicroRTS API classes with the match process.
 */
public final class ComparisonParentAgent extends AI {
    private static final String PARENT_CLASSES_PROPERTY = "eagle.comparison.parent.classes";

    private final UnitTypeTable utt;
    private final AI delegate;

    public ComparisonParentAgent(UnitTypeTable utt) {
        this.utt = utt;
        this.delegate = loadDelegate(utt);
    }

    private static AI loadDelegate(UnitTypeTable utt) {
        String path = System.getProperty(PARENT_CLASSES_PROPERTY);
        if (path == null || path.trim().isEmpty()) {
            throw new IllegalStateException("Missing -D" + PARENT_CLASSES_PROPERTY);
        }
        try {
            URL classes = new File(path).toURI().toURL();
            ClassLoader shared = ComparisonParentAgent.class.getClassLoader();
            URLClassLoader loader = new CandidateClassLoader(new URL[] {classes}, shared);
            Class<?> candidateClass = Class.forName("ai.generated.CandidateAgent", true, loader);
            Constructor<?> constructor = candidateClass.getConstructor(UnitTypeTable.class);
            Object instance = constructor.newInstance(utt);
            if (!(instance instanceof AI)) {
                throw new IllegalStateException("Comparison parent is not a MicroRTS AI");
            }
            return (AI) instance;
        } catch (ReflectiveOperationException | java.net.MalformedURLException error) {
            throw new IllegalStateException("Cannot load comparison parent CandidateAgent", error);
        }
    }

    @Override
    public void reset() {
        delegate.reset();
    }

    @Override
    public void reset(UnitTypeTable utt) {
        delegate.reset(utt);
    }

    @Override
    public PlayerAction getAction(int player, GameState gs) throws Exception {
        return delegate.getAction(player, gs);
    }

    @Override
    public AI clone() {
        return new ComparisonParentAgent(utt);
    }

    @Override
    public List<ParameterSpecification> getParameters() {
        return delegate.getParameters();
    }

    @Override
    public String statisticsString() {
        return delegate.statisticsString();
    }

    @Override
    public void preGameAnalysis(GameState gs, long milliseconds) throws Exception {
        delegate.preGameAnalysis(gs, milliseconds);
    }

    @Override
    public void preGameAnalysis(GameState gs, long milliseconds, String folder) throws Exception {
        delegate.preGameAnalysis(gs, milliseconds, folder);
    }

    @Override
    public void gameOver(int winner) throws Exception {
        delegate.gameOver(winner);
    }

    private static final class CandidateClassLoader extends URLClassLoader {
        CandidateClassLoader(URL[] urls, ClassLoader parent) {
            super(urls, parent);
        }

        @Override
        protected synchronized Class<?> loadClass(String name, boolean resolve)
                throws ClassNotFoundException {
            if (name.startsWith("ai.generated.")) {
                Class<?> loaded = findLoadedClass(name);
                if (loaded == null) {
                    try {
                        loaded = findClass(name);
                    } catch (ClassNotFoundException ignored) {
                        // Fall through to the shared MicroRTS/application loader.
                    }
                }
                if (loaded != null) {
                    if (resolve) {
                        resolveClass(loaded);
                    }
                    return loaded;
                }
            }
            return super.loadClass(name, resolve);
        }
    }
}
