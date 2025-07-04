# Maintaineh

## Database migrations

Some schema updates are handled through small scripts in the `scripts/` directory. After deploying a new version that introduces machine maintenance intervals, run:

```bash
python scripts/add_machine_maintenance_columns.py
```

The script connects to the database specified by the `DATABASE_URL` environment variable and adds the necessary columns if they do not already exist.
