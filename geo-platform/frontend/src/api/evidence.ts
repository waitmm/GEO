export type AnswerUnit = { run_id: number; raw_start: number; raw_end: number; raw_text: string };
export type FrozenAnswer = { run_id: number; text: string; text_hash: string };

// Python offsets count Unicode code points, not JavaScript UTF-16 code units.
export function locateAnswer(answers: FrozenAnswer[], unit: AnswerUnit) {
  const answer = answers.find(row => row.run_id === unit.run_id);
  if (!answer) return null;
  const chars = Array.from(answer.text);
  if (!Number.isInteger(unit.raw_start) || !Number.isInteger(unit.raw_end) ||
      unit.raw_start < 0 || unit.raw_end <= unit.raw_start || unit.raw_end > chars.length ||
      chars.slice(unit.raw_start, unit.raw_end).join("") !== unit.raw_text) return null;
  return { before: chars.slice(0, unit.raw_start).join(""), text: unit.raw_text,
    after: chars.slice(unit.raw_end).join("") };
}

export function evidenceLink(value: string): string | undefined {
  try {
    const url = new URL(value);
    return ["https:", "http:"].includes(url.protocol) && !url.username && !url.password ? url.href : undefined;
  } catch { return undefined; }
}
