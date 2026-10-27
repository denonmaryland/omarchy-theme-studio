import QtQuick
import QtQuick.Controls as QQC
import Quickshell
import Quickshell.Io
import Quickshell.Widgets
import qs.Ui
import qs.Commons
import qs.Commons as Commons

// Theme Studio: browse, apply and rotate themes, and install new ones from a
// pasted link (git repo, theme store page, archive, or images → generated theme).
Panel {
  id: root
  moduleName: "io.github.denonmaryland.theme-studio"
  ipcTarget: "io.github.denonmaryland.theme-studio"
  manageIpc: false
  implicitWidth: icon.implicitWidth
  implicitHeight: icon.implicitHeight

  readonly property color fg: bar ? bar.foreground : Color.foreground
  readonly property color accent: Commons.Color.accent
  readonly property color urgent: Commons.Color.urgent
  readonly property string family: bar ? bar.fontFamily : Style.font.family
  readonly property string glyphFamily: Style.font.family
  readonly property string home: Quickshell.env("HOME")
  // Helpers ship inside the plugin folder (the shell loads plugins via qs:// URLs).
  readonly property string pluginDir: decodeURIComponent(Qt.resolvedUrl(".").toString().replace(/^(file|qs):\/\//, "")).replace(/\/$/, "")
  readonly property string helper: pluginDir + "/helpers/control.py"
  readonly property string importer: pluginDir + "/helpers/importer.py"
  readonly property string discoverer: pluginDir + "/helpers/discover.py"
  readonly property string wallpaperer: pluginDir + "/helpers/wallpapers.py"

  property var values: ({ enabled: false, interval_minutes: 15, current_name: "Loading…", themes: [], backgrounds: [],
                          seconds_remaining: null, shuffle_background: false, pending_review: null, current_palette: [] })
  property bool loaded: false
  property string message: ""

  // Navigation
  property int tab: 0
  property string query: ""
  property bool favoritesOnly: false
  property string themeMode: "all"
  property var filtered: []
  // Wide two-pane layout: sidebar on the left, a big gallery on the right.
  property bool expanded: false
  readonly property string uiFile: home + "/.local/state/omarchy-theme-studio/ui-layout"
  // Fade the content out, swap layouts while the card resizes, then settle back in,
  // so neither layout is ever seen reflowing inside a frame of the wrong size.
  property bool pendingExpanded: false
  function toggleExpanded() { setExpanded(layoutSwap.running ? !pendingExpanded : !expanded) }
  function setExpanded(on) {
    if (on === expanded && !layoutSwap.running) return
    if (opened) {
      if (popup) popup.pin()  // the card moves out from under the pointer; don't hover-close it
      pendingExpanded = on
      layoutSwap.restart()
    } else {
      expanded = on
    }
    Quickshell.execDetached(["sh", "-c", "mkdir -p \"$(dirname \"$2\")\" && printf %s \"$1\" > \"$2\"", "sh", on ? "wide" : "compact", uiFile])
  }
  property int matchCount: 0
  // Lookalikes: near-identical themes collapse into one stacked tile.
  property bool groupLookalikes: true
  property string openGroup: ""
  property string openGroupName: ""

  // Discover: community themes not installed yet
  property string themeScope: "installed"
  property var discover: []
  property var discoverModel: []
  property bool discoverLoaded: false
  property bool discoverWanted: false
  property string discoverError: ""
  property string discoverSort: "popular"
  property var discoverPick: null
  property string discoverProgress: ""
  property string discoverInstallError: ""
  property bool discoverThumbsDone: false

  // Wallpaper catalog (Backgrounds → Find more)
  property string bgScope: "theme"
  property var wallResults: []
  property string wallQuery: ""
  property int wallPage: 1
  property bool wallHasMore: false
  property bool wallLoaded: false
  property string wallError: ""
  property var wallSuggest: []
  property var wallPick: null
  property var wallNext: null
  property string wallSaving: ""
  property var gridModel: [{ surprise: true }]
  property int cursor: -1
  property bool menuOpen: false
  property bool confirmDelete: false
  property bool borderOpen: false
  onBorderOpenChanged: if (!borderOpen) borderHover = ""
  property string borderHover: ""    // swatch label shown in the picker subtitle
  property string borderPending: ""  // choice shown before the helper confirms it
  readonly property var borderInfo: values.border || ({ choice: "theme", global: "theme", options: [], default: "" })
  readonly property string borderChoice: !borderInfo.installed ? "theme"
    : borderPending || (borderInfo.choice === "default" ? "theme" : borderInfo.choice) || "theme"
  property string borderGlobalPending: ""
  readonly property bool borderGlobalNone: (borderGlobalPending || borderInfo.global) === "none"
  // Plain values for the ⋯ menu model: they only notify when they really
  // change, so the 5-second refresh doesn't rebuild the menu under the mouse.
  readonly property bool menuHasVariant: !!values.variant_target
  readonly property bool menuCanDelete: !!values.can_delete_current
  readonly property string menuVariantLabel: "Switch to " + (String(values.current).endsWith("-light") ? "dark" : "light") + " variant"
  property bool showHelp: false

  // Importer
  readonly property bool linkMode: isLink(query)
  property var linkInfo: null
  property string linkError: ""
  property string importProgress: ""
  property string importName: ""
  property string importMode: "auto"
  property bool importApply: true

  // Theme switching is optimistic and latest-click-wins: the grid and hero
  // show the requested theme immediately, one switch runs at a time, and a
  // click made during a switch replaces whatever was still waiting.
  // Back: repeated presses walk a snapshot of Recent instead of bouncing
  // between the last two themes. Any other pick starts a fresh trail.
  property var backTrail: []
  property int backStep: 0
  readonly property var backList: backTrail.length ? backTrail : (values.recent || [])
  readonly property string backTarget: backStep < backList.length ? backList[backStep] : ""
  function goBack() {
    if (!backTarget) return
    if (!backTrail.length) backTrail = (values.recent || []).slice()
    let slug = backTarget
    backStep += 1
    requestTheme(slug, true)
  }
  function resetBack() { backTrail = []; backStep = 0 }
  property string wantTheme: ""      // slug or "*random*" still to apply
  property string activeTheme: ""    // request currently running in themeProc
  property int themeSeq: 0           // bumped per click; tells repeat randoms apart
  property int activeSeq: 0          // themeSeq of the request in themeProc
  property string optimistic: ""     // slug shown as current before it lands
  readonly property string shownCurrent: optimistic || values.current || ""
  readonly property var shownItem: (values.themes || []).find(t => t.slug === shownCurrent) || null
  readonly property bool switching: themeProc.running || !!wantTheme
  property var actQueue: []
  property string lastAction: ""
  readonly property real sidebarWidth: Style.space(352)
  readonly property int gridCols: expanded ? Math.max(3, Math.floor(rightPane.width / Style.space(200))) : 3
  readonly property bool busy: actionProc.running || actQueue.length > 0
  readonly property bool importing: importProc.running
  readonly property bool reviewing: !!values.pending_review && values.pending_review === values.current

  function alphaOf(c, a) { return Qt.rgba(c.r, c.g, c.b, a) }
  function luminance(c) {
    const lin = v => v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4)
    return 0.2126 * lin(c.r) + 0.7152 * lin(c.g) + 0.0722 * lin(c.b)
  }
  // The review card sits above the grids, so showing or hiding it moves every
  // tile. Hold it while picks land or the pointer is over a grid; it settles
  // once the pointer leaves or the panel closes.
  property bool reviewShown: false
  property string reviewSlug: ""
  property string reviewName: ""
  readonly property bool holdReview: switching || gridHover.hovered || discoverHover.hovered || wallHover.hovered
  readonly property bool canRate: reviewing && !switching && values.pending_review === reviewSlug
  function syncReview() {
    if (opened && holdReview) return
    reviewShown = reviewing
    if (reviewing) { reviewSlug = values.pending_review; reviewName = values.current_name || "" }
  }
  onReviewingChanged: syncReview()
  onHoldReviewChanged: syncReview()

  function isLink(text) {
    let parts = String(text || "").trim().split(/\s+/).filter(p => p.length)
    if (!parts.length) return false
    return parts.every(p => /^(https?:\/\/|git@|ssh:\/\/|git:\/\/|file:\/\/|~\/|\/)/i.test(p)
                         || /^[\w-]+(\.[\w-]+)+\/\S+/.test(p))
  }

  function rebuild() {
    let words = query.trim().toLowerCase().split(/\s+/).filter(w => w.length)
    let pool = values.themes || []
    if (themeScope === "recent") {
      let bySlug = {}
      for (const t of pool) bySlug[t.slug] = t
      pool = (values.recent || []).map(slug => bySlug[slug]).filter(t => !!t)
    }
    let items = pool.filter(item => (!favoritesOnly || item.favorite)
      && (themeMode === "all" || item.mode === themeMode)
      && (isLink(query) || words.every(w => (item.name + " " + item.slug).toLowerCase().indexOf(w) !== -1)))
    matchCount = items.length
    if (openGroup) items = items.filter(i => i.group === openGroup)
    else if (groupLookalikes && !words.length && themeScope === "installed") items = collapse(items)
    let tiles = (themeScope === "recent" || words.length || favoritesOnly || openGroup || themeMode !== "all" || !items.length ? [] : [{ surprise: true }]).concat(items)
    if (JSON.stringify(tiles) === JSON.stringify(gridModel)) return
    // Same tiles in the same order (e.g. a favorite toggled): keep the cursor
    // and scroll position instead of jumping back to the top.
    let sameOrder = tiles.length === gridModel.length && tiles.every((t, i) => t.slug === gridModel[i].slug)
    let keepY = grid.contentY
    if (!sameOrder) cursor = -1
    filtered = items
    gridModel = tiles
    if (sameOrder) grid.contentY = keepY
    if (cursor >= gridModel.length) cursor = gridModel.length - 1
  }
  // One tile per lookalike group: the current theme, else a favorite, else
  // the first by name represents it; `stack` counts the members.
  function collapse(items) {
    let groups = {}, out = []
    for (const i of items) {
      let g = i.group || i.slug
      ;(groups[g] = groups[g] || []).push(i)
    }
    for (const i of items) {
      let g = i.group || i.slug, members = groups[g]
      if (!members) continue
      delete groups[g]
      let rep = members.find(x => x.slug === shownCurrent) || members.find(x => x.favorite) || members[0]
      out.push(members.length > 1 ? Object.assign({}, rep, { stack: members.length }) : rep)
    }
    return out
  }
  property real groupReturnY: 0  // gallery scroll to restore when leaving a lookalike group
  function openLookalikes(item) {
    groupReturnY = grid.contentY
    openGroupName = item.name
    openGroup = item.group
    rebuild(); grid.positionViewAtBeginning()
  }
  function closeLookalikes() {
    openGroup = ""; rebuild()
    Qt.callLater(() => { grid.contentY = Math.min(groupReturnY, Math.max(0, grid.contentHeight - grid.height)) })
  }
  onGroupLookalikesChanged: { openGroup = ""; rebuild(); grid.positionViewAtBeginning() }
  onThemeModeChanged: { rebuild(); rebuildDiscover(); grid.positionViewAtBeginning() }
  onFavoritesOnlyChanged: { rebuild(); grid.positionViewAtBeginning() }
  onDiscoverSortChanged: { rebuildDiscover(); discoverGrid.positionViewAtBeginning() }
  onThemeScopeChanged: {
    cursor = -1
    if (themeScope !== "discover") { rebuild(); grid.positionViewAtBeginning() }
    if (themeScope === "discover") loadDiscover(false)
  }
  onBgScopeChanged: { if (bgScope === "more" && !wallLoaded) { loadWallSuggestions(); searchWalls("", 1) } }
  onQueryChanged: {
    rebuild()
    rebuildDiscover()
    linkInfo = null; linkError = ""; importProgress = ""
    if (isLink(query)) inspectTimer.restart()
  }

  function helperError(text) {
    let line = String(text || "").trim().split("\n").pop() || ""
    line = line.replace(/^theme-studio:\s*/, "")
    return line ? line : "That didn't work."
  }
  function refresh() { if (!readProc.running) readProc.running = true }
  function receive(text) {
    try {
      let updated = JSON.parse(text)
      if (values.current !== updated.current) { confirmDelete = false; borderOpen = false }
      if (!actQueue.some(a => a[0] === "border" || a[0] === "border-default")) { borderPending = ""; borderGlobalPending = "" }
      values = updated
      loaded = true
      rebuild()
      if (updated.last_error) message = updated.last_error
    } catch (e) { message = "Could not read theme settings." }
  }
  // Other actions queue instead of being dropped while something else runs.
  function borderColorOf(choice) {
    if (choice === "none") return "transparent"
    if (choice === "default" || choice === "theme") return borderInfo.default || accent
    let o = (borderInfo.options || []).find(i => i.key === choice)
    return o ? o.color : accent
  }
  function pickBorder(choice) {
    borderPending = choice
    act("border", choice)
  }
  // "No color on every theme": the current theme follows unless it has its own pick.
  function setBorderGlobal(none) {
    let value = none ? "none" : "theme"
    if (borderChoice === (borderInfo.global || "theme")) borderPending = value
    borderGlobalPending = value
    act("border-default", value)
  }
  function act(action, value) {
    if (action === "random") { requestTheme("*random*"); return }
    if (action === "border" || action === "border-default") actQueue = actQueue.filter(a => a[0] !== action)  // last pick wins
    actQueue = actQueue.concat([[action].concat(value === undefined ? [] : [String(value)])])
    runQueue()
  }
  function runQueue() {
    if (actionProc.running || !actQueue.length) return
    let next = actQueue[0]
    actQueue = actQueue.slice(1)
    lastAction = next[0]
    if (next[0] !== "favorite" && next[0] !== "border" && next[0] !== "border-default") message = "Applying…"
    actionProc.command = ["/usr/bin/python3", helper].concat(next)
    actionProc.running = true
  }
  function themeName(slug) {
    let t = (values.themes || []).find(i => i.slug === slug)
    return t ? t.name : slug
  }
  function requestTheme(slug, fromBack) {
    if (!slug) return
    if (!fromBack) resetBack()
    themeSeq++
    wantTheme = slug
    optimistic = slug === "*random*" ? "" : slug
    message = slug === "*random*" ? "Picking a theme…" : "Applying " + themeName(slug) + "…"
    pumpTheme()
  }
  function pumpTheme() {
    if (themeProc.running) return
    let slug = wantTheme
    if (!slug || (slug !== "*random*" && slug === values.current)) {
      wantTheme = ""; optimistic = ""
      if (!themeError) message = ""
      return
    }
    themeError = false
    activeTheme = slug
    activeSeq = themeSeq
    wantTheme = slug === "*random*" ? "" : slug
    themeProc.command = slug === "*random*" ? ["/usr/bin/python3", helper, "random"] : ["/usr/bin/python3", helper, "theme-select", slug]
    themeProc.running = true
  }
  property bool themeError: false
  function remaining() {
    if (!values.enabled) return "Rotation paused"
    return "Next theme in " + Math.max(1, Math.ceil((values.seconds_remaining || 0) / 60)) + " min"
  }
  function activateTile(item) {
    if (!item) return
    if (item.surprise) requestTheme("*random*")
    else if (item.slug !== shownCurrent) requestTheme(item.slug)
  }
  function moveCursor(dx, dy) {
    if (tab !== 0 || linkMode || themeScope === "discover") return
    let n = gridModel.length
    if (!n) return
    let next = cursor < 0 ? Math.max(0, gridModel.findIndex(i => i.slug === shownCurrent)) : cursor + dx + dy * gridCols
    cursor = Math.max(0, Math.min(n - 1, next))
    grid.positionViewAtIndex(cursor, GridView.Contain)
  }
  function startImport() {
    if (importing || busy || !linkMode || !linkInfo || linkError) return
    linkError = ""
    importProgress = "Starting…"
    let cmd = ["/usr/bin/python3", importer, "install", query.trim(), "--mode", importMode]
    if (linkInfo && linkInfo.images && importName.trim()) cmd = cmd.concat(["--name", importName.trim()])
    if (importApply) cmd.push("--apply")
    importProc.command = cmd
    importProc.running = true
  }
  // ---- Discover
  function loadDiscover(refresh) {
    if (discoverProc.running) { discoverWanted = true; return }
    discoverError = ""
    discoverProc.command = ["/usr/bin/python3", discoverer, "list"].concat(refresh ? ["--refresh"] : [])
    discoverProc.running = true
  }
  function receiveDiscover(text) {
    try {
      let r = JSON.parse(text)
      if (!r.ok) { discoverError = r.error || "Couldn't load community themes."; return }
      discover = r.themes || []
      discoverLoaded = true
      rebuildDiscover()
      if (!discoverThumbsDone && !discoverThumbsProc.running && discover.some(t => !t.preview)) discoverThumbsProc.running = true
    } catch (e) { discoverError = "Couldn't load community themes." }
  }
  function rebuildDiscover() {
    let words = query.trim().toLowerCase().split(/\s+/).filter(w => w.length)
    // Same name as an installed theme (e.g. a different repo of it) counts as installed.
    let have = {}
    for (const t of (values.themes || [])) have[String(t.name).toLowerCase()] = true
    let items = discover.filter(t => !t.installed && !have[String(t.name).toLowerCase()]
      && (themeMode === "all" || t.mode === themeMode)
      && (isLink(query) || words.every(w => (t.name + " " + t.owner + " " + t.hue + " " + (t.description || "")).toLowerCase().indexOf(w) !== -1)))
    if (discoverSort === "new") items = items.slice().sort((a, b) => String(b.pushed_at).localeCompare(String(a.pushed_at)))
    if (JSON.stringify(items) === JSON.stringify(discoverModel)) return
    let sameOrder = items.length === discoverModel.length && items.every((t, i) => t.id === discoverModel[i].id)
    let keepY = discoverGrid.contentY
    discoverModel = items
    if (sameOrder) discoverGrid.contentY = keepY
    if (discoverPick) discoverPick = discover.find(t => t.id === discoverPick.id) || null
  }
  function installDiscover(apply) {
    if (!discoverPick || discoverInstallProc.running || importing) return
    discoverInstallError = ""
    discoverProgress = "Starting…"
    discoverInstallProc.command = ["/usr/bin/python3", discoverer, "install", discoverPick.id].concat(apply ? ["--apply"] : [])
    discoverInstallProc.running = true
  }
  function discoverLine(line) {
    let msg
    try { msg = JSON.parse(line) } catch (e) { return }
    if (msg.progress) { discoverProgress = msg.progress; return }
    if (msg.ok) {
      message = (msg.applied ? "Installed and applied " : "Installed ") + (msg.name || msg.slug)
      discoverPick = null
      discoverProgress = ""
      Qt.callLater(refresh)
      Qt.callLater(() => loadDiscover(false))
    } else if (msg.error) {
      discoverInstallError = msg.error
      discoverProgress = ""
    }
  }

  // ---- Wallpaper catalog
  function loadWallSuggestions() {
    if (!wallSuggestProc.running) wallSuggestProc.running = true
  }
  function searchWalls(q, page) {
    if (wallProc.running) { wallNext = [q, page]; return }
    wallError = ""
    wallQuery = q
    wallPage = page
    if (page === 1) wallPick = null
    wallProc.command = ["/usr/bin/python3", wallpaperer, "search"].concat(q ? [q] : []).concat(["--page", String(page)])
    wallProc.running = true
  }
  function receiveWalls(text) {
    try {
      let r = JSON.parse(text)
      if (!r.ok) { wallError = r.error || "Couldn't search wallpapers."; return }
      wallResults = r.page > 1 ? wallResults.concat(r.results || []) : (r.results || [])
      wallHasMore = !!r.has_more
      wallLoaded = true
      if (r.page === 1) wallGrid.positionViewAtBeginning()
    } catch (e) { wallError = "Couldn't search wallpapers." }
  }
  function saveWall(item, apply) {
    if (!item || wallSaveProc.running) return
    wallSaving = item.id
    message = apply ? "Setting background…" : "Saving to " + (values.current_name || "theme") + "…"
    wallSaveProc.command = ["/usr/bin/python3", wallpaperer, "save", item.id, "--theme", String(values.current)].concat(apply ? ["--apply"] : [])
    wallSaveProc.running = true
  }
  function receiveWallSave(text) {
    try {
      let r = JSON.parse(text)
      if (!r.ok) { message = "That didn't work: " + (r.error || "save failed"); return }
      message = r.applied ? "Background set · credit saved" : "Saved to " + (values.current_name || "theme")
      Qt.callLater(refresh)
    } catch (e) { message = "That didn't work. Check the service log." }
  }

  // ---- Follow the sun
  function sunTime(epoch) { return epoch ? Qt.formatTime(new Date(epoch * 1000), "h:mm AP") : "—" }

  function importLine(line) {
    let msg
    try { msg = JSON.parse(line) } catch (e) { return }
    if (msg.progress) { importProgress = msg.progress; return }
    if (msg.ok) {
      message = (msg.applied ? "Installed and applied " : "Installed ") + msg.name
      search.text = ""
      importName = ""
      tab = 0
      Qt.callLater(refresh)
    } else if (msg.error) {
      linkError = msg.error
      importProgress = ""
    }
  }

  Component.onCompleted: refresh()
  FileView {
    path: root.uiFile
    printErrors: false
    onLoaded: root.expanded = text().trim() === "wide"
  }
  onOpenedChanged: {
    syncReview()
    if (opened) {
      refresh()
      if (!thumbsProc.running) thumbsProc.running = true
      if (!discoverLoaded) loadDiscover(false)
      cursor = -1
    } else { menuOpen = false; confirmDelete = false; showHelp = false; borderOpen = false; resetBack() }
  }

  Timer {
    id: inspectTimer
    interval: 450
    onTriggered: {
      if (!root.isLink(root.query)) return
      inspectProc.command = ["/usr/bin/python3", root.importer, "inspect", root.query.trim()]
      inspectProc.running = true
    }
  }
  // Live refresh only while the panel is open.
  Timer { interval: 5000; repeat: true; running: root.opened; onTriggered: root.refresh() }
  // Rotation and Follow the sun run from the shell (no background service):
  // a cheap tick while either is on.
  Timer {
    interval: 20000; repeat: true; triggeredOnStart: true
    running: root.loaded && !!(root.values.enabled || (root.values.sun && root.values.sun.enabled))
    onTriggered: if (!tickProc.running) tickProc.running = true
  }
  Process {
    id: tickProc
    command: ["/usr/bin/python3", root.helper, "tick"]
    stdout: StdioCollector { onStreamFinished: root.receive(text) }
  }
  // Theme changes from anywhere (Omarchy menu, other tools) feed Recent / Back.
  FileView {
    path: root.home + "/.local/state/omarchy/current/theme.name"
    watchChanges: true
    printErrors: false
    onFileChanged: { reload(); historyTimer.restart() }
  }
  Timer { id: historyTimer; interval: 800; onTriggered: root.refresh() }
  Timer { id: wallNextTimer; interval: 50; onTriggered: { let n = root.wallNext; root.wallNext = null; if (n) root.searchWalls(n[0], n[1]) } }

  IpcHandler {
    target: "io.github.denonmaryland.theme-studio"
    function open(): void { root.open(); root.refresh() }
    function close(): void { root.close() }
    // Development aid: swap the popup host live ("stock" or "glass").
    function host(kind: string): string {
      root.close()
      root.useGlassHost = kind === "glass"
      hostLoader.setSource(root.useGlassHost ? "hosts/GlassHost.qml" : "hosts/StockHost.qml", { studio: root, anchorItem: icon, bar: root.bar })
      return root.useGlassHost ? "glass" : "stock"
    }
    function border(): void { root.open(); root.refresh(); root.menuOpen = false; root.borderOpen = true }
    function review(): void { root.open(); root.refresh() }
    function state(): string { return JSON.stringify(root.values) }
    function backgroundStep(direction: int): void { root.act("background-step", direction) }
    function browseThemes(favorites: bool, query: string): void {
      root.tab = 0; root.favoritesOnly = favorites; search.text = query; root.open(); root.refresh()
    }
    function themeStep(direction: int): void { root.moveCursor(direction, 0) }
    function browserState(): string {
      let item = root.gridModel[root.cursor]
      return JSON.stringify({ tab: root.tab, favorites: root.favoritesOnly, mode: root.themeMode, query: root.query, count: root.filtered.length,
                              selected: item ? (item.slug || "surprise") : "", link: root.linkMode })
    }
    function applyPreview(): void { root.activateTile(root.gridModel[root.cursor]) }
    function favoritePreview(): void { let i = root.gridModel[root.cursor]; if (i && i.slug) root.act("favorite", i.slug) }
    function filterMode(mode: string): void { if (["all", "dark", "light"].indexOf(mode) >= 0) root.themeMode = mode }
    function expand(on: bool): void { root.setExpanded(on) }
    function setTab(index: int): void { root.tab = Math.max(0, Math.min(2, index)) }
    function setScope(scope: string): void { if (scope === "installed" || scope === "discover") { root.tab = 0; root.themeScope = scope } }
    function setBgScope(scope: string): void { if (scope === "theme" || scope === "more") { root.tab = 1; root.bgScope = scope } }
    function groupLookalikes(on: bool): void { root.groupLookalikes = on }
    function openGroupOf(slug: string): void { let i = (root.values.themes || []).find(t => t.slug === slug); if (i && i.group) root.openLookalikes(i) }
    function pickDiscover(index: int): void { root.discoverPick = root.discoverModel[index] || null }
    function pickWall(index: int): void { root.wallPick = root.wallResults[index] || null }
    function searchWallpapers(q: string): void { root.tab = 1; root.bgScope = "more"; root.searchWalls(q, 1) }
    function setImportMode(mode: string): void { root.importMode = mode }
    function uiState(): string {
      return JSON.stringify({ scope: root.themeScope, bgScope: root.bgScope, tiles: root.gridModel.length, matches: root.matchCount,
        stacks: root.gridModel.filter(t => t.stack > 1).length, openGroup: root.openGroup, discover: root.discoverModel.length,
        discoverError: root.discoverError, pick: root.discoverPick ? root.discoverPick.id : "", walls: root.wallResults.length,
        wallError: root.wallError, wallPick: root.wallPick ? root.wallPick.id : "", profiles: root.linkInfo && root.linkInfo.profiles ? root.linkInfo.profiles.length : 0,
        importMode: root.importMode, sun: root.values.sun || null,
        layout: { expanded: root.expanded, pane: [rightPane.width, rightPane.height], body: [themesBody.y, themesBody.height, themesBody.parent === themesSlot],
                  dcol: discoverCol.y, dgrid: [discoverGrid.y, discoverGrid.height, discoverGrid.contentY, discoverGrid.originY], grid: [grid.y, grid.height, grid.contentY, grid.originY],
                  bg: [bgBody.parent === bgSlot, bgBody.visible, bgBody.x, bgBody.y, bgBody.width, bgBody.height],
                  rot: [rotBody.parent === rotSlot, rotBody.visible, rotBody.x, rotBody.y, rotBody.width, rotBody.height],
                  rotDbg: [rotBody.opacity, rotBody.children.length, rotBody.children.map(c => [c.visible, c.width, c.height, c.opacity]),
                           rotationTab.visible, rotationTab.y, rotationTab.height, String(rotBody.parent), rotBody.mapToItem(content, 0, 0).y, content.height] } })
    }
    function install(link: string): void { root.tab = 0; root.open(); search.text = link }
    function confirmInstall(apply: bool): void { root.importApply = apply; root.startImport() }
    function importState(): string { return JSON.stringify({ link: root.linkMode, info: root.linkInfo, error: root.linkError, progress: root.importProgress, busy: root.importing, name: root.importName, message: root.message }) }
  }

  Process {
    id: readProc
    command: ["/usr/bin/python3", root.helper, "state"]
    stdout: StdioCollector { onStreamFinished: root.receive(text) }
  }
  Process {
    id: actionProc
    stdout: StdioCollector { onStreamFinished: root.receive(text) }
    stderr: StdioCollector { id: actionErr }
    onExited: function(code) {
      root.message = code !== 0 ? root.helperError(actionErr.text) : (root.switching ? root.message : "")
      // A deleted community theme belongs back in Discover.
      if (code === 0 && root.lastAction === "remove-current") Qt.callLater(() => root.loadDiscover(false))
      Qt.callLater(root.refresh)
      Qt.callLater(root.runQueue)
    }
  }
  Process {
    id: themeProc
    stdout: StdioCollector { onStreamFinished: root.receive(text) }
    onExited: function(code) {
      if (code !== 0) {
        // Drop the failed pick; keep a newer click if one is waiting.
        if (root.themeSeq === root.activeSeq) root.wantTheme = ""
        if (!root.wantTheme) root.optimistic = ""
        root.themeError = true
        root.message = "That theme didn't apply. It may have been removed; try another."
      }
      root.activeTheme = ""
      Qt.callLater(root.pumpTheme)
      Qt.callLater(root.refresh)
    }
  }
  Process {
    id: discoverProc
    stdout: StdioCollector { onStreamFinished: root.receiveDiscover(text) }
    onExited: { if (root.discoverWanted) { root.discoverWanted = false; Qt.callLater(() => root.loadDiscover(false)) } }
  }
  Process {
    id: discoverThumbsProc
    command: ["/usr/bin/python3", root.discoverer, "thumbs"]
    onExited: { root.discoverThumbsDone = true; Qt.callLater(() => root.loadDiscover(false)) }
  }
  Process {
    id: discoverInstallProc
    stdout: SplitParser { onRead: function(line) { root.discoverLine(line) } }
    onExited: function(code) { if (code !== 0 && !root.discoverInstallError) root.discoverInstallError = "Install failed."; root.discoverProgress = "" }
  }
  Process {
    id: wallProc
    stdout: StdioCollector { onStreamFinished: root.receiveWalls(text) }
    onExited: { if (root.wallNext) wallNextTimer.restart() }
  }
  Process {
    id: wallSuggestProc
    command: ["/usr/bin/python3", root.wallpaperer, "suggestions"]
    stdout: StdioCollector { onStreamFinished: { try { let r = JSON.parse(text); if (r.ok) root.wallSuggest = r.queries || [] } catch (e) {} } }
  }
  Process {
    id: wallSaveProc
    stdout: StdioCollector { onStreamFinished: root.receiveWallSave(text) }
    onExited: { root.wallSaving = "" }
  }
  Process {
    id: thumbsProc
    command: ["/usr/bin/python3", root.helper, "thumbs"]
    onExited: Qt.callLater(root.refresh)
  }
  Process {
    id: inspectProc
    stdout: StdioCollector {
      onStreamFinished: {
        let lines = text.trim().split("\n")
        try {
          let r = JSON.parse(lines[lines.length - 1])
          if (r.ok) {
            root.linkInfo = r
            if (r.images && !root.importName) root.importName = r.title || ""
          } else root.linkError = r.error
        } catch (e) { root.linkError = "Couldn't read that link." }
      }
    }
  }
  Process {
    id: importProc
    stdout: SplitParser { onRead: function(line) { root.importLine(line) } }
    onExited: function(code) { if (code !== 0 && !root.linkError) root.linkError = "Install failed." ; root.importProgress = "" }
  }

  BarIconButton {
    id: icon
    anchors.fill: parent
    bar: root.bar
    text: "󰏘"
    tooltipText: "Theme Studio · rotation " + (root.values.enabled ? "on" : "paused")
    onPressed: if (!(popup && popup.commitHover(root))) root.toggle()
  }

  // ---------------------------------------------------------------- pieces
  // Inset tile that groups related rows (foreground at 5% over the card).
  component GlassTile: Rectangle {
    property color foreground: Commons.Color.foreground
    radius: Math.max(6, Style.cornerRadius - Style.space(4))
    color: Qt.rgba(foreground.r, foreground.g, foreground.b, 0.05)
  }
  component HeroChip: Rectangle {
    id: chip
    property string glyph: ""
    property string tip: ""
    property bool lit: false
    signal clicked()
    width: Style.space(30); height: width; radius: width / 2
    color: chipMouse.containsMouse ? Qt.rgba(0.04, 0.04, 0.03, 0.78) : Qt.rgba(0.04, 0.04, 0.03, 0.55)
    border.width: 1
    border.color: Qt.rgba(1, 1, 1, chipMouse.containsMouse ? 0.3 : 0.15)
    Text {
      anchors.centerIn: parent
      text: chip.glyph
      color: chip.lit ? root.accent : "#fff7e3"
      font.family: root.glyphFamily
      font.pixelSize: Style.font.body + 1
    }
    MouseArea { id: chipMouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: chip.clicked() }
    PanelToolTip { visible: chipMouse.containsMouse && chip.tip !== ""; text: chip.tip; fontFamily: root.family }
  }

  component Dots: Row {
    property var colors: []
    property real size: Style.space(8)
    property real ring: 0.2
    spacing: Style.space(2)
    Repeater {
      model: parent.colors
      Rectangle {
        required property var modelData
        required property int index
        width: parent.size; height: width; radius: width / 2
        color: modelData
        border.width: index === 0 ? 1 : 0
        border.color: Qt.rgba(1, 1, 1, parent.ring)
      }
    }
  }

  // Explicit geometry keeps each selected pill inside the track border.
  component SegmentTrack: Rectangle {
    id: segmentTrack
    property color foreground: root.fg
    property real inset: Style.space(4)
    property real segmentHeight: Style.space(30)
    default property alias segments: segmentBody.data
    implicitHeight: segmentHeight + inset * 2
    radius: height / 2
    color: Commons.Color.background.hslLightness > 0.5
      ? root.alphaOf(foreground, 0.06) : Qt.rgba(0, 0, 0, 0.24)
    border.width: 1
    border.color: root.alphaOf(foreground, 0.1)
    Item {
      id: segmentBody
      x: segmentTrack.inset
      y: segmentTrack.inset
      width: segmentTrack.width - segmentTrack.inset * 2
      height: segmentTrack.segmentHeight
    }
  }

  // Two or three options in a recessed track with one sliding thumb.
  component ScopeSwitch: SegmentTrack {
    id: scope
    property var options: []
    property string value: ""
    signal picked(string key)
    segmentHeight: Style.space(28)
    foreground: root.fg
    readonly property int sel: Math.max(0, options.findIndex(o => o.key === value))
    readonly property real cell: (width - inset * 2 - Style.space(2) * (options.length - 1)) / Math.max(1, options.length)
    Rectangle {
      width: scope.cell; height: scope.segmentHeight; radius: height / 2
      x: scope.sel * (scope.cell + Style.space(2))
      color: root.alphaOf(root.fg, 0.14)
      Behavior on x { enabled: root.opened; NumberAnimation { duration: 280; easing.type: Easing.OutQuint } }
    }
    Row {
      spacing: Style.space(2)
      Repeater {
        model: scope.options
        Item {
          required property var modelData
          width: scope.cell; height: scope.segmentHeight
          Row {
            anchors.centerIn: parent
            spacing: Style.space(6)
            Text {
              text: modelData.label
              color: scope.value === modelData.key ? root.fg : root.alphaOf(root.fg, 0.55)
              Behavior on color { ColorAnimation { duration: 180; easing.type: Easing.OutCubic } }
              font.family: root.family; font.pixelSize: Style.font.bodySmall + 1; font.weight: Font.DemiBold
            }
            Text {
              visible: !!modelData.count
              anchors.verticalCenter: parent.verticalCenter
              text: modelData.count || ""
              color: root.alphaOf(root.fg, 0.4)
              font.family: root.family; font.pixelSize: Style.font.caption + 1
            }
          }
          MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: scope.picked(modelData.key) }
        }
      }
    }
  }

  // Small pill used for suggestions and quiet links.
  component Chip: Rectangle {
    id: chipPill
    property string label: ""
    property bool on: false
    signal clicked()
    height: Style.space(26)
    width: chipLabel.implicitWidth + Style.space(22)
    radius: height / 2
    color: on ? root.alphaOf(root.accent, 0.18) : chipPillMouse.containsMouse ? root.alphaOf(root.fg, 0.1) : root.alphaOf(root.fg, 0.05)
    border.width: 1
    border.color: on ? root.alphaOf(root.accent, 0.4) : root.alphaOf(root.fg, 0.08)
    Behavior on color { ColorAnimation { duration: 140 } }
    Text {
      id: chipLabel
      anchors.centerIn: parent
      text: chipPill.label
      color: chipPill.on ? root.accent : root.alphaOf(root.fg, 0.75)
      font.family: root.family; font.pixelSize: Style.font.bodySmall + 1; font.weight: Font.Medium
    }
    MouseArea { id: chipPillMouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: chipPill.clicked() }
  }

  component Tab: Rectangle {
    id: tabItem
    property string label: ""
    property string count: ""
    property bool dot: false
    property bool dotOn: false
    property int index: 0
    readonly property bool on: root.tab === index
    height: Style.space(30)
    radius: height / 2
    color: !on && tabMouse.containsMouse ? root.alphaOf(root.fg, 0.05) : "transparent"
    Behavior on color { ColorAnimation { duration: 120 } }
    Row {
      anchors.centerIn: parent
      spacing: Style.space(6)
      Rectangle {
        visible: tabItem.dot
        width: Style.space(6); height: width; radius: width / 2
        anchors.verticalCenter: parent.verticalCenter
        color: tabItem.dotOn ? Commons.Color.accent : root.alphaOf(root.fg, 0.3)
      }
      Text {
        text: tabItem.label
        color: tabItem.on ? root.fg : root.alphaOf(root.fg, 0.6)
        Behavior on color { ColorAnimation { duration: 180; easing.type: Easing.OutCubic } }
        font.family: root.family; font.pixelSize: Style.font.bodySmall + 1
        font.weight: Font.DemiBold
      }
      Text {
        visible: tabItem.count !== ""
        anchors.verticalCenter: parent.verticalCenter
        text: tabItem.count
        color: root.alphaOf(root.fg, tabItem.on ? 0.55 : 0.35)
        Behavior on color { ColorAnimation { duration: 180; easing.type: Easing.OutCubic } }
        font.family: root.family; font.pixelSize: Style.font.caption + 1
      }
    }
    MouseArea { id: tabMouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.tab = tabItem.index }
  }

  component PrimaryButton: Rectangle {
    id: pb
    property string label: ""
    property string glyph: ""
    property bool enabledState: true
    signal clicked()
    height: Style.space(34)
    radius: Style.space(10)
    color: root.accent
    opacity: enabledState ? (pbMouse.pressed ? 0.85 : 1) : 0.45
    Row {
      anchors.centerIn: parent
      spacing: Style.space(7)
      Text { visible: pb.glyph !== ""; text: pb.glyph; color: Commons.Color.background; font.family: root.glyphFamily; font.pixelSize: Style.font.body; anchors.verticalCenter: parent.verticalCenter }
      Text { text: pb.label; color: Commons.Color.background; font.family: root.family; font.pixelSize: Style.font.body; font.weight: Font.DemiBold }
    }
    MouseArea { id: pbMouse; anchors.fill: parent; enabled: pb.enabledState; cursorShape: Qt.PointingHandCursor; onClicked: pb.clicked() }
  }

  component GhostButton: Rectangle {
    id: gb
    property string label: ""
    property string glyph: ""
    property color tint: root.fg
    property bool enabledState: true
    readonly property alias containsMouse: gbMouse.containsMouse
    signal clicked()
    height: Style.space(34)
    radius: Style.space(10)
    implicitWidth: gbRow.implicitWidth + Style.space(28)
    color: gbMouse.containsMouse ? root.alphaOf(root.fg, 0.1) : root.alphaOf(root.fg, 0.06)
    opacity: enabledState ? 1 : 0.45
    Row {
      id: gbRow
      anchors.centerIn: parent
      spacing: Style.space(7)
      Text { visible: gb.glyph !== ""; text: gb.glyph; color: gb.tint; opacity: 0.8; font.family: root.glyphFamily; font.pixelSize: Style.font.body; anchors.verticalCenter: parent.verticalCenter }
      Text { text: gb.label; color: gb.tint; opacity: 0.85; font.family: root.family; font.pixelSize: Style.font.body; font.weight: Font.Medium }
    }
    MouseArea { id: gbMouse; anchors.fill: parent; hoverEnabled: true; enabled: gb.enabledState; cursorShape: Qt.PointingHandCursor; onClicked: gb.clicked() }
  }

  component Label: Text {
    color: root.alphaOf(root.fg, 0.55)
    font.family: root.family; font.pixelSize: Style.font.caption + 1
    font.weight: Font.DemiBold; font.letterSpacing: 0.5
    font.capitalization: Font.AllUppercase
    leftPadding: Style.space(3)
  }

  component Field: QQC.TextField {
    id: field
    height: Style.space(34)
    color: root.fg
    placeholderTextColor: root.alphaOf(root.fg, 0.45)
    selectionColor: root.alphaOf(root.accent, 0.4)
    selectedTextColor: root.fg
    font.family: root.family
    font.pixelSize: Style.font.body
    leftPadding: Style.space(12)
    rightPadding: Style.space(12)
    background: Rectangle {
      radius: Style.space(10)
      color: Commons.Color.background.hslLightness > 0.5 ? root.alphaOf(root.fg, 0.06) : Qt.rgba(0, 0, 0, 0.24)
      border.width: 1
      border.color: field.activeFocus ? root.alphaOf(root.accent, 0.55) : root.alphaOf(root.fg, 0.08)
    }
  }

  // ---------------------------------------------------------------- card
  // The popup host is Omarchy's stock KeyboardPanel, or the glass panel host
  // from the denon.bar plugin when that is installed. Both share one API; the
  // panel content below is reparented into whichever loads (hosts/*.qml).
  property bool hostChosen: false
  property bool useGlassHost: false
  readonly property var popup: hostLoader.item
  readonly property Item keyboardItem: keyboard
  readonly property real contentImplicitHeight: content.implicitHeight
  // Compact galleries give up height when the screen is too short for the
  // full panel, so the card never overflows (adjusted after layout settles).
  property real compactShrink: 0
  readonly property real roomCap: popup && popup.availableCardHeight > 0
    ? Math.min(popup.availableCardHeight, Style.space(880)) - popup.verticalContentInset : 1e6
  function refit() {
    if (expanded) { compactShrink = 0; return }
    let next = Math.max(0, compactShrink + content.implicitHeight - roomCap)
    if (Math.abs(next - compactShrink) > 0.5) compactShrink = next
  }
  function fitted(desired, minimum) { return Math.max(minimum, desired - compactShrink) }
  onRoomCapChanged: Qt.callLater(refit)
  onExpandedChanged: Qt.callLater(refit)
  Connections { target: content; function onImplicitHeightChanged() { Qt.callLater(root.refit) } }
  FileView {
    path: root.pluginDir + "/../denon.bar/panels/PopupPanel.qml"
    printErrors: false
    onLoaded: { root.useGlassHost = true; root.hostChosen = true }
    onLoadFailed: root.hostChosen = true
  }
  onHostChosenChanged: hostLoader.setSource(useGlassHost ? "hosts/GlassHost.qml" : "hosts/StockHost.qml",
                                            { studio: root, anchorItem: icon, bar: root.bar })
  Loader { id: hostLoader }
  Item { id: parking; visible: false; width: Style.space(420); height: Style.space(600) }

  PanelKeyCatcher {
    id: keyboard
    parent: root.popup ? root.popup.slot : parking
    anchors.fill: parent
    blocked: search.activeFocus || nameField.activeFocus
    onCloseRequested: { if (root.menuOpen) root.menuOpen = false; else if (root.borderOpen) root.borderOpen = false; else root.close() }
    onTabRequested: function(direction) { root.switchPanel(direction) }
    onMoveRequested: function(dx, dy) { root.moveCursor(dx, dy) }
    onActivateRequested: root.activateTile(root.gridModel[root.cursor])
    onTextKey: function(text) {
      if (text === "/") { root.tab = 0; search.forceActiveFocus() }
      else if (text === "1" || text === "2" || text === "3") root.tab = Number(text) - 1
      else if (text === "e") root.toggleExpanded()
      else if (text === "b") root.goBack()
      else if (text === "f") { let i = root.gridModel[root.cursor]; if (i && i.slug) root.act("favorite", i.slug) }
    }

    SequentialAnimation {
      id: layoutSwap
      NumberAnimation { target: keyboard; property: "opacity"; to: 0; duration: 90; easing.type: Easing.InCubic }
      ScriptAction { script: { root.expanded = root.pendingExpanded; keyboard.scale = 0.985 } }
      PauseAnimation { duration: 110 }
      ParallelAnimation {
        NumberAnimation { target: keyboard; property: "opacity"; to: 1; duration: 220; easing.type: Easing.OutCubic }
        NumberAnimation { target: keyboard; property: "scale"; to: 1; duration: 260; easing.type: Easing.OutQuint }
      }
      onStopped: { keyboard.opacity = 1; keyboard.scale = 1 }
    }

    Column {
      id: content
      width: root.expanded ? root.sidebarWidth : parent.width
      spacing: Style.space(12)

      // ---- Hero: the current theme
      ClippingRectangle {
        id: hero
        width: parent.width
        height: Style.space(150)
        radius: Style.space(12)
        color: Commons.Color.background

        // Cached thumbnail of the shown theme underneath, so the hero follows
        // a click at once and never flashes empty while the wallpaper loads.
        Image {
          anchors.fill: parent
          source: root.shownItem ? (root.shownItem.thumb || "") : ""
          sourceSize.width: 360
          fillMode: Image.PreserveAspectCrop
          asynchronous: true
        }
        Image {
          anchors.fill: parent
          source: root.values.background && !root.optimistic ? "file://" + root.values.background : ""
          sourceSize.width: 840
          fillMode: Image.PreserveAspectCrop
          asynchronous: true
          cache: false
          opacity: status === Image.Ready ? 1 : 0
          Behavior on opacity { NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
        }
        Rectangle {
          anchors.fill: parent
          gradient: Gradient {
            GradientStop { position: 0.3; color: Qt.rgba(0.035, 0.035, 0.03, 0) }
            GradientStop { position: 1.0; color: Qt.rgba(0.035, 0.035, 0.03, 0.88) }
          }
        }
        Column {
          anchors.left: parent.left
          anchors.bottom: parent.bottom
          anchors.margins: Style.space(14)
          anchors.right: heroChips.left
          spacing: Style.space(4)
          Text {
            text: root.reviewing && root.shownCurrent === root.values.pending_review ? "JUST ROTATED IN" : "CURRENT THEME"
            // Dark accents (common in light themes) vanish on the shaded artwork.
            color: root.luminance(root.accent) < 0.2 ? "#fff7e3" : root.accent
            font.family: root.family; font.pixelSize: Style.font.caption + 1
            font.weight: Font.DemiBold; font.letterSpacing: 0.8
          }
          Text {
            width: parent.width
            text: root.shownItem ? root.shownItem.name : (root.values.current_name || "")
            color: "#fff7e3"
            elide: Text.ElideRight
            font.family: root.family; font.pixelSize: Style.font.display - 3
            font.weight: Font.DemiBold
          }
          Dots { colors: root.shownItem ? (root.shownItem.palette || []) : (root.values.current_palette || []); size: Style.space(11); ring: 0.3; spacing: Style.space(4) }
        }
        HeroChip {
          anchors.left: parent.left; anchors.top: parent.top
          anchors.margins: Style.space(12)
          width: Style.space(28)
          glyph: root.expanded ? "󰊔" : "󰊓"
          tip: root.expanded ? "Compact panel  (E)" : "Expand to a wide window  (E)"
          onClicked: root.toggleExpanded()
        }
        Row {
          id: heroChips
          anchors.right: parent.right
          anchors.bottom: parent.bottom
          anchors.margins: Style.space(14)
          spacing: Style.space(6)
          HeroChip {
            visible: !!root.backTarget || root.backStep > 0
            opacity: root.backTarget ? 1 : 0.4
            glyph: "󰁍"
            tip: root.backTarget ? "Back to " + root.themeName(root.backTarget) + "  (B)" : "No older themes"
            onClicked: root.goBack()
          }
          HeroChip { glyph: root.values.current_favorite ? "★" : "☆"; lit: !!root.values.current_favorite; tip: root.values.current_favorite ? "Unfavorite" : "Favorite"; onClicked: root.act("favorite") }
          HeroChip { visible: !!root.values.variant_target; glyph: String(root.values.current).endsWith("-light") ? "󰖔" : "󰖙"; tip: "Switch to " + (String(root.values.current).endsWith("-light") ? "dark" : "light") + " variant"; onClicked: root.act("variant") }
          HeroChip {
            id: borderChip
            visible: (root.borderInfo.options || []).length > 0 || !root.borderInfo.installed
            lit: root.borderOpen
            tip: "Window border color"
            onClicked: { root.borderOpen = !root.borderOpen; root.menuOpen = false }
            Rectangle {
              anchors.centerIn: parent
              width: Style.space(14); height: width; radius: Style.space(4)
              color: "transparent"
              border.width: 2
              border.color: root.borderChoice === "none" ? Qt.rgba(1, 1, 1, 0.35) : root.borderColorOf(root.borderChoice)
              Behavior on border.color { ColorAnimation { duration: 200; easing.type: Easing.OutCubic } }
              Rectangle {  // slash for "no border"
                visible: root.borderChoice === "none"
                anchors.centerIn: parent
                width: parent.width * 1.25; height: 1.5; rotation: -45
                color: Qt.rgba(1, 1, 1, 0.6)
              }
            }
          }
          HeroChip { id: moreChip; glyph: "󰇘"; lit: root.menuOpen; tip: "More"; onClicked: { root.menuOpen = !root.menuOpen; root.confirmDelete = false; root.borderOpen = false } }
        }
      }

      // ---- New theme review (after an automatic rotation)
      Rectangle {
        visible: root.reviewShown
        width: parent.width
        height: reviewCol.implicitHeight + Style.space(24)
        radius: Style.space(12)
        color: root.alphaOf(root.accent, 0.1)
        border.width: 1
        border.color: root.alphaOf(root.accent, 0.24)
        Column {
          id: reviewCol
          x: Style.space(12); y: Style.space(12)
          width: parent.width - Style.space(24)
          spacing: Style.space(10)
          Text {
            width: parent.width
            text: "Keep " + root.reviewName + " in the rotation?"
            color: root.fg; elide: Text.ElideRight
            font.family: root.family; font.pixelSize: Style.font.body + 1; font.weight: Font.DemiBold
          }
          Row {
            width: parent.width
            spacing: Style.space(6)
            readonly property real cell: (width - spacing * 2) / 3
            PrimaryButton { width: parent.cell; height: Style.space(32); glyph: "󰄬"; label: "Keep"; enabledState: !root.busy && root.canRate; onClicked: root.act("rate", "yes") }
            GhostButton { width: parent.cell; height: Style.space(32); label: "Maybe"; enabledState: !root.busy && root.canRate; onClicked: root.act("rate", "maybe") }
            GhostButton { width: parent.cell; height: Style.space(32); glyph: "󰅖"; label: "Not for me"; enabledState: !root.busy && root.canRate; onClicked: root.act("rate", "no") }
          }
        }
      }

      // ---- Tabs
      SegmentTrack {
        id: tabsTrack
        width: parent.width
        foreground: root.fg
        Rectangle {
          width: tabsRow.cell
          height: tabsTrack.segmentHeight
          radius: height / 2
          x: root.tab * (width + tabsRow.spacing)
          color: root.alphaOf(root.fg, 0.14)
          Behavior on x {
            enabled: root.opened
            NumberAnimation { duration: 280; easing.type: Easing.OutQuint }
          }
        }
        Row {
          id: tabsRow
          width: parent.width
          spacing: Style.space(2)
          readonly property real cell: (width - spacing * 2) / 3
          Tab { width: parent.cell; index: 0; label: "Themes"; count: String(root.themeScope === "discover" ? root.discoverModel.length : root.matchCount) }
          Tab { width: parent.cell; index: 1; label: "Backgrounds"; count: String((root.values.backgrounds || []).length) }
          Tab { width: parent.cell; index: 2; label: "Rotation"; dot: true; dotOn: !!root.values.enabled }
        }
      }

      // ================================================================ Themes
      Column {
        id: themesCol
        visible: root.tab === 0
        width: parent.width
        spacing: Style.space(12)

        ScopeSwitch {
          width: parent.width
          value: root.themeScope
          options: [{ key: "installed", label: "Installed", count: String((root.values.themes || []).length) },
                    { key: "recent", label: "Recent", count: String((root.values.recent || []).length) },
                    { key: "discover", label: "Discover", count: root.discoverLoaded ? String(root.discoverModel.length) : "" }]
          onPicked: function(key) { root.themeScope = key }
        }

        Row {
          width: parent.width
          spacing: Style.space(8)
          Field {
            id: search
            width: parent.width
            placeholderText: root.themeScope === "discover" ? "Search community themes or paste a link" : "Search themes or paste a link"
            leftPadding: Style.space(32)
            onTextChanged: root.query = text
            onAccepted: {
              if (root.linkMode) root.startImport()
              else if (root.themeScope === "discover") root.discoverPick = root.discoverModel[0] || null
              else root.activateTile(root.gridModel[root.cursor >= 0 ? root.cursor : (root.gridModel.length > 0 && root.query ? 0 : -1)])
            }
            Keys.onEscapePressed: { if (text) text = ""; else { focus = false; keyboard.forceActiveFocus() } }
            Keys.onDownPressed: { focus = false; keyboard.forceActiveFocus(); root.moveCursor(0, 0) }
            Text {
              x: Style.space(11)
              anchors.verticalCenter: parent.verticalCenter
              text: root.linkMode ? "󰌷" : "󰍉"
              color: root.linkMode ? root.accent : root.alphaOf(root.fg, 0.5)
              font.family: root.glyphFamily; font.pixelSize: Style.font.body + 1
            }
          }
        }

        Row {
          width: parent.width
          spacing: Style.space(8)
          SegmentTrack {
            id: filterTrack
            width: parent.width - (favoritesButton.visible ? favoritesButton.width + parent.spacing : 0)
              - (groupButton.visible ? groupButton.width + parent.spacing : 0)
              - (sortButton.visible ? sortButton.width + parent.spacing : 0) - addButton.width - parent.spacing
            segmentHeight: Style.space(28)
            foreground: root.fg
            // One shared thumb preserves the visual connection between modes.
            Rectangle {
              id: modeThumb
              readonly property int selectedIndex: Math.max(0, ["all", "dark", "light"].indexOf(root.themeMode))
              width: (filterRow.width - filterRow.spacing * 2) / 3
              height: filterTrack.segmentHeight
              radius: height / 2
              x: selectedIndex * (width + filterRow.spacing)
              color: root.alphaOf(root.fg, 0.14)
              Behavior on x {
                enabled: root.opened
                NumberAnimation { duration: 280; easing.type: Easing.OutQuint }
              }
            }
            Row {
              id: filterRow
              width: parent.width
              spacing: Style.space(2)
              Repeater {
                model: [{ label: "All", mode: "all" }, { label: "Dark", mode: "dark" }, { label: "Light", mode: "light" }]
                Rectangle {
                  required property var modelData
                  readonly property bool on: root.themeMode === modelData.mode
                  width: (filterRow.width - filterRow.spacing * 2) / 3
                  height: filterTrack.segmentHeight
                  radius: height / 2
                  color: "transparent"
                  Text {
                    id: chipText
                    anchors.centerIn: parent
                    text: modelData.label
                    color: parent.on ? root.fg : root.alphaOf(root.fg, 0.55)
                    Behavior on color { ColorAnimation { duration: 180; easing.type: Easing.OutCubic } }
                    font.family: root.family; font.pixelSize: Style.font.bodySmall + 1
                    font.weight: Font.DemiBold
                  }
                  MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.themeMode = modelData.mode }
                }
              }
            }
          }
          GhostButton {
            id: groupButton
            visible: root.themeScope === "installed"
            label: "󰌨"
            tint: root.groupLookalikes ? root.accent : root.fg
            color: root.groupLookalikes ? root.alphaOf(root.accent, 0.18) : root.alphaOf(root.fg, 0.06)
            height: filterTrack.height
            onClicked: root.groupLookalikes = !root.groupLookalikes
            PanelToolTip { visible: groupButton.containsMouse; text: root.groupLookalikes ? "Show every lookalike" : "Group lookalike themes"; fontFamily: root.family }
          }
          GhostButton {
            id: sortButton
            visible: root.themeScope === "discover"
            label: root.discoverSort === "new" ? "Recent" : "Popular"
            glyph: root.discoverSort === "new" ? "󰥔" : "★"
            height: filterTrack.height
            onClicked: root.discoverSort = root.discoverSort === "new" ? "popular" : "new"
            PanelToolTip { visible: sortButton.containsMouse; text: root.discoverSort === "new" ? "Recently updated first" : "Most starred first"; fontFamily: root.family }
          }
          GhostButton {
            id: favoritesButton
            visible: root.themeScope !== "discover"
            label: "★"
            tint: root.favoritesOnly ? root.accent : root.fg
            color: root.favoritesOnly ? root.alphaOf(root.accent, 0.18) : root.alphaOf(root.fg, 0.06)
            height: filterTrack.height
            onClicked: root.favoritesOnly = !root.favoritesOnly
            PanelToolTip { visible: favoritesButton.containsMouse; text: root.favoritesOnly ? "Show all themes" : "Favorites only"; fontFamily: root.family }
          }
          // Wide fonts (Omarchy's monospace default): drop the label before the
          // All / Dark / Light filter gets cramped.
          TextMetrics { id: segMetrics; font.family: root.family; font.pixelSize: Style.font.body; text: "Light" }
          TextMetrics { id: addMetrics; font.family: root.family; font.pixelSize: Style.font.body; text: "Add theme" }
          GhostButton {
            id: addButton
            readonly property real others: (favoritesButton.visible ? favoritesButton.width + parent.spacing : 0)
              + (groupButton.visible ? groupButton.width + parent.spacing : 0)
              + (sortButton.visible ? sortButton.width + parent.spacing : 0)
            readonly property bool roomForLabel: parent.width - others - parent.spacing - (addMetrics.width + Style.space(44))
              >= 3 * (segMetrics.width + Style.space(26))
            height: filterTrack.height
            label: root.expanded || !roomForLabel ? "" : "Add theme"
            glyph: "+"
            onClicked: { root.showHelp = !root.showHelp; search.forceActiveFocus() }
          }
        }

        Column {
          id: themesBody
          // Moves to the right-hand pane in the wide layout.
          parent: root.expanded ? themesSlot : themesCol
          // A Column positioned it; start at the top of the pane after moving.
          onParentChanged: if (parent === themesSlot) { x = 0; y = 0 }

        // ---- Install from link
        GlassTile {
          visible: root.linkMode || root.showHelp
          width: parent.width
          foreground: root.fg
          implicitHeight: installCol.implicitHeight + Style.space(28)
          Column {
            id: installCol
            x: Style.space(14); y: Style.space(14)
            width: parent.width - Style.space(28)
            spacing: Style.space(12)

            Row {
              width: parent.width
              spacing: Style.space(12)
              Rectangle {
                width: Style.space(36); height: width; radius: Style.space(10)
                color: root.alphaOf(root.accent, 0.16)
                Text {
                  anchors.centerIn: parent
                  text: !root.linkMode ? "󰐕" : (root.linkInfo && root.linkInfo.images ? "󰸉" : "󰊢")
                  color: root.accent; font.family: root.glyphFamily; font.pixelSize: Style.font.iconLarge
                }
              }
              Column {
                width: parent.width - Style.space(48)
                anchors.verticalCenter: parent.verticalCenter
                spacing: Style.space(2)
                Text {
                  text: !root.linkMode ? "Add a theme" : (root.linkInfo && root.linkInfo.images ? "Make a theme from art" : "Install from link")
                  color: root.fg
                  font.family: root.family; font.pixelSize: Style.font.body + 1; font.weight: Font.DemiBold
                }
                Text {
                  width: parent.width
                  wrapMode: Text.WordWrap
                  text: !root.linkMode
                    ? "Paste a GitHub repo, a theme page from omarchy.org or omarchythemes.com, a .zip, or image links from any artist."
                    : root.linkError ? root.linkError
                    : root.importing ? root.importProgress
                    : root.linkInfo ? root.linkInfo.label : "Checking link…"
                  color: root.linkError ? root.urgent : root.alphaOf(root.fg, 0.6)
                  font.family: root.family; font.pixelSize: Style.font.bodySmall + 1
                }
              }
            }

            Column {
              visible: root.linkMode && !!root.linkInfo && !!root.linkInfo.images
              width: parent.width
              spacing: Style.space(8)
              Field {
                id: nameField
                width: parent.width
                placeholderText: "Theme name"
                text: root.importName
                onTextChanged: root.importName = text
                onAccepted: root.startImport()
              }
              // Six palette styles, each previewed with its real colors.
              Grid {
                id: profileGrid
                visible: !!root.linkInfo && !!root.linkInfo.profiles && root.linkInfo.profiles.length > 0
                width: parent.width
                columns: 3
                spacing: Style.space(6)
                readonly property real cell: (width - spacing * 2) / 3
                Repeater {
                  model: profileGrid.visible ? root.linkInfo.profiles : []
                  Item {
                    id: prof
                    required property var modelData
                    readonly property bool on: root.importMode === modelData.id
                    readonly property var c: modelData.colors || []
                    width: profileGrid.cell
                    height: profCard.height + Style.space(20)
                    Rectangle {
                      id: profCard
                      width: parent.width
                      height: Style.space(48)
                      radius: Style.space(9)
                      color: prof.c[0] || "#222"
                      border.width: prof.on ? 2 : 1
                      border.color: prof.on ? root.accent : root.alphaOf(root.fg, profMouse.containsMouse ? 0.3 : 0.12)
                      Behavior on border.color { ColorAnimation { duration: 140 } }
                      Text {
                        x: Style.space(8); y: Style.space(6)
                        text: "Aa"
                        color: prof.c[1] || "#fff"
                        font.family: root.family; font.pixelSize: Style.font.body + 1; font.weight: Font.DemiBold
                      }
                      Rectangle {
                        x: Style.space(8); y: parent.height - Style.space(13)
                        width: parent.width * 0.38; height: Style.space(5); radius: height / 2
                        color: prof.c[2] || root.accent
                      }
                      Row {
                        anchors.right: parent.right; anchors.rightMargin: Style.space(7)
                        y: Style.space(8)
                        spacing: Style.space(3)
                        Repeater {
                          model: prof.c.slice(3, 6)
                          Rectangle { required property var modelData; width: Style.space(7); height: width; radius: width / 2; color: modelData }
                        }
                      }
                    }
                    Text {
                      y: profCard.height + Style.space(4)
                      width: parent.width
                      horizontalAlignment: Text.AlignHCenter
                      text: prof.modelData.label
                      elide: Text.ElideRight
                      color: prof.on ? root.fg : root.alphaOf(root.fg, 0.6)
                      font.family: root.family; font.pixelSize: Style.font.caption + 1
                      font.weight: prof.on ? Font.DemiBold : Font.Medium
                    }
                    MouseArea { id: profMouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.importMode = prof.modelData.id }
                  }
                }
              }
              SegmentTrack {
                visible: !profileGrid.visible
                width: parent.width
                foreground: root.fg
                Row {
                  width: parent.width
                  spacing: Style.space(2)
                  Repeater {
                    model: [["auto", "Match the art"], ["dark", "Dark"], ["light", "Light"]]
                    Rectangle {
                      required property var modelData
                      readonly property bool on: root.importMode === modelData[0]
                      width: (parent.width - Style.space(4)) / 3
                      height: Style.space(30)
                      radius: height / 2
                      color: on ? root.alphaOf(root.fg, 0.14) : "transparent"
                      Text {
                        anchors.centerIn: parent
                        text: modelData[1]
                        color: parent.on ? root.fg : root.alphaOf(root.fg, 0.55)
                        font.family: root.family; font.pixelSize: Style.font.bodySmall + 1
                        font.weight: parent.on ? Font.DemiBold : Font.Medium
                      }
                      MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.importMode = modelData[0] }
                    }
                  }
                }
              }
            }

            Row {
              visible: root.linkMode
              width: parent.width
              spacing: Style.space(8)
              PrimaryButton {
                width: parent.width - installOnly.width - parent.spacing
                glyph: root.importing ? "" : "󰄬"
                label: root.importing ? "Installing…" : "Install & apply"
                enabledState: !root.importing && !root.busy && !!root.linkInfo && !root.linkError
                onClicked: { root.importApply = true; root.startImport() }
              }
              GhostButton {
                id: installOnly
                label: "Install only"
                enabledState: !root.importing && !root.busy && !!root.linkInfo && !root.linkError
                onClicked: { root.importApply = false; root.startImport() }
              }
            }
          }
        }

          width: parent.width
          spacing: Style.space(12)

        // ---- Inside a lookalike group
        Row {
          visible: !!root.openGroup && root.themeScope === "installed" && !root.linkMode
          width: parent.width
          spacing: Style.space(10)
          Chip { label: "‹  All themes"; onClicked: root.closeLookalikes() }
          Text {
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width - Style.space(120)
            elide: Text.ElideRight
            text: root.gridModel.length + " lookalikes of " + root.openGroupName
            color: root.alphaOf(root.fg, 0.6)
            font.family: root.family; font.pixelSize: Style.font.bodySmall + 1
          }
        }

        // ---- Grid
        GridView {
          id: grid
          HoverHandler { id: gridHover }
          visible: !root.linkMode && root.themeScope !== "discover"
          width: parent.width
          readonly property real thumbH: Math.round((width / root.gridCols - Style.space(9)) * 0.62)
          // Room for the pile on top-row lookalike stacks.
          topMargin: Style.space(4)
          height: root.expanded ? Math.max(Style.space(200), rightPane.height - y)
                                : root.fitted(Math.min(contentHeight + topMargin, (thumbH + Style.space(46)) * (root.reviewShown ? 2 : 3)), Style.space(96))
          cellWidth: width / root.gridCols
          cellHeight: thumbH + Style.space(46)
          clip: true
          boundsBehavior: Flickable.StopAtBounds
          model: root.gridModel
          cacheBuffer: 400
          QQC.ScrollBar.vertical: QQC.ScrollBar { policy: QQC.ScrollBar.AsNeeded }

          delegate: Item {
            id: tile
            required property var modelData
            required property int index
            readonly property bool current: !modelData.surprise && modelData.slug === root.shownCurrent
            readonly property bool landing: current && root.switching
            readonly property bool cursored: index === root.cursor
            width: grid.cellWidth
            height: grid.cellHeight
            readonly property int stack: modelData.stack || 0

            // A collapsed lookalike group peeks out behind the card like a pile.
            Rectangle {
              visible: tile.stack > 1
              x: thumbBox.x + Style.space(14); y: -Style.space(4)
              width: thumbBox.width - Style.space(28); height: Style.space(12)
              radius: Style.space(6)
              color: root.alphaOf(root.fg, 0.12)
            }
            Rectangle {
              visible: tile.stack > 1
              x: thumbBox.x + Style.space(7); y: -Style.space(0.5)
              width: thumbBox.width - Style.space(14); height: Style.space(12)
              radius: Style.space(8)
              color: root.alphaOf(root.fg, 0.22)
            }

            ClippingRectangle {
              id: thumbBox
              x: Style.space(3); y: Style.space(3)
              width: parent.width - Style.space(6)
              height: grid.thumbH
              radius: Style.space(10)
              color: root.alphaOf(root.fg, 0.05)
              Image {
                visible: !tile.modelData.surprise
                anchors.fill: parent
                source: tile.modelData.thumb || tile.modelData.url || ""
                sourceSize.width: 360
                fillMode: Image.PreserveAspectCrop
                asynchronous: true
                opacity: status === Image.Ready ? 1 : 0
                Behavior on opacity { NumberAnimation { duration: 160 } }
              }
              // Surprise me: a mosaic of four random themes
              Grid {
                visible: !!tile.modelData.surprise
                anchors.fill: parent
                columns: 2
                opacity: 0.4
                Repeater {
                  model: tile.modelData.surprise ? 4 : 0
                  Image {
                    required property int index
                    width: thumbBox.width / 2; height: thumbBox.height / 2
                    readonly property var pick: root.filtered.length ? root.filtered[(index * 53 + 7) % root.filtered.length] : null
                    source: pick ? (pick.thumb || "") : ""
                    sourceSize.width: 200
                    fillMode: Image.PreserveAspectCrop
                    asynchronous: true
                  }
                }
              }
              Rectangle {
                visible: !!tile.modelData.surprise
                anchors.centerIn: parent
                width: Style.space(34); height: width; radius: width / 2
                color: Qt.rgba(0.035, 0.035, 0.03, 0.72)
                border.width: 1; border.color: root.alphaOf(root.fg, 0.18)
                Text { anchors.centerIn: parent; text: "󰒝"; color: root.accent; font.family: root.glyphFamily; font.pixelSize: Style.font.iconLarge - 2 }
              }
              // Lookalike count: click to see the whole group
              Rectangle {
                visible: tile.stack > 1
                anchors.left: parent.left; anchors.bottom: parent.bottom
                anchors.margins: Style.space(6)
                height: Style.space(20); width: stackText.implicitWidth + Style.space(14)
                radius: height / 2
                color: Qt.rgba(0.035, 0.035, 0.03, stackMouse.containsMouse ? 0.88 : 0.66)
                border.width: 1; border.color: Qt.rgba(1, 1, 1, stackMouse.containsMouse ? 0.3 : 0.14)
                Text {
                  id: stackText
                  anchors.centerIn: parent
                  text: "+" + (tile.stack - 1)
                  color: "#fff7e3"
                  font.family: root.family; font.pixelSize: Style.font.caption + 1; font.weight: Font.DemiBold
                }
                MouseArea {
                  id: stackMouse
                  anchors.fill: parent
                  hoverEnabled: true
                  cursorShape: Qt.PointingHandCursor
                  onClicked: root.openLookalikes(tile.modelData)
                }
                PanelToolTip { visible: stackMouse.containsMouse; text: (tile.stack - 1) + (tile.stack === 2 ? " lookalike" : " lookalikes") + " · show all"; fontFamily: root.family }
              }
              // Favorite / current badge
              Rectangle {
                visible: tile.current || (!tile.modelData.surprise && (tile.modelData.favorite || tileMouse.containsMouse))
                anchors.top: parent.top; anchors.right: parent.right
                anchors.margins: Style.space(6)
                width: Style.space(20); height: width; radius: width / 2
                color: tile.current ? root.accent : Qt.rgba(0.035, 0.035, 0.03, starMouse.containsMouse ? 0.85 : 0.6)
                // Breathes while the clicked theme is being applied.
                SequentialAnimation on opacity {
                  running: tile.landing
                  loops: Animation.Infinite
                  alwaysRunToEnd: true
                  NumberAnimation { to: 0.45; duration: 420; easing.type: Easing.InOutSine }
                  NumberAnimation { to: 1; duration: 420; easing.type: Easing.InOutSine }
                }
                Text {
                  anchors.centerIn: parent
                  text: tile.current ? "󰄬" : (tile.modelData.favorite ? "★" : "☆")
                  color: tile.current ? Commons.Color.background : "#ffe3a3"
                  font.family: root.glyphFamily; font.pixelSize: Style.font.bodySmall
                }
                MouseArea {
                  id: starMouse
                  anchors.fill: parent
                  enabled: !tile.current
                  hoverEnabled: true
                  cursorShape: Qt.PointingHandCursor
                  onClicked: root.act("favorite", tile.modelData.slug)
                }
              }
            }
            Rectangle {
              x: thumbBox.x - 2; y: thumbBox.y - 2
              width: thumbBox.width + 4; height: thumbBox.height + 4
              radius: thumbBox.radius + 2
              color: "transparent"
              border.width: tile.current || tile.cursored || tileMouse.containsMouse ? 2 : 1
              border.color: tile.current ? root.accent
                : tile.cursored ? root.alphaOf(root.fg, 0.7)
                : tileMouse.containsMouse ? root.alphaOf(root.fg, 0.35) : root.alphaOf(root.fg, 0.06)
              Behavior on border.color { ColorAnimation { duration: 140; easing.type: Easing.OutCubic } }
            }
            Item {
              x: Style.space(5)
              y: thumbBox.y + thumbBox.height + Style.space(6)
              width: parent.width - Style.space(10)
              height: Style.space(18)
              Text {
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                text: tile.modelData.surprise ? "Surprise me" : tile.modelData.name
                elide: Text.ElideRight
                color: tile.modelData.surprise ? root.accent : (tile.current ? root.fg : root.alphaOf(root.fg, 0.72))
                font.family: root.family; font.pixelSize: Style.font.bodySmall + 1
                font.weight: tile.current || tile.modelData.surprise ? Font.DemiBold : Font.Medium
              }
              Dots {
                id: tileDots
                anchors.left: parent.left
                y: Style.space(20)
                colors: tile.modelData.surprise ? [] : (tile.modelData.palette || []).slice(0, 3)
                size: Style.space(7)
              }
            }
            MouseArea {
              id: tileMouse
              anchors.fill: thumbBox
              z: -1
              hoverEnabled: true
              acceptedButtons: Qt.LeftButton | Qt.RightButton
              cursorShape: Qt.PointingHandCursor
              onClicked: function(mouse) {
                root.cursor = tile.index
                if (mouse.button === Qt.RightButton) { if (tile.modelData.slug) root.act("favorite", tile.modelData.slug) }
                else root.activateTile(tile.modelData)
              }
            }
            PanelToolTip {
              visible: tileMouse.containsMouse && !tile.modelData.surprise && tile.modelData.name.length > 14
              text: tile.modelData.name || ""
              fontFamily: root.family
            }
          }
        }

        // ================================================ Discover
        Column {
          id: discoverCol
          visible: root.themeScope === "discover" && !root.linkMode
          width: parent.width
          spacing: Style.space(10)

          // Detail card for the picked community theme
          GlassTile {
            visible: !!root.discoverPick
            width: parent.width
            foreground: root.fg
            implicitHeight: pickCol.implicitHeight + Style.space(24)
            Column {
              id: pickCol
              x: Style.space(12); y: Style.space(12)
              width: parent.width - Style.space(24)
              spacing: Style.space(10)
              Row {
                width: parent.width
                spacing: Style.space(12)
                ClippingRectangle {
                  width: Style.space(root.expanded ? 260 : 132); height: Style.space(root.expanded ? 160 : 82)
                  radius: Style.space(9)
                  color: root.alphaOf(root.fg, 0.06)
                  Image {
                    anchors.fill: parent
                    source: root.discoverPick ? (root.discoverPick.preview || "") : ""
                    sourceSize.width: 360
                    fillMode: Image.PreserveAspectCrop
                    asynchronous: true
                  }
                }
                Column {
                  width: parent.width - Style.space(root.expanded ? 272 : 144)
                  spacing: Style.space(3)
                  Text {
                    width: parent.width; elide: Text.ElideRight
                    textFormat: Text.PlainText
                    text: root.discoverPick ? root.discoverPick.name : ""
                    color: root.fg
                    font.family: root.family; font.pixelSize: Style.font.body + 2; font.weight: Font.DemiBold
                  }
                  Text {
                    width: parent.width; elide: Text.ElideRight
                    textFormat: Text.PlainText
                    text: root.discoverPick ? "by " + root.discoverPick.owner + "  ·  ★ " + root.discoverPick.stars + (root.discoverPick.official ? "  ·  omarchy.org" : "") : ""
                    color: root.alphaOf(root.fg, 0.6)
                    font.family: root.family; font.pixelSize: Style.font.bodySmall + 1
                  }
                  Dots { colors: root.discoverPick ? (root.discoverPick.palette || []) : []; size: Style.space(9); spacing: Style.space(3) }
                  Text {
                    width: parent.width
                    visible: text !== ""
                    maximumLineCount: 2; wrapMode: Text.WordWrap; elide: Text.ElideRight
                    textFormat: Text.PlainText
                    text: root.discoverInstallError || root.discoverProgress || (root.discoverPick ? (root.discoverPick.description || "") : "")
                    color: root.discoverInstallError ? root.urgent : root.alphaOf(root.fg, 0.55)
                    font.family: root.family; font.pixelSize: Style.font.caption + 1
                  }
                }
              }
              Text {
                visible: !!root.discoverPick && (root.discoverPick.warnings || []).length > 0
                width: parent.width
                wrapMode: Text.WordWrap
                textFormat: Text.PlainText
                    text: root.discoverPick ? "Note: " + (root.discoverPick.warnings || []).join(" · ") + " (skipped on install)" : ""
                color: root.alphaOf(root.fg, 0.5)
                font.family: root.family; font.pixelSize: Style.font.caption + 1
              }
              Row {
                width: parent.width
                spacing: Style.space(8)
                PrimaryButton {
                  width: parent.width - installOnlyD.width - sourceD.width - closeD.width - parent.spacing * 3
                  glyph: discoverInstallProc.running ? "" : "󰄬"
                  label: discoverInstallProc.running ? "Installing…" : "Install & apply"
                  enabledState: !discoverInstallProc.running && !root.importing
                  onClicked: root.installDiscover(true)
                }
                GhostButton { id: installOnlyD; label: "Install"; enabledState: !discoverInstallProc.running && !root.importing; onClicked: root.installDiscover(false) }
                GhostButton {
                  id: sourceD
                  label: "󰏌"
                  onClicked: if (root.discoverPick) Quickshell.execDetached(["xdg-open", root.discoverPick.repo])
                  PanelToolTip { visible: sourceD.containsMouse; text: "Open on GitHub"; fontFamily: root.family }
                }
                GhostButton { id: closeD; label: "󰅖"; onClicked: { root.discoverPick = null; root.discoverInstallError = "" } }
              }
            }
          }

          Text {
            visible: !root.discoverLoaded || root.discoverError !== "" || root.discoverModel.length === 0
            width: parent.width
            topPadding: Style.space(18); bottomPadding: Style.space(18)
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            text: root.discoverError ? root.discoverError
              : !root.discoverLoaded ? "Loading community themes…"
              : root.query ? "No community themes match “" + root.query + "”." : "You already have every theme in this view."
            color: root.discoverError ? root.urgent : root.alphaOf(root.fg, 0.55)
            font.family: root.family; font.pixelSize: Style.font.body
          }

          GridView {
            id: discoverGrid
            HoverHandler { id: discoverHover }
            visible: root.discoverModel.length > 0
            width: parent.width
            readonly property real thumbH: Math.round((width / root.gridCols - Style.space(9)) * 0.62)
            height: root.expanded ? Math.max(Style.space(200), rightPane.height - discoverCol.y - y)
                                  : root.fitted(Math.min(contentHeight, (thumbH + Style.space(46)) * (root.discoverPick ? 2 : 3)), Style.space(96))
            cellWidth: width / root.gridCols
            cellHeight: thumbH + Style.space(46)
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            model: root.discoverModel
            cacheBuffer: 400
            QQC.ScrollBar.vertical: QQC.ScrollBar { policy: QQC.ScrollBar.AsNeeded }
            delegate: Item {
              id: dtile
              required property var modelData
              readonly property bool picked: !!root.discoverPick && root.discoverPick.id === modelData.id
              width: discoverGrid.cellWidth
              height: discoverGrid.cellHeight
              ClippingRectangle {
                id: dthumb
                x: Style.space(3); y: Style.space(3)
                width: parent.width - Style.space(6)
                height: discoverGrid.thumbH
                radius: Style.space(10)
                color: dtile.modelData.palette && dtile.modelData.palette.length ? dtile.modelData.palette[0] : root.alphaOf(root.fg, 0.05)
                // Until the preview arrives, show the palette as a strip.
                Row {
                  anchors.bottom: parent.bottom
                  width: parent.width; height: Style.space(6)
                  Repeater {
                    model: (dtile.modelData.palette || []).slice(1)
                    Rectangle { required property var modelData; width: dthumb.width / 4; height: parent.height; color: modelData }
                  }
                }
                Image {
                  anchors.fill: parent
                  source: dtile.modelData.preview || ""
                  sourceSize.width: 360
                  fillMode: Image.PreserveAspectCrop
                  asynchronous: true
                  opacity: status === Image.Ready ? 1 : 0
                  Behavior on opacity { NumberAnimation { duration: 160 } }
                }
                Rectangle {
                  anchors.top: parent.top; anchors.right: parent.right
                  anchors.margins: Style.space(6)
                  height: Style.space(18); width: starText.implicitWidth + Style.space(12)
                  radius: height / 2
                  color: Qt.rgba(0.035, 0.035, 0.03, 0.62)
                  Text { id: starText; anchors.centerIn: parent; text: "★ " + dtile.modelData.stars; color: "#ffe3a3"; font.family: root.family; font.pixelSize: Style.font.caption }
                }
              }
              Rectangle {
                x: dthumb.x - 2; y: dthumb.y - 2
                width: dthumb.width + 4; height: dthumb.height + 4
                radius: dthumb.radius + 2
                color: "transparent"
                border.width: dtile.picked || dMouse.containsMouse ? 2 : 1
                border.color: dtile.picked ? root.accent : dMouse.containsMouse ? root.alphaOf(root.fg, 0.35) : root.alphaOf(root.fg, 0.06)
                Behavior on border.color { ColorAnimation { duration: 140; easing.type: Easing.OutCubic } }
              }
              Item {
                x: Style.space(5)
                y: dthumb.y + dthumb.height + Style.space(6)
                width: parent.width - Style.space(10)
                height: Style.space(18)
                Text {
                  anchors.left: parent.left; anchors.right: parent.right
                  textFormat: Text.PlainText
                    text: dtile.modelData.name
                  elide: Text.ElideRight
                  color: dtile.picked ? root.fg : root.alphaOf(root.fg, 0.72)
                  font.family: root.family; font.pixelSize: Style.font.bodySmall + 1
                  font.weight: dtile.picked ? Font.DemiBold : Font.Medium
                }
                Text {
                  y: Style.space(17)
                  width: parent.width
                  elide: Text.ElideRight
                  textFormat: Text.PlainText
                    text: dtile.modelData.owner
                  color: root.alphaOf(root.fg, 0.42)
                  font.family: root.family; font.pixelSize: Style.font.caption
                }
              }
              MouseArea {
                id: dMouse
                anchors.fill: dthumb
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: { root.discoverPick = dtile.picked ? null : dtile.modelData; root.discoverInstallError = "" }
              }
            }
          }
        }

        Text {
          visible: root.themeScope !== "discover" && !root.linkMode && root.filtered.length === 0 && root.loaded
          width: parent.width
          topPadding: Style.space(20); bottomPadding: Style.space(20)
          horizontalAlignment: Text.AlignHCenter
          wrapMode: Text.WordWrap
          text: root.themeScope === "recent" && !root.query && !root.favoritesOnly && root.themeMode === "all" ? "Themes you switch away from show up here, newest first." : root.favoritesOnly && !root.query ? ((root.values.favorite_count || 0) ? "No favorites match this filter." : "No favorites yet. Star a theme to keep it here.") : (root.query ? "No themes match “" + root.query + "”." : "No " + (root.themeMode === "all" ? "" : root.themeMode + " ") + "themes found.")
          color: root.alphaOf(root.fg, 0.55)
          font.family: root.family; font.pixelSize: Style.font.body
        }
        }
      }

      // ================================================================ Backgrounds
      Column {
        id: bgCol
        visible: root.tab === 1
        width: parent.width
        spacing: Style.space(12)

        ScopeSwitch {
          width: parent.width
          value: root.bgScope
          options: [{ key: "theme", label: "This theme", count: String((root.values.backgrounds || []).length) },
                    { key: "more", label: "Find more" }]
          onPicked: function(key) { root.bgScope = key }
        }

        Column {
          id: bgBody
          parent: root.expanded ? bgSlot : bgCol
          // A Column positioned it; start at the top of the pane after moving.
          onParentChanged: if (parent === bgSlot) { x = 0; y = 0 }
          width: parent.width
          spacing: Style.space(12)

        Flow {
          visible: root.bgScope === "theme"
          width: parent.width
          spacing: Style.space(8)
          Repeater {
            model: root.values.backgrounds || []
            Item {
              id: bgTile
              required property var modelData
              required property int index
              readonly property bool on: index === root.values.background_index
              width: root.expanded ? (parent.width - Style.space(16)) / 3 : (parent.width - Style.space(8)) / 2
              height: bgBox.height + Style.space(24)
              ClippingRectangle {
                id: bgBox
                width: parent.width
                height: Math.round(width * 0.58)
                radius: Style.space(10)
                color: root.alphaOf(root.fg, 0.05)
                Image {
                  anchors.fill: parent
                  source: bgTile.modelData.url
                  sourceSize.width: 420
                  fillMode: Image.PreserveAspectCrop
                  asynchronous: true
                }
                Rectangle {
                  visible: bgTile.on
                  anchors.top: parent.top; anchors.right: parent.right
                  anchors.margins: Style.space(7)
                  width: Style.space(20); height: width; radius: width / 2
                  color: root.accent
                  Text { anchors.centerIn: parent; text: "󰄬"; color: Commons.Color.background; font.family: root.glyphFamily; font.pixelSize: Style.font.bodySmall }
                }
              }
              Rectangle {
                x: -2; y: -2
                width: bgBox.width + 4; height: bgBox.height + 4
                radius: bgBox.radius + 2
                color: "transparent"
                border.width: bgTile.on || bgMouse.containsMouse ? 2 : 1
                border.color: bgTile.on ? root.accent : bgMouse.containsMouse ? root.alphaOf(root.fg, 0.35) : root.alphaOf(root.fg, 0.06)
              }
              Text {
                y: bgBox.height + Style.space(6)
                width: parent.width
                readonly property string pretty: bgTile.modelData.name.replace(/^\d+[-_ ]*/, "").replace(/[-_@]+/g, " ").replace(/\b(4k|8k|hd|uhd)\b/gi, "").trim()
                text: /^[a-z]{3,}( [a-z]+)*$/i.test(pretty) ? pretty : "Background " + (bgTile.index + 1)
                elide: Text.ElideRight
                color: bgTile.on ? root.fg : root.alphaOf(root.fg, 0.7)
                font.family: root.family; font.pixelSize: Style.font.bodySmall + 1
                font.weight: bgTile.on ? Font.DemiBold : Font.Medium
                font.capitalization: Font.Capitalize
              }
              MouseArea {
                id: bgMouse
                anchors.fill: bgBox
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: if (!bgTile.on) root.act("background-set", bgTile.modelData.path)
              }
            }
          }
        }
        Text {
          visible: root.bgScope === "theme" && !(root.values.backgrounds || []).length
          width: parent.width
          horizontalAlignment: Text.AlignHCenter
          text: "This theme has no backgrounds."
          color: root.alphaOf(root.fg, 0.55)
          font.family: root.family; font.pixelSize: Style.font.body
        }

        GlassTile {
          visible: root.bgScope === "theme"
          width: parent.width
          foreground: root.fg
          implicitHeight: shuffleRow.implicitHeight + Style.space(24)
          Row {
            id: shuffleRow
            x: Style.space(12); y: Style.space(12)
            width: parent.width - Style.space(24)
            spacing: Style.space(12)
            Rectangle {
              width: Style.space(32); height: width; radius: Style.space(9)
              anchors.verticalCenter: parent.verticalCenter
              color: root.alphaOf(root.fg, 0.06)
              Text { anchors.centerIn: parent; text: "󰒝"; color: root.alphaOf(root.fg, 0.75); font.family: root.glyphFamily; font.pixelSize: Style.font.body + 1 }
            }
            Column {
              width: parent.width - Style.space(44) - shuffleSwitch.width - Style.space(12)
              anchors.verticalCenter: parent.verticalCenter
              spacing: Style.space(2)
              Text { text: "Shuffle backgrounds"; color: root.fg; font.family: root.family; font.pixelSize: Style.font.body + 1; font.weight: Font.DemiBold }
              Text { width: parent.width; wrapMode: Text.WordWrap; text: "Pick a matching one each time the theme changes"; color: root.alphaOf(root.fg, 0.55); font.family: root.family; font.pixelSize: Style.font.bodySmall + 1 }
            }
            ToggleSwitch {
              id: shuffleSwitch
              anchors.verticalCenter: parent.verticalCenter
              checked: !!root.values.shuffle_background
              foreground: root.fg
              onToggled: root.act("background-mode", root.values.shuffle_background ? "theme" : "shuffle")
            }
          }
        }
        // ================================================ Find more (openly licensed wallpapers)
        Column {
          id: findMoreCol
          visible: root.bgScope === "more"
          width: parent.width
          spacing: Style.space(10)

          Field {
            id: wallSearch
            width: parent.width
            placeholderText: "Search free wallpapers (CC0 / CC BY)"
            leftPadding: Style.space(32)
            onAccepted: root.searchWalls(text.trim(), 1)
            Keys.onEscapePressed: { if (text) text = ""; else { focus = false; keyboard.forceActiveFocus() } }
            Text {
              x: Style.space(11)
              anchors.verticalCenter: parent.verticalCenter
              text: "󰍉"
              color: root.alphaOf(root.fg, 0.5)
              font.family: root.glyphFamily; font.pixelSize: Style.font.body + 1
            }
          }
          Flow {
            width: parent.width
            spacing: Style.space(6)
            Repeater {
              model: root.wallSuggest
              Chip {
                required property var modelData
                label: modelData
                on: root.wallQuery === modelData
                onClicked: { wallSearch.text = modelData; root.searchWalls(modelData, 1) }
              }
            }
          }

          // Detail for the picked wallpaper
          GlassTile {
            visible: !!root.wallPick
            width: parent.width
            foreground: root.fg
            implicitHeight: wallPickCol.implicitHeight + Style.space(24)
            Column {
              id: wallPickCol
              x: Style.space(12); y: Style.space(12)
              width: parent.width - Style.space(24)
              spacing: Style.space(10)
              ClippingRectangle {
                width: parent.width
                height: Math.round(width * (root.expanded ? 0.26 : 0.34))
                radius: Style.space(9)
                color: root.alphaOf(root.fg, 0.06)
                Image {
                  anchors.fill: parent
                  source: root.wallPick ? (root.wallPick.thumb || "") : ""
                  sourceSize.width: 360
                  fillMode: Image.PreserveAspectCrop
                  asynchronous: true
                }
              }
              Column {
                width: parent.width
                spacing: Style.space(2)
                Text {
                  width: parent.width; elide: Text.ElideRight
                  textFormat: Text.PlainText
                    text: root.wallPick ? root.wallPick.title : ""
                  color: root.fg
                  font.family: root.family; font.pixelSize: Style.font.body + 1; font.weight: Font.DemiBold
                }
                Text {
                  width: parent.width; elide: Text.ElideRight
                  text: root.wallPick ? (root.wallPick.creator ? root.wallPick.creator + "  ·  " : "") + root.wallPick.license + "  ·  " + root.wallPick.width + "×" + root.wallPick.height : ""
                  color: root.alphaOf(root.fg, 0.55)
                  font.family: root.family; font.pixelSize: Style.font.bodySmall + 1
                }
              }
              Row {
                width: parent.width
                spacing: Style.space(8)
                PrimaryButton {
                  width: parent.width - saveWallBtn.width - wallSrc.width - wallClose.width - parent.spacing * 3
                  glyph: root.wallSaving ? "" : "󰸉"
                  label: root.wallSaving ? "Downloading…" : "Use as background"
                  enabledState: !root.wallSaving
                  onClicked: root.saveWall(root.wallPick, true)
                }
                GhostButton { id: saveWallBtn; label: "Save"; enabledState: !root.wallSaving; onClicked: root.saveWall(root.wallPick, false) }
                GhostButton {
                  id: wallSrc
                  label: "󰏌"
                  onClicked: if (root.wallPick && root.wallPick.landing) Quickshell.execDetached(["xdg-open", root.wallPick.landing])
                  PanelToolTip { visible: wallSrc.containsMouse; text: "Open source & license"; fontFamily: root.family }
                }
                GhostButton { id: wallClose; label: "󰅖"; onClicked: root.wallPick = null }
              }
            }
          }

          Text {
            readonly property bool searching: wallProc.running && root.wallPage === 1
            visible: searching || root.wallError !== "" || !root.wallLoaded || root.wallResults.length === 0
            width: parent.width
            topPadding: Style.space(14); bottomPadding: Style.space(14)
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            // New searches can be slow on Openverse's side; repeats are cached.
            text: searching ? "Searching “" + (root.wallQuery || "landscape") + "”… new searches can take up to a minute."
              : root.wallError ? root.wallError : !root.wallLoaded ? "Finding wallpapers…" : "Nothing found. Try another word."
            color: root.wallError ? root.urgent : root.alphaOf(root.fg, 0.55)
            font.family: root.family; font.pixelSize: Style.font.body
          }

          GridView {
            id: wallGrid
            HoverHandler { id: wallHover }
            visible: root.wallResults.length > 0
            width: parent.width
            readonly property int cols: root.expanded ? 3 : 2
            readonly property real thumbH: Math.round((width / cols - Style.space(8)) * 0.58)
            height: root.expanded ? Math.max(Style.space(180), rightPane.height - findMoreCol.y - y - Style.space(80))
                                  : root.fitted(Math.min(contentHeight, (thumbH + Style.space(30)) * (root.wallPick ? 1.5 : 2.6)), Style.space(96))
            cellWidth: width / cols
            cellHeight: thumbH + Style.space(30)
            clip: true
            boundsBehavior: Flickable.StopAtBounds
            model: root.wallResults
            cacheBuffer: 400
            QQC.ScrollBar.vertical: QQC.ScrollBar { policy: QQC.ScrollBar.AsNeeded }
            // Reaching the end loads the next page.
            onAtYEndChanged: if (atYEnd && root.wallHasMore && !wallProc.running && contentHeight > height) root.searchWalls(root.wallQuery, root.wallPage + 1)
            delegate: Item {
              id: wtile
              required property var modelData
              readonly property bool picked: !!root.wallPick && root.wallPick.id === modelData.id
              width: wallGrid.cellWidth
              height: wallGrid.cellHeight
              ClippingRectangle {
                id: wthumb
                x: Style.space(3); y: Style.space(3)
                width: parent.width - Style.space(6)
                height: wallGrid.thumbH
                radius: Style.space(10)
                color: root.alphaOf(root.fg, 0.05)
                Image {
                  anchors.fill: parent
                  source: wtile.modelData.thumb || ""
                  sourceSize.width: 360
                  fillMode: Image.PreserveAspectCrop
                  asynchronous: true
                  opacity: status === Image.Ready ? 1 : 0
                  Behavior on opacity { NumberAnimation { duration: 160 } }
                }
                Rectangle {
                  anchors.left: parent.left; anchors.bottom: parent.bottom
                  anchors.margins: Style.space(6)
                  height: Style.space(18); width: licText.implicitWidth + Style.space(12)
                  radius: height / 2
                  color: Qt.rgba(0.035, 0.035, 0.03, 0.62)
                  Text { id: licText; anchors.centerIn: parent; text: wtile.modelData.license; color: "#fff7e3"; font.family: root.family; font.pixelSize: Style.font.caption }
                }
              }
              Rectangle {
                x: wthumb.x - 2; y: wthumb.y - 2
                width: wthumb.width + 4; height: wthumb.height + 4
                radius: wthumb.radius + 2
                color: "transparent"
                border.width: wtile.picked || wMouse.containsMouse ? 2 : 1
                border.color: wtile.picked ? root.accent : wMouse.containsMouse ? root.alphaOf(root.fg, 0.35) : root.alphaOf(root.fg, 0.06)
                Behavior on border.color { ColorAnimation { duration: 140; easing.type: Easing.OutCubic } }
              }
              Text {
                x: Style.space(5)
                y: wthumb.y + wthumb.height + Style.space(5)
                width: parent.width - Style.space(10)
                elide: Text.ElideRight
                textFormat: Text.PlainText
                    text: wtile.modelData.title
                color: wtile.picked ? root.fg : root.alphaOf(root.fg, 0.7)
                font.family: root.family; font.pixelSize: Style.font.bodySmall + 1
                font.weight: wtile.picked ? Font.DemiBold : Font.Medium
              }
              MouseArea {
                id: wMouse
                anchors.fill: wthumb
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.wallPick = wtile.picked ? null : wtile.modelData
              }
            }
          }
          Chip {
            id: wallMore
            visible: root.wallHasMore && root.wallResults.length > 0
            anchors.horizontalCenter: parent.horizontalCenter
            label: wallProc.running ? "Loading…" : "Load more"
            onClicked: if (!wallProc.running) root.searchWalls(root.wallQuery, root.wallPage + 1)
          }
          Text {
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            text: "Openly licensed images via Openverse. Saved to this theme with credit in CREDITS.md."
            color: root.alphaOf(root.fg, 0.4)
            font.family: root.family; font.pixelSize: Style.font.caption + 1
          }
        }
        }
      }

      // ================================================================ Rotation
      Column {
        id: rotationTab
        visible: root.tab === 2
        width: parent.width
        spacing: Style.space(14)

        Column {
          id: rotBody
          parent: root.expanded ? rotSlot : rotationTab
          // A Column positioned it; start at the top of the pane after moving.
          onParentChanged: if (parent === rotSlot) { x = 0; y = 0 }
          width: root.expanded ? Math.min(parent.width, Style.space(640)) : parent.width
          spacing: Style.space(14)

        GlassTile {
          width: parent.width
          foreground: root.fg
          implicitHeight: rotCol.implicitHeight + Style.space(28)
          Column {
            id: rotCol
            x: Style.space(14); y: Style.space(14)
            width: parent.width - Style.space(28)
            spacing: Style.space(12)
            Row {
              width: parent.width
              spacing: Style.space(12)
              Rectangle {
                width: Style.space(32); height: width; radius: Style.space(9)
                anchors.verticalCenter: parent.verticalCenter
                color: root.alphaOf(root.accent, 0.16)
                Text { anchors.centerIn: parent; text: "󰑓"; color: root.accent; font.family: root.glyphFamily; font.pixelSize: Style.font.body + 2 }
              }
              Column {
                width: parent.width - Style.space(44) - rotSwitch.width - Style.space(12)
                anchors.verticalCenter: parent.verticalCenter
                spacing: Style.space(2)
                Text { text: "Random rotation"; color: root.fg; font.family: root.family; font.pixelSize: Style.font.body + 1; font.weight: Font.DemiBold }
                Text { text: root.remaining(); color: root.alphaOf(root.fg, 0.55); font.family: root.family; font.pixelSize: Style.font.bodySmall + 1 }
              }
              ToggleSwitch {
                id: rotSwitch
                anchors.verticalCenter: parent.verticalCenter
                checked: !!root.values.enabled
                foreground: root.fg
                onToggled: root.act("toggle")
              }
            }
            Rectangle {
              width: parent.width; height: Style.space(3); radius: height / 2
              color: root.alphaOf(root.fg, 0.08)
              Rectangle {
                height: parent.height; radius: parent.radius
                color: root.accent
                opacity: root.values.enabled ? 1 : 0.35
                width: parent.width * (root.values.enabled && root.values.interval_minutes
                  ? Math.max(0.02, 1 - (root.values.seconds_remaining || 0) / (root.values.interval_minutes * 60)) : 0)
                Behavior on width { NumberAnimation { duration: 400; easing.type: Easing.OutCubic } }
              }
            }
          }
        }

        GlassTile {
          width: parent.width
          foreground: root.fg
          readonly property var sun: root.values.sun || ({})
          implicitHeight: sunCol.implicitHeight + Style.space(28)
          Column {
            id: sunCol
            x: Style.space(14); y: Style.space(14)
            width: parent.width - Style.space(28)
            spacing: Style.space(10)
            Row {
              width: parent.width
              spacing: Style.space(12)
              Rectangle {
                width: Style.space(32); height: width; radius: Style.space(9)
                anchors.verticalCenter: parent.verticalCenter
                color: root.alphaOf(root.accent, 0.16)
                Text { anchors.centerIn: parent; text: parent.parent.parent.parent.sun.phase === "night" ? "󰖔" : "󰖙"; color: root.accent; font.family: root.glyphFamily; font.pixelSize: Style.font.body + 2 }
              }
              Column {
                width: parent.width - Style.space(44) - sunSwitch.width - Style.space(12)
                anchors.verticalCenter: parent.verticalCenter
                spacing: Style.space(2)
                Text { text: "Follow the sun"; color: root.fg; font.family: root.family; font.pixelSize: Style.font.body + 1; font.weight: Font.DemiBold }
                Text {
                  width: parent.width
                  elide: Text.ElideRight
                  readonly property var sun: root.values.sun || ({})
                  text: !sun.sunrise && !sun.sunset ? (sun.phase === "night" ? "Polar night · dark all day" : "Light themes by day, dark at night")
                    : "Light at " + root.sunTime(sun.sunrise) + " · dark at " + root.sunTime(sun.sunset)
                  color: root.alphaOf(root.fg, 0.55); font.family: root.family; font.pixelSize: Style.font.bodySmall + 1
                }
              }
              ToggleSwitch {
                id: sunSwitch
                anchors.verticalCenter: parent.verticalCenter
                checked: !!(root.values.sun && root.values.sun.enabled)
                foreground: root.fg
                onToggled: root.act("sun-toggle")
              }
            }
            Column {
              visible: !!(root.values.sun && root.values.sun.enabled)
              width: parent.width
              spacing: Style.space(6)
              readonly property var sun: root.values.sun || ({})
              Row {
                width: parent.width
                spacing: Style.space(6)
                readonly property real cell: (width - spacing) / 2
                Repeater {
                  model: [{ glyph: "󰖙", label: "Day", name: (root.values.sun || {}).light_name || "" },
                          { glyph: "󰖔", label: "Night", name: (root.values.sun || {}).dark_name || "" }]
                  Rectangle {
                    required property var modelData
                    width: parent.cell; height: Style.space(42)
                    radius: Style.space(9)
                    color: Commons.Color.background.hslLightness > 0.5 ? root.alphaOf(root.fg, 0.05) : Qt.rgba(0, 0, 0, 0.2)
                    Column {
                      x: Style.space(10); anchors.verticalCenter: parent.verticalCenter
                      width: parent.width - Style.space(20)
                      spacing: 1
                      Text { text: modelData.glyph + "  " + modelData.label; color: root.alphaOf(root.fg, 0.5); font.family: root.family; font.pixelSize: Style.font.caption + 1 }
                      Text { width: parent.width; elide: Text.ElideRight; text: modelData.name || "Learns from your picks"; color: modelData.name ? root.fg : root.alphaOf(root.fg, 0.45); font.family: root.family; font.pixelSize: Style.font.bodySmall + 1; font.weight: Font.Medium }
                    }
                  }
                }
              }
              Item {
                width: parent.width
                height: Math.max(locText.implicitHeight, locChip.height)
                Text {
                  id: locText
                  anchors.left: parent.left; anchors.right: locChip.left; anchors.rightMargin: Style.space(8)
                  anchors.verticalCenter: parent.verticalCenter
                  elide: Text.ElideRight
                  readonly property var loc: (root.values.sun || {}).location || ({})
                  text: "󰍎  " + (loc.label || "Unknown location") + (loc.source === "timezone" ? " · from your time zone" : "")
                  color: root.alphaOf(root.fg, 0.5)
                  font.family: root.family; font.pixelSize: Style.font.caption + 1
                }
                Chip {
                  id: locChip
                  anchors.right: parent.right
                  anchors.verticalCenter: parent.verticalCenter
                  label: sunLoc.visible ? "Cancel" : "Change"
                  onClicked: { sunLoc.visible = !sunLoc.visible; if (sunLoc.visible) sunLoc.forceActiveFocus() }
                }
              }
              Row {
                visible: sunLoc.visible
                width: parent.width
                spacing: Style.space(8)
                Field {
                  id: sunLoc
                  visible: false
                  width: parent.width - autoLoc.width - parent.spacing
                  placeholderText: "Latitude, longitude  (e.g. 38.9, -77.0)"
                  onAccepted: { root.act("sun-location", text.trim()); visible = false; text = "" }
                  Keys.onEscapePressed: { visible = false; text = "" }
                }
                GhostButton { id: autoLoc; label: "Use time zone"; onClicked: { root.act("sun-location", "auto"); sunLoc.visible = false } }
              }
            }
          }
        }

        Column {
          width: parent.width
          spacing: Style.space(8)
          Label { text: "Change every" }
          SegmentTrack {
            width: parent.width
            foreground: root.fg
            Row {
              width: parent.width
              spacing: Style.space(2)
              Repeater {
                model: [15, 30, 60]
                Rectangle {
                  required property int modelData
                  readonly property bool on: root.values.interval_minutes === modelData
                  width: (parent.width - Style.space(4)) / 3
                  height: Style.space(30)
                  radius: height / 2
                  color: on ? root.alphaOf(root.fg, 0.14) : "transparent"
                  Text {
                    anchors.centerIn: parent
                    text: modelData === 60 ? "1 hour" : modelData + " min"
                    color: parent.on ? root.fg : root.alphaOf(root.fg, 0.55)
                    font.family: root.family; font.pixelSize: Style.font.bodySmall + 1
                    font.weight: parent.on ? Font.DemiBold : Font.Medium
                  }
                  MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: root.act("interval", modelData) }
                }
              }
            }
          }
        }

        Row {
          width: parent.width
          spacing: Style.space(8)
          PrimaryButton {
            width: parent.width - (hiddenButton.visible ? hiddenButton.width + parent.spacing : 0)
            glyph: "󰒝"; label: "Next theme now"
            enabledState: !root.busy
            onClicked: root.act("random")
          }
          GhostButton {
            id: hiddenButton
            visible: (root.values.hidden_count || 0) > 0
            glyph: "󰈉"; label: root.values.hidden_count + " hidden"
            onClicked: root.act("unhide-all")
            PanelToolTip { visible: parent.containsMouse; text: "Show hidden themes again"; fontFamily: root.family }
          }
        }
        }
      }

      // ---- Footer
      Item {
        parent: root.expanded ? footerSlot : content
        onParentChanged: if (parent === footerSlot) { x = 0; y = 0 }
        width: parent.width
        height: Style.space(28)
        Rectangle { width: parent.width; height: 1; color: root.alphaOf(root.fg, 0.08) }
        Row {
          id: footerStatus
          width: parent.width * 0.43
          anchors.left: parent.left
          anchors.leftMargin: Style.space(4)
          anchors.bottom: parent.bottom
          spacing: Style.space(7)
          Rectangle {
            width: Style.space(7); height: width; radius: width / 2
            anchors.verticalCenter: parent.verticalCenter
            color: root.values.enabled ? root.accent : root.alphaOf(root.fg, 0.3)
          }
          Text {
            width: footerStatus.width - Style.space(14)
            elide: Text.ElideRight
            text: root.message || root.remaining()
            color: root.message && root.message.indexOf("didn't") >= 0 ? root.urgent : root.alphaOf(root.fg, 0.6)
            font.family: root.family; font.pixelSize: Style.font.bodySmall + 1
          }
        }
        Text {
          anchors.right: parent.right
          anchors.rightMargin: Style.space(4)
          anchors.bottom: parent.bottom
          text: root.tab === 0 ? (root.themeScope === "discover" ? "Community themes · omarchytheme.com" : "/ Search · ↑↓ Browse · Enter Apply")
            : root.tab === 1 ? (root.bgScope === "more" ? "Saves to " + root.values.current_name : "Backgrounds for " + root.values.current_name)
            : "Press 1 2 3 to switch tabs"
          color: root.alphaOf(root.fg, 0.38)
          elide: Text.ElideRight
          width: Math.min(implicitWidth, parent.width * 0.55)
          horizontalAlignment: Text.AlignRight
          font.family: root.family; font.pixelSize: Style.font.caption + 1
        }
      }
    }

    // ---- Wide layout: gallery pane and a footer pinned under the sidebar
    // Each tab body moves into its own slot. The bodies themselves stay
    // visible: reparenting an item while it is hidden left it unpainted.
    Item {
      id: rightPane
      visible: root.expanded
      x: root.sidebarWidth + Style.space(18)
      width: parent.width - x
      height: parent.height
      Item { id: themesSlot; anchors.fill: parent; visible: root.tab === 0 }
      Item { id: bgSlot; anchors.fill: parent; visible: root.tab === 1 }
      Item { id: rotSlot; anchors.fill: parent; visible: root.tab === 2 }
    }
    Rectangle {
      visible: root.expanded
      x: root.sidebarWidth + Style.space(8)
      width: 1; height: parent.height
      color: root.alphaOf(root.fg, 0.07)
    }
    Item {
      id: footerSlot
      visible: root.expanded
      width: root.sidebarWidth
      height: Style.space(28)
      anchors.bottom: parent.bottom
    }

    // ---- Window border picker (overlays the card under the hero)
    MouseArea {
      anchors.fill: parent
      visible: root.borderOpen
      onClicked: root.borderOpen = false
    }
    Rectangle {
      id: borderPop
      visible: opacity > 0
      opacity: root.borderOpen ? 1 : 0
      scale: root.borderOpen ? 1 : 0.97
      transformOrigin: Item.TopRight
      Behavior on opacity { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
      Behavior on scale { NumberAnimation { duration: 200; easing.type: Easing.OutQuint } }
      z: 20
      width: Style.space(264)
      x: (root.expanded ? root.sidebarWidth : parent.width) - width - Style.space(4)
      y: hero.y + hero.height - Style.space(10)
      height: borderCol.implicitHeight + Style.space(28)
      radius: Style.space(14)
      color: Qt.rgba(Commons.Color.background.r, Commons.Color.background.g, Commons.Color.background.b, 0.96)
      border.width: 1
      border.color: root.alphaOf(root.fg, 0.12)
      MouseArea { anchors.fill: parent }  // keep clicks on the card from closing it
      Column {
        id: borderCol
        x: Style.space(14); y: Style.space(14)
        width: parent.width - Style.space(28)
        spacing: Style.space(12)
        Column {
          width: parent.width
          spacing: Style.space(2)
          Text { text: "Window border"; color: root.fg; font.family: root.family; font.pixelSize: Style.font.body + 1; font.weight: Font.DemiBold }
          Text {
            width: parent.width; elide: Text.ElideRight
            text: root.borderHover || ("For " + (root.shownItem ? root.shownItem.name : (root.values.current_name || "this theme")) + " · from its palette")
            color: root.alphaOf(root.fg, 0.55); font.family: root.family; font.pixelSize: Style.font.caption + 1
          }
        }
        // Consent: coloring borders needs one line in the user's hyprland.lua.
        Column {
          visible: !root.borderInfo.installed
          width: parent.width
          spacing: Style.space(10)
          Text {
            width: parent.width; wrapMode: Text.WordWrap
            text: root.borderInfo.supported === false
              ? "Window borders need Omarchy's Lua Hyprland config (~/.config/hypr/hyprland.lua)."
              : "To color window borders, Theme Studio adds one marked line to ~/.config/hypr/hyprland.lua and a small file next to it. Nothing else is changed, and ⋯ → Remove system changes takes both out again."
            color: root.alphaOf(root.fg, 0.75); font.family: root.family; font.pixelSize: Style.font.body
          }
          PrimaryButton {
            visible: root.borderInfo.supported !== false
            width: parent.width; height: Style.space(32)
            glyph: "󰄬"; label: "Allow"
            enabledState: !root.busy
            onClicked: root.act("border-install")
          }
        }
        Flow {
          id: swatchFlow
          visible: !!root.borderInfo.installed
          width: parent.width
          spacing: Style.space(8)
          readonly property real cell: (width - spacing * 5) / 6
          Repeater {
            model: root.borderInfo.options || []
            Item {
              id: swatch
              required property var modelData
              readonly property bool chosen: root.borderChoice === modelData.key
              width: swatchFlow.cell; height: width
              Rectangle {  // selection ring
                anchors.fill: parent
                radius: width / 2
                color: "transparent"
                border.width: 2
                border.color: root.fg
                opacity: swatch.chosen ? 0.9 : 0
                Behavior on opacity { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
              }
              Rectangle {
                anchors.centerIn: parent
                width: parent.width - Style.space(swatch.chosen ? 8 : 4); height: width; radius: width / 2
                color: swatch.modelData.color
                border.width: 1
                border.color: Qt.rgba(1, 1, 1, 0.14)
                scale: swatchMouse.containsMouse && !swatch.chosen ? 1.08 : 1
                Behavior on width { NumberAnimation { duration: 200; easing.type: Easing.OutQuint } }
                Behavior on scale { NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
              }
              MouseArea {
                id: swatchMouse
                anchors.fill: parent
                hoverEnabled: true
                cursorShape: Qt.PointingHandCursor
                onClicked: root.pickBorder(swatch.modelData.key)
                onContainsMouseChanged: {
                  if (containsMouse) root.borderHover = (swatch.modelData.label || swatch.modelData.key) + "  ·  " + swatch.modelData.color
                  else if (root.borderHover.startsWith(swatch.modelData.label || swatch.modelData.key)) root.borderHover = ""
                }
              }
            }
          }
        }
        Row {
          visible: !!root.borderInfo.installed
          width: parent.width
          spacing: Style.space(6)
          readonly property real cell: (width - spacing) / 2
          Repeater {
            model: [{ key: "theme", label: "Theme's color" }, { key: "none", label: "No color" }]
            Rectangle {
              id: pill
              required property var modelData
              readonly property bool chosen: root.borderChoice === modelData.key
              width: parent.cell; height: Style.space(30); radius: height / 2
              color: chosen ? root.alphaOf(root.fg, 0.14) : (pillMouse.containsMouse ? root.alphaOf(root.fg, 0.07) : "transparent")
              border.width: 1
              border.color: root.alphaOf(root.fg, chosen ? 0.22 : 0.12)
              Behavior on color { ColorAnimation { duration: 180; easing.type: Easing.OutCubic } }
              Row {
                anchors.centerIn: parent
                spacing: Style.space(6)
                Rectangle {
                  anchors.verticalCenter: parent.verticalCenter
                  width: Style.space(10); height: width; radius: width / 2
                  color: pill.modelData.key === "theme" ? root.borderColorOf("theme") : "transparent"
                  border.width: 1
                  border.color: root.alphaOf(root.fg, 0.4)
                }
                Text { text: pill.modelData.label; color: root.fg; font.family: root.family; font.pixelSize: Style.font.body; anchors.verticalCenter: parent.verticalCenter }
              }
              MouseArea { id: pillMouse; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: root.pickBorder(pill.modelData.key) }
            }
          }
        }
        Rectangle { visible: !!root.borderInfo.installed; width: parent.width; height: 1; color: root.alphaOf(root.fg, 0.08) }
        Item {
          visible: !!root.borderInfo.installed
          width: parent.width
          height: Math.max(globalText.implicitHeight, globalSwitch.height)
          Column {
            id: globalText
            anchors.left: parent.left
            anchors.right: globalSwitch.left
            anchors.rightMargin: Style.space(10)
            anchors.verticalCenter: parent.verticalCenter
            spacing: Style.space(2)
            Text { text: "No color on every theme"; color: root.fg; font.family: root.family; font.pixelSize: Style.font.body; font.weight: Font.DemiBold }
            Text {
              width: parent.width; wrapMode: Text.WordWrap
              text: "New and rotated themes too. A color picked above still wins for that theme."
              color: root.alphaOf(root.fg, 0.55); font.family: root.family; font.pixelSize: Style.font.caption + 1
            }
          }
          ToggleSwitch {
            id: globalSwitch
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            checked: root.borderGlobalNone
            foreground: root.fg
            onToggled: root.setBorderGlobal(!root.borderGlobalNone)
          }
        }
      }
    }

    // ---- ⋯ menu (overlays the card under the hero)
    MouseArea {
      anchors.fill: parent
      visible: root.menuOpen
      onClicked: { root.menuOpen = false; root.confirmDelete = false }
    }
    Rectangle {
      id: menu
      visible: root.menuOpen
      z: 20
      width: Style.space(230)
      x: (root.expanded ? root.sidebarWidth : parent.width) - width - Style.space(4)
      y: hero.y + hero.height - Style.space(10)
      height: menuCol.implicitHeight + Style.space(12)
      radius: Style.space(14)
      color: Qt.rgba(Commons.Color.background.r, Commons.Color.background.g, Commons.Color.background.b, 0.96)
      border.width: 1
      border.color: root.alphaOf(root.fg, 0.12)
      Column {
        id: menuCol
        x: Style.space(6); y: Style.space(6)
        width: parent.width - Style.space(12)
        spacing: 1
        Repeater {
          model: [
            { id: "variant", glyph: "󰔎", label: root.menuVariantLabel, show: root.menuHasVariant },
            { id: "folder", glyph: "󰉋", label: "Open theme folder", show: true },
            { id: "sep", show: true },
            { id: "hide", glyph: "󰈉", label: "Hide from rotation", show: true },
            { id: "cleanup", glyph: "󰃢", label: "Remove system changes", show: !!(root.values.border && root.values.border.installed) },
            { id: "delete", glyph: "󰆴", label: "Delete theme…", show: root.menuCanDelete, danger: true }
          ].filter(i => i.show)
          Rectangle {
            required property var modelData
            width: menuCol.width
            height: modelData.id === "sep" ? Style.space(9) : Style.space(34)
            radius: Style.space(8)
            color: modelData.id !== "sep" && itemMouse.containsMouse ? root.alphaOf(root.fg, 0.08) : "transparent"
            Rectangle { visible: modelData.id === "sep"; anchors.centerIn: parent; width: parent.width - Style.space(12); height: 1; color: root.alphaOf(root.fg, 0.08) }
            Row {
              visible: modelData.id !== "sep"
              anchors.verticalCenter: parent.verticalCenter
              x: Style.space(10)
              spacing: Style.space(10)
              Text { text: modelData.glyph || ""; color: modelData.danger ? root.urgent : root.alphaOf(root.fg, 0.75); font.family: root.glyphFamily; font.pixelSize: Style.font.body + 1; anchors.verticalCenter: parent.verticalCenter }
              Text { text: modelData.id === "delete" && root.confirmDelete ? "Click again to delete" : (modelData.label || ""); color: modelData.danger ? root.urgent : root.fg; font.family: root.family; font.pixelSize: Style.font.body; font.weight: modelData.danger && root.confirmDelete ? Font.DemiBold : Font.Normal }
            }
            MouseArea {
              id: itemMouse
              anchors.fill: parent
              enabled: modelData.id !== "sep"
              hoverEnabled: true
              cursorShape: Qt.PointingHandCursor
              onClicked: {
                if (modelData.id === "variant") { root.menuOpen = false; root.act("variant") }
                else if (modelData.id === "folder") {
                  root.menuOpen = false
                  Quickshell.execDetached(["sh", "-c", "xdg-open \"$(omarchy theme dir \"$1\")\"", "sh", String(root.values.current)])
                }
                else if (modelData.id === "hide") { root.menuOpen = false; root.act("hide-current") }
                else if (modelData.id === "cleanup") { root.menuOpen = false; root.act("cleanup") }
                else if (modelData.id === "delete") {
                  if (!root.confirmDelete) root.confirmDelete = true
                  else { root.act("remove-current"); root.menuOpen = false; root.confirmDelete = false }
                }
              }
            }
          }
        }
      }
    }
  }
}
