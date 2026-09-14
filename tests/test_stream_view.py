"""Exercise transfers with focus on the remote display, without moving real apps."""
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
        (self.root / "sunshine.conf").write_text("output_name = HEADLESS-1\n")
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
        self.env = dict(os.environ, PATH=str(self.root) + ":" + os.environ["PATH"],
                        XDG_STATE_HOME=str(self.root), SUNSHINE_CONF=str(self.root / "sunshine.conf"),
                        FAKE_DESKTOP=str(self.desktop), FAKE_CALLS=str(self.root / "calls"))

    def run_command(self, *args):
        return subprocess.run([str(HELPER), *args], env=self.env, capture_output=True, text=True, check=True)

    def state(self):
        return json.loads(self.desktop.read_text())

    def active(self, monitor):
        return next(m["activeWorkspace"]["id"] for m in self.state()["monitors"] if m["name"] == monitor)

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


if __name__ == "__main__":
    unittest.main()
