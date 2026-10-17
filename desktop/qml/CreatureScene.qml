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
        // The optional perception sketch contains normalized geometry only.
        Repeater {
            model: scene.desktopRects
            delegate: Rectangle {
                required property var modelData
                x: 48+modelData.x*344; y: 156+modelData.y*146
                width: modelData.w*344; height: modelData.h*146
                radius: 3; color: "#020e646a"
                border.width: .55; border.color: "#123fadb2"
            }
        }
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
                required property var modelData
                property real active: modelData.activation
                property real strength: modelData.weight
                property real visibility: .55+.45*(.5+.5*Math.sin(scene.clock*.31+modelData.index*1.618))
                property real edgeAlpha: scene.alpha((13+strength*24+active*72+(modelData.focus?16:0))/255*visibility*scene.graphGain)
                Shape {
                    preferredRendererType: Shape.CurveRenderer
                    ShapePath {
                        fillColor: "transparent"
                        strokeColor: Qt.rgba(.26,.75,.79,edgeItem.edgeAlpha*.19)
                        strokeWidth: 4.5+edgeItem.strength
                        capStyle: ShapePath.RoundCap
                        startX: edgeItem.modelData.x0; startY: edgeItem.modelData.y0
                        PathQuad { x: edgeItem.modelData.x1; y: edgeItem.modelData.y1; controlX: edgeItem.modelData.cx; controlY: edgeItem.modelData.cy }
                    }
                    ShapePath {
                        fillColor: "transparent"
                        strokeColor: Qt.rgba(.50,.88,.84,edgeItem.edgeAlpha)
                        strokeWidth: .55+edgeItem.strength*.8
                        capStyle: ShapePath.RoundCap
                        startX: edgeItem.modelData.x0; startY: edgeItem.modelData.y0
                        PathQuad { x: edgeItem.modelData.x1; y: edgeItem.modelData.y1; controlX: edgeItem.modelData.cx; controlY: edgeItem.modelData.cy }
                    }
                }
                Image {
                    visible: edgeItem.active>.06
                    source: scene.glowSourceUrl
                    width: 14+edgeItem.active*8; height: width
                    property real phase: (scene.clock*(.08+edgeItem.active*.15)+edgeItem.modelData.index*.381)%1
                    property point position: scene.point(edgeItem.modelData,phase)
                    x: position.x-width/2; y: position.y-height/2
                    opacity: scene.alpha((35+edgeItem.active*100)/255*scene.graphGain)
                }
            }
        }
        Repeater {
            model: scene.nodes
            delegate: Item {
                id: nodeItem
                required property var modelData
                x: modelData.x; y: modelData.y
                property real active: modelData.activation
                property real radius: modelData.contact ? 6+active*2 : 1.2+active*2.5+(modelData.focus?1:0)
                Image {
                    source: scene.glowSourceUrl
                    width: (7+nodeItem.active*12+(nodeItem.modelData.focus?3:0))*3
                    height: width; x: -width/2; y: -height/2
                    opacity: scene.alpha((16+nodeItem.active*95+(nodeItem.modelData.focus?18:0))/255*scene.graphGain*(.75+.25*Math.sin(scene.clock*(.65+nodeItem.active)+nodeItem.modelData.index*1.7)))
                }
                Rectangle {
                    x: -nodeItem.radius; y: -nodeItem.radius
                    width: nodeItem.radius*2; height: width; radius: width/2
                    color: nodeItem.modelData.contact ? "#326e72" : Qt.rgba(.37,.82,.77,(65+nodeItem.active*150)/255)
                    border.color: Qt.rgba(.67,.96,.89,scene.alpha((120+nodeItem.active*100)/255*scene.graphGain))
                    border.width: .55
                    Rectangle {
                        visible: nodeItem.modelData.contact
                        width: parent.width*.44; height: width; radius: width/2
                        x: parent.width*.18; y: parent.height*.12
                        color: "#abf4df"; opacity: .8
                    }
                }
                Rectangle {
                    visible: nodeItem.modelData.focus
                    x: -width/2; y: -height/2
                    width: (nodeItem.radius+3)*2; height: width; radius: width/2
                    color: "transparent"; border.width: .65
                    border.color: Qt.rgba(.62,.96,.87,(.15+nodeItem.active*.25)*scene.graphGain)
                    opacity: .65+.2*Math.sin(scene.clock*.7)
                }
            }
        }
        Repeater {
            model: scene.tendrils
            delegate: Shape {
                id: arm
                required property var modelData
                preferredRendererType: Shape.CurveRenderer
                ShapePath {
                    strokeColor: "#ef061c35"; strokeWidth: 1.1
                    fillGradient: LinearGradient {
                        x1: arm.modelData.x0; y1: arm.modelData.y0
                        x2: arm.modelData.x1; y2: arm.modelData.y1
                        GradientStop { position: 0; color: "#16566b" }
                        GradientStop { position: .38; color: "#276b7c" }
                        GradientStop { position: .70; color: "#54497d" }
                        GradientStop { position: 1; color: "#55d9c3" }
                    }
                    PathSvg { path: arm.modelData.outline }
                }
                ShapePath {
                    fillColor: "transparent"; strokeColor: "#708cecda"; strokeWidth: .8
                    startX: arm.modelData.x0; startY: arm.modelData.y0
                    PathCubic { x: arm.modelData.x1; y: arm.modelData.y1
                        control1X: arm.modelData.cx0; control1Y: arm.modelData.cy0
                        control2X: arm.modelData.cx1; control2Y: arm.modelData.cy1 }
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
                required property var modelData
                source: modelData.source; x: modelData.x; y: modelData.y
                width: 17; height: 20; opacity: modelData.opacity
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
