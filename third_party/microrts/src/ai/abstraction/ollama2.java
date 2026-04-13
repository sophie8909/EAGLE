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

/**
 * Second Ollama-based AI for LLM vs LLM games.
 * Uses OLLAMA_MODEL_P2 environment variable to configure a different model.
 *
 * Example usage:
 *   export OLLAMA_MODEL=llama3.1:8b      # For Player 0 (ollama.java)
 *   export OLLAMA_MODEL_P2=qwen3:4b      # For Player 1 (ollama2.java)
 */
public class ollama2 extends AbstractionLayerAI {

    static final String OLLAMA_HOST =
            System.getenv().getOrDefault("OLLAMA_HOST", "http://localhost:11434");

    // Use OLLAMA_MODEL_P2 for second player, falls back to different model
    static String MODEL =
            System.getenv().getOrDefault("OLLAMA_MODEL_P2", "qwen3:4b");

    static final String OLLAMA_FORMAT = "json";
    static final boolean OLLAMA_STREAM = false;
    static final Integer LLM_INTERVAL = 1;

    protected UnitTypeTable utt;
    UnitType resourceType, workerType, lightType, heavyType, rangedType, baseType, barracksType;

    Instant promptTime, responseTime;
    long Latency = 0;
    private boolean logsInitialized = false;
    String fileName01 = "";

    String PROMPT = """
You are an AI playing a real-time strategy game. You control ALLY units only.

CRITICAL RULES:
1. You can ONLY command units marked as "Ally" - NEVER command "Enemy" or "Neutral" units
2. Each move MUST be a JSON object with ALL four required fields
3. The unit_position MUST match an Ally unit's position exactly from the game state

ACTIONS (use exact format):
- move((x, y)) - Move to position
- harvest((resource_x, resource_y), (base_x, base_y)) - Worker gathers resources
- train(unit_type) - Base trains: worker | Barracks trains: light, heavy, ranged
- build((x, y), building_type) - Worker builds: base, barracks
- attack((enemy_x, enemy_y)) - Attack enemy at position

REQUIRED JSON FORMAT:
{
  "thinking": "Brief strategy",
  "moves": [
    {
      "raw_move": "(x, y): unit_type action((args))",
      "unit_position": [x, y],
      "unit_type": "worker",
      "action_type": "harvest"
    }
  ]
}

EVERY MOVE OBJECT MUST HAVE ALL 4 FIELDS:
- raw_move: string like "(2, 0): worker harvest((0, 0), (2, 1))"
- unit_position: [x, y] array matching YOUR Ally unit position
- unit_type: "worker", "base", "barracks", "light", "heavy", or "ranged"
- action_type: "move", "harvest", "train", "build", or "attack"

VALID MOVE EXAMPLES:
{"raw_move": "(1, 1): worker harvest((0, 0), (2, 1))", "unit_position": [1, 1], "unit_type": "worker", "action_type": "harvest"}
{"raw_move": "(2, 1): base train(worker)", "unit_position": [2, 1], "unit_type": "base", "action_type": "train"}
{"raw_move": "(1, 1): worker attack((5, 6))", "unit_position": [1, 1], "unit_type": "worker", "action_type": "attack"}
{"raw_move": "(1, 1): worker move((3, 3))", "unit_position": [1, 1], "unit_type": "worker", "action_type": "move"}
{"raw_move": "(1, 1): worker build((3, 3), barracks)", "unit_position": [1, 1], "unit_type": "worker", "action_type": "build"}

STRATEGY: Harvest resources, train workers, build barracks, train army, attack enemy base.
""";

    public ollama2(UnitTypeTable a_utt) {
        this(a_utt, new AStarPathFinding());
        System.out.println("[ollama2] Initialized with model: " + MODEL);
    }

    public ollama2(UnitTypeTable a_utt, PathFinding a_pf) {
        super(a_pf);
        reset(a_utt);
    }

    public void reset() {
        super.reset();
        TIME_BUDGET = -1;
        ITERATIONS_BUDGET = -1;
    }

