package ai.eagle;

import ai.core.AI;
import ai.core.ParameterSpecification;
import java.lang.reflect.Constructor;
import java.util.ArrayList;
import java.util.List;
import rts.GameState;
import rts.PlayerAction;
import rts.units.UnitTypeTable;

/**
 * Runtime containment for the pinned upstream AlliBot implementation.
 *
 * <p>This class intentionally has no compile-time dependency on the upstream
 * AlliBot JAR. Its delegate is loaded only at runtime, after the pinned JAR
 * has been independently verified by the Python preflight. A delegate fault
 * permanently changes this wrapper instance to legal no-op actions so one
 * opponent defect cannot terminate the JVM running a candidate match.</p>
 */
public final class SafeAllInBot extends AI {
    public static final String DELEGATE_CLASS =
            "ai.abstraction.submissions.allibot.alli";
    public static final String FALLBACK_MARKER =
            "EAGLE_SAFE_ALLINBOT_FALLBACK";

    private UnitTypeTable utt;
    private AI delegate;
    private boolean fallback;
    private boolean markerWritten;

    public SafeAllInBot(UnitTypeTable utt) {
        this.utt = utt;
        delegate = loadDelegate(utt);
    }

    private AI loadDelegate(UnitTypeTable table) {
        try {
            Class<?> delegateClass = Class.forName(DELEGATE_CLASS);
            Constructor<?> constructor = delegateClass.getConstructor(UnitTypeTable.class);
            Object instance = constructor.newInstance(table);
            if (!(instance instanceof AI)) {
                switchToFallback("delegate_not_ai", null);
                return null;
            }
            return (AI) instance;
        } catch (ReflectiveOperationException error) {
            switchToFallback("delegate_initialization", error);
            return null;
        }
    }

    @Override
    public void reset() {
        if (fallback || delegate == null) {
            return;
        }
        try {
            delegate.reset();
        } catch (RuntimeException error) {
            switchToFallback("delegate_reset", error);
        }
    }

    @Override
    public void reset(UnitTypeTable table) {
        utt = table;
        if (fallback || delegate == null) {
            return;
        }
        try {
            delegate.reset(table);
        } catch (RuntimeException error) {
            switchToFallback("delegate_reset", error);
        }
    }

    @Override
    public PlayerAction getAction(int player, GameState gs) {
        if (fallback || delegate == null) {
            return passiveAction(player, gs);
        }
        try {
            PlayerAction action = delegate.getAction(player, gs);
            if (!isValid(action)) {
                switchToFallback("invalid_player_action", null);
                return passiveAction(player, gs);
            }
            return action;
        } catch (Exception error) {
            switchToFallback("delegate_get_action", error);
            return passiveAction(player, gs);
        }
    }

    @Override
    public AI clone() {
        return new SafeAllInBot(utt);
    }

    @Override
    public List<ParameterSpecification> getParameters() {
        if (!fallback && delegate != null) {
            try {
                return delegate.getParameters();
            } catch (RuntimeException error) {
                switchToFallback("delegate_parameters", error);
            }
        }
        return new ArrayList<>();
    }

    @Override
    public void preGameAnalysis(GameState gs, long milliseconds) {
        if (fallback || delegate == null) {
            return;
        }
        try {
            delegate.preGameAnalysis(gs, milliseconds);
        } catch (Exception error) {
            switchToFallback("delegate_pre_game", error);
        }
    }

    @Override
    public void gameOver(int winner) {
        if (fallback || delegate == null) {
            return;
        }
        try {
            delegate.gameOver(winner);
        } catch (Exception error) {
            switchToFallback("delegate_game_over", error);
        }
    }

    private static boolean isValid(PlayerAction action) {
        try {
            return action != null
                    && action.getResourceUsage() != null
                    && action.getActions() != null
                    && action.integrityCheck();
        } catch (RuntimeException error) {
            return false;
        }
    }

    private PlayerAction passiveAction(int player, GameState gs) {
        PlayerAction action = new PlayerAction();
        action.fillWithNones(gs, player, 10);
        return action;
    }

    private void switchToFallback(String reason, Exception error) {
        fallback = true;
        delegate = null;
        if (!markerWritten) {
            markerWritten = true;
            String detail = error == null ? "" : " error=" + error.getClass().getSimpleName();
            System.err.println(FALLBACK_MARKER + " reason=" + reason + detail);
        }
    }
}
