INPUT_CANDIDATES = [
    "#chat-textarea",
    ".ci-textarea",
    "textarea.ci-textarea",
    "textarea",
    '[contenteditable="true"][role="textbox"]',
    '[contenteditable="true"]',
    '[role="textbox"]',
    '[class*="chat-input"]',
    '[class*="editor"]',
    '[class*="input"] textarea',
]

SUBMIT_BUTTON_CANDIDATES = [
    "#ci-submit-button-ai",
    '[class*="submit-button"]',
    '[class*="send"]',
    'button:has-text("发送")',
]

REFERENCE_PANEL_CANDIDATES = [
    '[role="dialog"]',
    '[aria-modal="true"]',
    '[class*="popover"]',
    '[class*="drawer"]',
    '[class*="reference"]',
    '[class*="source"]',
    '[class*="citation"]',
    '[class*="search"]',
]

LOGIN_TEXT_MARKERS = [
    "登录",
    "扫码登录",
    "手机登录",
    "百度账号",
    "立即登录",
]

CAPTCHA_TEXT_MARKERS = [
    "验证码",
    "安全验证",
    "拖动滑块",
    "请完成验证",
]

STOP_BUTTON_TEXT_MARKERS = [
    "停止生成",
    "停止回答",
    "停止",
]

ANSWER_NOISE_MARKERS = {
    "换一换",
    "复制",
    "分享",
    "重新生成",
    "共参考",
    "展开",
    "收起",
}

REFERENCE_TEXT_PATTERN = r"共参考\s*(\d+)\s*篇资料"
