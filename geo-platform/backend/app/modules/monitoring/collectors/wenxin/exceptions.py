class WenxinCollectorError(Exception):
    error_type = "unknown_error"


class LoginRequiredError(WenxinCollectorError):
    error_type = "login_required"


class CaptchaRequiredError(WenxinCollectorError):
    error_type = "captcha_required"


class AnswerTimeoutError(WenxinCollectorError):
    error_type = "answer_timeout"


class ConfigurationError(WenxinCollectorError):
    error_type = "configuration_error"


class PageStructureError(WenxinCollectorError):
    error_type = "page_structure_not_matched"


class BrowserCrashedError(WenxinCollectorError):
    error_type = "browser_crashed"
