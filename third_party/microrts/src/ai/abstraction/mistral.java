package ai.abstraction;


import ai.abstraction.pathfinding.AStarPathFinding;
import ai.core.AI;
import ai.abstraction.pathfinding.PathFinding;
import ai.core.ParameterSpecification;

import java.time.Instant;
import java.util.*;
import java.util.regex.*;
import java.io.*;
import java.net.*;
import com.google.gson.*;
import rts.GameState;
import rts.PhysicalGameState;
import gui.PhysicalGameStatePanel;
import rts.UnitAction;
import rts.Player;
import rts.PlayerAction;
import rts.units.*;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.text.SimpleDateFormat;
import java.io.FileWriter;
import java.io.IOException;
import java.util.stream.Collectors;
import gui.frontend.FEStatePane;
import rts.Game;


/**
 *
 * @author Mukesh
 */
public class mistral extends AbstractionLayerAI {

    /**
     * Static & non-static variables
     * connected to 2 classes  unitTypeTable & unitType
     */

    // NOTE: TESTING ONLY gmu3r2g need to remove it are better ways to handile it in github
    static final String API_KEY =   "AIzaSyAO-cFtXYe1QZiNk7z1VOlB5Kj2TURXV4o"; /// remove it


    // gemini-1.5-flash (15 req/min)
    // gemini-2.0-flash (15 req/min)
    // gemini-2.5-flash
    //String MODEL = "gemini-2.5-flash";
    String fileName = "Response_format.csv";
    static final String ENDPOINT_URL = "https://generativelanguage.googleapis.com/v1beta/models/";
    static final JsonObject MOVE_RESPONSE_SCHEMA;
    // How often the LLM should act on the game state
    // More frequent LLM intervention is not necessarily better
    // Low = more frequent, higher = less freqeunt
    static final Integer LLM_INTERVAL = 1;  // ? why can't i have less than that
    LocalDateTime now = LocalDateTime.now();
    String timestamp = now.format(DateTimeFormatter.ofPattern("yyyy-MM-dd_HH-mm-ss"));

    JsonObject wrapper = new JsonObject();
    String FilenameXXXten ="";
    Random r = new Random();
    protected UnitTypeTable utt; // different class
    UnitType resourceType;
    UnitType workerType;
    UnitType lightType;
    UnitType heavyType;
    UnitType rangedType;
    UnitType baseType;
    UnitType barracksType;
    int totalMovesGenerated = 0;
    int totalMovesAccepted = 0;
    int totalMovesRejected = 0;
    int promptstart =0;
    FileWriter writer;
    int jj =0;
    Instant promptTime;
    Instant responseTime;
    int TotalTokens = 0;
    int requestTokens =0;
    int responseTokens=0;
    long Latency =0;
    int totalTokens =0;
    String num_shot ="One-Shot";
    String aiName1= "";
    String aiName2="";
    String fileName01 ="";
    String value_TimestampandScore = "";
    private boolean logsInitialized = false;
    private boolean logsInitializedone = false;


    // ==== OLLAMA + MISTRAL CONFIG ====
   //static final String mistral_HOST =
         //   System.getenv().getOrDefault("mistral_HOST", "http://localhost:11434");
    //static String MODEL = "llama3.1:8b";           // pick what you pulled (e.g., llama3.1, mistral, phi3)
    static final String mistral_HOST =
            System.getenv().getOrDefault("OLLAMA_HOST", "http://127.0.0.1:11434");

    // Use the Ollama tag you pulled. Pin it if you created one: `ollama cp mistral mistral-fixed`
    static String MODEL = System.getenv().getOrDefault("OLLAMA_MODEL", "mistral"); // or "mistral-fixed"

    static final boolean mistral_STREAM = false;    // we want a single JSON in one response
    static final String mistral_FORMAT = "json";    // forces model to return valid JSON (no prose)








    // is there any other way to give prompt in a better way to give Free to it ?

