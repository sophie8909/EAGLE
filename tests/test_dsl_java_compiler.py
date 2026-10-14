"""Golden and real MicroRTS checks for deterministic Strategy DSL Java compilation."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import shutil
import tempfile
import unittest
from pathlib import Path

from eagle.generation.agent_template import JavaTemplatePaths, load_java_template
from eagle.generation.dsl_java_compiler import compile_strategy_dsl
from eagle.generation.java_agent_generator import validate_generated_java_source
from eagle.evaluation.compiler import compile_generated_agent
from eagle.evaluation.microrts_runner import integrate_microrts_agent

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "dsl_compiler"


class DslJavaCompilerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.scaffold = load_java_template(JavaTemplatePaths())

    def test_golden_policies_are_stable_and_valid(self):
        expected = json.loads((FIXTURES / "golden_hashes.json").read_text(encoding="utf-8"))
        for name in ("empty", "worker_rush", "full"):
            with self.subTest(name=name):
                policy = (FIXTURES / f"{name}_policy.json").read_text(encoding="utf-8")
                compiled = compile_strategy_dsl(policy, scaffold=self.scaffold)
                again = compile_strategy_dsl(json.loads(policy), scaffold=self.scaffold)
                self.assertEqual(compiled, again)
                self.assertEqual(
                    (compiled.policy_sha256, compiled.scaffold_sha256, compiled.source_sha256),
                    tuple(expected[name]),
                )
                self.assertEqual(compiled.compiler_version, "eagle-dsl-java-v1")
                self.assertEqual(compiled.complete_source, (FIXTURES / f"{name}_CandidateAgent.java").read_text(encoding="utf-8"))
                self.assertEqual(
                    hashlib.sha256(compiled.complete_source.encode("utf-8")).hexdigest(),
                    compiled.source_sha256,
                )
                self.assertFalse(compiled.diagnostics)
                validation = validate_generated_java_source(compiled.complete_source, "CandidateAgent")
                self.assertTrue(validation.ok, validation.failed_checks)

    def test_rejects_invalid_policy_and_scaffold(self):
        with self.assertRaisesRegex(ValueError, "expected fields"):
            compile_strategy_dsl({"version": "eagle-strategy-dsl-v1", "rules": [{}]}, scaffold=self.scaffold)
        with self.assertRaisesRegex(ValueError, "unsupported compiler_version"):
            compile_strategy_dsl({"version": "eagle-strategy-dsl-v1", "rules": []}, scaffold=self.scaffold, compiler_version="future")
        with self.assertRaisesRegex(ValueError, "marker"):
            compile_strategy_dsl({"version": "eagle-strategy-dsl-v1", "rules": []}, scaffold="class X {}")

    def test_emitted_source_has_static_policy_without_json_interpreter(self):
        policy = (FIXTURES / "full_policy.json").read_text(encoding="utf-8")
        compiled = compile_strategy_dsl(policy, scaffold=self.scaffold)
        region = compiled.strategy_region
        self.assertIn("actors.sort((a, b) -> Long.compare(a.getID(), b.getID()))", region)
        self.assertIn("context.reservations.consistentWith", region)
        self.assertIn("Math.floorMod(dslHash(context, actor)", region)
        self.assertIn("commandReturn(actor, plan.target, context, plan.action)", region)
        self.assertIn("commandPlannedAction(actor, plan.action, context)", region)
        self.assertNotIn("JsonObject", region)
        self.assertNotIn("JSON", region)

    @unittest.skipUnless(shutil.which("javac"), "javac required")
    def test_real_java_compile_and_seven_check_integration(self):
        policy = (FIXTURES / "full_policy.json").read_text(encoding="utf-8")
        compiled = compile_strategy_dsl(policy, scaffold=self.scaffold)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            source = output / "CandidateAgent.java"
            source.write_text(compiled.complete_source, encoding="utf-8")
            classes = output / "classes"
            javac = compile_generated_agent(
                source, microrts_dir=ROOT / "third_party" / "microrts", output_dir=classes,
            )
            self.assertTrue(javac.ok, javac.stderr)
            result = integrate_microrts_agent(
                microrts_dir=ROOT / "third_party" / "microrts",
                classes_dir=classes,
                agent_class="ai.generated.CandidateAgent",
                integration_artifacts_dir=output / "integration",
            )
            self.assertTrue(result.ok, result.stderr or result.stdout)
            self.assertEqual(len(result.checks), 7)
            harness = output / "DslBehaviorProbe.java"
            harness.write_text("""
