-- Sign-up no longer needs the owner's approval: accounts that were still waiting can sign in now.
UPDATE users SET pending = 0, is_active = 1, updated_at = datetime('now') WHERE pending = 1;