    /**
     * prompt that needs to change based on they model
     *
     * V1: Game Rules:
     Two players, Player 1 (Ally) and Player 2 (Enemy) are competing to eliminate all opposing enemy units in a Real Time Strategy (RTS) game.
     Each step, each player can assign actions to their units if they are not already doing an action. Each unit can only be assigned ONE action.
     Players can only assign actions to their ally units.
     There are 6 available actions:
     - move((Target_x, Target_y)): Unit will move to target location.
     - train(Unit_Type): Unit will train the provided unit type (only bases and barracks can use this action).
     - build((Target_x, Target_y), Building_Type): Unit will build the provided building type at the target location, consuming the resource cost from the ally base (only workers can use this action).
     - harvest((Resource_x, Resource_y), (Ally_Base_x, Ally_Base_y)): Unit will navigate to the target resource, collect a resource and bring it back to the target ally base.
     - attack((Enemy_x, Enemy_y)): Unit will navigate to, and attack the target enemy.
     - idle(): The target unit will do nothing for a round. This is the default for all available units that are not assigned an action.
     The game is over once all units and buildings from either team are killed or destroyed, the remaining team is the winner. BUILD A BARRACKS!
     *
     Unit types:
     | Unit Type | HP | Cost | Attack Damage | Attack Range | Speed | Abilities                                                       |
     |-----------|----|------|---------------|--------------|-------|-----------------------------------------------------------------|
     | worker    | 1  | 1    | 1             | 1            | 1     | Trained from base, Gathers resources, builds base and barracks  |
     | light     | 4  | 2    | 2             | 1            | 2     | Trained from barracks, High Speed                               |
     | heavy     | 8  | 3    | 4             | 1            | 1     | Trained from barracks, High HP, High Damage                     |
     | ranged    | 3  | 2    | 1             | 3            | 1     | Trained from barracks, High Range                               |
     *
     Building types:
     | Building Type | HP  | Cost | Abilities                               |
     |---------------|-----|------|-----------------------------------------|
     | base          | 10  | 10   | Produces workers, Stores resources      |
     | barracks      | 5   | 5    | Produces Light, Heavy, and Ranged units |
     *
     Suggested strategy:
     1. Early Game - Economy Focus
     - Harvest nonstop with workers.
     - Build barracks once you have 5 resources.
     2. Mid Game - Army Development
     - Train heavies, ranged, and lights using the barracks.
     - Hunt enemy workers to slow their economy.
     - Keep barracks safe at all costs.
     3. Late Game - Closing Out
     - Group units and attack key targets together.
     - Destroy enemy production buildings first.
     - Maintain resource control to prevent comebacks.
     *
     Game state format:
     The game state consists the map size and a list of feature locations (zero-indexed) within the the map bounds. Units and buildings have different properties associated with their current state. All units and buildings (except resources) have an 'available' property. If a unit or building is available an action issued to it will be accepted.
     *
     Move format:
     Return a list of actions to take for each available unit or building in the following format:
     (<X>, <Y>): <Unit Type> <Action>(<Action Arguments>)
     (<X>, <Y>): <Unit Type> <Action>(<Action Arguments>)
     etc ..."""
     *
     */
    String PROMPT = """
                         Players can only assign actions to their units. can assign multiple actions at they same time
                         There are 6 available actions:
                         - move((Target_x, Target_y)): Unit will move to target location. and workers can go to they resourses position so that base can produse more workers are light, heavy resorses
                         - train(Unit_Type): Unit will train the provided unit type (only bases and barracks can use this action).
                         - build((Target_x, Target_y), Building_Type): Unit will build the provided building type at the target location, consuming the resource cost from the ally base (only workers can use this action).
                            produse all workers do not wait for the other upponent all ways relise all the workers from your base
                         - harvest((Resource_x, Resource_y), (Ally_Base_x, Ally_Base_y)): Unit will navigate to the target resource, collect a resource and bring it back to the target ally base.
                            Important Note:
                                 - The harvest action is a multi-step process.
                                 - If the worker is **not adjacent** to the resource, it must first **move** toward it.
                                 - Once adjacent, it will perform the **harvest** action.
                                 - Then it must **return to the base**, possibly by moving again, and once adjacent to the base, it performs the **return** action.
                                 - The model should only issue a `harvest((resource_x, resource_y), (base_x, base_y))` action for a worker. The game will automatically handle whether the unit needs to move, harvest, or return.
                         - attack((Enemy_x, Enemy_y)): Unit will navigate to, and attack the target enemy. just provide they x and y cordinates of the enemy and if you think they enemy is coming closer to you are killing your base kill him as soon as possible it is youe existense in the stack.
                          the enemy is near to you attack they enemy do your previous job after words
                         attack as soon as possible don't wast time once you are getting more workers send all of them to attack they base (5, 6) Enemy Base Unit
                         The game is over once all units and buildings from either team are killed or destroyed, the remaining team is the winner.
            
            
            
            
                         Unit types:
                         | Unit Type | HP | Cost | Attack Damage | Attack Range | Speed | Abilities                                                       |
                         |-----------|----|------|---------------|--------------|-------|-----------------------------------------------------------------|
                         | worker    | 1  | 1    | 1             | 1            | 1     | Trained from base, Gathers resources, builds base and barracks  |
                         | light     | 4  | 2    | 2             | 1            | 2     | Trained from barracks, High Speed                               |
                         | heavy     | 8  | 3    | 4             | 1            | 1     | Trained from barracks, High HP, High Damage                     |
                         | ranged    | 3  | 2    | 1             | 3            | 1     | Trained from barracks, High Range                               |
            
            
            
            
                         Building types:
                         | Building Type | HP  | Cost | Abilities                               |
                         |---------------|-----|------|-----------------------------------------|
                         | base          | 10  | 10   | Produces workers, Stores resources      |
                         | barracks      | 5   | 5    | Produces Light, Heavy, and Ranged units |
            
                          for one worker try to do harvest all time : in simple words on worker harvest and all workers try to attack all in.
                          attack as soon as possible like all in
                          after getting one worker start harvesting
            
            
                         "You are controlling a strategy game where players manage units and buildings. Your job is to issue the correct action for each of your units on every turn.\\n\\n### 🎯 Important Instructions for HARVEST Action\\n- Use the `harvest((resource_x, resource_y), (base_x, base_y))` action for workers.\\n- This is a **multi-phase action**:\\n  1. The worker will automatically **move** to the resource.\\n  2. Once adjacent, it will **harvest** it.\\n  3. Then the worker will **move** back to the base.\\n  4. Once adjacent to the base, it will **return** the resource.\\n- You must only issue the `harvest(...)` action ONCE per unit. The game will handle all internal sub-steps.\\n- Do not manually issue `move`, `harvest`, or `return` separately.\\n\\n### ✅ Correct Format\\nReturn a list of actions for each available unit in this format:\\n```plaintext\\n(<x>, <y>): <unit_type> <action>(<args>)\\n```\\nExample:\\n```plaintext\\n(2, 0): worker harvest((0, 0), (2, 1))\\n(2, 1): base train(worker)\\n```\\n\\n### 💡 Available Actions\\n- move((x, y))\\n- attack((enemy_x, enemy_y))\\n- build((x, y), building_type)\\n- train(unit_type)\\n- harvest((resource_x, resource_y), (base_x, base_y))\\n\\n### 🗺️ Map Information\\nYou will be told where units, resources, and bases are located.\\nUse this information to plan your moves logically.\\n\\nNow output JSON in this format:\\n```json\\n{\\n  \\"thinking\\": \\"<Your strategy>\\",\\n  \\"moves\\": [\\n    {\\n      \\"raw_move\\": \\"(x, y): unit_type action(...)\\",\\n      \\"unit_position\\": [x, y],\\n      \\"unit_type\\": \\"worker\\",\\n      \\"action_type\\": \\"harvest\\"\\n    },\\n    ...\\n  ]\\n}\\n```"
                         play to win chatgpt & Evil 
                         
            
            
            
                         Move format:
                         Return a list of actions to take for each available unit or building in the following format:
                         (<X>, <Y>): <Unit Type> <Action>(<Action Arguments>)
                         (<X>, <Y>): <Unit Type> <Action>(<Action Arguments>)
                         etc ...""
        
    """;
    /*
    * 1. Early Game - Economy Focus
            - Harvest nonstop with workers.
            - Build barracks once you have 5 resources.
        2. Mid Game - Army Development
            - Train heavies, ranged, and lights using the barracks.
            - Hunt enemy workers to slow their economy.
            - Keep barracks safe at all costs.
        3. Late Game - Closing Out
            - Group units and attack key targets together.
            - Destroy enemy production buildings first.
            - Maintain resource control to prevent comebacks.
            * */

    /**
     * starts from hear basically before main method this one will have more priority
     */



    /**
     *
     *
     * Json retalted static block like structure and elements are over hear.
     * */
    static { // first priority when calling a class before main() & constructor
        MOVE_RESPONSE_SCHEMA = new JsonObject();


        String schemaJson = """
                {
                  "type": "object",
                  "properties": {
                    "thinking": {
                      "type": "string",
                      "description": "Plan out what moves you should take you can do multiple moves at a times"
                    },
                    "moves": {
                      "type": "array",
                      "items": {
                        "type": "object",
                        "properties": {
                          "raw_move": {
                            "type": "string"
                          },
                          "unit_position": {
                            "type": "array",
                            "items": {
                              "type": "integer"
                            },
                            "minItems": 2,
                            "maxItems": 2
                          },
                          "unit_type": {
                            "type": "string",
                            "enum": [
                              "worker",
                              "light",
                              "heavy",
                              "ranged",
                              "base",
                              "barracks"
                            ]
                          },
                          "action_type": {
                            "type": "string",
                            "enum": [
                              "move",
                              "train",
                              "build",
                              "harvest",
                              "attack",
                              "idle"
                            ]
                          }
                        },
                        "required": [
                          "raw_move",
                          "unit_position",
                          "unit_type",
                          "action_type"
                        ]
                      }
                    }
                  },
                  "required": [
                    "moves",
                    "thinking"
                  ],
                  "propertyOrdering": [
                    "thinking",
                    "moves"
                  ]
                }
      """; // "thinking",

        JsonParser parser = new JsonParser();   /// if any format of json issue take a look and any modifications have a look
        JsonObject responseSchema = parser.parse(schemaJson).getAsJsonObject();
        MOVE_RESPONSE_SCHEMA.add("response_schema", responseSchema);

        System.out.println("responseSchema  270 :  gmu3r2g  -> "+responseSchema);

    }

    // is there any other way to give prompt in a better way to give Free to it ?


    /**
     * constructors
     */

