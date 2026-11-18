/**
 * Keeps a user-visible observation request tied to the exact selection that
 * started it. This is deliberately separate from page-load generations: a
 * user can change one of the frozen inputs while a comparison request is in
 * flight without reloading the page.
 */
export class ObservationRequestEpoch {
  private value = 0;

  begin(): number {
    return ++this.value;
  }

  invalidate(): number {
    return ++this.value;
  }

  isCurrent(epoch: number): boolean {
    return this.value === epoch;
  }
}