    public void reset(UnitTypeTable a_utt) {
        utt = a_utt;
        resourceType = utt.getUnitType("Resource");
        workerType = utt.getUnitType("Worker");
        lightType = utt.getUnitType("Light");
        heavyType = utt.getUnitType("Heavy");
        rangedType = utt.getUnitType("Ranged");
        baseType = utt.getUnitType("Base");
        barracksType = utt.getUnitType("Barracks");
    }

    @Override
    public AI clone() {
        return new ollama2(utt, pf);
    }

    private void initLogsIfNeeded() {
        if (logsInitialized) return;
        String ts = new SimpleDateFormat("yyyy-MM-dd_HH-mm-ss").format(new Date());
        fileName01 = "Response" + ts + "_ollama2_" + MODEL + ".csv";
        try (FileWriter writer = new FileWriter(fileName01)) {
            writer.append("Thinking,Moves,Latency\n");
        } catch (IOException e) {
            e.printStackTrace();
        }
        logsInitialized = true;
    }

    @Override
    public PlayerAction getAction(int player, GameState gs) throws Exception {
        initLogsIfNeeded();
        System.out.println("[ollama2.getAction] Player " + player + " using model: " + MODEL);

        if (gs.getTime() % LLM_INTERVAL != 0) {
            return translateActions(player, gs);
        }

        PhysicalGameState pgs = gs.getPhysicalGameState();
        Player p = gs.getPlayer(player);

        ArrayList<String> features = new ArrayList<>();
        int maxActions = 0;

        for (Unit u : pgs.getUnits()) {
            if (u.getPlayer() == player) maxActions++;

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
            String team = (u.getPlayer() == player) ? "Ally" :
                    (u.getType() == resourceType ? "Neutral" : "Enemy");

            features.add(unitPos + " " + team + " " + unitType + " " + unitStats);
        }

        String mapPrompt = "Map size: " + pgs.getWidth() + "x" + pgs.getHeight();
        String turnPrompt = "Turn: " + gs.getTime() + "/" + 5000;
        String maxActionsPrompt = "Max actions: " + maxActions;
        String featuresPrompt = "Feature locations:\n" + String.join("\n", features);

        String finalPrompt = PROMPT + "\n\n" + mapPrompt + "\n" + turnPrompt + "\n" + maxActionsPrompt + "\n\n" + featuresPrompt + "\n";

        String response = prompt(finalPrompt);
        System.out.println("[ollama2] Response: " + response.substring(0, Math.min(100, response.length())) + "...");

        JsonObject jsonResponse = parseJsonStrictThenLenient(response);
        JsonArray moveElements = jsonResponse.getAsJsonArray("moves");

        if (moveElements == null || moveElements.size() == 0) {
            return translateActions(player, gs);
        }

        for (JsonElement moveElement : moveElements) {
            try {
                if (!moveElement.isJsonObject()) continue;
                JsonObject move = moveElement.getAsJsonObject();

                if (!move.has("unit_position") || !move.get("unit_position").isJsonArray()) continue;
                JsonArray unitPosition = move.getAsJsonArray("unit_position");
                if (unitPosition.size() < 2) continue;

                int unitX = unitPosition.get(0).getAsInt();
                int unitY = unitPosition.get(1).getAsInt();
                Unit unit = pgs.getUnitAt(unitX, unitY);

                if (unit == null || unit.getPlayer() != player) continue;
                if (!move.has("action_type") || !move.has("raw_move")) continue;

                String actionType = move.get("action_type").getAsString();
                String rawMove = move.get("raw_move").getAsString();

                switch (actionType) {
                    case "move": {
                        if (unit.getType() == baseType || unit.getType() == barracksType) break;
                        Pattern pattern = Pattern.compile("\\(\\s*\\d+,\\s*\\d+\\):.*?move\\(\\(\\s*(\\d+),\\s*(\\d+)\\s*\\)\\)");
                        Matcher matcher = pattern.matcher(rawMove);
                        if (matcher.find()) {
                            move(unit, Integer.parseInt(matcher.group(1)), Integer.parseInt(matcher.group(2)));
                        }
                        break;
                    }
                    case "harvest": {
                        if (unit.getType() != workerType) break;
                        Pattern pattern = Pattern.compile("\\(\\s*\\d+,\\s*\\d+\\):.*?harvest\\(\\((\\d+),\\s*(\\d+)\\),\\s*\\((\\d+),\\s*(\\d+)\\)\\)");
                        Matcher matcher = pattern.matcher(rawMove);
                        if (matcher.find()) {
                            Unit resourceUnit = pgs.getUnitAt(Integer.parseInt(matcher.group(1)), Integer.parseInt(matcher.group(2)));
                            Unit baseUnit = pgs.getUnitAt(Integer.parseInt(matcher.group(3)), Integer.parseInt(matcher.group(4)));
                            if (resourceUnit != null && baseUnit != null) harvest(unit, resourceUnit, baseUnit);
                        }
                        break;
                    }
                    case "train": {
                        if (unit.getType() != baseType && unit.getType() != barracksType) break;
                        Pattern pattern = Pattern.compile("\\(\\s*\\d+,\\s*\\d+\\):.*?train\\(\\s*['\"]?(\\w+)['\"]?\\s*\\)");
                        Matcher matcher = pattern.matcher(rawMove);
                        if (matcher.find()) {
                            train(unit, stringToUnitType(matcher.group(1)));
                        }
                        break;
                    }
                    case "build": {
                        if (unit.getType() != workerType) break;
                        Pattern pattern = Pattern.compile("\\(\\s*\\d+,\\s*\\d+\\):.*?build\\(\\s*\\(\\s*(\\d+),\\s*(\\d+)\\s*\\),\\s*['\"]?(\\w+)['\"]?\\s*\\)");
                        Matcher matcher = pattern.matcher(rawMove);
                        if (matcher.find()) {
                            build(unit, stringToUnitType(matcher.group(3)), Integer.parseInt(matcher.group(1)), Integer.parseInt(matcher.group(2)));
                        }
                        break;
                    }
                    case "attack": {
                        Pattern pattern = Pattern.compile("\\(\\s*\\d+,\\s*\\d+\\):.*?attack\\(\\s*\\(\\s*(\\d+),\\s*(\\d+)\\s*\\)\\s*\\)");
                        Matcher matcher = pattern.matcher(rawMove);
                        if (matcher.find()) {
                            Unit enemyUnit = pgs.getUnitAt(Integer.parseInt(matcher.group(1)), Integer.parseInt(matcher.group(2)));
                            if (enemyUnit != null) attack(unit, enemyUnit);
                        }
                        break;
                    }
                    case "idle": {
                        idle(unit);
                        break;
                    }
                }
            } catch (Exception ex) {
                System.out.println("[ollama2] Error applying move: " + ex.getMessage());
            }
        }

        // Auto-attack if adjacent to enemy
        for (Unit u1 : pgs.getUnits()) {
            if (u1.getPlayer() != player || !u1.getType().canAttack) continue;
            for (Unit u2 : pgs.getUnits()) {
                if (u2.getPlayer() == player) continue;
                int d = Math.abs(u2.getX() - u1.getX()) + Math.abs(u2.getY() - u1.getY());
                if (d == 1 && getAbstractAction(u1) == null) {
                    attack(u1, u2);
                    break;
                }
            }
        }

        return translateActions(player, gs);
    }

