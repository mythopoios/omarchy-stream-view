import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui

// Stream View — choose which physical monitor a Moonlight client sees.
//
// The Omarchy bar is drawn on every output, including the headless one Sunshine
// captures, so this widget and its panel are visible and clickable from the
// remote client itself. Pick a monitor and that screen's current workspace is
// borrowed onto the stream; Desktop hands it back; Recover restores the layout
// captured when the client connected.
//
// All compositor logic lives in bin/stream-view so the shell code stays thin
// and the behaviour can be tested without a running shell.
Panel {
  id: root
  moduleName: "io.github.mythopoios.stream-view"
  ipcTarget: "io.github.mythopoios.stream-view"

  // Resolve the bundled helper relative to this file, so the plugin works from
  // whatever directory it was installed into.
  readonly property string tool: Qt.resolvedUrl("bin/stream-view").toString().replace("file://", "")

  property bool ready: false
  property string reason: ""
  property string streaming: "none"      // "none" | "<monitor number>" | "?"
  property var monitors: []              // [{index, name, activeWs}]
  property bool cursorActive: false
  property int cursorIndex: 0

  readonly property int monCount: monitors.length
  // Monitor buttons, then Desktop, then Recover.
  readonly property int actionCount: monCount + 2

  readonly property string iconMonitor: "󰍹"
  readonly property string iconDesktop: "󰇄"
  readonly property string iconRecover: "󰑐"
  readonly property string iconSetup: "󰅱"
  readonly property string iconBar: streaming === "none" ? "󰤴" : "󰤷"

  // Setup creates a display and restarts Sunshine, so it takes a moment and
  // the button says so rather than looking like it did nothing.
  property bool busy: false

  function run(args) { if (root.bar) root.bar.run(root.tool + " " + args) }
  function refresh() { if (!statusProc.running) statusProc.running = true }

  function runSetup() {
    if (busy) return
    busy = true
    setupProc.running = true
  }

  function applyStatus(text) {
    try {
      var d = JSON.parse(text)
      root.ready = d.ready === true
      root.reason = String(d.reason || "")
      root.streaming = String(d.streaming || "none")
      root.monitors = d.monitors || []
    } catch (e) {
      // Keep the last known state rather than flashing an empty panel.
    }
  }

  function actionCommand(i) {
    if (i < monCount) return "show " + monitors[i].index
    if (i === monCount) return "desktop"
    return "restore"
  }

  function activateAt(i) {
    if (i < 0 || i >= actionCount) return
    run(actionCommand(i))
    settleTimer.restart()
  }

  // The base Panel already registers open/close/toggle on `ipcTarget`.

  Process {
    id: statusProc
    command: [root.tool, "status", "--json"]
    stdout: StdioCollector { waitForEnd: true; onStreamFinished: root.applyStatus(text) }
  }

  Process {
    id: setupProc
    command: [root.tool, "setup"]
    onExited: {
      root.busy = false
      // Sunshine has just been restarted; give it a beat before believing the
      // first status reading.
      setupSettle.restart()
    }
  }

  Timer { id: setupSettle; interval: 1500; repeat: false; onTriggered: root.refresh() }
  Timer { id: settleTimer; interval: 350; repeat: false; onTriggered: root.refresh() }
  Timer { interval: 4000; running: root.opened; repeat: true; onTriggered: root.refresh() }

  onOpenedChanged: {
    if (opened) {
      cursorActive = false
      cursorIndex = (streaming !== "none" && streaming !== "?")
        ? Math.max(0, parseInt(streaming) - 1) : monCount
      refresh()
    }
  }

  Component.onCompleted: refresh()

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

  BarIconButton {
    id: button
    anchors.fill: parent
    bar: root.bar
    text: root.iconBar
    active: root.streaming !== "none"
    tooltipText: !root.ready ? "Stream View: no streaming display"
      : (root.streaming === "none" ? "Stream: idle desktop"
                                   : "Streaming monitor " + root.streaming)
    onPressed: function(b) { root.toggle() }
  }

  KeyboardPanel {
    id: panel
    anchorItem: button
    owner: root
    bar: root.bar
    open: root.opened
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(340))
    contentHeight: panel.fittedContentHeight(column.implicitHeight)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onMoveRequested: function(dx, dy) {
        if (!root.ready) return
        if (!root.cursorActive) { root.cursorActive = true; return }
        var step = (dx !== 0) ? dx : dy
        root.cursorIndex = (root.cursorIndex + step + root.actionCount) % root.actionCount
      }
      onActivateRequested: if (root.ready && root.cursorActive) root.activateAt(root.cursorIndex)
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }

      Column {
        id: column
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        spacing: Style.space(14)

        // ---------- Hero ----------
        Item {
          width: parent.width
          implicitHeight: Math.max(heroIcon.implicitHeight, heroLabels.implicitHeight)

          Text {
            id: heroIcon
            textFormat: Text.PlainText
            text: root.iconBar
            color: root.bar.foreground
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.display
            anchors.left: parent.left
            anchors.verticalCenter: parent.verticalCenter
          }

          Column {
            id: heroLabels
            anchors.left: heroIcon.right
            anchors.leftMargin: Style.space(14)
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.space(2)

            Text {
              text: "Stream view"
              color: root.bar.foreground
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.title
              font.bold: true
              elide: Text.ElideRight
              width: parent.width
            }

            Text {
              textFormat: Text.PlainText
              text: !root.ready ? "NO STREAMING DISPLAY"
                : (root.streaming === "none" ? "IDLE DESKTOP" : "MONITOR " + root.streaming)
              color: Qt.darker(root.bar.foreground, 1.4)
              font.family: root.bar.fontFamily
              font.pixelSize: Style.font.caption
              font.bold: true
              font.letterSpacing: 1.2
              elide: Text.ElideRight
              width: parent.width
            }
          }
        }

        // ---------- Not ready: explain, and offer to fix it ----------
        Column {
          visible: !root.ready
          width: parent.width
          spacing: Style.space(10)

          Text {
            width: parent.width
            textFormat: Text.PlainText
            text: root.busy
              ? "Creating the streaming display and pointing Sunshine at it..."
              : "Sunshine needs a display of its own to capture. Setting up creates one off to the side, points Sunshine at it, and restarts Sunshine."
            color: Qt.darker(root.bar.foreground, 1.4)
            font.family: root.bar.fontFamily
            font.pixelSize: Style.font.bodySmall
            wrapMode: Text.WordWrap
          }

          Button {
            width: parent.width
            iconText: root.iconSetup
            iconSize: Style.font.title
            text: root.busy ? "Setting up..." : "Set up"
            fontSize: Style.font.bodySmall
            foreground: root.bar.foreground
            fontFamily: root.bar.fontFamily
            horizontalPadding: Style.spacing.controlPaddingX
            verticalPadding: Style.spacing.controlPaddingY + Style.space(4)
            bordered: true
            enabled: !root.busy
            onClicked: root.runSetup()
          }
        }

        // ---------- Monitor pickers ----------
        Column {
          visible: root.ready
          width: parent.width
          spacing: Style.space(10)

          PanelSectionHeader {
            text: "SHOW ON STREAM"
            foreground: root.bar.foreground
            fontFamily: root.bar.fontFamily
          }

          Row {
            id: monRow
            width: parent.width
            spacing: Style.space(6)

            readonly property real cellWidth: root.monCount > 0
              ? (width - spacing * (root.monCount - 1)) / root.monCount
              : width

            Repeater {
              model: root.monitors
              Button {
                required property var modelData
                required property int index
                width: monRow.cellWidth
                iconText: root.iconMonitor
                iconSize: Style.font.title
                text: "Monitor " + modelData.index
                fontSize: Style.font.bodySmall
                foreground: root.bar.foreground
                fontFamily: root.bar.fontFamily
                horizontalPadding: Style.spacing.controlPaddingX
                verticalPadding: Style.spacing.controlPaddingY + Style.space(4)
                bordered: true
                active: root.streaming === String(modelData.index)
                hasCursor: root.cursorActive && root.cursorIndex === index
                onClicked: root.activateAt(index)
                onHovered: function(h) { if (h) { root.cursorActive = true; root.cursorIndex = index } }
              }
            }
          }
        }

        PanelSeparator { visible: root.ready; foreground: root.bar.foreground }

        // ---------- Release + Recover ----------
        Row {
          id: actionRow
          visible: root.ready
          width: parent.width
          spacing: Style.space(6)
          readonly property real cellWidth: (width - spacing) / 2

          Button {
            width: actionRow.cellWidth
            iconText: root.iconDesktop
            iconSize: Style.font.title
            text: "Desktop"
            fontSize: Style.font.bodySmall
            foreground: root.bar.foreground
            fontFamily: root.bar.fontFamily
            horizontalPadding: Style.spacing.controlPaddingX
            verticalPadding: Style.spacing.controlPaddingY + Style.space(2)
            bordered: true
            active: root.streaming === "none"
            hasCursor: root.cursorActive && root.cursorIndex === root.monCount
            onClicked: root.activateAt(root.monCount)
            onHovered: function(h) { if (h) { root.cursorActive = true; root.cursorIndex = root.monCount } }
          }

          Button {
            width: actionRow.cellWidth
            iconText: root.iconRecover
            iconSize: Style.font.title
            text: "Recover"
            fontSize: Style.font.bodySmall
            foreground: root.bar.foreground
            fontFamily: root.bar.fontFamily
            horizontalPadding: Style.spacing.controlPaddingX
            verticalPadding: Style.spacing.controlPaddingY + Style.space(2)
            bordered: true
            hasCursor: root.cursorActive && root.cursorIndex === root.monCount + 1
            onClicked: root.activateAt(root.monCount + 1)
            onHovered: function(h) { if (h) { root.cursorActive = true; root.cursorIndex = root.monCount + 1 } }
          }
        }

        Text {
          visible: root.ready
          width: parent.width
          textFormat: Text.PlainText
          text: "Recover puts every window back on the workspace it was on when this session connected."
          color: Qt.darker(root.bar.foreground, 1.4)
          font.family: root.bar.fontFamily
          font.pixelSize: Style.font.caption
          wrapMode: Text.WordWrap
        }
      }
    }
  }
}
