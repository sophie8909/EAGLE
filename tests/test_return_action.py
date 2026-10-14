"""Real MicroRTS fixtures for the canonical, dedicated resource-return API."""
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from eagle.evaluation.compiler import compile_generated_agent
from eagle.generation.agent_template import JavaTemplatePaths, assemble_canonical_java_source, load_java_template
from eagle.generation.java_agent_generator import validate_generated_java_source

ROOT = Path(__file__).resolve().parents[1]
MICRORTS = ROOT / "third_party/microrts"
HARNESS = r'''
import ai.generated.CandidateAgent;
import rts.*;
import rts.units.*;

public class ReturnFixture {
    public static void main(String[] args) throws Exception {
        UnitTypeTable utt = new UnitTypeTable();
        PhysicalGameState pgs = new PhysicalGameState(8, 8);
        pgs.addPlayer(new Player(0, 0));
        pgs.addPlayer(new Player(1, 0));
        Unit worker = new Unit(5L, 0, utt.getUnitType("Worker"), 1, 1, 1);
        Unit base = new Unit(1L, 0, utt.getUnitType("Base"), args[0].equals("adjacent") ? 2 : 5, 1, 0);
        pgs.addUnit(worker);
        pgs.addUnit(base);
        pgs.addUnit(new Unit(20L, 1, utt.getUnitType("Base"), 7, 7, 0));
        GameState gs = new GameState(pgs, utt);
        CandidateAgent ai = new CandidateAgent(utt);
        PlayerAction pa = ai.getAction(0, gs);
        UnitAction action = pa.getAction(worker);
        int expected = args[0].equals("adjacent") ? UnitAction.TYPE_RETURN : UnitAction.TYPE_MOVE;
        if (action == null || action.getType() != expected || !gs.isUnitActionAllowed(worker, action)
                || !pa.integrityCheck()) throw new AssertionError("illegal return action: " + action);
        if (ai.getAbstractAction(worker) == null
                || !ai.getAbstractAction(worker).getClass().getSimpleName().equals("ReturnAction"))
            throw new AssertionError("return must use the dedicated abstraction");
        gs.issueSafe(pa);
        for (int i = 0; i < 20; i++) gs.cycle();
        if (expected == UnitAction.TYPE_RETURN
                && (worker.getResources() != 0 || gs.getPlayer(0).getResources() != 1))
            throw new AssertionError("return did not transfer resources");
        if (expected == UnitAction.TYPE_MOVE && worker.getX() == 1 && worker.getY() == 1)
            throw new AssertionError("distant return did not move");
        System.out.println("RETURN_FIXTURE_OK");
    }
}
'''


@unittest.skipUnless(shutil.which("javac") and shutil.which("java"), "Java runtime required")
class CanonicalReturnTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        scaffold = load_java_template(JavaTemplatePaths())
        region = """    private void decide(AgentContext context) {
        actions.clear();
        for (Unit unit : context.units) {
            if (unit.getType() == workerType && isIdleAlly(unit, context)) {
                if (!commandReturn(unit, ownBase(context), context)) commandIdle(unit);
            }
        }
    }
"""
        start = scaffold.index("// EAGLE_AGENT_STRATEGY_START") + len("// EAGLE_AGENT_STRATEGY_START")
        end = scaffold.index("// EAGLE_AGENT_STRATEGY_END")
        source = assemble_canonical_java_source(scaffold[:start] + "\n" + region + "\n" + scaffold[end:], scaffold)
        validation = validate_generated_java_source(source, "CandidateAgent", template_paths=JavaTemplatePaths())
        if not validation.ok:
            raise AssertionError(validation.error)
        path = cls.root / "CandidateAgent.java"
        path.write_text(source)
        fixture = cls.root / "ReturnFixture.java"
        fixture.write_text(HARNESS)
        cls.classes = cls.root / "classes"
        compiled = compile_generated_agent((path, fixture), microrts_dir=MICRORTS, output_dir=cls.classes)
        if not compiled.ok:
            raise AssertionError(compiled.stderr)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def fixture(self, kind):
        cp = os.pathsep.join((str(self.classes), str(MICRORTS / "bin"), str(MICRORTS / "lib/*")))
        result = subprocess.run(["java", "-cp", cp, "ReturnFixture", kind],
                                cwd=MICRORTS, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("RETURN_FIXTURE_OK", result.stdout)

    def test_adjacent_worker_issues_real_return_and_transfers_resource(self):
        self.fixture("adjacent")

    def test_distant_worker_issues_real_move_toward_base(self):
        self.fixture("distant")

    def test_canonical_return_never_uses_nullable_harvest_target(self):
        source = load_java_template(JavaTemplatePaths())
        return_region = source[source.index("    private boolean commandReturn("):
                               source.index("    private boolean commandTrain(")]
        self.assertNotIn("harvest(", return_region)
        self.assertIn("UnitAction.TYPE_RETURN", return_region)

    def test_checked_in_seed_scaffolds_offer_dedicated_return_and_integrate(self):
        from eagle.evaluation.microrts_runner import integrate_microrts_agent
        for index, seed in enumerate((ROOT / "eagle/java_seeds/CandidateAgent.java",
                                      ROOT / "eagle/java_seeds/worker_rush/CandidateAgent.java")):
            with self.subTest(seed=str(seed)):
                source = seed.read_text()
                self.assertIn("commandReturn(Unit worker, Unit base, AgentContext context)", source)
                validation = validate_generated_java_source(source, "CandidateAgent",
                                                             template_paths=JavaTemplatePaths(seed))
                self.assertTrue(validation.ok, validation.error)
                classes = self.root / ("seed_classes_" + str(index))
                compiled = compile_generated_agent(seed, microrts_dir=MICRORTS, output_dir=classes)
                self.assertTrue(compiled.ok, compiled.stderr)
                result = integrate_microrts_agent(microrts_dir=MICRORTS, classes_dir=classes,
                        agent_class="ai.generated.CandidateAgent",
                        integration_artifacts_dir=self.root / ("seed_integration_" + str(index)))
                self.assertTrue(result.ok, result.stderr or result.stdout)
                self.assertTrue(all(check.status == "passed" for check in result.checks))
