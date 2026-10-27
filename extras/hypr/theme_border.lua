-- Theme Studio: per-theme window border colour, picked in the panel.
-- Choices live in ~/.local/state/omarchy-theme-rotation/borders.lua. Themes
-- without a choice use the "*" default, or keep their own border if unset.
-- omarchy theme set writes theme.name before it reloads Hyprland, so a switch
-- picks up the override in that reload.
local home = os.getenv("HOME")
local ok, borders = pcall(dofile, home .. "/.local/state/omarchy-theme-rotation/borders.lua")
if not ok or type(borders) ~= "table" then return end

local file = io.open(home .. "/.local/state/omarchy/current/theme.name")
if not file then return end
local theme = (file:read("l") or ""):match("^%s*(.-)%s*$")
file:close()

-- A theme's own entry wins (false = keep the theme's border); otherwise "*".
local color = borders[theme]
if color == nil then color = borders["*"] end
if color then
  hl.config({
    general = { col = { active_border = color } },
    group = { col = { border_active = color } },
  })
end