import ai.generated.CandidateAgent;
import rts.GameState;
import rts.PhysicalGameState;
import rts.PlayerAction;
import rts.UnitAction;
import rts.units.Unit;
import rts.units.UnitTypeTable;
public final class DslBehaviorProbe {
    public static void main(String[] args) throws Exception {
        UnitTypeTable utt = new UnitTypeTable();
        GameState gs = new GameState(
            PhysicalGameState.load("maps/8x8/basesWorkers8x8.xml", utt), utt);
        PlayerAction action = new CandidateAgent(utt).getAction(0, gs);
        Unit base = gs.getUnit(6);
        Unit worker = gs.getUnit(8);
        UnitAction train = action.getAction(base);
        UnitAction harvestStep = action.getAction(worker);
        if (train == null || train.getType() != UnitAction.TYPE_PRODUCE
                || train.getDirection() != UnitAction.DIRECTION_UP)
            throw new AssertionError("Base did not use the first free adjacent cell");
        if (harvestStep == null || harvestStep.getType() != UnitAction.TYPE_MOVE)
            throw new AssertionError("Worker did not move toward reachable Resource");
        if (!action.integrityCheck()) throw new AssertionError("invalid PlayerAction");
        PhysicalGameState adjacentMap = PhysicalGameState.load(
                "maps/8x8/basesWorkers8x8.xml", utt);
        GameState adjacentState = new GameState(adjacentMap, utt);
        Unit adjacentWorker = adjacentState.getUnit(8);
        adjacentWorker.setResources(1);
        PlayerAction adjacentAction = new CandidateAgent(utt).getAction(0, adjacentState);
        if (adjacentAction.getAction(adjacentWorker).getType() != UnitAction.TYPE_RETURN
                || adjacentAction.getAction(adjacentWorker).getDirection()
                    != UnitAction.DIRECTION_RIGHT)
            throw new AssertionError("adjacent return failed");
        PhysicalGameState distantMap = PhysicalGameState.load(
                "maps/8x8/basesWorkers8x8.xml", utt);
        GameState distantState = new GameState(distantMap, utt);
        Unit distantWorker = distantState.getUnit(8);
        distantWorker.setResources(1);
        distantWorker.setX(0);
        distantWorker.setY(2);
        PlayerAction distantAction = new CandidateAgent(utt).getAction(0, distantState);
        if (distantAction.getAction(distantWorker).getType() != UnitAction.TYPE_MOVE)
            throw new AssertionError("distant return did not path toward Base");

        PhysicalGameState absentMap = PhysicalGameState.load(
                "maps/8x8/basesWorkers8x8.xml", utt);
        for (Unit candidate : new java.util.ArrayList<Unit>(absentMap.getUnits()))
            if (candidate.getType() == utt.getUnitType("Resource")) absentMap.removeUnit(candidate);
        GameState absentState = new GameState(absentMap, utt);
        absentState.getPlayer(0).setResources(0);
        java.lang.reflect.Field fallthroughTime = GameState.class.getDeclaredField("time");
        fallthroughTime.setAccessible(true);
        fallthroughTime.setInt(absentState, 5);
        Unit absentWorker = absentState.getUnit(8);
        PlayerAction absentAction = new CandidateAgent(utt).getAction(0, absentState);
        if (absentAction.getAction(absentWorker).getType() != UnitAction.TYPE_MOVE)
            throw new AssertionError("absent harvest target did not fall through to engage");

        PhysicalGameState resourceMap = new PhysicalGameState(5, 5);
        resourceMap.addPlayer(new rts.Player(0, 1));
        resourceMap.addPlayer(new rts.Player(1, 1));
        Unit resourceFirst = new Unit(10, 0, utt.getUnitType("Base"), 1, 2, 0);
        Unit resourceSecond = new Unit(11, 0, utt.getUnitType("Base"), 3, 2, 0);
        resourceMap.addUnit(resourceSecond);
        resourceMap.addUnit(resourceFirst);
        resourceMap.addUnit(new Unit(12, 1, utt.getUnitType("Base"), 4, 4, 0));
        PlayerAction resourceAction = new CandidateAgent(utt).getAction(
                0, new GameState(resourceMap, utt));
        if (resourceAction.getAction(resourceFirst).getType() != UnitAction.TYPE_PRODUCE
                || resourceAction.getAction(resourceSecond).getType() != UnitAction.TYPE_NONE)
            throw new AssertionError("resource reservation or ascending ID order failed");

        PhysicalGameState cellMap = new PhysicalGameState(5, 5);
        for (int y = 0; y < 5; y++)
            for (int x = 0; x < 5; x++)
                cellMap.setTerrain(x, y, PhysicalGameState.TERRAIN_WALL);
        for (int[] free : new int[][]{{1, 2}, {2, 2}, {3, 2}, {4, 4}})
            cellMap.setTerrain(free[0], free[1], PhysicalGameState.TERRAIN_NONE);
        cellMap.addPlayer(new rts.Player(0, 5));
        cellMap.addPlayer(new rts.Player(1, 5));
        Unit cellFirst = new Unit(20, 0, utt.getUnitType("Base"), 1, 2, 0);
        Unit cellSecond = new Unit(21, 0, utt.getUnitType("Base"), 3, 2, 0);
        cellMap.addUnit(cellSecond);
        cellMap.addUnit(cellFirst);
        cellMap.addUnit(new Unit(22, 1, utt.getUnitType("Base"), 4, 4, 0));
        PlayerAction cellAction = new CandidateAgent(utt).getAction(0, new GameState(cellMap, utt));
        if (cellAction.getAction(cellFirst).getType() != UnitAction.TYPE_PRODUCE
                || cellAction.getAction(cellFirst).getDirection() != UnitAction.DIRECTION_RIGHT
                || cellAction.getAction(cellSecond).getType() != UnitAction.TYPE_NONE)
            throw new AssertionError("destination-cell reservation failed");
        Class<?> contextClass = null;
        for (Class<?> nested : CandidateAgent.class.getDeclaredClasses())
            if (nested.getSimpleName().equals("AgentContext")) contextClass = nested;
        if (contextClass == null) throw new AssertionError("missing context");
        java.lang.reflect.Constructor<?> contextConstructor = contextClass.getDeclaredConstructor(
                int.class, GameState.class, java.util.List.class);
        contextConstructor.setAccessible(true);
        Object context = contextConstructor.newInstance(0, gs, gs.getUnits());
        java.lang.reflect.Method select = CandidateAgent.class.getDeclaredMethod(
                "dslSelectEntity", contextClass, Unit.class,
                int.class, int.class, rts.units.UnitType[].class, int.class);
        select.setAccessible(true);
        java.lang.reflect.Field targetField = null;
        long[] expected = {7, 9, 9, 7, 7, 9};
        java.lang.reflect.Field timeField = GameState.class.getDeclaredField("time");
        timeField.setAccessible(true);
        timeField.setInt(gs, 1);
        for (int selector = 0; selector < 6; selector++) {
            Object plan = select.invoke(new CandidateAgent(utt), context, worker, 4, 1,
                    new rts.units.UnitType[]{utt.getUnitType("Base"), utt.getUnitType("Worker")},
                    selector);
            if (plan == null) throw new AssertionError("selector filtered all legal targets: " + selector);
            if (targetField == null) {
                targetField = plan.getClass().getDeclaredField("target");
                targetField.setAccessible(true);
            }
            Unit chosen = (Unit) targetField.get(plan);
            if (chosen.getID() != expected[selector])
                throw new AssertionError("selector " + selector + " chose " + chosen.getID());
        }
        java.lang.reflect.Field actorIdField = Unit.class.getDeclaredField("ID");
        actorIdField.setAccessible(true);
        actorIdField.setLong(worker, Long.MAX_VALUE);
        timeField.setInt(gs, Integer.MAX_VALUE);
        java.lang.reflect.Method hashMethod = CandidateAgent.class.getDeclaredMethod(
                "dslHash", contextClass, Unit.class);
        hashMethod.setAccessible(true);
        long exactHash = (Long) hashMethod.invoke(new CandidateAgent(utt), context, worker);
        if (exactHash != -9223371970282782764L)
            throw new AssertionError("hash did not use normative long overflow arithmetic: " + exactHash);
        System.out.println("DSL_BEHAVIOR_OK");
    }
}
""", encoding="utf-8")
            microrts = ROOT / "third_party" / "microrts"
            classpath = os.pathsep.join((str(classes), str(microrts / "bin"), str(microrts / "lib" / "*")))
            build = subprocess.run(
                ["javac", "-cp", classpath, "-d", str(classes), str(harness)],
                cwd=microrts, text=True, capture_output=True,
            )
            self.assertEqual(build.returncode, 0, build.stderr)
            behavior = subprocess.run(
                ["java", "-cp", classpath, "DslBehaviorProbe"],
                cwd=microrts, text=True, capture_output=True,
            )
            self.assertEqual(behavior.returncode, 0, behavior.stderr or behavior.stdout)
            self.assertIn("DSL_BEHAVIOR_OK", behavior.stdout)


    @unittest.skipUnless(shutil.which("javac"), "javac required")
    def test_empty_and_worker_rush_real_java_integration(self):
        for name in ("empty", "worker_rush"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                output = Path(directory)
                source = output / "CandidateAgent.java"
                source.write_text(
                    (FIXTURES / f"{name}_CandidateAgent.java").read_text(encoding="utf-8"),
                    encoding="utf-8",
                )
                classes = output / "classes"
                javac = compile_generated_agent(
                    source, microrts_dir=ROOT / "third_party" / "microrts", output_dir=classes,
                )
                self.assertTrue(javac.ok, javac.stderr)
                result = integrate_microrts_agent(
                    microrts_dir=ROOT / "third_party" / "microrts",
                    classes_dir=classes,
                    agent_class="ai.generated.CandidateAgent",
                    integration_artifacts_dir=output / "integration",
                )
                self.assertTrue(result.ok, result.stderr or result.stdout)
                self.assertEqual(len(result.checks), 7)
    @unittest.skipUnless(shutil.which("javac"), "javac required")
    def test_real_java_choose_hash_and_adjacent_move_fallthrough(self):
        base = {"kind": "entity", "owner": "friendly",
                "types": ["Base"], "selector": "nearest"}
        policy = {"version": "eagle-strategy-dsl-v1", "rules": [
            {"actor": "Worker", "when": {"compare": {"metric": "time", "op": "!=", "value": 1}},
             "action": {"type": "choose", "options": [
                 {"type": "return", "target": base},
                 {"type": "move", "target": {"kind": "cell", "selector": "hashed_free_adjacent"}},
                 {"type": "idle"}]}},
            {"actor": "Worker", "when": True, "action": {"type": "move", "target": base}},
            {"actor": "Worker", "when": True, "action": {"type": "move",
                "target": {"kind": "cell", "selector": "first_free_adjacent"}}},
        ]}
        compiled = compile_strategy_dsl(policy, scaffold=self.scaffold)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            source = output / "CandidateAgent.java"
            source.write_text(compiled.complete_source, encoding="utf-8")
            classes = output / "classes"
            microrts = ROOT / "third_party" / "microrts"
            javac = compile_generated_agent(source, microrts_dir=microrts, output_dir=classes)
            self.assertTrue(javac.ok, javac.stderr)
            harness = output / "DslChoiceProbe.java"
            harness.write_text("""
