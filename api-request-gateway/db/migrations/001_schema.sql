CREATE EXTENSION IF NOT EXISTS "pgcrypto";

CREATE TABLE IF NOT EXISTS platforms (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL,
    api_key VARCHAR(255) NOT NULL UNIQUE,
    webhook_url VARCHAR(2048),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS students (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    external_id VARCHAR(255) NOT NULL,
    platform VARCHAR(255) NOT NULL,
    platform_id UUID REFERENCES platforms(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_student_external_platform UNIQUE (external_id, platform_id)
);

CREATE INDEX IF NOT EXISTS idx_students_external ON students (external_id);

CREATE TABLE IF NOT EXISTS analyses (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id UUID NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    task_description TEXT NOT NULL,
    code TEXT NOT NULL,
    score INT,
    weak_spots JSONB,
    tags TEXT[],
    recommendations JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_analyses_student ON analyses (student_id);

CREATE TABLE IF NOT EXISTS generated_tasks (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    student_id UUID NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    analysis_id UUID REFERENCES analyses(id) ON DELETE SET NULL,
    tags TEXT[],
    difficulty VARCHAR(32) NOT NULL,
    task_json JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_generated_student ON generated_tasks (student_id);

INSERT INTO platforms (id, name, api_key, webhook_url)
VALUES (
    'a0000000-0000-4000-8000-000000000001',
    'local-dev',
    '6e1e4e1b8f8b36d08901cdb51b97841dfe20f5efd2fd2fd00768971408c46274',
    NULL
) ON CONFLICT (api_key) DO NOTHING;
