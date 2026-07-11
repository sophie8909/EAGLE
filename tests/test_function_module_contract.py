import tempfile
import unittest
from pathlib import Path

from eagle.candidate import DEFAULT_MODULE_BODIES, MODULE_NAMES
from evaluation.compiler import compile_generated_agent
from generation.agent_template import render_blank_strategy_agent, render_function_agent
from generation.java_module_validator import validate_function_module


class FunctionModuleContractTests(unittest.TestCase):
    def test_valid_complete_method(self):
        validate_function_module(DEFAULT_MODULE_BODIES["controller"], "controller")

    def test_statement_body_rejected(self):
        with self.assertRaises(ValueError):
            validate_function_module("return new Decision();", "controller")

    def test_wrong_name_rejected(self):
        with self.assertRaisesRegex(ValueError, "name"):
            validate_function_module("private Decision wrong(AgentContext context) { return new Decision(); }", "controller")

    def test_wrong_return_rejected(self):
        with self.assertRaisesRegex(ValueError, "return type"):
            validate_function_module("private Unit decide(AgentContext context) { return null; }", "controller")

    def test_wrong_parameters_rejected(self):
        with self.assertRaisesRegex(ValueError, "parameter types"):
            validate_function_module("private Decision decide(Unit context) { return new Decision(); }", "controller")

    def test_two_methods_and_helper_rejected(self):
        for suffix in (
            " private Decision decide(AgentContext context) { return new Decision(); }",
            " private int helper() { return 1; }",
        ):
            with self.assertRaisesRegex(ValueError, "exactly one"):
                validate_function_module(DEFAULT_MODULE_BODIES["controller"] + suffix, "controller")

    def test_fields_and_imports_rejected(self):
        for source in ("private int value;", "import java.util.List;\n" + DEFAULT_MODULE_BODIES["controller"]):
            with self.assertRaises(ValueError):
                validate_function_module(source, "controller")

    def test_assembled_methods_occur_once(self):
        source = render_function_agent("GeneratedAgent_test", DEFAULT_MODULE_BODIES)
        signatures = (
            "private Decision decide(", "private List<ActionProposal> economy(",
            "private List<ActionProposal> combat(", "private List<ActionProposal> expansion(",
            "private Unit selectTarget(", "private PathChoice findPath(",
        )
        for signature in signatures:
            self.assertEqual(source.count(signature), 1)

    def test_base_candidate_compiles(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temp:
            source_path = Path(temp) / "GeneratedAgent_test.java"
            source_path.write_text(render_blank_strategy_agent("GeneratedAgent_test"), encoding="utf-8")
            result = compile_generated_agent(source_path, microrts_dir=Path("third_party/microrts"), output_dir=Path(temp) / "classes")
            self.assertTrue(result.ok, result.stderr)


if __name__ == "__main__":
    unittest.main()
