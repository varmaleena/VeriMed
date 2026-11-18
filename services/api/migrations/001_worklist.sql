CREATE TABLE IF NOT EXISTS patients (
  tenant_id uuid NOT NULL,
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  fhir_patient_id text NOT NULL,
  display_token text NOT NULL,
  birth_year integer,
  sex text,
  source text NOT NULL,
  PRIMARY KEY (tenant_id, id),
  UNIQUE (tenant_id, fhir_patient_id)
);
CREATE TABLE IF NOT EXISTS encounters (
  tenant_id uuid NOT NULL,
  id uuid NOT NULL DEFAULT gen_random_uuid(),
  patient_id uuid NOT NULL,
  scribe_adapter text NOT NULL,
  status text NOT NULL CHECK (status IN ('INGESTING','READY_FOR_AUDIT','AUDITING','IN_REVIEW','SIGNED','FAILED')),
  assigned_user_id uuid,
  started_at timestamptz NOT NULL,
  source text NOT NULL,
  PRIMARY KEY (tenant_id, id),
  FOREIGN KEY (tenant_id, patient_id) REFERENCES patients (tenant_id, id)
);
CREATE INDEX IF NOT EXISTS encounters_worklist ON encounters (tenant_id, started_at DESC, id DESC);
ALTER TABLE patients ENABLE ROW LEVEL SECURITY;
ALTER TABLE patients FORCE ROW LEVEL SECURITY;
ALTER TABLE encounters ENABLE ROW LEVEL SECURITY;
ALTER TABLE encounters FORCE ROW LEVEL SECURITY;
DO $$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='verimed_api') THEN
    CREATE ROLE verimed_api NOLOGIN NOSUPERUSER NOBYPASSRLS;
  END IF;
END $$;
GRANT verimed_api TO CURRENT_USER;
DROP POLICY IF EXISTS tenant_scope ON patients;
CREATE POLICY tenant_scope ON patients USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
DROP POLICY IF EXISTS tenant_scope ON encounters;
CREATE POLICY tenant_scope ON encounters USING (tenant_id = nullif(current_setting('app.tenant_id', true), '')::uuid);
GRANT USAGE ON SCHEMA public TO verimed_api;
GRANT SELECT ON patients, encounters TO verimed_api;
