import QtQuick
import QtQuick.Shapes

Item {
    id: scene
    signal rendererError(string message)
    property real clock: 0
    property real skinClock: 0
    property real graphGain: 2.8
    property var nodes: []
    property var edges: []
    property var tendrils: []
    property var glyphs: []
    property var statusLabel: ({})
    property var desktopRects: []
    property var cursorState: ({})
    property bool micActive: false
    property string bodySourceUrl: ""
    property string forwardSourceUrl: ""
    property string backwardSourceUrl: ""
    property string glowSourceUrl: ""
    property vector4d firstRect: Qt.vector4d(0,0,1,1)
    property vector4d secondRect: Qt.vector4d(0,0,1,1)
    property vector4d firstFlowRect: Qt.vector4d(0,0,1,1)
    property vector4d secondFlowRect: Qt.vector4d(0,0,1,1)
    property vector4d bodyRect: Qt.vector4d(120,20,192,208)
    property vector4d pigment: Qt.vector4d(.64,.20,.16,0)
    property vector2d flowRange: Qt.vector2d(64/384,64/416)
    property real skinIntensity: .75
    property real phase: 0
    property real morphStrength: 1
    property real bank: 0
    property real pivotOffset: 30
    property bool mirror: false
    property bool bodyVisible: true
    // No input handlers, focus scopes, timers or autonomous animation clocks.
    focus: false
    activeFocusOnTab: false
    function point(edge, t) {
        var s=1-t
        return Qt.point(s*s*edge.x0+2*s*t*edge.cx+t*t*edge.x1,
                        s*s*edge.y0+2*s*t*edge.cy+t*t*edge.y1)
    }
    function alpha(value) { return Math.max(0,Math.min(1,value)) }
    Item {
        width: 440; height: 340
        scale: Math.min(scene.width/440,scene.height/340)
        transformOrigin: Item.TopLeft
        // Window geometry remains private awareness; it is not drawn as UI
        // boxes behind the organism's memory graph.
        Image {
            visible: !!scene.cursorState.motion && scene.cursorState.motion>.02
            source: scene.glowSourceUrl
            width: 12; height: 12
            x: 48+(scene.cursorState.x || 0)*344-width/2
            y: 156+(scene.cursorState.y || 0)*146-height/2
            opacity: .12+Math.min(.2,scene.cursorState.motion || 0)
        }
        Rectangle {
            visible: scene.micActive
            x: 211; y: 295; width: 18; height: 2; radius: 1
            color: "#6076f3db"; opacity: .45+.25*Math.sin(scene.clock*2.3)
        }
        Repeater {
            model: scene.edges
            delegate: Item {
                id: edgeItem
                objectName: "graph-edge-"+entry.index
                required property var entry
                property real active: entry.activation
                property real strength: entry.weight
                property real focusStrength: entry.focusStrength===undefined ? (entry.focus?1:0) : scene.alpha(entry.focusStrength)
                property real visibility: .55+.45*(.5+.5*Math.sin(scene.clock*.31+entry.index*1.618))
                property real edgeAlpha: scene.alpha((13+strength*24+active*72+focusStrength*16)/255*visibility*scene.graphGain)
                Shape {
                    preferredRendererType: Shape.CurveRenderer
                    ShapePath {
                        fillColor: "transparent"
                        strokeColor: Qt.rgba(.26,.75,.79,edgeItem.edgeAlpha*.19)
                        strokeWidth: 4.5+edgeItem.strength
                        capStyle: ShapePath.RoundCap
                        startX: edgeItem.entry.x0; startY: edgeItem.entry.y0
                        PathQuad { x: edgeItem.entry.x1; y: edgeItem.entry.y1; controlX: edgeItem.entry.cx; controlY: edgeItem.entry.cy }
                    }
                    ShapePath {
                        fillColor: "transparent"
                        strokeColor: Qt.rgba(.50,.88,.84,edgeItem.edgeAlpha)
                        strokeWidth: .55+edgeItem.strength*.8
                        capStyle: ShapePath.RoundCap
                        startX: edgeItem.entry.x0; startY: edgeItem.entry.y0
                        PathQuad { x: edgeItem.entry.x1; y: edgeItem.entry.y1; controlX: edgeItem.entry.cx; controlY: edgeItem.entry.cy }
                    }
                }
                Image {
                    visible: edgeItem.active>.06
                    source: scene.glowSourceUrl
                    width: 14+edgeItem.active*8; height: width
                    property real phase: (scene.clock*(.08+edgeItem.active*.15)+edgeItem.entry.index*.381)%1
                    property point position: scene.point(edgeItem.entry,phase)
                    x: position.x-width/2; y: position.y-height/2
                    opacity: scene.alpha((35+edgeItem.active*100)/255*scene.graphGain)
                }
            }
        }
        Repeater {
            model: scene.nodes
            delegate: Item {
                id: nodeItem
                objectName: "graph-node-"+entry.index
                required property var entry
                x: entry.x; y: entry.y
                property real active: entry.activation
                property real focusStrength: entry.focusStrength===undefined ? (entry.focus?1:0) : scene.alpha(entry.focusStrength)
                property real contactStrength: entry.contactStrength===undefined ? (entry.contact?1:0) : scene.alpha(entry.contactStrength)
                property real radius: (1-contactStrength)*(1.2+active*2.5+focusStrength)+contactStrength*(6+active*2)
                Image {
                    source: scene.glowSourceUrl
                    width: (7+nodeItem.active*12+nodeItem.focusStrength*3)*3
                    height: width; x: -width/2; y: -height/2
                    opacity: scene.alpha((16+nodeItem.active*95+nodeItem.focusStrength*18)/255*scene.graphGain*(.75+.25*Math.sin(scene.clock*(.65+nodeItem.active)+nodeItem.entry.index*1.7)))
                }
                Rectangle {
                    x: -nodeItem.radius; y: -nodeItem.radius
                    width: nodeItem.radius*2; height: width; radius: width/2
                    color: Qt.rgba(.37*(1-nodeItem.contactStrength)+.196*nodeItem.contactStrength,
                                   .82*(1-nodeItem.contactStrength)+.431*nodeItem.contactStrength,
                                   .77*(1-nodeItem.contactStrength)+.447*nodeItem.contactStrength,
                                   (65+nodeItem.active*150)/255*(1-nodeItem.contactStrength)+nodeItem.contactStrength)
                    border.color: Qt.rgba(.67,.96,.89,scene.alpha((120+nodeItem.active*100)/255*scene.graphGain))
                    border.width: .55
                    Rectangle {
                        visible: nodeItem.contactStrength>.001
                        width: parent.width*.44; height: width; radius: width/2
                        x: parent.width*.18; y: parent.height*.12
                        color: "#abf4df"; opacity: .8*nodeItem.contactStrength
                    }
                }
                Rectangle {
                    visible: nodeItem.focusStrength>.001
                    x: -width/2; y: -height/2
                    width: (nodeItem.radius+3)*2; height: width; radius: width/2
                    color: "transparent"; border.width: .65
                    border.color: Qt.rgba(.62,.96,.87,(.15+nodeItem.active*.25)*scene.graphGain)
                    opacity: nodeItem.focusStrength*(.65+.2*Math.sin(scene.clock*.7))
                }
            }
        }
        Repeater {
            model: scene.tendrils
            delegate: Shape {
                id: arm
                required property var entry
                preferredRendererType: Shape.CurveRenderer
                ShapePath {
                    strokeColor: "#ef061c35"; strokeWidth: 1.1
                    fillGradient: LinearGradient {
                        x1: arm.entry.x0; y1: arm.entry.y0
                        x2: arm.entry.x1; y2: arm.entry.y1
                        GradientStop { position: 0; color: "#16566b" }
                        GradientStop { position: .38; color: "#276b7c" }
                        GradientStop { position: .70; color: "#54497d" }
                        GradientStop { position: 1; color: "#55d9c3" }
                    }
                    PathSvg { path: arm.entry.outline }
                }
                ShapePath {
                    fillColor: "transparent"; strokeColor: "#708cecda"; strokeWidth: .8
                    startX: arm.entry.x0; startY: arm.entry.y0
                    PathCubic { x: arm.entry.x1; y: arm.entry.y1
                        control1X: arm.entry.cx0; control1Y: arm.entry.cy0
                        control2X: arm.entry.cx1; control2Y: arm.entry.cy1 }
                }
            }
        }
        Item {
            x: scene.bodyRect.x; y: scene.bodyRect.y
            width: scene.bodyRect.z; height: scene.bodyRect.w
            visible: scene.bodyVisible
            transform: [
                Rotation { origin.x: scene.bodyRect.z/2; origin.y: scene.bodyRect.w/2+scene.pivotOffset; angle: scene.bank },
                Scale { origin.x: scene.bodyRect.z/2; origin.y: scene.bodyRect.w/2+scene.pivotOffset; xScale: scene.mirror ? -1:1 }
            ]
            Image { id: bodySource; visible: false; source: scene.bodySourceUrl; cache: false; smooth: true }
            Image { id: forwardSource; visible: false; source: scene.forwardSourceUrl; cache: false; smooth: true }
            Image { id: backwardSource; visible: false; source: scene.backwardSourceUrl; cache: false; smooth: true }
            ShaderEffect {
                id: bodyEffect
                anchors.fill: parent
                property variant bodyAtlas: bodySource
                property variant forwardAtlas: forwardSource
                property variant backwardAtlas: backwardSource
                property vector4d firstRect: scene.firstRect
                property vector4d secondRect: scene.secondRect
                property vector4d firstFlowRect: scene.firstFlowRect
                property vector4d secondFlowRect: scene.secondFlowRect
                property vector4d skinWeights: scene.pigment
                property vector2d flowRange: scene.flowRange
                property real phase: scene.phase
                property real clock: scene.skinClock
                property real intensity: scene.skinIntensity
                property real morphStrength: scene.morphStrength
                fragmentShader: Qt.resolvedUrl("../shaders/body.frag.qsb")
                blending: true
                onStatusChanged: if (status === ShaderEffect.Error) scene.rendererError(log)
            }
        }
        Repeater {
            model: scene.glyphs
            delegate: Image {
                required property var entry
                source: entry.source; x: entry.x; y: entry.y
                width: 17; height: 20; opacity: entry.opacity
            }
        }
        Rectangle {
            visible: !!scene.statusLabel.visible
            width: Math.min(396,label.implicitWidth+20); height: 24
            x: 220-width/2; y: 310; radius: 9; color: "#d20a141c"
            Text { id: label; anchors.centerIn: parent; text: scene.statusLabel.text || ""; color: "#c3eddf"; font.pixelSize: 10; elide: Text.ElideRight; width: Math.min(376,implicitWidth) }
        }
    }
}