import ai.generated.CandidateAgent;
import java.lang.reflect.Field;
import rts.GameState;
import rts.PhysicalGameState;
import rts.PlayerAction;
import rts.UnitAction;
import rts.units.UnitTypeTable;
public final class DslChoiceProbe {
    static UnitAction at(int time) throws Exception {
        UnitTypeTable utt = new UnitTypeTable();
        GameState gs = new GameState(
            PhysicalGameState.load("maps/8x8/basesWorkers8x8.xml", utt), utt);
        Field field = GameState.class.getDeclaredField("time");
        field.setAccessible(true);
        field.setInt(gs, time);
        PlayerAction action = new CandidateAgent(utt).getAction(0, gs);
        return action.getAction(gs.getUnit(8));
    }
    public static void main(String[] args) throws Exception {
        UnitAction zero = at(0), one = at(1), three = at(3);
        if (zero.getType() != UnitAction.TYPE_MOVE
                || zero.getDirection() != UnitAction.DIRECTION_DOWN)
            throw new AssertionError("choose legality or hashed cell");
        if (one.getType() != UnitAction.TYPE_MOVE
                || one.getDirection() != UnitAction.DIRECTION_UP)
            throw new AssertionError("adjacent entity move fallback");
        if (three.getType() != UnitAction.TYPE_NONE)
            throw new AssertionError("hashed choose idle");
        System.out.println("DSL_CHOICE_OK");
    }
}
""", encoding="utf-8")
            classpath = os.pathsep.join(
                (str(classes), str(microrts / "bin"), str(microrts / "lib" / "*")))
            build = subprocess.run(
                ["javac", "-cp", classpath, "-d", str(classes), str(harness)],
                cwd=microrts, text=True, capture_output=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            behavior = subprocess.run(
                ["java", "-cp", classpath, "DslChoiceProbe"],
                cwd=microrts, text=True, capture_output=True)
            self.assertEqual(behavior.returncode, 0, behavior.stderr or behavior.stdout)
            self.assertIn("DSL_CHOICE_OK", behavior.stdout)
    def test_json_field_order_comparison_ops_and_metrics(self):
        from eagle.strategy_dsl import worker_rush_policy

        self.assertEqual(
            (FIXTURES / "worker_rush_policy.json").read_text(encoding="utf-8").strip(),
            worker_rush_policy(),
        )
        target = {"owner": "enemy", "types": ["Ranged"]}
        metrics = ("stockpile", "time", "actor_hp", "actor_resources",
                   "actor_id_rank", "count", "distance")
        for metric in metrics:
            for op in ("<", "<=", "==", "!=", ">=", ">"):
                with self.subTest(metric=metric, op=op):
                    comparison = {"metric": metric, "op": op, "value": 2}
                    if metric in ("count", "distance"):
                        comparison["entities"] = target
                    policy = {"version": "eagle-strategy-dsl-v1", "rules": [
                        {"actor": "Worker", "when": {"compare": comparison},
                         "action": {"type": "idle"}},
                    ]}
                    source = json.dumps(policy)
                    sorted_source = json.dumps(policy, sort_keys=True)
                    first = compile_strategy_dsl(source, scaffold=self.scaffold)
                    second = compile_strategy_dsl(sorted_source, scaffold=self.scaffold)
                    self.assertEqual(first.normalized_policy, second.normalized_policy)
                    self.assertEqual(first.complete_source, second.complete_source)
                    self.assertIn(f" {op} 2)", first.strategy_region)
    @unittest.skipUnless(shutil.which("javac"), "javac required")
    def test_real_java_infinity_busy_rank_boolean_and_first_legal_rule(self):
        ranged = {"owner": "enemy", "types": ["Ranged"]}
        policy = {"version": "eagle-strategy-dsl-v1", "rules": [
            {"actor": "Worker",
             "when": {"compare": {"metric": "actor_id_rank", "op": "==", "value": 1}},
             "action": {"type": "move", "target": {
                 "kind": "cell", "selector": "first_free_adjacent"}}},
            {"actor": "Worker",
             "when": {"all": [{"not": False},
                 {"any": [False, {"compare": {
                     "metric": "distance", "op": ">", "value": 1000000,
                     "entities": ranged}}]}]},
             "action": {"type": "idle"}},
            {"actor": "Worker", "when": True,
             "action": {"type": "move", "target": {
                 "kind": "cell", "selector": "first_free_adjacent"}}},
            {"actor": "Worker", "when": True,
             "action": {"type": "attack", "target": {
                 "kind": "entity", "owner": "enemy", "types": ["Worker"],
                 "selector": "nearest"}}},
        ]}
        compiled = compile_strategy_dsl(policy, scaffold=self.scaffold)
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            source = output / "CandidateAgent.java"
            source.write_text(compiled.complete_source, encoding="utf-8")
            classes = output / "classes"
            microrts = ROOT / "third_party" / "microrts"
            javac = compile_generated_agent(source, microrts_dir=microrts, output_dir=classes)
            self.assertTrue(javac.ok, javac.stderr)
            harness = output / "DslConditionsProbe.java"
            harness.write_text("""
