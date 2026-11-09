"""Archive relocation is explicit, listed, byte preserving and confined to its payload."""
from dataclasses import FrozenInstanceError
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import unittest

from dsh_eval.archive_paths import ArchivePaths, archive_context_active, archive_read_context, logical_str, physical


class ArchivePathsTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dsh-archive-paths-")
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.payload = self.base / "bundle/payload"
        self.payload.mkdir(parents=True)
        self.names = ["experiment/experiment-result.json", "experiment/batches/one/.batch-resume-claim.json",
                      "experiment/batches/one/cases/case/evidence.json"]
        for name in self.names:
            path = self.payload / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'{"unchanged":true}\n')
        self.resolver = ArchivePaths("Z:\\retired\\runs", self.payload, self.names)

    def test_windows_logical_prefix_maps_to_listed_files_and_back_without_original_path(self):
        original = r"Z:\retired\runs\experiment\experiment-result.json"
        target = self.resolver.physical(original)
        self.assertEqual(target, self.payload / self.names[0])
        self.assertEqual(target.read_bytes(), b'{"unchanged":true}\n')
        self.assertEqual(self.resolver.logical_str(target), original)
        self.assertEqual(self.resolver.physical(r"z:\RETIRED\RUNS\EXPERIMENT\experiment-result.json"), target)
        self.assertEqual(self.resolver.physical(self.payload), self.payload)
        self.assertEqual(self.resolver.logical_str(self.payload), r"Z:\retired\runs")

    def test_posix_original_paths_are_parsed_without_accessing_the_original_root(self):
        resolver = ArchivePaths("/retired/experiment-data", self.payload, self.names)
        target = resolver.physical("/retired/experiment-data/" + self.names[0])
        self.assertEqual(target, self.payload / self.names[0])
        self.assertEqual(resolver.logical_str(target), "/retired/experiment-data/" + self.names[0])

    @unittest.skipUnless(os.name == "nt", "Windows short temporary path behavior")
    def test_fixture_paths_are_canonical_when_the_child_temp_root_uses_an_actual_short_alias(self):
        import ctypes
        import sys
        temporary_root = self.base / "long temporary directory for archive alias"
        temporary_root.mkdir()
        buffer = ctypes.create_unicode_buffer(32768)
        length = ctypes.windll.kernel32.GetShortPathNameW(str(temporary_root), buffer, len(buffer))
        if not length or length >= len(buffer) or Path(buffer.value) == temporary_root:
            self.skipTest("The temporary volume does not provide an actual 8.3 alias")
        self.assertEqual(Path(buffer.value).resolve(), temporary_root)
        # Run every other path test in a fresh interpreter; omitting this one avoids recursion.
        selected = ["test_archive_paths.ArchivePathsTests." + name
                    for name in unittest.defaultTestLoader.getTestCaseNames(type(self)) if name != self._testMethodName]
        root = Path(__file__).resolve().parents[1]
        existing = os.environ.get("PYTHONPATH")
        environment = {**os.environ, "TMP": buffer.value, "TEMP": buffer.value,
                       "PYTHONPATH": str(root / "test") + (os.pathsep + existing if existing else "")}
        child = subprocess.run([sys.executable, "-m", "unittest", *selected], cwd=root, env=environment,
                               capture_output=True, text=True, encoding="utf-8", timeout=30)
        self.assertEqual(child.returncode, 0, child.stderr + child.stdout)

    def test_required_hidden_claim_is_allowed_but_other_hidden_or_private_members_are_rejected(self):
        claim = self.payload / self.names[1]
        self.assertEqual(self.resolver.physical(claim), claim)
        for name in (".secret.json", "a/.private/b.json", "home/data.json", "a/workspace/x.json",
                     "a/node_modules/package.json", "private-notes/a.json", "secrets/x.json", "credentials/x.json",
                     ".batch-resume-claim.json/file.json"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                ArchivePaths("/old", self.payload, [name])

    def test_unlisted_relative_external_and_parent_references_never_fall_back_to_the_filesystem(self):
        unknown = self.payload / "extra.json"
        unknown.write_text("sensitive", encoding="utf-8")
        for value in (unknown, r"Z:\retired\runs\extra.json", "experiment/experiment-result.json",
                      r"Z:\elsewhere\experiment-result.json", self.base / "outside.json",
                      r"Z:\retired\runs\experiment\..\experiment\experiment-result.json",
                      self.payload / "experiment/../experiment/experiment-result.json"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.resolver.physical(value)
        self.assertTrue(self.resolver.recognizes(unknown))
        self.assertTrue(self.resolver.recognizes(r"Z:\retired\runs\extra.json"))
        self.assertFalse(self.resolver.recognizes(self.base / "outside.json"))
        self.assertFalse(self.resolver.recognizes([]))

    def test_member_inventory_rejects_collisions_and_ambiguous_names(self):
        inventories = ([], "one.json", ["one.json", "one.json"], ["a.json", "a.json/file.json"],
                       ["A/x.json", "a/y.json"], ["a/../x.json"], ["a//x.json"], ["a\\x.json"],
                       ["/x.json"], ["a:x.json"], ["a/\0.json"], [None])
        for names in inventories:
            with self.subTest(names=names), self.assertRaises(ValueError):
                ArchivePaths(r"Z:\old", self.payload, names)
        with self.assertRaises(ValueError):
            ArchivePaths("relative/root", self.payload, self.names)

    def test_explicit_context_preserves_defaults_and_restores_after_errors(self):
        original = r"Z:\retired\runs\experiment\experiment-result.json"
        self.assertFalse(archive_context_active())
        self.assertEqual(physical(self.payload / self.names[0]), (self.payload / self.names[0]).resolve())
        self.assertEqual(logical_str("../verbatim"), "../verbatim")
        with self.assertRaisesRegex(RuntimeError, "check"):
            with archive_read_context(self.resolver):
                self.assertTrue(archive_context_active())
                self.assertEqual(physical(original), self.payload / self.names[0])
                self.assertEqual(logical_str(self.payload / self.names[0]), original)
                with archive_read_context(self.resolver):
                    self.assertEqual(physical(original).read_bytes(), b'{"unchanged":true}\n')
                raise RuntimeError("check")
        self.assertFalse(archive_context_active())

    def test_context_does_not_leak_into_other_threads_or_allow_a_different_nested_mapping(self):
        observed = []
        other = ArchivePaths("/different", self.payload, self.names)
        with archive_read_context(self.resolver):
            worker = threading.Thread(target=lambda: observed.append(archive_context_active()))
            worker.start()
            worker.join()
            with self.assertRaisesRegex(ValueError, "different"):
                with archive_read_context(other):
                    pass
            self.assertTrue(archive_context_active())
        self.assertEqual(observed, [False])

    def test_read_context_rejects_continuation_planning_and_execution_before_any_output(self):
        from dsh_eval.experiment_resume import plan_experiment_resume, resume_experiment
        from dsh_eval.experiment_resume_chain import execute_chain, plan_chain
        from dsh_eval.resume import _execute_resume, plan_batch_resume, resume_batch
        source = self.base / "never-created/batch-result.json"
        operations = (
            lambda: plan_batch_resume(source), lambda: plan_experiment_resume(source), lambda: plan_chain(source),
            lambda: resume_batch(source), lambda: resume_experiment(source),
            lambda: execute_chain(source, None, None, False, max_samples=None, expected_plan_sha256="0" * 64),
            lambda: _execute_resume(source, {}, {}, {}, self.base / "outputs", None, False),
        )
        with archive_read_context(self.resolver):
            for operation in operations:
                with self.subTest(operation=operation), self.assertRaisesRegex(ValueError, "Archive relocation is read-only"):
                    operation()
        self.assertFalse(source.parent.exists())
        self.assertFalse((self.base / "outputs").exists())

    def test_resolver_inventory_is_immutable(self):
        with self.assertRaises(FrozenInstanceError):
            self.resolver.payload_root = self.base
        self.assertIsInstance(self.resolver.members, frozenset)
        with self.assertRaises(TypeError):
            self.resolver._files["new"] = "new"

    def test_already_physical_paths_win_when_the_source_prefix_contains_the_bundle(self):
        resolver = ArchivePaths(str(self.base), self.payload, self.names)
        target = self.payload / self.names[0]
        self.assertEqual(resolver.physical(target), target)
        self.assertEqual(resolver.logical_str(target), str(self.base / self.names[0]))

    def test_linked_member_or_payload_is_rejected(self):
        outside = self.base / "outside.json"
        outside.write_text("outside", encoding="utf-8")
        linked = self.payload / "linked.json"
        try:
            linked.symlink_to(outside)
        except OSError:
            self.skipTest("File symlink creation is unavailable in this environment")
        resolver = ArchivePaths("/old", self.payload, ["linked.json"])
        with self.assertRaisesRegex(ValueError, "link"):
            resolver.physical("/old/linked.json")
        link_root = self.base / "linked-payload"
        try:
            link_root.symlink_to(self.payload, target_is_directory=True)
        except OSError:
            self.skipTest("Directory symlink creation is unavailable in this environment")
        with self.assertRaisesRegex(ValueError, "link"):
            ArchivePaths("/old", link_root, self.names)

    @unittest.skipUnless(os.name == "nt", "Windows junction behavior")
    def test_windows_junction_is_rejected_before_following_the_target(self):
        outside = self.base / "outside-directory"
        outside.mkdir()
        (outside / "data.json").write_text("outside", encoding="utf-8")
        linked = self.payload / "junction"
        process = subprocess.run(["cmd", "/c", "mklink", "/J", str(linked), str(outside)],
                                 capture_output=True, timeout=10)
        if process.returncode:
            self.skipTest("Windows junction creation is unavailable in this environment")
        self.assertTrue(linked.is_junction())
        resolver = ArchivePaths("/old", self.payload, ["junction/data.json"])
        with self.assertRaisesRegex(ValueError, "link"):
            resolver.physical("/old/junction/data.json")
        with self.assertRaisesRegex(ValueError, "link"):
            ArchivePaths("/old", linked, ["data.json"])


if __name__ == "__main__":
    unittest.main()