    public String prompt(String finalPrompt) {
        try {
            JsonObject body = new JsonObject();
            body.addProperty("model", MODEL);
            body.addProperty("prompt", "/no_think " + finalPrompt);
            body.addProperty("stream", OLLAMA_STREAM);
            body.addProperty("format", OLLAMA_FORMAT);

            URL url = new URL(OLLAMA_HOST + "/api/generate");
            HttpURLConnection conn = (HttpURLConnection) url.openConnection();
            conn.setRequestMethod("POST");
            conn.setRequestProperty("Content-Type", "application/json");
            conn.setDoOutput(true);

            promptTime = Instant.now();

            try (OutputStream os = conn.getOutputStream()) {
                os.write(body.toString().getBytes(java.nio.charset.StandardCharsets.UTF_8));
            }

            int code = conn.getResponseCode();
            InputStream is = (code == HttpURLConnection.HTTP_OK) ? conn.getInputStream() : conn.getErrorStream();

            StringBuilder sb = new StringBuilder();
            try (BufferedReader br = new BufferedReader(new InputStreamReader(is, java.nio.charset.StandardCharsets.UTF_8))) {
                for (String line; (line = br.readLine()) != null; ) sb.append(line);
            }

            responseTime = Instant.now();
            Latency = responseTime.toEpochMilli() - promptTime.toEpochMilli();

            if (code != HttpURLConnection.HTTP_OK) {
                System.err.println("[ollama2] Error: " + sb);
                return "{\"thinking\":\"error\",\"moves\":[]}";
            }

            JsonObject top = JsonParser.parseString(sb.toString()).getAsJsonObject();
            String modelText = "";
            if (top.has("response") && !top.get("response").getAsString().isEmpty()) {
                modelText = top.get("response").getAsString();
            } else if (top.has("thinking") && !top.get("thinking").isJsonNull()) {
                modelText = top.get("thinking").getAsString();
            } else {
                return "{\"thinking\":\"invalid_response\",\"moves\":[]}";
            }

            return modelText;
        } catch (Exception e) {
            e.printStackTrace();
            return "{\"thinking\":\"exception\",\"moves\":[]}";
        }
    }

