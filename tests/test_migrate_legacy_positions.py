"""Tests for moving JSON day files of positions to CSV, against a fake gh.

The fake keeps the release as a directory and implements only the gh calls
the script makes. Stdlib only; skipped where bash is older than 4 (macOS's
/bin/bash), since the script relies on mapfile.
"""

import csv
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import textwrap
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(REPO, "migrate_legacy_positions.sh")
sys.path.insert(0, REPO)

import merge_vehicle_positions as merger

FIELDS = ["vehicle_id", "route_id", "trip_id", "direction_id", "lat", "lon",
          "bearing", "speed", "timestamp", "stop_id", "current_stop_sequence",
          "current_status"]

FAKE_GH = textwrap.dedent('''\
    #!/usr/bin/env python3
    import os, shutil, sys
    release = os.environ["FAKE_RELEASE"]
    args = sys.argv[1:]
    with open(os.environ["FAKE_LOG"], "a") as log:
        log.write(" ".join(args) + "\\n")
    def opt(name):
        return args[args.index(name) + 1]
    if args[:2] == ["release", "view"]:
        if not os.path.isdir(release):
            sys.exit(1)
        print("\\n".join(sorted(os.listdir(release))))
    elif args[:2] == ["release", "download"]:
        os.makedirs(opt("--dir"), exist_ok=True)
        shutil.copy(os.path.join(release, opt("--pattern")), opt("--dir"))
    elif args[:2] == ["release", "upload"]:
        shutil.copy(args[-1], release)
    elif args[:2] == ["release", "delete-asset"]:
        os.remove(os.path.join(release, args[3]))
    else:
        sys.exit("fake gh: unexpected " + " ".join(args))
''')


def _bash_major():
    bash = shutil.which("bash")
    if not bash:
        return 0
    out = subprocess.run([bash, "-c", "echo ${BASH_VERSINFO[0]}"],
                         capture_output=True, text=True)
    return int(out.stdout.strip() or 0)


def legacy_day(sampled_at, vehicle_ids):
    rows = [[v, "42", "1", 0, 39.95, -75.2, None, 1.0, 1791685040, "311", 4,
             "STOPPED_AT"] for v in vehicle_ids]
    return {"date": sampled_at[:10], "fields": FIELDS, "samples": [
        {"sampled_at": sampled_at, "feed_timestamp": 1791685045,
         "vehicles": rows}]}


@unittest.skipIf(_bash_major() < 4, "needs bash 4 or later")
class MigrateTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.release = os.path.join(self.tmp, "release")
        os.makedirs(self.release)
        bin_dir = os.path.join(self.tmp, "bin")
        os.makedirs(bin_dir)
        gh = os.path.join(bin_dir, "gh")
        with open(gh, "w", encoding="utf-8") as handle:
            handle.write(FAKE_GH)
        os.chmod(gh, os.stat(gh).st_mode | stat.S_IEXEC)
        python = os.path.join(bin_dir, "python")
        os.symlink(sys.executable, python)
        self.log = os.path.join(self.tmp, "gh.log")
        self.env = dict(os.environ, PATH=bin_dir + os.pathsep + os.environ["PATH"],
                        FAKE_RELEASE=self.release, FAKE_LOG=self.log,
                        GITHUB_REPOSITORY="owner/repo", GH_TOKEN="x")

    def put(self, name, content):
        with open(os.path.join(self.release, name), "w", encoding="utf-8") as handle:
            handle.write(content)

    def run_script(self):
        return subprocess.run(["bash", SCRIPT], cwd=REPO, env=self.env,
                              capture_output=True, text=True)

    def rows(self, name):
        with open(os.path.join(self.release, name), encoding="utf-8") as handle:
            return list(csv.DictReader(handle))

    def test_a_json_day_becomes_a_csv_and_the_json_goes(self):
        self.put("septapositions_2026-10-13.json",
                 json.dumps(legacy_day("2026-10-13T03:33:50Z", ["3641", "3025"])))

        result = self.run_script()

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(sorted(os.listdir(self.release)),
                         ["septapositions_2026-10-13.csv"])
        self.assertEqual(len(self.rows("septapositions_2026-10-13.csv")), 2)

    def test_a_day_split_across_both_formats_ends_up_whole(self):
        self.put("septapositions_2026-10-13.json",
                 json.dumps(legacy_day("2026-10-13T03:33:50Z", ["3641"])))
        later = {"sampled_at": "2026-10-13T14:21:16Z",
                 "feed_timestamp": 1791685045, "fields": FIELDS,
                 "vehicles": legacy_day("x", ["3025"])["samples"][0]["vehicles"]}
        self.put("septapositions_2026-10-13.csv",
                 merger.render(merger.merge(None, later)))

        result = self.run_script()

        self.assertEqual(result.returncode, 0, result.stderr)
        rows = self.rows("septapositions_2026-10-13.csv")
        self.assertEqual(sorted({row["sampled_at"] for row in rows}),
                         ["2026-10-13T03:33:50Z", "2026-10-13T14:21:16Z"])
        self.assertFalse(os.path.exists(
            os.path.join(self.release, "septapositions_2026-10-13.json")))

    def test_nothing_left_means_nothing_done(self):
        self.put("septapositions_2026-10-13.csv", "sampled_at\n")

        result = self.run_script()

        self.assertEqual(result.returncode, 0, result.stderr)
        with open(self.log, encoding="utf-8") as handle:
            calls = handle.read().splitlines()
        self.assertEqual(len(calls), 1)
        self.assertIn("No JSON day files left", result.stdout)

    def test_a_json_that_cannot_be_converted_is_kept(self):
        self.put("septapositions_2026-10-13.json", "{not json")

        result = self.run_script()

        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(os.listdir(self.release),
                         ["septapositions_2026-10-13.json"])

    def test_no_release_is_not_an_error(self):
        os.rmdir(self.release)

        result = self.run_script()

        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
