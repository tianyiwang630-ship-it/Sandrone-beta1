export const SHELL_RESIZER_WIDTH = 8
export const MIN_CHAT_WIDTH = 520
export const MIN_CHAT_WIDTH_WITH_DRAWER = 180
export const MIN_DRAWER_WIDTH = 520

export function fitDrawerWidth(drawerWidth: number, viewportWidth: number, sidebarWidth: number) {
  const maxWidth = Math.max(
    MIN_DRAWER_WIDTH,
    viewportWidth - sidebarWidth - MIN_CHAT_WIDTH_WITH_DRAWER - SHELL_RESIZER_WIDTH,
  )
  return Math.min(Math.max(drawerWidth, MIN_DRAWER_WIDTH), maxWidth)
}
