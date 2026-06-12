CREATE TABLE IF NOT EXISTS users (
    id UUID PRIMARY KEY,
    platform_id UUID NOT NULL REFERENCES platforms(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_users_id_platform UNIQUE (id, platform_id)
);

CREATE INDEX IF NOT EXISTS idx_users_platform ON users (platform_id);