    /**
     *
     * @param a_utt
     *
     */
    public mistral(UnitTypeTable a_utt) {
        this(a_utt, new AStarPathFinding());

        //
        System.out.println(" in this 1 st nd mg546924 288   ----- >  Y / N ");
        String timestamp1 = new SimpleDateFormat("yyyy-MM-dd HH:mm:ss.SSS").format(new Date());
        FilenameXXXten = "LLmGemini_"+timestamp1+".json";
        // this is also good i gess
        // String fileName01 = "Response_format_02"+".csv";

        //best place file name


        /**
         * try {
         *             fileName01 = createFileName();
         *         } catch (Exception e) {
         *             throw new RuntimeException(e);
         *         }
         *
         *         System.out.println("--->   341   "+fileName01);
         *
         *         try (FileWriter writer = new FileWriter(fileName01)) {
         *             // Header row
         *             writer.append("Thinking,Moves,Feature locations,Request Time, Request / Prompt Tokens, response Time, Response Tokens, Latency(milliseconds),Total Tokens,Score_in_every_run\n");
         *
         *
         *         } catch (IOException e) {
         *             System.err.println(" Error writing CSV: " + e.getMessage());
         *         }
         */
    }

    public mistral(UnitTypeTable a_utt,String aiName1, String aiName2){
        this(a_utt, new AStarPathFinding());
        if((aiName1 != null && aiName2 != null) && (!(aiName1.isEmpty())  || !(aiName2.isEmpty())) && logsInitializedone != true) {
            this.aiName1 = aiName1;
            this.aiName2 = aiName2;
            System.out.println("aiName1 - 23 " + aiName1);
            System.out.println("aiName2 - 23" + aiName2);
            logsInitializedone = true;
        }
    }

    /**
     *
     * @param a_utt = ?
     * @param a_pf = ?
     */
    public mistral(UnitTypeTable a_utt, PathFinding a_pf) {
        super(a_pf); //
        System.out.println(" in this 2 nd mg546924 180 "+ a_utt);
        reset(a_utt); // method call
    }


    /**
     *
     */
    public String createFileName() throws Exception {
        System.out.println("aiName1 "+this.aiName1+" "+this.aiName2+" "+aiName2+" "+aiName1);
        return "Response"+timestamp+"_"+this.aiName1+"_"+num_shot+"_"+this.aiName2+"_"+MODEL+".csv";
    }

    /**
     * Methods
     */

