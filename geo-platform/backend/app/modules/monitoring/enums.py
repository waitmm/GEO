WENXIN_PLATFORM = "wenxin"
WENXIN_WEB_ADAPTER = "wenxin_web_audit"
WENXIN_WEB_PLATFORM = WENXIN_WEB_ADAPTER
BROWSER_AUDIT_ENTRY_TYPE = "browser_audit"

# Display-only provenance.  This is deliberately not a production collector
# admission registry: yuanbao remains unavailable to get_collector().
PLATFORM_DISPLAY_NAMES = {
    WENXIN_PLATFORM: "文心助手",
    "yuanbao": "腾讯元宝",
}


def platform_display_name(platform: str) -> str:
    value = str(platform or "").strip()
    return PLATFORM_DISPLAY_NAMES.get(value, value or "未知平台")

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
    "rate_limited",
    "configuration_error",
}
