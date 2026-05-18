-- Minimal schema; adjust for production
CREATE TABLE IF NOT EXISTS hs_codes (
  id INTEGER PRIMARY KEY,
  code TEXT UNIQUE,
  title_ru TEXT,
  title_en TEXT,
  chapter TEXT,
  heading TEXT,
  subheading TEXT
);

CREATE TABLE IF NOT EXISTS notes (
  id INTEGER PRIMARY KEY,
  level TEXT,    -- 'section' | 'chapter'
  ref_id TEXT,   -- e.g. 'I' or '01'
  text TEXT
);
