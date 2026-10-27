const BEIJING_TIME_ZONE = "Asia/Shanghai";
const BEIJING_OFFSET_MS = 8 * 60 * 60 * 1000;

export function parseApiDateTime(value: string | null | undefined): Date | null {
  if (!value) return null;
  const raw = String(value).trim();
  const normalized = raw.includes("T") ? raw : raw.replace(" ", "T");
  const hasTimezone = /(?:Z|[+-]\d{2}:?\d{2})$/.test(normalized);
  const parsed = new Date(hasTimezone ? normalized : `${normalized}Z`);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

export function formatBeijingDateTime(
  value: string | null | undefined,
  fallback = "时间未知",
): string {
  const parsed = parseApiDateTime(value);
  if (!parsed) return value ? String(value) : fallback;
  const formatted = new Intl.DateTimeFormat("zh-CN", {
    timeZone: BEIJING_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(parsed);
  return `${formatted}（北京时间）`;
}

export function beijingDateTimeLocalValue(value = new Date()): string {
  const parts = new Intl.DateTimeFormat("en-CA", {
    timeZone: BEIJING_TIME_ZONE,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).formatToParts(value);
  const get = (type: Intl.DateTimeFormatPartTypes) =>
    parts.find(part => part.type === type)?.value || "";
  return `${get("year")}-${get("month")}-${get("day")}T${get("hour")}:${get("minute")}`;
}

export function beijingLocalDateTimeToIso(value: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2}))?$/.exec(
    String(value || "").trim(),
  );
  if (!match) throw new Error("北京时间格式无效");
  const [, year, month, day, hour, minute, second = "00"] = match;
  const utcMillis = Date.UTC(
    Number(year), Number(month) - 1, Number(day), Number(hour), Number(minute), Number(second),
  ) - BEIJING_OFFSET_MS;
  const parsed = new Date(utcMillis);
  if (
    beijingDateTimeLocalValue(parsed) !== `${year}-${month}-${day}T${hour}:${minute}`
  ) throw new Error("北京时间不存在或超出有效范围");
  return parsed.toISOString();
}
