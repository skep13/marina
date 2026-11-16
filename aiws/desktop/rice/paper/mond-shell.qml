// Mond clock for Hyprland: the same widget as the Mac's Übersicht one
// (itself a port of the Fedora Asahi conky skin), as a Quickshell desktop
// layer. Sits above the wallpaper, below windows; clicks go through it.
//
//   qs -c mond -d        (started from ~/.config/caelestia/hypr-user.lua)
//
// DAY in Anurati, letter-spaced date, time between dashes, then CPU / RAM
// / DISK / BAT with thin bars. Paper theme: ink text, sage labels and bars.
import QtQuick
import Quickshell
import Quickshell.Io
import Quickshell.Wayland

ShellRoot {
    id: root

    readonly property color soft: "#3a312b"
    readonly property color label: "#4c6838"
    readonly property color shade: Qt.rgba(1, 1, 1, 0.9)        // a soft paper emboss
    readonly property color track: Qt.rgba(76 / 255, 104 / 255, 56 / 255, 0.16)
    readonly property string body: "Inter"

    property var stats: [0, 0, 0, 0]
    property date now: new Date()

    function pad(n) { return n < 10 ? "0" + n : "" + n }

    Process {
        id: poll
        command: [Quickshell.env("HOME") + "/.config/quickshell/mond/stats.sh"]
        stdout: StdioCollector {
            onStreamFinished: {
                const v = this.text.trim().split("|").map(n => Math.max(0, Math.min(100, parseInt(n) || 0)));
                if (v.length === 4) root.stats = v;
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
            margins { top: 86; left: 0 }
            implicitWidth: 560
            implicitHeight: col.implicitHeight + 10

            Column {
                id: col
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
                Text {                            // -  10:20 AM  -
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    readonly property int h: root.now.getHours()
                    text: "-      " + ((h % 12) || 12) + ":" + root.pad(root.now.getMinutes())
                          + " " + (h < 12 ? "AM" : "PM") + "      -"
                    font.family: root.body; font.weight: Font.Medium
                    font.pixelSize: 16.5; font.letterSpacing: 16.5 * 0.22; leftPadding: 16.5 * 0.22
                    color: root.soft; style: Text.Raised; styleColor: root.shade
                }
                Item { width: 1; height: 36 }

                Grid {
                    anchors.horizontalCenter: parent.horizontalCenter
                    columns: 4; columnSpacing: 32; rowSpacing: 13

                    Repeater {                    // labels + values
                        model: ["C P U", "R A M", "D I S K", "B A T"]
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
                        model: 4
                        Rectangle {
                            required property int index
                            width: 100; height: 4; color: root.track
                            Rectangle { width: parent.width * root.stats[index] / 100; height: parent.height; color: root.label }
                        }
                    }
                }
            }
        }
    }
}
