package rts;

/***
 * The main class for running a MicroRTS game. To modify existing settings change the file "config.properties".
 */
public class MicroRTS {

    public static void main(String args[]) throws Exception {

        for (int i = args.length; i > 0; i--) {
            if (args[i - 1].equals("-h")) {
                System.out.println(GameSettings.getHelpMessage());
                return;
            }
        }
        
        String configFile = "resources/config.properties";

        for (int i = args.length; i > 0; i--) {
            if (args[i - 1].equals("-f")) {
                configFile = args[i];
            }
        }

        GameSettings gameSettings;
        try {
            gameSettings = GameSettings.loadFromConfig(GameSettings.fetchConfig(configFile))
                .overrideFromArgs(args);
        } catch (java.io.FileNotFoundException ex) {
            System.err.println(
                "File " + configFile + " not found. Trying to initialize from command-line args.");
            gameSettings = new GameSettings(args);
        }

        System.out.println(gameSettings);

        switch (gameSettings.getLaunchMode()) {
            case STANDALONE:
            case HUMAN:
                runStandAloneGame(gameSettings);
                break;
            case GUI:
            case SERVER:
            case CLIENT:
                throw new UnsupportedOperationException(
                    "Only STANDALONE and HUMAN launch modes are kept in this EAGLE checkout.");
        }
    }
    
    
    /**
     * Starts a standalone game of microRTS with the specified opponents, and game setting
     * @param gameSettings
     * @throws Exception 
     */
    public static void runStandAloneGame(GameSettings gameSettings) throws Exception {
        if (gameSettings.getLaunchMode() == GameSettings.LaunchMode.STANDALONE)
            new Game(gameSettings).start();
        else if (gameSettings.getLaunchMode() == GameSettings.LaunchMode.HUMAN)
            new MouseGame(gameSettings).start();
    }
}
