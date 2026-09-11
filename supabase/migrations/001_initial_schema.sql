-- Enable UUID generation
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- PROFILES: one row per authenticated user
CREATE TABLE IF NOT EXISTS profiles (
  id           UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
  email        TEXT NOT NULL,
  full_name    TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Automatically create profile on signup
CREATE OR REPLACE FUNCTION public.handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
  INSERT INTO public.profiles (id, email)
  VALUES (NEW.id, NEW.email)
  ON CONFLICT (id) DO NOTHING;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION public.handle_new_user();

-- MONITORED_SITES: URLs being tracked
CREATE TABLE IF NOT EXISTS monitored_sites (
  id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id           UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  name              TEXT NOT NULL,
  url               TEXT NOT NULL,
  check_interval_s  INTEGER NOT NULL DEFAULT 300 CHECK (check_interval_s IN (300, 900, 3600)),
  is_active         BOOLEAN NOT NULL DEFAULT TRUE,
  last_status       TEXT,            -- 'up' | 'down' | 'unknown'
  last_checked_at   TIMESTAMPTZ,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- MONITOR_CHECKS: individual probe results
CREATE TABLE IF NOT EXISTS monitor_checks (
  id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  site_id         UUID NOT NULL REFERENCES monitored_sites(id) ON DELETE CASCADE,
  checked_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  is_up           BOOLEAN NOT NULL,
  status_code     INTEGER,           -- e.g. 200, 500, NULL if timeout
  response_ms     INTEGER,           -- round-trip in milliseconds
  error_message   TEXT,              -- e.g. "ECONNREFUSED", "timeout"
  page_url        TEXT,
  screenshot_path TEXT,
  evidence        JSONB NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS idx_checks_site_time ON monitor_checks(site_id, checked_at DESC);

ALTER TABLE monitor_checks ADD COLUMN IF NOT EXISTS page_url TEXT;
ALTER TABLE monitor_checks ADD COLUMN IF NOT EXISTS screenshot_path TEXT;
ALTER TABLE monitor_checks ADD COLUMN IF NOT EXISTS evidence JSONB NOT NULL DEFAULT '{}'::jsonb;

-- INCIDENTS: tracks a contiguous downtime window
CREATE TABLE IF NOT EXISTS incidents (
  id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  site_id       UUID NOT NULL REFERENCES monitored_sites(id) ON DELETE CASCADE,
  started_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  resolved_at   TIMESTAMPTZ,         -- NULL = still active
  title         TEXT,
  severity      TEXT NOT NULL DEFAULT 'medium' CHECK (severity IN ('info', 'low', 'medium', 'high', 'critical')),
  root_cause    TEXT,
  page_url      TEXT,
  screenshot_path TEXT,
  evidence      JSONB NOT NULL DEFAULT '{}'::jsonb,
  diagnosis     JSONB NOT NULL DEFAULT '{}'::jsonb,
  reproduction_steps JSONB NOT NULL DEFAULT '[]'::jsonb,
  fix_suggestion TEXT,
  verified_at   TIMESTAMPTZ,
  verification_note TEXT,
  resolution_note TEXT
);
CREATE INDEX IF NOT EXISTS idx_incidents_site ON incidents(site_id, started_at DESC);

ALTER TABLE incidents ADD COLUMN IF NOT EXISTS title TEXT;
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS severity TEXT NOT NULL DEFAULT 'medium';
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS page_url TEXT;
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS screenshot_path TEXT;
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS evidence JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS diagnosis JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS reproduction_steps JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS fix_suggestion TEXT;
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS verified_at TIMESTAMPTZ;
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS verification_note TEXT;
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS resolution_note TEXT;

-- ALERT_CHANNELS: how to notify users
CREATE TABLE IF NOT EXISTS alert_channels (
  id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id       UUID NOT NULL REFERENCES profiles(id) ON DELETE CASCADE,
  site_id       UUID REFERENCES monitored_sites(id) ON DELETE CASCADE, -- NULL = all sites
  channel_type  TEXT NOT NULL CHECK (channel_type IN ('email', 'webhook')),
  config        JSONB NOT NULL,      -- { "email": "user@example.com" } or { "url": "https://..." }
  is_active     BOOLEAN NOT NULL DEFAULT TRUE,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ROW LEVEL SECURITY: users can only see their own data
ALTER TABLE profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE monitored_sites ENABLE ROW LEVEL SECURITY;
ALTER TABLE monitor_checks ENABLE ROW LEVEL SECURITY;
ALTER TABLE incidents ENABLE ROW LEVEL SECURITY;
ALTER TABLE alert_channels ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'profiles' AND policyname = 'Users own profiles') THEN
    CREATE POLICY "Users own profiles" ON profiles USING (id = auth.uid());
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'monitored_sites' AND policyname = 'Users own sites') THEN
    CREATE POLICY "Users own sites" ON monitored_sites USING (user_id = auth.uid());
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'monitor_checks' AND policyname = 'Users see checks for their sites') THEN
    CREATE POLICY "Users see checks for their sites" ON monitor_checks USING (site_id IN (SELECT id FROM monitored_sites WHERE user_id = auth.uid()));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'incidents' AND policyname = 'Users see incidents for their sites') THEN
    CREATE POLICY "Users see incidents for their sites" ON incidents USING (site_id IN (SELECT id FROM monitored_sites WHERE user_id = auth.uid()));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_policies WHERE tablename = 'alert_channels' AND policyname = 'Users own alert channels') THEN
    CREATE POLICY "Users own alert channels" ON alert_channels USING (user_id = auth.uid());
  END IF;
END $$;

-- REALTIME: enable live status updates on dashboard
ALTER PUBLICATION supabase_realtime ADD TABLE monitored_sites;
ALTER PUBLICATION supabase_realtime ADD TABLE incidents;

INSERT INTO storage.buckets (id, name, public)
VALUES ('incident-screenshots', 'incident-screenshots', true)
ON CONFLICT (id) DO NOTHING;