import ai.generated.CandidateAgent;
import rts.*;
import rts.units.*;
public final class DslConditionsProbe {
    static PhysicalGameState map(UnitTypeTable utt) throws Exception {
        return PhysicalGameState.load("maps/8x8/basesWorkers8x8.xml", utt);
    }
    public static void main(String[] args) throws Exception {
        UnitTypeTable utt = new UnitTypeTable();
        GameState emptyDistance = new GameState(map(utt), utt);
        Unit worker = emptyDistance.getUnit(8);
        PlayerAction idle = new CandidateAgent(utt).getAction(0, emptyDistance);
        if (idle.getAction(worker).getType() != UnitAction.TYPE_NONE)
            throw new AssertionError("missing distance must be +Infinity; all/any/not");
        PhysicalGameState priorityMap = map(utt);
        priorityMap.addUnit(new Unit(10, 1, utt.getUnitType("Ranged"), 6, 0, 0));
        priorityMap.addUnit(new Unit(11, 1, utt.getUnitType("Worker"), 1, 2, 0));
        GameState priorityState = new GameState(priorityMap, utt);
        PlayerAction priority = new CandidateAgent(utt).getAction(0, priorityState);
        UnitAction chosen = priority.getAction(priorityState.getUnit(8));
        if (chosen.getType() != UnitAction.TYPE_MOVE
                || chosen.getDirection() != UnitAction.DIRECTION_UP)
            throw new AssertionError("first legal move did not stop later legal attack");
        PhysicalGameState busyMap = map(utt);
        Unit second = new Unit(12, 0, utt.getUnitType("Worker"), 3, 2, 0);
        busyMap.addUnit(second);
        GameState busyState = new GameState(busyMap, utt);
        PlayerAction busy = new PlayerAction();
        busy.addUnitAction(busyState.getUnit(8),
                new UnitAction(UnitAction.TYPE_NONE, 10));
        busyState.issueSafe(busy);
        if (busyState.getUnitAction(busyState.getUnit(8)) == null)
            throw new AssertionError("first worker was not busy");
        PlayerAction ranked = new CandidateAgent(utt).getAction(0, busyState);
        if (ranked.getAction(second).getType() != UnitAction.TYPE_MOVE)
            throw new AssertionError("busy worker was excluded from ID rank");
        System.out.println("DSL_CONDITIONS_OK");
    }
}
""", encoding="utf-8")
            classpath = os.pathsep.join(
                (str(classes), str(microrts / "bin"), str(microrts / "lib" / "*")))
            build = subprocess.run(
                ["javac", "-cp", classpath, "-d", str(classes), str(harness)],
                cwd=microrts, text=True, capture_output=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            behavior = subprocess.run(
                ["java", "-cp", classpath, "DslConditionsProbe"],
                cwd=microrts, text=True, capture_output=True)
            self.assertEqual(behavior.returncode, 0, behavior.stderr or behavior.stdout)
            self.assertIn("DSL_CONDITIONS_OK", behavior.stdout)
    @unittest.skipUnless(shutil.which("javac"), "javac required")
    def test_empty_policy_runtime_never_auto_defends(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            source = output / "CandidateAgent.java"
            source.write_text(
                (FIXTURES / "empty_CandidateAgent.java").read_text(encoding="utf-8"),
                encoding="utf-8")
            classes = output / "classes"
            microrts = ROOT / "third_party" / "microrts"
            javac = compile_generated_agent(source, microrts_dir=microrts, output_dir=classes)
            self.assertTrue(javac.ok, javac.stderr)
            harness = output / "DslEmptyProbe.java"
            harness.write_text("""
