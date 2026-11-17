// Toolbar button: open or close the sidebar. The click counts as the user
// action that sidebarAction.toggle() needs.
browser.action.onClicked.addListener(() => browser.sidebarAction.toggle());
