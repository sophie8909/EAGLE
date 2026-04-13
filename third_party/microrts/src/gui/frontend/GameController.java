package gui.frontend;

public class GameController {
    public static volatile boolean isPaused = false;

    public static synchronized void pause() {
        isPaused = true;
        System.out.println("🔴 Game Paused");
    }

    public static synchronized void resume() {
        isPaused = false;
        System.out.println("🟢 Game Resumed");
        GameController.class.notifyAll();  // notify threads waiting on this class
    }

    public static synchronized void waitIfPaused() {
        while (isPaused) {
            try {
                GameController.class.wait();
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
            }
        }
    }

    public static boolean isPaused() {
        return isPaused;
    }

    public static void togglePause() {
        if (isPaused) {
            resume();
        } else {
            pause();
        }
    }
}
