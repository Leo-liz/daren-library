PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS import_batches (
    batch_id TEXT PRIMARY KEY,
    source_type TEXT NOT NULL CHECK (source_type IN ('creator', 'video', 'live')),
    source_name TEXT NOT NULL,
    platform TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    period_start TEXT,
    period_end TEXT,
    period_source TEXT NOT NULL DEFAULT 'import_time',
    total_rows INTEGER NOT NULL DEFAULT 0,
    accepted_rows INTEGER NOT NULL DEFAULT 0,
    rejected_rows INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS creators (
    platform TEXT NOT NULL,
    creator_key TEXT NOT NULL,
    creator_username TEXT,
    creator_id TEXT,
    creator_name TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (platform, creator_key)
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_creators_platform_id
    ON creators(platform, creator_id) WHERE creator_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS raw_creator (
    platform TEXT NOT NULL,
    source_record_key TEXT NOT NULL,
    creator_key TEXT NOT NULL,
    creator_username TEXT,
    creator_id TEXT,
    creator_name TEXT,
    alliance_gmv_vnd INTEGER,
    alliance_items INTEGER,
    estimated_commission_vnd INTEGER,
    targeted_gmv_vnd INTEGER,
    public_gmv_vnd INTEGER,
    refunded_gmv_vnd INTEGER,
    affiliate_followers INTEGER,
    click_rate REAL,
    source_row_number INTEGER NOT NULL,
    import_batch_id TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    PRIMARY KEY (platform, source_record_key),
    FOREIGN KEY (platform, creator_key) REFERENCES creators(platform, creator_key),
    FOREIGN KEY (import_batch_id) REFERENCES import_batches(batch_id)
);

CREATE TABLE IF NOT EXISTS raw_video (
    platform TEXT NOT NULL,
    source_record_key TEXT NOT NULL,
    creator_key TEXT NOT NULL,
    creator_username TEXT,
    creator_id TEXT,
    creator_name TEXT,
    video_id TEXT NOT NULL,
    published_at TEXT,
    product_name TEXT,
    attributed_gmv_vnd INTEGER,
    attributed_items INTEGER,
    indirect_gmv_vnd INTEGER,
    views INTEGER,
    interactions INTEGER,
    likes INTEGER,
    comments INTEGER,
    shares INTEGER,
    new_followers INTEGER,
    favorites INTEGER,
    completion_rate REAL,
    ctor REAL,
    source_row_number INTEGER NOT NULL,
    import_batch_id TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    PRIMARY KEY (platform, source_record_key),
    FOREIGN KEY (platform, creator_key) REFERENCES creators(platform, creator_key),
    FOREIGN KEY (import_batch_id) REFERENCES import_batches(batch_id)
);

CREATE INDEX IF NOT EXISTS idx_raw_video_creator
    ON raw_video(platform, creator_key);

CREATE INDEX IF NOT EXISTS idx_raw_video_batch_creator
    ON raw_video(platform, import_batch_id, creator_key);

CREATE TABLE IF NOT EXISTS raw_live (
    platform TEXT NOT NULL,
    source_record_key TEXT NOT NULL,
    creator_key TEXT NOT NULL,
    creator_username TEXT,
    creator_id TEXT,
    creator_name TEXT,
    live_id TEXT NOT NULL,
    started_at TEXT,
    event_at_utc7 TEXT,
    attributed_gmv_vnd INTEGER,
    indirect_gmv_vnd INTEGER,
    attributed_orders INTEGER,
    attributed_items INTEGER,
    viewers INTEGER,
    view_count INTEGER,
    comments INTEGER,
    shares INTEGER,
    likes INTEGER,
    favorites INTEGER,
    conversion_rate REAL,
    source_row_number INTEGER NOT NULL,
    import_batch_id TEXT NOT NULL,
    raw_json TEXT NOT NULL,
    PRIMARY KEY (platform, source_record_key),
    FOREIGN KEY (platform, creator_key) REFERENCES creators(platform, creator_key),
    FOREIGN KEY (import_batch_id) REFERENCES import_batches(batch_id)
);

CREATE INDEX IF NOT EXISTS idx_raw_live_creator
    ON raw_live(platform, creator_key);

CREATE INDEX IF NOT EXISTS idx_raw_live_batch_creator
    ON raw_live(platform, import_batch_id, creator_key);

CREATE TABLE IF NOT EXISTS costs (
    platform TEXT NOT NULL,
    creator_key TEXT NOT NULL,
    target_type TEXT NOT NULL DEFAULT 'creator' CHECK (target_type IN ('creator', 'video', 'live')),
    target_id TEXT NOT NULL DEFAULT '',
    quote_vnd INTEGER,
    collaboration_cost_vnd INTEGER,
    slot_fee_vnd INTEGER,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (platform, creator_key, target_type, target_id),
    FOREIGN KEY (platform, creator_key) REFERENCES creators(platform, creator_key)
);

CREATE TABLE IF NOT EXISTS raw_creator_periods (
    platform TEXT NOT NULL,
    creator_key TEXT NOT NULL,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    period_source TEXT NOT NULL,
    alliance_gmv_vnd INTEGER,
    alliance_items INTEGER,
    estimated_commission_vnd INTEGER,
    targeted_gmv_vnd INTEGER,
    import_batch_id TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (platform, creator_key, period_start, period_end),
    FOREIGN KEY (platform, creator_key) REFERENCES creators(platform, creator_key),
    FOREIGN KEY (import_batch_id) REFERENCES import_batches(batch_id)
);

CREATE TABLE IF NOT EXISTS bd_followups (
    followup_id INTEGER PRIMARY KEY AUTOINCREMENT,
    platform TEXT NOT NULL,
    creator_key TEXT NOT NULL,
    followed_at TEXT NOT NULL,
    bd_name TEXT NOT NULL,
    content TEXT NOT NULL,
    next_step TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (platform, creator_key) REFERENCES creators(platform, creator_key)
);

CREATE TABLE IF NOT EXISTS commissions (
    platform TEXT NOT NULL,
    creator_key TEXT NOT NULL,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL,
    organic_commission_vnd INTEGER,
    paid_commission_vnd INTEGER,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (platform, creator_key, period_start, period_end),
    FOREIGN KEY (platform, creator_key) REFERENCES creators(platform, creator_key)
);

CREATE TABLE IF NOT EXISTS tags (
    tag_id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    is_preset INTEGER NOT NULL DEFAULT 0 CHECK (is_preset IN (0, 1)),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS creator_tags (
    platform TEXT NOT NULL,
    creator_key TEXT NOT NULL,
    tag_id INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (platform, creator_key, tag_id),
    FOREIGN KEY (platform, creator_key) REFERENCES creators(platform, creator_key),
    FOREIGN KEY (tag_id) REFERENCES tags(tag_id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS creator_annotations (
    platform TEXT NOT NULL,
    creator_key TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (platform, creator_key),
    FOREIGN KEY (platform, creator_key) REFERENCES creators(platform, creator_key)
);

CREATE TABLE IF NOT EXISTS config_change_log (
    change_id INTEGER PRIMARY KEY AUTOINCREMENT,
    changed_at TEXT NOT NULL,
    config_key TEXT NOT NULL,
    old_value TEXT NOT NULL,
    new_value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS metrics (
    platform TEXT NOT NULL,
    creator_key TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    metric_value REAL,
    source_table TEXT NOT NULL,
    source_field TEXT NOT NULL,
    source_batches TEXT NOT NULL,
    computed_at TEXT NOT NULL,
    PRIMARY KEY (platform, creator_key, metric_name),
    FOREIGN KEY (platform, creator_key) REFERENCES creators(platform, creator_key)
);

CREATE TABLE IF NOT EXISTS ratings (
    platform TEXT NOT NULL,
    creator_key TEXT NOT NULL,
    grade TEXT NOT NULL CHECK (grade IN ('S', 'A', 'B', 'C', 'D')),
    score REAL NOT NULL,
    evidence_json TEXT NOT NULL,
    rules_hash TEXT NOT NULL,
    computed_at TEXT NOT NULL,
    PRIMARY KEY (platform, creator_key),
    FOREIGN KEY (platform, creator_key) REFERENCES creators(platform, creator_key)
);

CREATE INDEX IF NOT EXISTS idx_ratings_platform_grade
    ON ratings(platform, grade);

CREATE TABLE IF NOT EXISTS recompute_queue (
    platform TEXT NOT NULL,
    creator_key TEXT NOT NULL,
    reason TEXT NOT NULL CHECK (reason IN ('import', 'cost')),
    queued_at TEXT NOT NULL,
    PRIMARY KEY (platform, creator_key, reason),
    FOREIGN KEY (platform, creator_key) REFERENCES creators(platform, creator_key)
);

CREATE INDEX IF NOT EXISTS idx_recompute_queue_platform
    ON recompute_queue(platform, queued_at, creator_key);