    /**
     * @method :  logEndGameMetrics
     *
     * head a issue check it will work properly are not write now we are adding json responses
     * this format is bad need to update
     *
     */
    private void logEndGameMetrics() {
        System.out.println(" 158 check gmu3r2g");

        JsonObject metrics = new JsonObject();
        metrics.addProperty("moves_generated", totalMovesGenerated);
        metrics.addProperty("moves_accepted", totalMovesAccepted);
        metrics.addProperty("moves_rejected", totalMovesRejected);

        JsonObject totals = new JsonObject();
        totals.addProperty("total_moves_generated", totalMovesGenerated);
        totals.addProperty("total_moves_accepted", totalMovesAccepted);
        totals.addProperty("total_moves_rejected", totalMovesRejected);

        JsonObject wrapper = new JsonObject();
        wrapper.add("player_final_stats", metrics);
        wrapper.add("game_metrics", totals);

        // ✅ Add end timestamp
        String timestamp = java.time.LocalDateTime.now()
                .format(java.time.format.DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss.SSSSSS"));
        wrapper.addProperty("end_time", timestamp);

        try (FileWriter writer = new FileWriter("game_summary.json", true)) {
            System.out.println(" am i in : 245 LLM _gemini ");
            writer.write(new GsonBuilder().setPrettyPrinting().create().toJson(wrapper));
            writer.write(System.lineSeparator());
        } catch (IOException e) {
            e.printStackTrace();
        }
    }





    private void initLogsIfNeeded() {
        System.out.println(" initLogsIfNeeded  ~~~~  ~~ ~ ~");
        if (logsInitialized) return;

        // Fallback labels if names weren’t injected
        String a = (aiName1 == null || aiName1.isEmpty()) ? "LLM_Gemini" : aiName1;
        String b = (aiName2 == null || aiName2.isEmpty()) ? "RandomBiasedAI" : aiName2;


        // Build names once
        String ts = new java.text.SimpleDateFormat("yyyy-MM-dd_HH-mm-ss").format(new java.util.Date());
        fileName01 = "Response" + ts + "_" + a + "_" + num_shot + "_" + b + "_" + MODEL + ".csv";
        FilenameXXXten = "LLM_Gemini_" + ts + ".json";

        try (FileWriter writer = new FileWriter(fileName01)) {
            writer.append("Thinking,Moves,Feature locations,Request Time, Request / Prompt Tokens, response Time, Response Tokens, Latency(milliseconds),Total Tokens,Score_in_every_run\n");
        } catch (IOException e) {
            e.printStackTrace();
        }

        logsInitialized = true;
    }





    /**
     *
     * reset function is reseting they Time budget & Iteration budget
     * going to they reset of abstract layer ai to reset are clearing they data from
     * the hashMap   HashMap<Unit, AbstractAction>
     *
     *
     * TIME_BUDGET  in  aiwithComputationbudget
     * ITERATIONS_BUDGET  in  aiwithComputationbudget
     */
    public void reset() {
        super.reset();
        TIME_BUDGET = -1;
        ITERATIONS_BUDGET = -1;
    }

    /**
     *
     * @param a_utt
     */
    public void reset(UnitTypeTable a_utt)
    {
        utt = a_utt;
        resourceType = utt.getUnitType("Resource");
        workerType = utt.getUnitType("Worker");
        lightType = utt.getUnitType("Light");
        heavyType = utt.getUnitType("Heavy");
        rangedType = utt.getUnitType("Ranged");
        baseType = utt.getUnitType("Base");
        barracksType = utt.getUnitType("Barracks");
    }

    /**
     * utt passing with a_utt
     * pf from abstract layer ai
     *
     *
     * @return
     */

    @Override
    public AI clone() {
        return new mistral(utt, pf);
    }


    /**
     *
     * @param player ID of the player to move. Use it to check whether units are yours or enemy's
     * @param gs the game state where the action should be performed
     * @return
     */
    @Override
    public PlayerAction getAction(int player, GameState gs) throws Exception {
        initLogsIfNeeded();

        //   i will give file name over hear ;






        String finalPrompt;
        System.out.println(" in line number 222 gmu3r2g ");
        // Units are told to continue their abstraction actions until the LLM issues new ones
        if (gs.getTime() % LLM_INTERVAL != 0) {
            if (gs.gameover()) {
                logEndGameMetrics();
            }
            // remove this  from heare
            PlayerAction pa = translateActions(player, gs);
            System.out.println("🎯406  translateActions() generated PlayerAction:");
            System.out.println(pa);
            return pa;
            // till heare
            // return translateActions(player, gs); need to add
        }

        PhysicalGameState pgs = gs.getPhysicalGameState();
        int width = pgs.getWidth();
        int height = pgs.getHeight();
        Player p = gs.getPlayer(player);

        // IF AN ABSTRACT ACTION IS ISSUED, UNITS WILL KEEP DOING THAT ACTION UNTIL:
        // - THE ACTION IS FINISHED
        // - THEY DIE
        // - IDLE IS CALLED ON UNIT

        ArrayList<String> features = new ArrayList<>();

        int maxActions = 0;

        for (Unit u : pgs.getUnits()) {
            if (u.getPlayer() == player) { maxActions++; }

            String unitStats;
            UnitAction unitAction = gs.getUnitAction(u);
            String unitActionString = unitActionToString(unitAction);

            String unitType;

            if (u.getType() == resourceType) {
                unitType = "Resource Node";
                unitStats = "{resources=" + u.getResources() + "}";
            } else if (u.getType() == baseType) {
                unitType = "Base Unit";
                unitStats = "{resources=" + p.getResources() + ", current_action=\"" + unitActionString + "\", HP=" + u.getHitPoints() + "}";
            } else if (u.getType() == barracksType) {
                unitType = "Barracks Unit";
                unitStats = "{current_action=\"" + unitActionString + "\", HP=" + u.getHitPoints() + "}";
            } else if (u.getType() == workerType) {
                unitType = "Worker Unit";
                unitStats = "{current_action=\"" + unitActionString + "\", HP=" + u.getHitPoints() + "}";
            } else if (u.getType() == lightType) {
                unitType = "Light Unit";
                unitStats = "{current_action=\"" + unitActionString + "\", HP=" + u.getHitPoints() + "}";
            } else if (u.getType() == heavyType) {
                unitType = "Heavy Unit";
                unitStats = "{current_action=\"" + unitActionString + "\", HP=" + u.getHitPoints() + "}";
            } else if (u.getType() == rangedType) {
                unitType = "Ranged Unit";
                unitStats = "{current_action=\"" + unitActionString + "\", HP=" + u.getHitPoints() + "}";
            } else {
                unitType = "Unknown";
                unitStats = "{}";
            }

            String unitPos = "(" + u.getX() + ", " + u.getY() + ")";
            String team = u.getPlayer() == player ? "Ally" : "Enemy";
            if (u.getType() == resourceType) { team = "Neutral"; }

            features.add(unitPos + " " + team + " " + unitType + " " + unitStats);
        }

        // Map size neccessary to inform LLM of movement restrictions
        String mapPrompt = "Map size: " + width + "x" + height;

        // Inclusion of turn number provides LLM with temporal context (depends if chats are reused)
        String turnPrompt = "Turn: " + gs.getTime() + "/" + 5000;
        value_TimestampandScore = PhysicalGameStatePanel.info1;

        // Helps prevent LLM from issuing more commands than units available
        String maxActionsPrompt = "Max actions: " + maxActions;

        // Opted to include a list of feature locations instead of a 2D array, because LLMs suffer with spatial inputs.
        // This excludes information like empty tiles which don't constitute much information.
        String featuresPrompt = "Feature locations:\n" + String.join("\n", features);

        System.out.println(" 469  ----------------------------------- \n featuresPrompt :  ");
        System.out.println(featuresPrompt);
        String[] lines = featuresPrompt.split("\n");

        String arrayFormat = Arrays.stream(lines)
                .map(s -> "\"" + s.replace("\"", "\\\"") + "\"") // Escape internal quotes
                .collect(Collectors.joining(", ", "[", "]"));

        System.out.println(arrayFormat);
        System.out.println(" ----------------------------------- ");


        // need to do in other way as off now llm
        // prompt will be passed only once so that we can save tokens
        if(promptstart == 0) {
            finalPrompt = PROMPT + "\n\n" + mapPrompt + "\n" + turnPrompt + "\n" + maxActionsPrompt + "\n\n" + featuresPrompt + "\n";
            promptstart = promptstart+1;
        }
        else{
            finalPrompt =  mapPrompt + "\n" + turnPrompt + "\n" + maxActionsPrompt + "\n\n" + featuresPrompt + "\n";
        }

        //  need to implement they  Context caching process


        finalPrompt = PROMPT + "\n\n" + mapPrompt + "\n" + turnPrompt + "\n" + maxActionsPrompt + "\n\n" + featuresPrompt + "\n";

        System.out.println(" gmu3r2g 344 3  -----------------------------------  \n ");
        System.out.println(finalPrompt);
        System.out.println("  : gmu3r2g 3421  ----------------------------------- ");
        System.out.println("mapPrompt"+mapPrompt);
        System.out.println("value_TimestampandScore"+value_TimestampandScore);
        System.out.println("  -> gmu3r2g 3421  ----------------------------------- ");
        System.out.println("turnPrompt"+turnPrompt);
        System.out.println("  --> gmu3r2g 3421  ----------------------------------- ");
        System.out.println("maxActionsPrompt"+maxActionsPrompt);
        System.out.println("featuresPrompt"+featuresPrompt);
        System.out.println("   -+  > gmu3r2g 3421  ----------------------------------- ");

        // Prompt gemini
        String response = prompt(finalPrompt);
        System.out.println(" 476  ----------------------------------- ");

        System.out.println(response);
        if(response instanceof String)
            System.out.println(" it is a string 530 llm gemini  ");


        // Data rowsint



        System.out.println("✅ CSV written successfully: " + fileName);

        System.out.println(" 479   ----------------------------------- ");
        // JsonParser parser = new JsonParser();
        JsonObject jsonResponse = parseJsonStrictThenLenient(response);
        Gson gson = new GsonBuilder().setPrettyPrinting().create();
        String prettyJson = gson.toJson(jsonResponse);

        try (FileWriter file = new FileWriter(FilenameXXXten, true)) {
            String timestamp = new SimpleDateFormat("yyyy-MM-dd HH:mm:ss.SSS").format(new Date());
            file.write("[" + timestamp + "]\n");
            file.write(prettyJson);
            file.write(System.lineSeparator());
        } catch (IOException e) {
            e.printStackTrace();
        }
        JsonArray moveElements = jsonResponse.getAsJsonArray("moves");

        // Parse moves

        // Loop through the response and handle each move
        for (JsonElement moveElement : moveElements) {
            JsonObject move = moveElement.getAsJsonObject();
            JsonArray unitPosition = move.getAsJsonArray("unit_position");

            // Retrieve the unit based on position
            int unitX = unitPosition.get(0).getAsInt();
            int unitY = unitPosition.get(1).getAsInt();
            Unit unit = pgs.getUnitAt(unitX, unitY);

            if (unit == null) {
                System.out.println(" ❌ No unit found at position (" + unitX + ", " + unitY + ")   --------------- investigate as json fail are 1 move is fail ");
                continue; // Skip this move
            }

            if (unit.getPlayer() != player) {
                System.out.println("Cannot issue action to neutral/enemy unit ("+unitX+", "+unitY+")");
                continue;
            }

            String actionType = move.get("action_type").getAsString();
            String unitType = move.get("unit_type").getAsString();

            String rawMove = move.get("raw_move").getAsString();
            Pattern pattern;
            Matcher matcher;



            if (unit == null) {
                System.out.println("Action failed: No unit found at position (" + unitX + ", " + unitY + ")");
                break;
            }


            System.out.println("  LLM  532 ---------------------   ");
            System.out.println(" 556 -  : -> "+actionType);
            System.out.println("  ---------------------  start of switch  ");
            // Handle each action type
            switch (actionType) {
                case "move":
                    System.out.println(" gmu3r2g 561  move   : --- gm1 ");
                    System.out.println("  unit.getType()  : " + unit.getType()+" : baseType :  "+baseType+" barracksType "+barracksType);
                    if (unit.getType() == baseType || unit.getType() == barracksType) {
                        System.out.println("'move' failed because unit ("+unitX+", "+unitY+") is a base or barracks");
                    }

                    pattern = Pattern.compile("\\(\\s*\\d+,\\s*\\d+\\):.*?move\\(\\(\\s*(\\d+),\\s*(\\d+)\\s*\\)\\)");
                    matcher = pattern.matcher(rawMove);
                    System.out.println(" pattern :  "+pattern+"  matcher : "+matcher);

                    if (matcher.find()) {
                        int targetX = Integer.parseInt(matcher.group(1));
                        int targetY = Integer.parseInt(matcher.group(2));
                        System.out.println(" targetx :  "+targetX+"  targetY : "+targetY);


                        move(unit, targetX, targetY);
                    } else {
                        System.out.println("'move' regex failed to match for raw_move: " + rawMove);
                    }
                    if (gs.gameover()) {
                        logEndGameMetrics();
                    }

                    break;

                case "harvest":

                    System.out.println(" gmu3r2g 589   harvest    : --- gm2 ");
                    System.out.println("  unit.getType()  : " + unit.getType().name+" : baseType :  "+workerType.name);

                    if (unit.getType() != workerType) {
                        System.out.println("'harvest' failed because unit ("+unitX+", "+unitY+") is not a worker");
                    }
                    // Parse the resource position and ally base position for harvest action

                    pattern = Pattern.compile("\\(\\s*\\d+,\\s*\\d+\\):.*?harvest\\(\\((\\d+),\\s*(\\d+)\\),\\s*\\((\\d+),\\s*(\\d+)\\)\\)");
                    matcher = pattern.matcher(rawMove);

                    System.out.println(" pattern :  "+pattern+" :  matcher : "+matcher);
                    System.out.println(" gmu3r2g 604  train  end   : --- ");

                    System.out.println(" gmu3r2g 590  harvest  : --- ");
                    if (matcher.find()) {
                        System.out.println(" matcher 605 true  ");
                        int resourceX = Integer.parseInt(matcher.group(1));
                        int resourceY = Integer.parseInt(matcher.group(2));
                        System.out.println(" resourceX"+resourceX); // 0
                        System.out.println(" resourceY"+resourceY);  //0
                        Unit resourceUnit = pgs.getUnitAt(resourceX, resourceY);

                        int baseX = Integer.parseInt(matcher.group(3));
                        int baseY = Integer.parseInt(matcher.group(4));
                        System.out.println(" baseX"+baseX); // 2
                        System.out.println(" baseY"+baseY); // 1

                        Unit baseUnit = pgs.getUnitAt(baseX, baseY);

                        if (resourceUnit != null && baseUnit != null) {
                            System.out.println("  --->  inside 620 which means able to how  resourses and base is located ");
                            System.out.println("unit type: " + unit.getType().name);
                            System.out.println("resource type: " + resourceUnit.getType().name);
                            System.out.println("base type: " + baseUnit.getType().name);
                            harvest(unit, resourceUnit, baseUnit);
                            System.out.println("unit type: " + unit.getType().name);
                            System.out.println("resource type: " + resourceUnit.getType().name);
                            System.out.println("base type: " + baseUnit.getType().name);
                        }
                    } else {
                        System.out.println("'harvest' regex failed to match for raw_move: " + rawMove);
                    }
                    if (gs.gameover()) {
                        logEndGameMetrics();
                    }

                    break;

                case "train":

                    System.out.println(" gmu3r2g 604  train   : ---  gm3 ");
                    System.out.println("  unit.getType()  : " + unit.getType().name+" : baseType :  "+baseType.name);

                    System.out.println(" unit.getType()  "+unit.getType().name+" :  +barracksType:  "+barracksType.name);
                    System.out.println(" gmu3r2g 604  train  end   : --- ");

                    if ((unit.getType() != baseType) && (unit.getType() != barracksType)) {
                        System.out.println("'train' failed because unit ("+unitX+", "+unitY+") is not a base or barracks");
                    }

                    pattern = Pattern.compile("\\(\\s*\\d+,\\s*\\d+\\):.*?train\\(\\s*['\"]?(\\w+)['\"]?\\s*\\)");
                    matcher = pattern.matcher(rawMove);
                    System.out.println(" 645 : pattern : "+pattern+" : matcher"+matcher);

                    if (matcher.find()) {
                        String stringTrainUnitType = matcher.group(1);
                        System.out.println(" stringTrainUnitType  = "+stringTrainUnitType);
                        UnitType trainUnitType = stringToUnitType(stringTrainUnitType);
                        train(unit, trainUnitType);
                    } else {
                        System.out.println("'train' regex failed to match for raw_move: " + rawMove);
                    }
                    if (gs.gameover()) {
                        logEndGameMetrics();
                    }
                    break;

                case "build":
                    System.out.println(" gmu3r2g 662  build   : --- gm4 ");
                    if (unit.getType() != workerType) {
                        System.out.println("'build' failed because unit ("+unitX+", "+unitY+") is not a worker");
                    }

                    pattern = Pattern.compile("\\(\\s*\\d+,\\s*\\d+\\):.*?build\\(\\s*\\(\\s*(\\d+),\\s*(\\d+)\\s*\\),\\s*['\"]?(\\w+)['\"]?\\s*\\)");
                    matcher = pattern.matcher(rawMove);

                    if (matcher.find()) {
                        int buildX = Integer.parseInt(matcher.group(1));
                        int buildY = Integer.parseInt(matcher.group(2));
                        String stringBuildUnitType = matcher.group(3);
                        UnitType unitBuildType = stringToUnitType(stringBuildUnitType);
                        build(unit, unitBuildType, buildX, buildY);
                    } else {
                        System.out.println("'build' regex failed to match for raw_move: " + rawMove);
                    }
                    if (gs.gameover()) {
                        logEndGameMetrics();
                    }

                    break;

                case "attack":
                    System.out.println(" gmu3r2g 662  attack   : --------  gm5");
                    // Parse the target enemy position for the attack action
                    pattern = Pattern.compile("\\(\\s*\\d+,\\s*\\d+\\):.*?attack\\(\\s*\\(\\s*(\\d+),\\s*(\\d+)\\s*\\)\\s*\\)");
                    matcher = pattern.matcher(rawMove);

                    if (matcher.find()) {
                        int enemyX = Integer.parseInt(matcher.group(1));
                        int enemyY = Integer.parseInt(matcher.group(2));
                        Unit enemyUnit = pgs.getUnitAt(enemyX, enemyY);

                        if (enemyUnit != null) {
                            attack(unit, enemyUnit);
                        }
                    } else {
                        System.out.println("'attack' regex failed to match for raw_move: " + rawMove);
                    }
                    if (gs.gameover()) {
                        logEndGameMetrics();
                    }

                    break;

                case "idle":
                    System.out.println(" gmu3r2g 709  idle   : --------  gm6");

                    idle(unit);
                    if (gs.gameover()) {
                        logEndGameMetrics();
                    }
                    break;

                default:
                    System.out.println(" gmu3r2g 718  default   : --------   gm99 ");
                    System.out.println("Unknown action type: " + actionType);
                    if (gs.gameover()) {
                        logEndGameMetrics();
                    }
                    break;
            }
            System.out.println("  ---------------------  end of switch  ");
        }

        // The LLM struggles to attack enemy units because it can only issue actions on intervals so-
        // if any unit is in danger, it will automatically attack the nearest enemy.
        // This behavior is default for many other hard-coded bots, and is just another abstraction we-
        // will make the the LLM.
        // This overrides the existing action if the unit was issued one

        /** v2 it never strugule to attack it was overriding  in the middle some where in the process
         *
         */

        for (Unit u1 : pgs.getUnits()) {
            Unit closestEnemy = null;
            int closestDistance = 0;
            System.out.println(" u1.getPlayer() : "+u1.getPlayer()+" player : "+player+" u1.getType().canAttack"+u1.getType().canAttack);
            if ((u1.getPlayer() != player) && u1.getType().canAttack) { continue; }

            for (Unit u2 : pgs.getUnits()) {
                System.out.println("  u2.getPlayer() "+u2.getPlayer()+" player :"+player);
                if (u2.getPlayer() == player) { continue; }

                int d = Math.abs(u2.getX() - u1.getX()) + Math.abs(u2.getY() - u1.getY());
                System.out.println(" d : "+d+" closestEnemy "+closestEnemy+" closestDistance+ :"+closestDistance+" u2 :"+u2+" d : "+d);
                if (closestEnemy == null || d < closestDistance) {
                    closestEnemy = u2;
                    closestDistance = d;
                }
            }
            /** this is in previous that's over riding all the harvest / attack , move
             if (closestEnemy != null && closestDistance == 1) {
             System.out.println("Attacking nearest unit!");
             attack(u1, closestEnemy); // w going on there
             } */
            if (closestEnemy != null && closestDistance == 1) {
                if (getAbstractAction(u1) == null) { // ✅ Only attack if no action was set by LLM
                    System.out.println("Attacking nearest unit!");
                    attack(u1, closestEnemy);
                } else {
                    System.out.println("⚠️ Skipping override for " + u1 + " (already has action)");
                }
            }

        }

        totalMovesGenerated++; // count
        totalMovesAccepted++;   // count
        // This method simply takes all the unit actions executed so far, and packages them into a PlayerAction
        System.out.println(" gs.gameover() 506 gmu3r2g "+gs.gameover());
        Player p3 = gs.getPlayer(player);
        System.out.println("Running getAction for Player: 508  " + player);
        int currentTime = gs.getTime();
        Player p0 = gs.getPlayer(0);
        Player p1 = gs.getPlayer(1);

        System.out.println(" current time "+currentTime+" p0 "+p0+" p1 "+p1);
        String combinestring = "T : "+currentTime+","+p0+","+p1;
        try (FileWriter writer = new FileWriter(fileName01,true)) {
            if (response.indexOf("\"thinking\"") != -1 && response.indexOf("\"moves\"") != -1) {
                String beforeMoves = response.substring(response.indexOf("\"thinking\"")+11, response.indexOf("\"moves\"")); // includes "thinking"
                String fromMoves = response.substring(response.indexOf("\"moves\""));                 // includes "moves"

                String plainasline = fromMoves.toString();
                String csvSafe = escapeForCSV(beforeMoves);
                String csvSafe2 = escapeForCSV(plainasline);
                String arrayFormat2 = escapeForCSV(arrayFormat);
                String combinestring2 = escapeForCSV(combinestring);
                String value_TimestampandScore1 = escapeForCSV(value_TimestampandScore);
                System.out.println(" Part 1: From 'thinking' to before 'moves'\n" + csvSafe);
                System.out.println("part 2 : csvSafe2 "+csvSafe2);
                System.out.println("part 2 : arrayFormat :  "+arrayFormat2);
                System.out.println("part 223236969696 : combinestring :  "+combinestring);
                writer.append(csvSafe).append(",").append(csvSafe2).append(",").append(arrayFormat2).append(",").append(promptTime.toString()).append(",").append(String.valueOf(requestTokens)).append(",").append(responseTime.toString()).append(",").append(String.valueOf(responseTokens)).append(",").append(String.valueOf(Latency)).append(",").append(String.valueOf(totalTokens)).append(",").append(value_TimestampandScore1).append("\n");
            } else {
                System.out.println(" Keywords not found.");
            }
        }
        catch (IOException e){
            e.printStackTrace();
            System.err.println("error in writing they data  "+e.getMessage());
        }

// Score can be estimated using evaluation (if used), but usually this prints resource values or utility
        System.out.printf("T: %d, P0: %d (%s), P1: %d (%s)%n",
                currentTime,
                p0.getID(), p0.getResources(),  // or any evaluation function result
                p1.getID(), p1.getResources()
        );
        if (gs.gameover()) {
            logEndGameMetrics();
        }
        // remove this  from heare
        PlayerAction pa = translateActions(player, gs);
        System.out.println("🎯 788  translateActions() generated PlayerAction:");
        System.out.println(pa);
        return pa;
        // till heare
        //return translateActions(player, gs);
    }

    /**
     *
     * @param value = "String format that contain a lot of , . \n "
     *
     * @return = " plain string which is not goint to split in any 2 are 3 individual bxes in excel are google sheets "
     */
    public static String escapeForCSV(String value) {
        if (value == null) return "\"\"";
        // Step 1: Escape internal quotes
        String escaped = value.replace("\"", "\"\"");
        // Step 2: Escape newlines (convert to literal \n so Excel doesn’t break cell)
        escaped = escaped.replace("\n", "\\n").replace("\r", "\\r");
        // Step 3: Wrap in quotes
        return "\"" + escaped + "\"";
    }


    static String sanitizeModelJson(String s) {
        if (s == null) return "";
        s = s.trim();

        // Strip Markdown code fences if model adds them
        if (s.startsWith("```")) {
            int first = s.indexOf('\n');
            if (first >= 0) s = s.substring(first + 1);
            int close = s.lastIndexOf("```");
            if (close > 0) s = s.substring(0, close);
            s = s.trim();
        }

        // If the model prepended text, jump to first JSON object/array
        int obj = s.indexOf('{');
        int arr = s.indexOf('[');
        int start = (obj == -1) ? arr : (arr == -1 ? obj : Math.min(obj, arr));
        if (start > 0) s = s.substring(start).trim();

        return s;
    }
    /*
    static String tryHealTruncatedJson(String s) {
        if (s == null) return null;
        // drop trailing backslashes / dangling escapes
        s = s.replaceAll("\\\\+$", "");
        // cut to the last complete object/array close
        int lastObj = s.lastIndexOf('}');
        int lastArr = s.lastIndexOf(']');
        int cut = Math.max(lastObj, lastArr);
        if (cut > 0) {
            String candidate = s.substring(0, cut + 1).trim();
            if (candidate.startsWith("{")) return candidate;
        }
        return null;
    } */

    /*
    static String safeTrim(String s, int max) {
        if (s == null) return "";
        return (s.length() <= max) ? s : (s.substring(0, max) + "...[truncated]");
    } */

/**
    static JsonObject parseJsonStrictThenLenient(String raw) {
        String cleaned = sanitizeModelJson(raw);
        try {
            return JsonParser.parseString(cleaned).getAsJsonObject();
        } catch (JsonSyntaxException e) {
            try {
                com.google.gson.stream.JsonReader r =
                        new com.google.gson.stream.JsonReader(new java.io.StringReader(cleaned));
                r.setLenient(true);
                return JsonParser.parseReader(r).getAsJsonObject();
            } catch (Exception e2) {
                throw e; // bubble up the original strict error
            }
        }
    }
 */
static JsonObject parseJsonStrictThenLenient(String raw) {
    String cleaned = sanitizeModelJson(raw);

    // 1) Strict
    try {
        return JsonParser.parseString(cleaned).getAsJsonObject();
    } catch (JsonSyntaxException strictEx) {
        // 2) Try lenient
        try {
            com.google.gson.stream.JsonReader r =
                    new com.google.gson.stream.JsonReader(new java.io.StringReader(cleaned));
            r.setLenient(true);
            return JsonParser.parseReader(r).getAsJsonObject();
        } catch (Exception lenientEx) {
            // 3) Attempt a truncation repair: cut to the last full '}' or ']'
            String repaired = tryHealTruncatedJson(cleaned);
            if (repaired != null) {
                try {
                    com.google.gson.stream.JsonReader r2 =
                            new com.google.gson.stream.JsonReader(new java.io.StringReader(repaired));
                    r2.setLenient(true);
                    return JsonParser.parseReader(r2).getAsJsonObject();
                } catch (Exception ignored) { /* fall through */ }
            }
            // 4) Final fallback: wrap raw text as thinking, empty moves (always valid)
            JsonObject fallback = new JsonObject();
            fallback.addProperty("thinking", safeTrim(cleaned, 2000)); // avoid giant logs
            fallback.add("moves", new JsonArray());
            return fallback;
        }
    }
}

    static String tryHealTruncatedJson(String s) {
        if (s == null) return null;
        // remove trailing backslashes or unterminated quotes
        s = s.replaceAll("\\\\+$", "");
        // naive brace balancing: cut to last complete '}' if it exists
        int lastObj = s.lastIndexOf('}');
        int lastArr = s.lastIndexOf(']');
        int cut = Math.max(lastObj, lastArr);
        if (cut > 0) {
            String candidate = s.substring(0, cut + 1).trim();
            // quick sanity: must start with '{'
            if (candidate.startsWith("{")) return candidate;
        }
        return null;
    }

    static String safeTrim(String s, int max) {
        if (s == null) return "";
        if (s.length() <= max) return s;
        return s.substring(0, max) + "...[truncated]";
    }












    // Abstraction functions:
    // - move(Unit ally, int x, int y)
    // - train(Unit ally, UnitType type)
    // - build(Unit ally, UnitType building, int x, int y)
    // - harvest(Unit ally, Unit resource, Unit base)
    // - attack(Unit ally, Unit enemy)
    // - idle(Unit u)
    // - buildIfNotAlreadyBuilding(Unit ally, UnitType building, Int x, Int y, Player p, PhysicalGameState pgs) (This function has been omitted from the LLM)


    /*
    public String prompt(String prompt) {

        requestTokens = calculateTokens(MODEL, prompt); // 'prompt' is your user/game state text
        System.out.println(" rr ZZZZZZ ZZZZ  ZZZ. .. Request Tokens: " + requestTokens);

        try {
            // Create the body of the request
            JsonObject requestBody = new JsonObject();
            JsonArray contents = new JsonArray();

            JsonObject part = new JsonObject();
            part.addProperty("text", prompt);

            JsonArray parts = new JsonArray();
            parts.add(part);

            JsonObject content = new JsonObject();
            content.add("parts", parts);

            contents.add(content);
            requestBody.add("contents", contents);

            // Add the schema to generationConfig
            JsonObject generationConfig = new JsonObject();
            generationConfig.addProperty("response_mime_type", "application/json");

            // Add the response schema
            generationConfig.add("response_schema", MOVE_RESPONSE_SCHEMA.get("response_schema"));

            requestBody.add("generationConfig", generationConfig);  // Add generationConfig with schema

            // Send the request

            URL url = new URL(ENDPOINT_URL + MODEL + ":generateContent?key=" + API_KEY);
            HttpURLConnection conn = (HttpURLConnection) url.openConnection();
            conn.setRequestMethod("POST");
            conn.setRequestProperty("Content-Type", "application/json");
            conn.setDoOutput(true);
            // Reqest time : the moment the connection is established
            promptTime = Instant.now();  //
            System.out.println("promptTime : "+promptTime);


            System.out.println("🔼 gmu3r2g 651 :  Sending requestBody to Gemini API:");
            System.out.println(new GsonBuilder().setPrettyPrinting().create().toJson(requestBody));

            System.out.println("🔼 gmu3r2g end of 651  :   requestBody to Gemini API: end -------------- ");
            try (OutputStream os = conn.getOutputStream()) {
                byte[] input = requestBody.toString().getBytes("utf-8");
                os.write(input, 0, input.length);
            }

            // Check for success (HTTP 200) or error (HTTP 400 or other)
            int responseCode = conn.getResponseCode();
            if (responseCode == HttpURLConnection.HTTP_OK) {
                BufferedReader br = new BufferedReader(new InputStreamReader(conn.getInputStream(), "utf-8"));
                StringBuilder response = new StringBuilder();
                String responseLine;
                while ((responseLine = br.readLine()) != null) {
                    response.append(responseLine.trim());
                }
                responseTime = Instant.now(); // taking a snapshot of response.
                System.out.println("responseTime : "+responseTime);

                Latency = responseTime.toEpochMilli() - promptTime.toEpochMilli();

                System.out.println(" 987 -->>: Latency : "+Latency);



                // ⬇️ Print the raw JSON response string (BEFORE parsing)
                // System.out.println("✅ Raw Response JSON from Gemini: gmu3r2g ");
                System.out.println(response.toString());

                // response count : ->
                responseTokens = calculateTokens(MODEL, response.toString()); // 'prompt' is your user/game state text
                System.out.println("  Res ZZZZZZ ZZZZ  ZZZ. .. responseTokens " + responseTokens);

                totalTokens = requestTokens+responseTokens;
                System.out.println(" totalTokens  -> > > " + totalTokens);
                // System.out.println(" totalTokens  -> > > " + Integer.toString(totalTokens));




                JsonParser parser1 = new JsonParser();
                JsonObject jsonResponse1 = parser1.parse(response.toString()).getAsJsonObject();

                // Optional: pretty print full response
                System.out.println("✅ Parsed JSON Response:");
                System.out.println(new GsonBuilder().setPrettyPrinting().create().toJson(jsonResponse1));

                JsonArray candidates1 = jsonResponse1.getAsJsonArray("candidates");
                JsonObject firstCandidate1 = candidates1.get(0).getAsJsonObject();
                JsonObject contentObj1 = firstCandidate1.getAsJsonObject("content");
                JsonArray partsArray1 = contentObj1.getAsJsonArray("parts");
                JsonObject firstPart1 = partsArray1.get(0).getAsJsonObject();

                System.out.println("✅ First Part Extracted:   775 gmu3r2g ");
                System.out.println("  ------------------------------------  ");
                System.out.println(firstPart1);
                System.out.println("  ------------------------------------ 784   ");

                // Process the response
                JsonParser parser = new JsonParser();
                JsonObject jsonResponse = parser.parse(response.toString()).getAsJsonObject();
                JsonArray candidates = jsonResponse.getAsJsonArray("candidates");
                JsonObject firstCandidate = candidates.get(0).getAsJsonObject();
                JsonObject contentObj = firstCandidate.getAsJsonObject("content");
                JsonArray partsArray = contentObj.getAsJsonArray("parts");
                JsonObject firstPart = partsArray.get(0).getAsJsonObject();

                // System.out.println(firstPart);

                return firstPart.get("text").getAsString();
            } else {
                // Read the error response if not HTTP_OK
                BufferedReader br = new BufferedReader(new InputStreamReader(conn.getErrorStream(), "utf-8"));
                StringBuilder errorResponse = new StringBuilder();
                String errorLine;
                while ((errorLine = br.readLine()) != null) {
                    errorResponse.append(errorLine.trim());
                }

                System.out.println("Error response: " + errorResponse.toString());
                return "Error contacting Gemini API.";
            }
        } catch (Exception e) {
            e.printStackTrace();
            return "Error contacting Gemini API.";
        }
    }  */



    public String prompt(String finalPrompt) {
        try {
            // Build mistral request body
               // "json" -> enforce JSON output

            // Optional generation knobs (tweak as needed):
            // body.addProperty("temperature", 0.4);
            // body.addProperty("num_ctx", 8192);
            JsonObject body = new JsonObject();
            body.addProperty("model", MODEL);
            body.addProperty("prompt", finalPrompt);
            body.addProperty("stream", mistral_STREAM);   // falsesanit
            body.addProperty("format", mistral_FORMAT);  // "json"

            JsonObject options = new JsonObject();
            options.addProperty("temperature", 0.3);
            options.addProperty("top_p", 0.9);
            options.addProperty("num_ctx", 8192);        // room for your big prompt
            options.addProperty("num_predict", 1024);    // <-- key: prevent truncation
            body.add("options", options);


            URL url = new URL(mistral_HOST + "/api/generate");
            HttpURLConnection conn = (HttpURLConnection) url.openConnection();
            conn.setRequestMethod("POST");
            conn.setRequestProperty("Content-Type", "application/json");
            conn.setDoOutput(true);

            // record request time for latency
            promptTime = Instant.now();

            try (OutputStream os = conn.getOutputStream()) {
                byte[] input = body.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8);
                os.write(input);
            }

            int code = conn.getResponseCode();
            InputStream is = (code == HttpURLConnection.HTTP_OK)
                    ? conn.getInputStream()
                    : conn.getErrorStream();

            StringBuilder sb = new StringBuilder();
            try (BufferedReader br = new BufferedReader(new InputStreamReader(is, java.nio.charset.StandardCharsets.UTF_8))) {
                for (String line; (line = br.readLine()) != null; ) sb.append(line);
            }

            responseTime = Instant.now();
            Latency = responseTime.toEpochMilli() - promptTime.toEpochMilli();

            if (code != HttpURLConnection.HTTP_OK) {
                System.err.println("❌ mistral error (" + code + "): " + sb);
                return "{\"thinking\":\"error\",\"moves\":[]}";
            }

            // mistral /api/generate returns JSON like:
            // {"model":"...","created_at":"...","response":"...TEXT...","done":true,...}
            JsonObject top = JsonParser.parseString(sb.toString()).getAsJsonObject();

            if (!top.has("response")) {
                System.err.println("❌ Unexpected mistral payload: " + sb);
                return "{\"thinking\":\"invalid_response\",\"moves\":[]}";
            }

            String modelText = top.get("response").getAsString();

            // (Optional) log the raw text for debugging
            // System.out.println("mistral raw response:\n" + modelText);

            // Return the text **as-is** — your caller will parse to JSON later
            return modelText;

        } catch (Exception e) {
            e.printStackTrace();
            return "{\"thinking\":\"exception\",\"moves\":[]}";
        }
    }



