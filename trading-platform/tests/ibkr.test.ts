import { describe, expect, it } from 'vitest';
// @ts-expect-error — plain JS server module
import { num, vol } from '../server/ibkr.js';

describe('IBKR snapshot parsing', () => {
  it('parses prefixed prices and suffixed volumes', () => {
    expect(num('C228.52')).toBe(228.52);
    expect(num('1,234.5')).toBe(1234.5);
    expect(num('')).toBeNull();
    expect(vol('45.2M')).toBe(45_200_000);
    expect(vol('900K')).toBe(900_000);
    expect(vol('1234')).toBe(1234);
  });
});
