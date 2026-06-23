# Security, RBAC, and Backup Improvements

## Summary

- Added role-based access control with Admin, Manager, and Viewer roles.
- Added automatic weekly SQLite backups with retention of the newest 8 backup files.
- Added admin-only manual backup creation and backup download controls.
- Removed hardcoded default admin credentials from code, README, and login UI.
- Added first-admin setup through environment variables only.
- Added `.env.example` with placeholders and `.gitignore` rules for secrets, databases, backups, uploads, caches, and temporary files.
- Updated README with environment variables, RBAC, backups, and Railway deployment instructions.

## Security Findings

- Hardcoded default admin credentials were present in `app.py` and `README.md`.
- The login page displayed demo/default credentials.
- The old role model only supported `admin` and `user`, with limited backend permission checks.
- Local SQLite database and uploaded CSV files exist under `data/`; `.gitignore` now excludes these paths from future commits.
- No API keys, private keys, email addresses, or token-like secrets were found in source, docs, or config after cleanup.

## Migration Instructions

1. Set first-admin environment variables before first deployment if the database has no users:
   - `FOLLOWERS_ADMIN_USERNAME`
   - `FOLLOWERS_ADMIN_PASSWORD`
2. Deploy normally. The app runs migrations during startup.
3. Existing `admin` users remain admins.
4. Existing non-admin `user` accounts become managers.
5. Optional: configure persistent storage paths:
   - `FOLLOWERS_DB_PATH`
   - `FOLLOWERS_UPLOAD_DIR`
   - `FOLLOWERS_BACKUP_DIR`
6. Verify the admin can access the `Users` and `Backups` pages.

## Rollback Instructions

1. Before rollback, download or copy the latest backup from the `Backups` page or configured backup directory.
2. Revert the application code to the previous version.
3. Restore the previous SQLite database file if the older application cannot read the migrated `users` role constraint.
4. Restart the Streamlit service.

## Verification

- `python3 -m py_compile app.py`
- Temp-database smoke test for first-admin creation and backup creation.
- Temp-database migration test from legacy `admin/user` roles to `admin/manager/viewer`.
- Secret scan over source, README, `.env.example`, `.gitignore`, and requirements.
