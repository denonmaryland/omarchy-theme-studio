import QtQuick
import qs.Ui
import qs.Commons

// Omarchy's stock popup card. Best Theme Plugin Ever reparents its content into `slot`.
KeyboardPanel {
  id: host
  property var studio: null
  readonly property Item slot: slotItem
  function pin() {}
  function commitHover(owner) { return false }

  owner: studio
  open: studio ? studio.opened : false
  focusTarget: studio ? studio.keyboardItem : null
  padding: Style.space(12)
  centerOnBar: studio ? studio.expanded : false
  contentWidth: host.fittedContentWidth(Style.space(studio && studio.expanded ? 1020 : 420))
  contentHeight: studio && studio.expanded ? host.fittedContentHeight(Style.space(740), Style.space(740))
                                           : host.fittedContentHeight(studio ? studio.contentImplicitHeight : 0, Style.space(880))

  Item { id: slotItem; anchors.fill: parent; clip: true }
}
