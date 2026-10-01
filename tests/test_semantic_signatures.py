from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from eagle.analysis.loader import RunData
from eagle.analysis.semantics import analyze_semantics
from evaluation.semantic_signature import (
    ProbeMap,
    SemanticLibrary,
    ensure_semantic_dataset,
    evaluate_semantic_signature,
)


ROOT = Path(__file__).resolve().parents[1]


class SemanticSignatureTests(unittest.TestCase):
    def test_library_uses_exact_dataset_scoped_equivalence(self) -> None:
        library = SemanticLibrary()
        first = {
            "status": "complete", "dataset_id": "d1", "probe_ids": ["p1"],
            "action_hashes": ["a1"], "global_hash": "same",
        }
        other_dataset = {
            "status": "complete", "dataset_id": "d2", "probe_ids": ["p1"],
            "action_hashes": ["a1"], "global_hash": "same",
        }
        same_hash_different_vector = {
            "status": "complete", "dataset_id": "d1", "probe_ids": ["p1"],
            "action_hashes": ["a2"], "global_hash": "same",
        }
        self.assertTrue(library.add("a", first))
        self.assertTrue(library.add("b", first))
        self.assertTrue(library.add("c", other_dataset))
        self.assertTrue(library.add("d", same_hash_different_vector))
        self.assertFalse(library.add("missing", {"status": "unavailable"}))
        self.assertEqual(library.find_equivalent(first), ("a", "b"))
        self.assertEqual(library.unique_count, 3)
        self.assertEqual(library.duplicate_count, 1)

    @unittest.skipUnless(shutil.which("java") and shutil.which("javac"), "Java is required")
    def test_real_microrts_probe_dataset_and_cache_are_deterministic(self) -> None:
        microrts = ROOT / "third_party" / "microrts"
        if not microrts.is_dir():
            self.skipTest("Pinned MicroRTS checkout is unavailable")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            classes = root / "candidate_classes"
            source = ROOT / "eagle" / "java_seeds" / "worker_rush" / "CandidateAgent.java"
            subprocess.run(
                [
                    "javac", "-cp", f"{microrts / 'bin'}:{microrts / 'lib' / '*'}",
                    "-d", str(classes), str(source),
                ],
                check=True, capture_output=True, text=True,
            )
            dataset = ensure_semantic_dataset(
                microrts_dir=microrts,
                maps=(
                    ProbeMap("m1", "maps/8x8/basesWorkers8x8.xml", 1500),
                    ProbeMap("m2", "maps/16x16/basesWorkers16x16.xml", 3000),
                    ProbeMap("m3", "maps/24x24/basesWorkers24x24.xml", 4000),
                ),
                output_root=root / "datasets",
                reference_agents=("ai.abstraction.WorkerRush", "ai.abstraction.HeavyRush"),
                player_side=0,
                phase_fractions=(0.1, 0.5, 0.9),
                timeout_seconds=30,
            )
            regenerated = ensure_semantic_dataset(
                microrts_dir=microrts,
                maps=(
                    ProbeMap("m1", "maps/8x8/basesWorkers8x8.xml", 1500),
                    ProbeMap("m2", "maps/16x16/basesWorkers16x16.xml", 3000),
                    ProbeMap("m3", "maps/24x24/basesWorkers24x24.xml", 4000),
                ),
                output_root=root / "regenerated_datasets",
                reference_agents=("ai.abstraction.WorkerRush", "ai.abstraction.HeavyRush"),
                player_side=0,
                phase_fractions=(0.1, 0.5, 0.9),
                timeout_seconds=30,
            )
            self.assertEqual(len(dataset.probes), 9)
            self.assertEqual(len({item["probe_id"] for item in dataset.probes}), 9)
            self.assertEqual(dataset.dataset_id, regenerated.dataset_id)
            self.assertEqual(dataset.dataset_sha256, regenerated.dataset_sha256)
            arguments = dict(
                candidate_id="seed",
                agent_class="ai.generated.CandidateAgent",
                candidate_classes_dir=classes,
                phenotype_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                dataset=dataset,
                microrts_dir=microrts,
                cache_root=root / "run" / "archives" / "semantic_signature_cache",
                timeout_seconds=30,
            )
            first = evaluate_semantic_signature(**arguments)
            second = evaluate_semantic_signature(**arguments)
            self.assertEqual(first.status, "complete")
            self.assertEqual(len(first.summary["action_hashes"]), 9)
            self.assertFalse(first.wrapper["cache_hit"])
            self.assertTrue(second.wrapper["cache_hit"])
            self.assertEqual(first.summary["global_hash"], second.summary["global_hash"])

    def test_offline_analysis_reads_wrappers_without_re_evaluation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            cache_dir = run / "archives" / "semantic_signature_cache"
            cache_dir.mkdir(parents=True)
            generations = [{
                "generation": 0,
                "population": [
                    {"candidate_id": "a"}, {"candidate_id": "b"}, {"candidate_id": "c"},
                ],
            }]
            for candidate_id in ("a", "b", "c"):
                candidate_dir = run / "candidates" / candidate_id
                (candidate_dir / "evaluation").mkdir(parents=True)
                (candidate_dir / "candidate.json").write_text(json.dumps({
                    "candidate_id": candidate_id,
                    "generation": 0,
                    "status": "evaluated",
                }), encoding="utf-8")
                cache_key = f"cache-{candidate_id}"
                cache_path = cache_dir / f"{cache_key}.json"
                cache_path.write_text(json.dumps({
                    "probe_results": [
                        {
                            "probe_id": "m:early:p0", "map_id": "m", "phase": "early",
                            "player_side": 0, "canonical_actions": [{"type": 1}],
                            "action_hash": "same-action",
                        }
                    ],
                    "global_signature_hash": "same-global",
                }), encoding="utf-8")
                (candidate_dir / "evaluation" / "semantic_signature.json").write_text(
                    json.dumps({
                        "status": "complete", "dataset_schema_version": "v1",
                        "dataset_id": "dataset" if candidate_id != "c" else "other-dataset",
                        "dataset_sha256": "dataset-sha" if candidate_id != "c" else "other-sha",
                        "normalization_version": "normalization", "cache_key": cache_key,
                        "cache_ref": str(cache_path.relative_to(run)),
                        "global_signature_hash": "same-global",
                    }),
                    encoding="utf-8",
                )
            data = RunData(
                run_dir=run, manifest={}, resolved_config={}, generation_metrics=[],
                generations=generations, final_population=None, timing=[], errors=[],
            )
            output = analyze_semantics(data)
            with (output / "semantic_uniqueness.csv").open(encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            global_all = next(
                item for item in rows
                if item["population_scope"] == "all_candidates" and item["scope_kind"] == "global"
            )
            self.assertEqual(global_all["unique_signature_count"], "2")
            self.assertEqual(global_all["duplicate_candidate_count"], "1")
            self.assertTrue((output / "semantic_library.json").is_file())


if __name__ == "__main__":
    unittest.main()
