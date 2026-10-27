import QtQuick
import qs.Commons
import "../../denon.bar/panels" as Motion

// Glass panel host from the denon.bar plugin: animated card morphs, hover to
// preview, click to keep. Only loaded when that plugin is installed.
Motion.PopupPanel {
  id: host
  property var studio: null
  readonly property Item slot: slotItem
  function pin() { Motion.PanelMotion.pin() }
  function commitHover(owner) { return Motion.PanelMotion.commitHover(owner) }

  owner: studio
  open: studio ? studio.opened : false
  focusTarget: studio ? studio.keyboardItem : null
  padding: Style.space(12)
  centerOnBar: studio ? studio.expanded : false
  contentWidth: host.fittedContentWidth(Style.space(studio && studio.expanded ? 1020 : 420))
  contentHeight: studio && studio.expanded ? host.fittedContentHeight(Style.space(740), Style.space(740))
                                           : host.fittedContentHeight(studio ? studio.contentImplicitHeight : 0, Style.space(880))

  Item { id: slotItem; anchors.fill: parent }
}