    static String sanitizeModelJson(String s) {
        if (s == null) return "";
        s = s.trim();
        if (s.startsWith("```")) {
            int first = s.indexOf('\n');
            if (first >= 0) s = s.substring(first + 1);
            int close = s.lastIndexOf("```");
            if (close > 0) s = s.substring(0, close);
            s = s.trim();
        }
        int obj = s.indexOf('{');
        int arr = s.indexOf('[');
        int start = (obj == -1) ? arr : (arr == -1 ? obj : Math.min(obj, arr));
        if (start > 0) s = s.substring(start).trim();
        return s;
    }

    static JsonObject parseJsonStrictThenLenient(String raw) {
        String cleaned = sanitizeModelJson(raw);
        try {
            return JsonParser.parseString(cleaned).getAsJsonObject();
        } catch (JsonSyntaxException e) {
            try {
                com.google.gson.stream.JsonReader r = new com.google.gson.stream.JsonReader(new java.io.StringReader(cleaned));
                r.setLenient(true);
                return JsonParser.parseReader(r).getAsJsonObject();
            } catch (Exception e2) {
                throw e;
            }
        }
    }

    @Override
    public List<ParameterSpecification> getParameters() {
        List<ParameterSpecification> parameters = new ArrayList<>();
        parameters.add(new ParameterSpecification("PathFinding", PathFinding.class, new AStarPathFinding()));
        return parameters;
    }

    private UnitType stringToUnitType(String string) {
        string = string.toLowerCase();
        switch (string) {
            case "worker": return workerType;
            case "light": return lightType;
            case "heavy": return heavyType;
            case "ranged": return rangedType;
            case "base": return baseType;
            case "barracks": return barracksType;
            default: return workerType;
        }
    }

    private String unitActionToString(UnitAction action) {
        if (action == null) return "idling";
        switch (action.getType()) {
            case UnitAction.TYPE_MOVE: return String.format("moving to (%d,%d)", action.getLocationX(), action.getLocationY());
            case UnitAction.TYPE_HARVEST: return String.format("harvesting from (%d,%d)", action.getLocationX(), action.getLocationY());
            case UnitAction.TYPE_RETURN: return String.format("returning resources to (%d,%d)", action.getLocationX(), action.getLocationY());
            case UnitAction.TYPE_PRODUCE: return String.format("producing unit at (%d,%d)", action.getLocationX(), action.getLocationY());
            case UnitAction.TYPE_ATTACK_LOCATION: return String.format("attacking location (%d,%d)", action.getLocationX(), action.getLocationY());
            case UnitAction.TYPE_NONE: return "idling";
            default: return "unknown action";
        }
    }
}
