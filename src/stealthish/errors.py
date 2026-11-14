"""Stable errors. Never include driver messages or request contents."""

MESSAGES = {
    "INVALID_CONFIG": "The configuration is invalid.",
    "INVALID_REQUEST": "The request is invalid.",
    "PROFILE_BUSY": "Another process owns this data directory.",
    "PROFILE_DOWNGRADE_BLOCKED": "This profile used a newer browser. A matching recovery decision is required.",
    "SESSION_BUSY": "A browser operation is already active.",
    "SESSION_CLOSED": "The session is closed.",
    "RELEASE_INVALID": "The selected release failed verification.",
    "MAINTENANCE_REQUIRED": "Maintenance is incomplete. Recover before browsing.",
    "ACQUISITION_FAILED": "The selected download or archive failed verification.",
    "RELEASE_EXISTS": "This release directory already exists. Choose a new release ID.",
    "BACKUP_FAILED": "The profile backup failed verification. No recovery is approved.",
    "NO_RECOVERY": "No unused recovery pair is available.",
    "RECOVERY_CONFIRMATION_REQUIRED": "Recovery requires explicit acceptance of the backup's point in time.",
    "UNSUPPORTED_PLATFORM": "This release is not validated for this platform.",
    "INCOMPATIBLE_DRIVER": "The driver does not match the reviewed adaptation.",
    "BLOCKER_SETUP_REQUIRED": "Explicit blocker setup is required before browsing.",
    "BLOCKER_UNAVAILABLE": "The selected blocker failed validation.",
    "BROWSER_ERROR": "The browser operation failed. Request contents are omitted.",
    "TIMEOUT": "The operation exceeded its deadline. It was not retried.",
    "STALE_REFERENCE": "The reference is no longer valid. Request a new snapshot.",
    "TAB_NOT_FOUND": "The requested tab is not available.",
    "TAB_LIMIT": "The session tab limit was reached.",
    "UNSUPPORTED": "This operation is not supported in this build.",
    "CONTENT_LIMIT": "The document exceeds the supported extraction limit. No partial article was returned.",
    "CHALLENGE_REQUIRED": "Site verification is incomplete. The site is paused. No retry was made.",
    "AUTH_REQUIRED": "The site requires authentication. No further input was sent.",
    "CONSENT_REQUIRED": "The site requires user consent. No consent was submitted.",
    "MANUAL_ACCESS": "The browser is held for manual use. Return control with headless mode before automation.",
}


class StealthishError(Exception):
    def __init__(self, code: str, *, message: str | None = None, data: dict | None = None):
        self.code = code
        self.data = data or {}
        super().__init__(message or MESSAGES.get(code, "The operation failed."))


class StartupError(StealthishError):
    """A session could not start. The caller must not submit browsing requests."""
