-- Ballymena Then & Now — photo spot overlay
-- Triggers a fullscreen "then/now" panel when the player enters a photo_* waypoint.
--
-- GuiHook fired: 'BallymenaPhotoSpot'
--   { active=true,  id, description, location, year_then, year_now,
--     credit_then, credit_now, tex_path }
--   { active=false }
--
-- Dismiss: press F (or the key bound to 'hornToggle') while the overlay is open.
-- Requires UI component BallymenaPhotoSpot.vue to be registered in the mod's
-- ui/modules/ directory.

local M = {}

local photoData   = {}
local overlayOpen = false


local function loadManifest()
  local path    = '/levels/ballymena/data/photo_manifest.json'
  local content = readFile(path)
  if not content then
    log('W', 'photo_spots', 'Could not load photo_manifest.json')
    return
  end
  local ok, data = pcall(jsonDecode, content)
  if not ok or type(data) ~= 'table' then
    log('W', 'photo_spots', 'photo_manifest.json parse error')
    return
  end
  for _, p in ipairs(data.photos or {}) do
    if p.id then
      photoData[p.id] = p
    end
  end
  log('I', 'photo_spots', string.format('Loaded %d photo entries', tableSize(photoData)))
end


local function openOverlay(photo)
  overlayOpen = true
  guihooks.trigger('BallymenaPhotoSpot', {
    active      = true,
    id          = photo.id          or '',
    description = photo.description or '',
    location    = photo.location_name or '',
    year_then   = photo.year_then,
    year_now    = photo.year_now,
    credit_then = photo.credit_then or '',
    credit_now  = photo.credit_now  or '',
    source_url  = photo.source_url  or '',
    tex_path    = '/levels/ballymena/art/textures/photo_spots/' .. (photo.id or '') .. '.png',
  })
end


local function closeOverlay()
  if overlayOpen then
    overlayOpen = false
    guihooks.trigger('BallymenaPhotoSpot', { active = false })
  end
end


-- Called by BeamNG when a vehicle enters a waypoint radius
local function onWaypointReached(waypointName, vehicleId)
  local id = waypointName:match('^photo_(.+)$')
  if not id then return end
  local photo = photoData[id]
  if photo then
    openOverlay(photo)
  else
    log('W', 'photo_spots',
        string.format('No manifest entry for waypoint "%s"', waypointName))
  end
end


-- Called by BeamNG when a vehicle leaves a waypoint radius
local function onWaypointLeft(waypointName, vehicleId)
  if waypointName:match('^photo_') then
    closeOverlay()
  end
end


-- Called by the UI when the player explicitly dismisses the overlay
local function onBallymenaPhotoSpotDismiss()
  closeOverlay()
end


M.onInit                      = loadManifest
M.onWaypointReached           = onWaypointReached
M.onWaypointLeft              = onWaypointLeft
M.onBallymenaPhotoSpotDismiss = onBallymenaPhotoSpotDismiss

return M
