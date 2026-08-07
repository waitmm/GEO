WENXIN_PLATFORM = "wenxin"
WENXIN_WEB_ADAPTER = "wenxin_web_audit"
WENXIN_WEB_PLATFORM = WENXIN_WEB_ADAPTER
BROWSER_AUDIT_ENTRY_TYPE = "browser_audit"

TASK_STATUSES = {
    "pending",
    "queued",
    "running",
    "completed",
    "partial_completed",
    "failed",
    "cancelled",
}

RUN_STAGES = {
    "queued",
    "launching_browser",
    "checking_login",
    "opening_platform",
    "submitting_query",
    "waiting_answer",
    "locating_answer",
    "extracting_answer",
    "opening_references",
    "loading_references",
    "parsing_references",
    "saving_evidence",
    "analyzing",
    "success",
    "partial_success",
    "failed",
}

RETRYABLE_ERRORS = {
    "browser_crashed",
    "browser_profile_locked",
    "answer_timeout",
    "reference_panel_not_opened",
    "network_error",
    "temporary_parse_failure",
}

NON_RETRYABLE_ERRORS = {
    "login_required",
    "captcha_required",
    "configuration_error",
}
