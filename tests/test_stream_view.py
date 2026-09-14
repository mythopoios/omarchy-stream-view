"""Exercise the helper against a stubbed hyprctl, without moving real apps."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


HELPER = Path(os.environ.get("STREAM_VIEW_TEST_HELPER", Path(__file__).resolve().parents[1] / "bin/stream-view"))

# Model Hyprland 0.56.2's moveWorkspaceToMonitor: a moved workspace becomes
# active on its destination automatically only when its source had focus.
HYPRCTL = r'''#!/usr/bin/env python3
import json, os, re, sys
from pathlib import Path
p = Path(os.environ['FAKE_DESKTOP'])
d = json.loads(p.read_text())
args = sys.argv[1:]
with open(os.environ['FAKE_CALLS'], 'a') as f:
    f.write(json.dumps(args) + '\n')
if args[0] == 'monitors':
    print(json.dumps(d['monitors']))
elif args[0] == 'workspaces':
    print(json.dumps(d['workspaces']))
elif args[0] == 'workspacerules':
    print(json.dumps([{'workspaceString': str(w['id']), 'monitor': w['home']}
                      for w in d['workspaces']]))
elif args[0] == 'output' and args[1:] == ['create', 'headless']:
    n = 1 + sum(1 for m in d['monitors'] if m['name'].startswith('HEADLESS'))
    name = 'HEADLESS-%d' % n
    d['monitors'].append({'name': name, 'x': 20000, 'y': 0, 'activeWorkspace': {'id': 30 + n}})
    d['workspaces'].append({'id': 30 + n, 'monitor': name, 'home': name})
    p.write_text(json.dumps(d))
    print('ok')
elif args[0] in ('eval', 'reload'):
    print('ok')
elif args[0] == 'dispatch':
    cmd = args[1]
    number = re.search(r'workspace = (\d+)', cmd)
    target = re.search(r'monitor = "([^"]+)"', cmd)
    if 'workspace.move' in cmd:
        ws = next(w for w in d['workspaces'] if w['id'] == int(number[1]))
        origin = next(m for m in d['monitors'] if m['name'] == ws['monitor'])
        dest = next(m for m in d['monitors'] if m['name'] == target[1])
        active = origin['activeWorkspace']['id'] == ws['id']
        if active:
            fallback = next(w for w in d['workspaces']
                            if w['monitor'] == origin['name'] and w['id'] != ws['id'])
            origin['activeWorkspace']['id'] = fallback['id']
        ws['monitor'] = dest['name']
        if active and d['focus'] == origin['name']:
            dest['activeWorkspace']['id'] = ws['id']
            d['focus'] = dest['name']
    elif 'hl.dsp.focus' in cmd:
        if number:
            ws = next(w for w in d['workspaces'] if w['id'] == int(number[1]))
            d['focus'] = ws['monitor']
            next(m for m in d['monitors'] if m['name'] == d['focus'])['activeWorkspace']['id'] = ws['id']
        else:
            d['focus'] = target[1]
    else:
        raise AssertionError(cmd)
    p.write_text(json.dumps(d))
    print('ok')
else:
    raise AssertionError(args)
'''


class StreamViewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        stub = self.root / "hyprctl"
        stub.write_text(HYPRCTL)
        stub.chmod(0o755)
        self.write_conf("output_name = HEADLESS-1\n")
        self.desktop = self.root / "desktop.json"
        monitors = [
            {"name": "DP-3", "x": 0, "y": -1440, "description": "top", "activeWorkspace": {"id": 1}},
            {"name": "DP-2", "x": 0, "y": 0, "description": "bottom", "activeWorkspace": {"id": 11}},
            {"name": "HEADLESS-1", "x": 10000, "y": 0, "activeWorkspace": {"id": 21}},
        ]
        workspaces = [{"id": n, "monitor": mon, "home": mon}
                      for mon, ids in [("DP-3", [1, 2]), ("DP-2", [11, 12]), ("HEADLESS-1", [21, 22])]
                      for n in ids]
        self.desktop.write_text(json.dumps({"monitors": monitors, "workspaces": workspaces, "focus": "HEADLESS-1"}))
        # A unit name nothing on the host owns, so session detection cannot
        # see the real Sunshine through the journal.
        self.env = dict(os.environ, PATH=str(self.root) + ":" + os.environ["PATH"],
                        XDG_STATE_HOME=str(self.root), SUNSHINE_CONF=str(self.root / "sunshine.conf"),
                        SUNSHINE_UNIT="stream-view-test-no-such-unit.service",
                        FAKE_DESKTOP=str(self.desktop), FAKE_CALLS=str(self.root / "calls"))

    def write_conf(self, text):
        (self.root / "sunshine.conf").write_text(text)

    def run_command(self, *args):
        return subprocess.run([str(HELPER), *args], env=self.env, capture_output=True, text=True, check=True)

    def status(self):
        return json.loads(self.run_command("status", "--json").stdout)

    def session(self):
        return self.run_command("session").stdout.strip()

    def state(self):
        return json.loads(self.desktop.read_text())

    def active(self, monitor):
        return next(m["activeWorkspace"]["id"] for m in self.state()["monitors"] if m["name"] == monitor)

    def headless_outputs(self):
        return [m["name"] for m in self.state()["monitors"] if m["name"].startswith("HEADLESS")]

    def hyprctl_calls(self, *kinds):
        path = self.root / "calls"
        if not path.exists():
            return []
        calls = [json.loads(line) for line in path.read_text().splitlines()]
        return [c for c in calls if not kinds or c[0] in kinds]

    # --- borrowing and returning workspaces --------------------------------

    def test_remote_click_makes_transferred_workspace_visible(self):
        self.run_command("show", "1")
        self.assertEqual(self.active("HEADLESS-1"), 1)
        self.assertEqual(self.state()["focus"], "HEADLESS-1")
        calls = [json.loads(line) for line in (self.root / "calls").read_text().splitlines()]
        self.assertLessEqual(len(calls), 5)

    def test_switch_then_recover_restores_original_layout(self):
        original = self.state()
        self.run_command("show", "1")
        self.run_command("show", "2")
        self.assertEqual(self.active("HEADLESS-1"), 11)
        self.assertEqual(next(w["monitor"] for w in self.state()["workspaces"] if w["id"] == 1), "DP-3")
        self.run_command("restore")
        self.assertEqual(self.state()["workspaces"], original["workspaces"])
        self.assertEqual(self.active("DP-3"), 1)
        self.assertEqual(self.active("DP-2"), 11)
        self.assertEqual(json.loads((self.root / "stream-view/borrowed.json").read_text()), [])
        self.assertFalse((self.root / "stream-view/snapshot.json").exists())

    def test_same_monitor_button_reselects_borrowed_workspace(self):
        self.run_command("show", "1")
        d = self.state()
        next(m for m in d["monitors"] if m["name"] == "HEADLESS-1")["activeWorkspace"]["id"] = 21
        self.desktop.write_text(json.dumps(d))
        self.run_command("show", "1")
        self.assertEqual(self.active("HEADLESS-1"), 1)

    def test_desktop_releases_borrowed_workspace(self):
        original = self.state()
        self.run_command("show", "1")
        self.run_command("desktop")
        self.assertEqual(self.state()["workspaces"], original["workspaces"])
        self.assertEqual(self.active("HEADLESS-1"), 21)

    # --- which output is the streaming display ------------------------------

    def test_physical_capture_is_not_ready(self):
        self.write_conf("output_name = DP-2\n")
        original = self.state()
        status = self.status()
        self.assertFalse(status["ready"])
        self.assertIsNone(status["headless"])
        self.assertIn("DP-2", status["reason"])
        self.assertEqual([m["name"] for m in status["monitors"]], ["DP-3", "DP-2"])
        result = subprocess.run([str(HELPER), "show", "1"], env=self.env, capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.state()["workspaces"], original["workspaces"])

    def test_stale_output_name_falls_back_to_present_headless(self):
        self.write_conf("output_name = HEADLESS-2\n")
        status = self.status()
        self.assertTrue(status["ready"])
        self.assertEqual(status["headless"], "HEADLESS-1")

    def test_ensure_keeps_existing_headless_when_capture_is_physical(self):
        self.write_conf("output_name = DP-2\n")
        self.run_command("ensure")
        self.assertEqual(self.headless_outputs(), ["HEADLESS-1"])

    def test_ensure_creates_headless_when_none_exists(self):
        d = self.state()
        d["monitors"] = [m for m in d["monitors"] if not m["name"].startswith("HEADLESS")]
        d["workspaces"] = [w for w in d["workspaces"] if not w["monitor"].startswith("HEADLESS")]
        self.desktop.write_text(json.dumps(d))
        self.assertFalse(self.status()["ready"])
        self.run_command("ensure")
        self.assertEqual(self.headless_outputs(), ["HEADLESS-1"])
        self.assertTrue(self.status()["ready"])

    # --- is a client streaming ---------------------------------------------

    def test_session_follows_sunshine_log(self):
        log = self.root / "sunshine.log"
        self.assertEqual(self.session(), "unknown")
        log.write_text("[t]: Info: Sunshine version: test\n")
        self.assertEqual(self.session(), "idle")
        with log.open("a") as f:
            f.write("[t]: Info: CLIENT CONNECTED\n")
        self.assertEqual(self.session(), "active")
        with log.open("a") as f:
            f.write("[t]: Info: CLIENT DISCONNECTED\n")
        self.assertEqual(self.session(), "idle")

    def test_session_honours_log_path_and_log_level(self):
        (self.root / "logs").mkdir()
        (self.root / "logs/s.log").write_text("[t]: Info: CLIENT CONNECTED\n")
        self.write_conf("output_name = HEADLESS-1\nlog_path = logs/s.log\n")
        self.assertEqual(self.session(), "active")
        self.write_conf("output_name = HEADLESS-1\nlog_path = logs/s.log\nmin_log_level = warning\n")
        self.assertEqual(self.session(), "unknown")

    def test_session_is_idle_when_sunshine_unit_is_down(self):
        stub = self.root / "systemctl"
        stub.write_text('#!/bin/sh\ncase "$*" in *LoadState*) printf "loaded\\nfailed\\n";; *) exit 1;; esac\n')
        stub.chmod(0o755)
        (self.root / "sunshine.log").write_text("[t]: Info: CLIENT CONNECTED\n")
        self.assertEqual(self.session(), "idle")

    # --- number keys -------------------------------------------------------

    def test_keys_toggle_is_remembered_and_reported(self):
        self.assertFalse(self.status()["keys"])
        self.assertEqual(self.run_command("keys", "on").stdout.strip(), "on")
        self.assertTrue(self.status()["keys"])
        self.assertEqual(self.run_command("keys", "toggle").stdout.strip(), "off")
        self.assertFalse(self.status()["keys"])
        self.assertEqual(self.hyprctl_calls("eval", "reload"), [])

    def test_session_swaps_number_keys_in_and_back(self):
        self.run_command("keys", "on")
        self.run_command("session-start")
        evals = self.hyprctl_calls("eval")
        self.assertEqual(len(evals), 1)
        self.assertTrue(evals[0][1].startswith("(function()"))   # eval takes an expression
        self.assertIn('"r~" .. n', evals[0][1])
        self.assertIn("hl.unbind", evals[0][1])
        self.assertTrue((self.root / "stream-view/keys-applied").exists())
        self.run_command("show", "1")
        self.run_command("session-end")
        self.assertIn(["reload", "config-only"], self.hyprctl_calls("reload"))
        self.assertFalse((self.root / "stream-view/keys-applied").exists())
        self.assertEqual(self.active("DP-3"), 1)
        self.assertFalse((self.root / "stream-view/snapshot.json").exists())

    def test_session_leaves_keys_alone_when_off(self):
        self.run_command("session-start")
        self.run_command("session-end")
        self.assertEqual(self.hyprctl_calls("eval", "reload"), [])

    def test_keys_apply_immediately_while_a_client_is_connected(self):
        (self.root / "sunshine.log").write_text("[t]: Info: CLIENT CONNECTED\n")
        self.run_command("keys", "on")
        self.assertEqual([c[0] for c in self.hyprctl_calls("eval", "reload")], ["eval"])
        self.run_command("keys", "off")
        self.assertEqual([c[0] for c in self.hyprctl_calls("eval", "reload")], ["eval", "reload"])


if __name__ == "__main__":
    unittest.main()
