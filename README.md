# Novakid Social Reports

Streamlit application for calculating Instagram followers from Meta Business Suite and Novakid PR CSV exports.

## Features

- Team login with role-based access control.
- Meta Business Suite CSV upload.
- Novakid PR CSV upload with automatic account matching.
- Final follower report with CSV and Excel export.
- Manual PR follower overrides for authorized users.
- Upload history for auditing.
- Automatic and manual SQLite database backups.

## Environment Variables

Create environment variables in your local shell or Railway project. Do not commit real secrets.

| Variable | Required | Description |
| --- | --- | --- |
| `FOLLOWERS_ADMIN_USERNAME` | First setup only | Username for the first admin user when the database has no users. |
| `FOLLOWERS_ADMIN_PASSWORD` | First setup only | Password for the first admin user. Must be at least 8 characters. |
| `FOLLOWERS_DB_PATH` | No | SQLite database path. Default: `data/followers_team.db`. |
| `FOLLOWERS_UPLOAD_DIR` | No | Uploaded CSV storage directory. Default: `data/uploads`. |
| `FOLLOWERS_BACKUP_DIR` | No | Backup storage directory. Default: `backups`. Use `/backups` when your host provides that mounted directory. |
| `FOLLOWERS_BACKUP_RETENTION` | No | Number of database backups to keep. Default: `8`. |
| `FOLLOWERS_BACKUP_INTERVAL_DAYS` | No | Automatic backup interval. Default: `7`. |

## Local Development

```bash
pip install -r requirements.txt
export FOLLOWERS_ADMIN_USERNAME="your-admin-user"
export FOLLOWERS_ADMIN_PASSWORD="change-this-password"
streamlit run app.py
```

On first startup, the app creates the first admin only from the environment variables above. Credentials are never displayed on the login screen.

## Roles And Permissions

| Role | Permissions |
| --- | --- |
| Admin | Access all features, create/edit/delete users, assign roles, manage backups. |
| Manager | Access business functionality: upload files, edit manual PR values, view/export reports and upload history. |
| Viewer | Read-only access to dashboard, reports, exports, and upload history. |

Existing databases are migrated automatically. Previous `admin` users remain admins, and previous non-admin users become managers.

## Backups

The app creates a SQLite snapshot automatically once per week using SQLite's backup API. This produces a consistent copy without stopping normal application usage.

Admins can also open the `Backups` page to:

- create a manual backup;
- download a backup file;
- view backup creation times and sizes.

Only the newest 8 backups are kept by default. Older backup files are deleted automatically after a new backup is created.

## Railway Deployment

1. Create a Railway service from this repository.
2. Add the required first-setup variables:
   - `FOLLOWERS_ADMIN_USERNAME`
   - `FOLLOWERS_ADMIN_PASSWORD`
3. Optional: add persistent volume paths and configure:
   - `FOLLOWERS_DB_PATH=/data/followers_team.db`
   - `FOLLOWERS_UPLOAD_DIR=/data/uploads`
   - `FOLLOWERS_BACKUP_DIR=/backups`
4. Use this start command:

```bash
streamlit run app.py --server.port $PORT --server.address 0.0.0.0
```

5. After the first admin user exists, rotate or remove first-setup environment variables according to your team's secret management policy.

## Security Notes

- No default credentials are hardcoded in the application.
- No credentials are shown in the UI.
- Passwords are stored as PBKDF2-SHA256 hashes with per-password salts.
- Secrets must be provided through environment variables.
- SQLite databases, backups, uploads, local env files, caches, and temporary files are ignored by Git.

