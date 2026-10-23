-- Self-registration with owner approval, and password reset by email.
-- is_active stays the single "may sign in" switch; pending marks sign-ups the owner has not approved yet.
ALTER TABLE users ADD COLUMN email TEXT;
ALTER TABLE users ADD COLUMN is_admin INTEGER NOT NULL DEFAULT 0;
ALTER TABLE users ADD COLUMN pending INTEGER NOT NULL DEFAULT 0;

-- The first existing account becomes the owner; usernames that are email addresses become the reset address.
UPDATE users SET is_admin = 1 WHERE id = (SELECT MIN(id) FROM users);
UPDATE users SET email = lower(username) WHERE username LIKE '%_@_%._%';
CREATE UNIQUE INDEX idx_users_email ON users(lower(email)) WHERE email IS NOT NULL;

-- One-time password-reset links. Only a hash of the token is stored.
CREATE TABLE password_resets (
    id INTEGER PRIMARY KEY,
    token_hash TEXT NOT NULL UNIQUE,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX idx_password_resets_user ON password_resets(user_id);
