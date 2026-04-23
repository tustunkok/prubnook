# Prubnook

A Django-based runbook automation platform for managing and executing operational procedures.

## Features

- **Runbook Management**: Create and organize multi-step operational runbooks
- **Step Types**: Support for manual, webhook, and shell execution steps
- **Execution Engine**: Run runbooks manually, via API, or on a schedule
- **Approval Workflows**: Require approvals for sensitive steps before execution
- **SSH Key Management**: Securely store and use SSH keys for remote shell execution
- **Scheduling**: Cron-based scheduling with APScheduler integration
- **Audit Logging**: Track all actions and executions for compliance
- **Role-Based Permissions**: Granular access control per runbook (view, edit, run, admin)
- **REST API**: Full API coverage via Django REST Framework
- **Notifications**: In-app notification system for approvals and execution updates

## Tech Stack

- Python 3.13+
- Django 5.2
- Django REST Framework
- APScheduler
- Jinja2 (templating)
- Paramiko (SSH)
- SQLite (default) / PostgreSQL (production)

## Quick Start

1. Install dependencies with [uv](https://docs.astral.sh/uv/):
   ```bash
   uv sync
   ```

2. Activate the virtual environment:
   ```bash
   source .venv/bin/activate  # Linux/macOS
   .venv\Scripts\activate     # Windows
   ```

3. Apply migrations:
   ```bash
   python manage.py migrate
   ```

4. Create a superuser:
   ```bash
   python manage.py createsuperuser
   ```

5. Run the development server:
   ```bash
   python manage.py runserver
   ```

6. (Optional) Start the scheduler for cron-based runbooks:
   ```bash
   python manage.py startscheduler
   ```

## Configuration

Key settings are managed via environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `SECRET_KEY` | Django secret key | *(dev fallback)* |
| `DEBUG` | Debug mode | `True` |
| `ALLOWED_HOSTS` | Comma-separated allowed hosts | `*` |
| `PLATFORM_ENCRYPTION_KEY` | Fernet key for SSH key encryption | *(empty)* |
| `SCHEDULER_ENABLED` | Enable APScheduler | `True` |
| `DATABASE_URL` | Database connection URL | `sqlite:///db.sqlite3` |

## Project Structure

```
prubnook/
├── core/              # Django project settings
├── runbook/           # Main application
│   ├── models.py      # Data models
│   ├── views.py       # Web & API views
│   ├── execution_engine.py
│   ├── crypto_utils.py
│   └── management/
│       └── commands/
│           └── startscheduler.py
├── templates/         # HTML templates
├── static/            # Static assets
├── manage.py
├── pyproject.toml
└── uv.lock
```

## License

MIT
