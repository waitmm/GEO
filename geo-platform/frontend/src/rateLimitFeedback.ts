export type RateLimitSignal = {
  status?: string | null;
  errorType?: string | null;
  blockedType?: string | null;
};

export const RATE_LIMIT_LABEL = "平台限流/配额受限";
export const RATE_LIMIT_RECOVERY_GUIDANCE = "不会自动重试；请等待平台窗口或配额恢复后，在正式 V2 样本池中由用户显式追加尝试。";

/** Only honor the frozen structured signal; never infer a rate limit from timeout text. */
export function isRateLimited(signal: RateLimitSignal): boolean {
  if (signal.status !== "blocked") return false;
  return [signal.errorType, signal.blockedType]
    .some((value) => value?.trim().toLowerCase() === "rate_limited");
}
