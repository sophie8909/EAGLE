import unittest

from eagle.generation.agent_template import (
    JavaTemplatePaths, STRATEGY_START_MARKER, STRATEGY_END_MARKER, load_java_template,
)
from eagle.generation.java_agent_generator import validate_generated_java_source


class GeneratedRandomnessTests(unittest.TestCase):
    def source(self, statement):
        scaffold = load_java_template(JavaTemplatePaths())
        start = scaffold.index(STRATEGY_START_MARKER) + len(STRATEGY_START_MARKER)
        end = scaffold.index(STRATEGY_END_MARKER)
        region = "\nprivate void decide(AgentContext context) { " + statement + " }\n"
        return scaffold[:start] + region + scaffold[end:]

    def test_uncontrolled_entropy_and_wall_clock_are_rejected(self):
        for statement in (
            "double x = Math.random();", "double x = StrictMath.random();",
            "java.util.Random r = new java.util.Random();",
            "java.util.SplittableRandom r = new java.util.SplittableRandom(7);",
            "java.security.SecureRandom r = new java.security.SecureRandom();",
            "int x = java.util.concurrent.ThreadLocalRandom.current().nextInt();",
            "Object x = java.util.random.RandomGenerator.getDefault();",
            "Object x = java.util.UUID.randomUUID();",
            "java.util.Collections.shuffle(context.units);",
            "long x = System.currentTimeMillis();", "long x = System.nanoTime();",
            "Object x = new java.util.Date();", "Object x = java.util.Calendar.getInstance();",
        ):
            with self.subTest(statement=statement):
                result = validate_generated_java_source(self.source(statement), "CandidateAgent")
                self.assertFalse(result.ok)
                self.assertTrue(any(item["check"] == "strategy_contract" for item in result.failed_checks))

    def test_root_seeded_rng_and_comments_are_accepted(self):
        for statement in (
            'java.util.Random rng = rts.RandomSource.create("strategy.target"); int x = rng.nextInt(5);',
            '// Math.random(); new Random(); System.nanoTime();\nint x = context.gameState.getTime();',
        ):
            result = validate_generated_java_source(self.source(statement), "CandidateAgent")
            self.assertTrue(result.ok, result.error)


if __name__ == "__main__":
    unittest.main()
