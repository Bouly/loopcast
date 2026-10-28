-- La ferme d'iPhones
CREATE TABLE phones(
  udid TEXT PRIMARY KEY,
  phone_id TEXT,                 -- id de devices.yaml (phone-1…), NULL si inconnu
  name TEXT, model TEXT, ios TEXT, connection TEXT,
  status TEXT,                   -- ok | attention | offline | unknown
  problems TEXT,                 -- JSON : liste de codes (untrusted, devmode_off, battery_low…)
  battery INTEGER, charging INTEGER,
  session_id TEXT,               -- session Appium en cours
  first_seen TEXT, last_seen TEXT, updated_at TEXT);
ALTER TABLE events ADD COLUMN phone_udid TEXT;
CREATE INDEX events_phone ON events(phone_udid, id);