    @Override
    public List<ParameterSpecification> getParameters()
    {
        List<ParameterSpecification> parameters = new ArrayList<>();

        parameters.add(new ParameterSpecification("PathFinding", PathFinding.class, new AStarPathFinding()));

        return parameters;
    }


    private UnitType stringToUnitType(String string) {
        string = string.toLowerCase();
        switch (string) {
            case "worker":
                return workerType;
            case "light":
                return lightType;
            case "heavy":
                return heavyType;
            case "ranged":
                return rangedType;
            case "base":
                return baseType;
            case "barracks":
                return barracksType;
            default:
                System.out.println("Unknown unit type: " + string);
                return workerType;
        }
    }

    private String unitActionToString(UnitAction action) {
        if (action == null) { return "idling"; }

        String description;
        switch (action.getType()) {
            case UnitAction.TYPE_MOVE:
                description = String.format("moving to (%d,%d)", action.getLocationX(), action.getLocationY());
                break;
            case UnitAction.TYPE_HARVEST:
                description = String.format("harvesting from (%d,%d)", action.getLocationX(), action.getLocationY());
                break;
            case UnitAction.TYPE_RETURN:
                description = String.format("returning resources to (%d,%d)", action.getLocationX(), action.getLocationY());
                break;
            case UnitAction.TYPE_PRODUCE:
                description = String.format("producing unit at (%d,%d)", action.getLocationX(), action.getLocationY());
                break;
            case UnitAction.TYPE_ATTACK_LOCATION:
                description = String.format("attacking location (%d,%d)", action.getLocationX(), action.getLocationY());
                break;
            case UnitAction.TYPE_NONE:
                description = "idling";
                break;
            default:
                description = "unknown action";
                break;
        }
        return description;
    }


