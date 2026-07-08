-- Align api_keys table with the SQLAlchemy APIKey model.
--
-- Earlier auth-table migration created api_keys.metadata, while the model uses
-- key_metadata to avoid SQLAlchemy's reserved metadata attribute name.
-- Existing databases therefore need this additive compatibility column.

ALTER TABLE api_keys
ADD COLUMN IF NOT EXISTS key_metadata JSONB DEFAULT '{}'::jsonb;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'api_keys'
          AND column_name = 'metadata'
    ) THEN
        UPDATE api_keys
        SET key_metadata = COALESCE(key_metadata, metadata, '{}'::jsonb)
        WHERE key_metadata IS NULL;
    END IF;
END $$;

COMMENT ON COLUMN api_keys.key_metadata IS 'API key metadata used by the SQLAlchemy APIKey model';
