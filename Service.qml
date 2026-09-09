import QtQuick
import Quickshell
import Quickshell.Io

// Session watcher.
//
// Snapshots the desktop layout when a Moonlight client connects, and puts
// everything back when it disconnects — so a borrowed workspace never stays
// stranded on a headless output nobody is looking at.
//
// This polls rather than hooking Sunshine's prep-commands on purpose: it keeps
// the whole plugin self-contained, so installing and removing it touches
// nothing outside this folder. Sunshine's own global_prep_cmd can be used
// instead for exact timing (see the README); both paths are idempotent, so
// running both is harmless.
Item {
  id: root

  property var shell: null
  property var manifest: null

  readonly property string tool: Qt.resolvedUrl("bin/stream-view").toString().replace("file://", "")

  // Seconds between checks. A stream that starts is noticed within one tick;
  // the cost is one `ss` call, so this stays cheap.
  readonly property int intervalMs: 5000

  property string session: "unknown"
  property bool started: false

  function apply(next) {
    var value = String(next || "").trim()
    if (value !== "active" && value !== "idle") return   // "unknown": tooling missing

    if (!started) {
      // First reading of the session establishes a baseline. Acting on it would
      // restore a layout we never snapshotted, or snapshot mid-stream.
      started = true
      session = value
      return
    }

    if (value === session) return
    session = value

    if (value === "active") actionProc.command = [root.tool, "snapshot"]
    else actionProc.command = [root.tool, "restore"]

    if (!actionProc.running) actionProc.running = true
  }

  Process {
    id: pollProc
    command: [root.tool, "session"]
    stdout: StdioCollector { waitForEnd: true; onStreamFinished: root.apply(text) }
  }

  Process { id: actionProc }

  Timer {
    interval: root.intervalMs
    running: true
    repeat: true
    triggeredOnStart: true
    onTriggered: if (!pollProc.running) pollProc.running = true
  }
}