import ai.generated.CandidateAgent;
import rts.*;
import rts.units.*;
public final class DslEmptyProbe {
    public static void main(String[] args) throws Exception {
        UnitTypeTable utt = new UnitTypeTable();
        PhysicalGameState map = PhysicalGameState.load(
            "maps/8x8/basesWorkers8x8.xml", utt);
        map.addUnit(new Unit(10, 1, utt.getUnitType("Worker"), 1, 2, 0));
        GameState gs = new GameState(map, utt);
        PlayerAction action = new CandidateAgent(utt).getAction(0, gs);
        if (action.getAction(gs.getUnit(8)).getType() != UnitAction.TYPE_NONE)
            throw new AssertionError("empty DSL auto-attacked adjacent enemy");
        System.out.println("DSL_EMPTY_OK");
    }
}
""", encoding="utf-8")
            classpath = os.pathsep.join(
                (str(classes), str(microrts / "bin"), str(microrts / "lib" / "*")))
            build = subprocess.run(
                ["javac", "-cp", classpath, "-d", str(classes), str(harness)],
                cwd=microrts, text=True, capture_output=True)
            self.assertEqual(build.returncode, 0, build.stderr)
            behavior = subprocess.run(
                ["java", "-cp", classpath, "DslEmptyProbe"],
                cwd=microrts, text=True, capture_output=True)
            self.assertEqual(behavior.returncode, 0, behavior.stderr or behavior.stdout)
            self.assertIn("DSL_EMPTY_OK", behavior.stdout)
if __name__ == "__main__":
    unittest.main()
