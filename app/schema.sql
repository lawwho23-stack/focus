CREATE TABLE IF NOT EXISTS idea (
    id                      INTEGER PRIMARY KEY,
    text                    TEXT NOT NULL,
    created_at               TEXT NOT NULL,
    unfreeze_at             TEXT NOT NULL,
    promoted_commitment_id  INTEGER REFERENCES commitment(id),
    dropped_at              TEXT
);


CREATE TABLE IF NOT EXISTS commitment (
    id                      INTEGER PRIMARY KEY,
    title                   TEXT NOT NULL,
    done_when               TEXT NOT NULL,
    lane                    TEXT NOT NULL
                                        CHECK(lane IN ('learning', 'income', 'client')),
    status                  TEXT NOT NULL DEFAULT 'active'
                                        CHECK (status IN ('active', 'done', 'killed')),
    active_slot             INTEGER
                                        CHECK (active_slot IS NULL OR active_slot BETWEEN 1 AND 3),
    kill_reason             TEXT,
    created_at              TEXT NOT NULL,
    finished_at             TEXT,
    last_touched_at         TEXT,

    CHECK (status <> 'killed' OR kill_reason IS NOT NULL),
    CHECK (status <> 'active' OR active_slot IS NOT NULL)

);

CREATE UNIQUE INDEX IF NOT EXISTS one_commitment_per_slot
    ON commitment(active_slot) WHERE status = 'active';


CREATE TABLE IF NOT EXISTS day (
    date                        TEXT PRIMARY KEY,
    primary_commitment_id       INTEGER REFERENCES commitment(id),
    primary_moved               INTEGER,
    energy                      INTEGER 
                                        CHECK (energy IS NULL OR energy BETWEEN 1 AND 5),
    note                        TEXT,
    closed_at                   TEXT
);