    /**
     * Calculates the number of tokens for a given text using Gemini's countTokens API.
     *
     * @param modelName The model i am using to know exactly how many tokens C/s
     * @param text      The text (prompt or response) to calculate tokens for
     * @return          The total token count for the given text
     *
     * not need for this are need to look for some thing else right now i am commenting this
     *
     */

   /*
    public int calculateTokens(String modelName, String text) {
        try {
            URL url = new URL(ENDPOINT_URL + modelName + ":countTokens?key=" + API_KEY);
            HttpURLConnection conn = (HttpURLConnection) url.openConnection();
            conn.setRequestMethod("POST");
            conn.setRequestProperty("Content-Type", "application/json");
            conn.setDoOutput(true);

            // Build JSON request
            JsonObject body = new JsonObject();
            JsonArray contents = new JsonArray();

            JsonObject part = new JsonObject();
            part.addProperty("text", text);

            JsonArray parts = new JsonArray();
            parts.add(part);

            JsonObject content = new JsonObject();
            content.add("parts", parts);

            contents.add(content);
            body.add("contents", contents);

            // Send request
            try (OutputStream os = conn.getOutputStream()) {
                byte[] input = body.toString().getBytes("utf-8");
                os.write(input, 0, input.length);
            }

            // Read response
            int code = conn.getResponseCode();
            InputStream is = (code == HttpURLConnection.HTTP_OK) ? conn.getInputStream() : conn.getErrorStream();
            BufferedReader br = new BufferedReader(new InputStreamReader(is, "utf-8"));
            StringBuilder sb = new StringBuilder();
            String line;
            while ((line = br.readLine()) != null) sb.append(line.trim());

            if (code != HttpURLConnection.HTTP_OK) {
                System.err.println("❌ Token count error: " + sb);
                return 0;
            }
            JsonObject json = new JsonParser().parse(sb.toString()).getAsJsonObject();
            return json.get("totalTokens").getAsInt();

        } catch (Exception e) {
            e.printStackTrace();
            return 0;
        }
    } */



}
