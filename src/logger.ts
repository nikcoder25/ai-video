const t0 = Date.now();

function stamp(): string {
  const s = ((Date.now() - t0) / 1000).toFixed(1);
  return `+${s}s`;
}

export const log = {
  step(msg: string): void {
    console.log(`\n\x1b[36m▶ ${msg}\x1b[0m \x1b[2m(${stamp()})\x1b[0m`);
  },
  info(msg: string): void {
    console.log(`  ${msg}`);
  },
  ok(msg: string): void {
    console.log(`  \x1b[32m✓\x1b[0m ${msg}`);
  },
  warn(msg: string): void {
    console.log(`  \x1b[33m!\x1b[0m ${msg}`);
  },
  error(msg: string): void {
    console.error(`  \x1b[31m✗ ${msg}\x1b[0m`);
  },
};
