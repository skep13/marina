// Mond clock for Hyprland: the same widget as the Mac's Übersicht one
// (itself a port of the Fedora Asahi conky skin), as a Quickshell desktop
// layer. Sits above the wallpaper, below windows; clicks go through it.
//
//   qs -c mond -d        (started from ~/.config/hypr/config/autostart.lua)
//
// DAY in Anurati, letter-spaced date, time between dashes, then CPU / RAM
// / GPU / DISK / BAT with thin bars, and a vinyl disc that spins while music
// plays. The spin pauses while a window is open on the workspace, so it costs
// nothing when you can't see it. Colours match the forest wallpaper.
import QtQuick
import QtQuick.Effects
import Quickshell
import Quickshell.Hyprland
import Quickshell.Io
import Quickshell.Services.Mpris
import Quickshell.Wayland

ShellRoot {
    id: root

    readonly property color soft: "#f2f7f5"
    readonly property color label: "#5fd6a8"
    readonly property color shade: Qt.rgba(4 / 255, 12 / 255, 10 / 255, 0.95)
    readonly property color track: Qt.rgba(242 / 255, 247 / 255, 245 / 255, 0.28)
    readonly property string body: "Inter"
    readonly property string mono: "IBM Plex Mono"

    property var stats: [0, 0, 0, 0, 0]
    property date now: new Date()

    // A window covering the desktop on this workspace (Marina's sphere doesn't count).
    readonly property bool covered: {
        const ws = Hyprland.focusedWorkspace;
        if (!ws) return false;
        return ws.toplevels.values.some(t => t.title !== "Marina");
    }
    readonly property bool animate: !covered

    // The player to show: a playing one first, else the first with a track.
    readonly property var player: {
        const all = Mpris.players.values;
        return all.find(p => p.isPlaying) ?? all.find(p => p.trackTitle) ?? null;
    }
    readonly property bool playing: player !== null && player.isPlaying

    function pad(n) { return n < 10 ? "0" + n : "" + n }

    Process {
        id: poll
        command: [Quickshell.env("HOME") + "/.config/quickshell/mond/stats.sh"]
        stdout: StdioCollector {
            onStreamFinished: {
                const v = this.text.trim().split("|").map(n => Math.max(0, Math.min(100, parseInt(n) || 0)));
                if (v.length === 5) root.stats = v;
            }
        }
    }

    Timer {
        interval: 2000; running: true; repeat: true; triggeredOnStart: true
        onTriggered: { root.now = new Date(); poll.running = true; }
    }

    Variants {
        model: Quickshell.screens

        PanelWindow {
            required property var modelData
            screen: modelData

            WlrLayershell.layer: WlrLayer.Bottom
            WlrLayershell.namespace: "mond-clock"
            exclusionMode: ExclusionMode.Ignore
            color: "transparent"
            mask: Region {}                       // click-through

            anchors { top: true; left: true }
            margins { top: 70; left: 0 }
            implicitWidth: 690
            implicitHeight: col.implicitHeight + 40

            Column {
                id: col
                y: 20
                width: parent.width

                Text {                            // MONDAY
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    text: root.now.toLocaleDateString(Qt.locale("en_GB"), "dddd").toUpperCase()
                    font.family: "Anurati"; font.pixelSize: 48; font.letterSpacing: 48 * 0.40
                    leftPadding: 48 * 0.40                  // cancels the trailing letter-space
                    color: root.soft; style: Text.Raised; styleColor: root.shade
                }
                Item { width: 1; height: 26 }
                Text {                            // 14 SEPTEMBER, 2026.
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    text: root.pad(root.now.getDate()) + " "
                          + root.now.toLocaleDateString(Qt.locale("en_GB"), "MMMM").toUpperCase()
                          + ", " + root.now.getFullYear() + "."
                    font.family: root.body; font.weight: Font.Medium
                    font.pixelSize: 18; font.letterSpacing: 18 * 0.30; leftPadding: 18 * 0.30
                    color: root.soft; style: Text.Raised; styleColor: root.shade
                }
                Item { width: 1; height: 18 }
                Row {                             // -  10:20 AM  -
                    anchors.horizontalCenter: parent.horizontalCenter
                    readonly property int h: root.now.getHours()
                    Text {
                        text: "-      " + ((parent.h % 12) || 12) + ":" + root.pad(root.now.getMinutes())
                              + " " + (parent.h < 12 ? "AM" : "PM")
                        font.family: root.body; font.weight: Font.Medium
                        font.pixelSize: 16; font.letterSpacing: 16 * 0.22; leftPadding: 16 * 0.22
                        color: root.soft; style: Text.Raised; styleColor: root.shade
                    }
                    Text {
                        text: "      -"
                        font.family: root.body; font.weight: Font.Medium
                        font.pixelSize: 16; font.letterSpacing: 16 * 0.22
                        color: root.soft; style: Text.Raised; styleColor: root.shade
                    }
                }
                Item { width: 1; height: 36 }

                Grid {
                    anchors.horizontalCenter: parent.horizontalCenter
                    columns: 5; columnSpacing: 32; rowSpacing: 13

                    Repeater {                    // labels + values
                        model: ["C P U", "R A M", "G P U", "D I S K", "B A T"]
                        Row {
                            required property string modelData
                            required property int index
                            width: 100
                            Text {
                                text: modelData
                                font.family: root.body; font.pixelSize: 13; font.letterSpacing: 13 * 0.20
                                color: root.label; style: Text.Raised; styleColor: root.shade
                            }
                            Text {
                                text: "  " + root.stats[index] + "%"
                                font.family: root.body; font.pixelSize: 13
                                color: root.soft; style: Text.Raised; styleColor: root.shade
                            }
                        }
                    }
                    Repeater {                    // bars
                        model: 5
                        Rectangle {
                            required property int index
                            width: 100; height: 4; color: root.track
                            Rectangle { width: parent.width * root.stats[index] / 100; height: parent.height; color: root.label }
                        }
                    }
                }
                Item { width: 1; height: 18 }
                // Now playing: a vinyl disc with the album art, spinning while music plays
                Item {
                    width: parent.width
                    height: root.player ? 150 : 0
                    visible: root.player !== null

                    Row {
                        anchors.centerIn: parent
                        spacing: 24

                        Item {
                            id: disc
                            width: 112; height: 112
                            anchors.verticalCenter: parent.verticalCenter

                            RotationAnimator on rotation {
                                from: 0; to: 360; duration: 4000
                                loops: Animation.Infinite
                                running: root.playing && root.animate
                            }

                            Rectangle {                 // vinyl
                                anchors.fill: parent; radius: width / 2
                                color: "#0f1514"
                                border.color: root.label; border.width: 1.5
                            }
                            Repeater {                  // grooves
                                model: 4
                                Rectangle {
                                    required property int index
                                    readonly property real d: disc.width - 16 - index * 10
                                    width: d; height: d; radius: d / 2
                                    anchors.centerIn: parent
                                    color: "transparent"
                                    border.color: root.track; border.width: 1
                                }
                            }
                            Image {                     // album art, cut to a circle
                                id: art
                                width: 50; height: 50
                                anchors.centerIn: parent
                                source: root.player ? root.player.trackArtUrl : ""
                                fillMode: Image.PreserveAspectCrop
                                visible: false
                                asynchronous: true
                            }
                            Rectangle {
                                id: artMask
                                width: 50; height: 50; radius: 25
                                anchors.centerIn: parent
                                visible: false
                                layer.enabled: true
                            }
                            MultiEffect {
                                anchors.fill: art
                                source: art
                                maskEnabled: true
                                maskSource: artMask
                                visible: art.status === Image.Ready
                            }
                            Rectangle {                 // label when there's no art
                                width: 50; height: 50; radius: 25
                                anchors.centerIn: parent
                                color: root.label; opacity: 0.35
                                visible: art.status !== Image.Ready
                            }
                            Rectangle {                 // spindle hole
                                width: 8; height: 8; radius: 4
                                anchors.centerIn: parent
                                color: "#000000"
                                border.color: root.label; border.width: 1
                            }
                        }

                        Column {
                            anchors.verticalCenter: parent.verticalCenter
                            spacing: 6
                            width: 300
                            Text {
                                text: root.playing ? "▶  N O W   P L A Y I N G" : "❚❚  P A U S E D"
                                font.family: root.mono; font.pixelSize: 11
                                color: root.label; opacity: 0.85
                            }
                            Text {
                                width: parent.width; elide: Text.ElideRight
                                text: root.player ? (root.player.trackTitle || "Unknown track") : ""
                                font.family: root.body; font.weight: Font.Medium; font.pixelSize: 17
                                color: root.soft; style: Text.Raised; styleColor: root.shade
                            }
                            Text {
                                width: parent.width; elide: Text.ElideRight
                                text: root.player ? (root.player.trackArtist || "") : ""
                                font.family: root.body; font.pixelSize: 13
                                color: root.label
                            }
                        }
                    }
                }
            }
        }
    }
}
