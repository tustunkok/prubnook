# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added

- **Syntax highlighting**: Added CodeMirror and Highlight.js styling to command, webhook configuration, and SSH key textareas for better readability.
- **Execution safeguards**: Disabled runbooks can no longer be executed manually via the web UI, API, or scheduler. Attempts now return a clear error and are properly logged.
- **Tests**: Added focused tests verifying that disabled runbooks are blocked while active runbooks continue to work across all three entry points.

### Fixed

- **Scheduler hot-reload**: The scheduler now detects cron expression changes and newly created or deactivated scheduled jobs dynamically, without requiring a full restart.
- **Alert visibility**: Fixed Django message alerts (`error`, `warning`, `success`, `info`) rendering with nearly invisible backgrounds. Alerts now use high-contrast colors with bold text and left accent borders so they are impossible to miss.

## [0.1.0] — 2026-04-23

### Added

- Initial release: Prubnook runbook automation platform.
- Core models: Runbook, Step, RunbookExecution, StepExecution, ApprovalRequest, ScheduledJob, AuditLog, Notification, RunbookPermission.
- Web UI for creating, editing, viewing, and running runbooks.
- Role-based permissions with ownership, direct user grants, and group grants.
- Scheduler based on APScheduler with cron expressions and dynamic job syncing.
- REST API built with Django REST Framework for programmatic access.
- Execution engine supporting manual, webhook, and shell step types with approval gates.

---

[Unreleased]: https://github.com/tustunkok/prubnook/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/tustunkok/prubnook/releases/tag/v0.1.0
