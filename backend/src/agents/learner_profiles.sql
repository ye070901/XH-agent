CREATE TABLE IF NOT EXISTS learner_profiles(
    learner_id TEXT PRIMARY KEY,
    knowledge_map TEXT DEFAULT '{}',
    skill_gaps TEXT DEFAULT '{}',
    updated_at TIMESTAMP
);
