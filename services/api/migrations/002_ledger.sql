CREATE TABLE IF NOT EXISTS public.ledger_heads (
  tenant_id uuid PRIMARY KEY,
  seq bigint NOT NULL CHECK (seq >= 0),
  hash text NOT NULL CHECK (hash ~ '^[0-9a-f]{64}$')
);
-- statement-break
CREATE TABLE IF NOT EXISTS public.ledger_events (
  tenant_id uuid NOT NULL,
  id uuid NOT NULL,
  seq bigint NOT NULL CHECK (seq >= 1),
  encounter_id uuid,
  version integer NOT NULL CHECK (version = 1),
  type text NOT NULL CHECK (type ~ '^[a-z][a-z0-9_.]{0,79}$'),
  payload jsonb NOT NULL CHECK (jsonb_typeof(payload) = 'object'),
  prev_hash text NOT NULL CHECK (prev_hash ~ '^[0-9a-f]{64}$'),
  hash text NOT NULL CHECK (hash ~ '^[0-9a-f]{64}$'),
  signature text NOT NULL CHECK (length(signature) BETWEEN 1 AND 8192),
  key_id text NOT NULL,
  created_at timestamptz NOT NULL,
  PRIMARY KEY (tenant_id, id),
  UNIQUE (tenant_id, seq),
  FOREIGN KEY (tenant_id, encounter_id) REFERENCES public.encounters (tenant_id, id)
);
-- statement-break
ALTER TABLE public.ledger_events ENABLE ROW LEVEL SECURITY;
-- statement-break
ALTER TABLE public.ledger_events FORCE ROW LEVEL SECURITY;
-- statement-break
ALTER TABLE public.ledger_heads ENABLE ROW LEVEL SECURITY;
-- statement-break
ALTER TABLE public.ledger_heads FORCE ROW LEVEL SECURITY;
-- statement-break
DROP POLICY IF EXISTS tenant_scope ON public.ledger_events;
-- statement-break
CREATE POLICY tenant_scope ON public.ledger_events
USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
-- statement-break
DROP POLICY IF EXISTS tenant_scope ON public.ledger_heads;
-- statement-break
CREATE POLICY tenant_scope ON public.ledger_heads
USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid)
WITH CHECK (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
-- statement-break
DO $$ BEGIN
 IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'verimed_ledger_append') THEN
   CREATE ROLE verimed_ledger_append NOLOGIN NOSUPERUSER NOBYPASSRLS;
 END IF;
END $$;
-- statement-break
GRANT verimed_ledger_append TO CURRENT_USER;
-- statement-break
GRANT USAGE ON SCHEMA public TO verimed_ledger_append;
-- statement-break
REVOKE ALL ON public.ledger_events, public.ledger_heads FROM PUBLIC;
-- statement-break
GRANT SELECT, INSERT ON public.ledger_events TO verimed_ledger_append;
-- statement-break
GRANT SELECT ON public.ledger_heads TO verimed_ledger_append;
-- statement-break
GRANT SELECT ON public.ledger_events, public.ledger_heads TO verimed_api;
-- statement-break
CREATE OR REPLACE FUNCTION public.ledger_advance_head() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public AS $$
DECLARE current_head public.ledger_heads%ROWTYPE;
BEGIN
 IF NEW.tenant_id IS DISTINCT FROM nullif(current_setting('app.tenant_id', true), '')::uuid THEN
   RAISE EXCEPTION 'Ledger tenant context mismatch' USING ERRCODE = '42501';
 END IF;
 PERFORM pg_advisory_xact_lock(hashtextextended(NEW.tenant_id::text, 44801754));
 INSERT INTO public.ledger_heads (tenant_id, seq, hash)
 VALUES (NEW.tenant_id, 0, repeat('0', 64)) ON CONFLICT (tenant_id) DO NOTHING;
 SELECT * INTO STRICT current_head FROM public.ledger_heads WHERE tenant_id = NEW.tenant_id FOR UPDATE;
 IF NEW.seq != current_head.seq + 1 OR NEW.prev_hash != current_head.hash THEN
   RAISE EXCEPTION 'Ledger head conflict' USING ERRCODE = '23514';
 END IF;
 UPDATE public.ledger_heads SET seq = NEW.seq, hash = NEW.hash WHERE tenant_id = NEW.tenant_id;
 RETURN NEW;
END $$;
-- statement-break
REVOKE ALL ON FUNCTION public.ledger_advance_head() FROM PUBLIC;
-- statement-break
DROP TRIGGER IF EXISTS ledger_advance_head ON public.ledger_events;
-- statement-break
CREATE TRIGGER ledger_advance_head BEFORE INSERT ON public.ledger_events
FOR EACH ROW EXECUTE FUNCTION public.ledger_advance_head();
-- statement-break
CREATE OR REPLACE FUNCTION public.ledger_reject_mutation() RETURNS trigger
LANGUAGE plpgsql SET search_path = pg_catalog AS $$
BEGIN
 RAISE EXCEPTION 'Ledger events are append-only' USING ERRCODE = '42501';
END $$;
-- statement-break
REVOKE ALL ON FUNCTION public.ledger_reject_mutation() FROM PUBLIC;
-- statement-break
DROP TRIGGER IF EXISTS ledger_reject_mutation ON public.ledger_events;
-- statement-break
CREATE TRIGGER ledger_reject_mutation BEFORE UPDATE OR DELETE OR TRUNCATE ON public.ledger_events
FOR EACH STATEMENT EXECUTE FUNCTION public.ledger_reject_mutation();
