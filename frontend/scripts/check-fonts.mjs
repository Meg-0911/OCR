import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';

const root = new URL('../public/', import.meta.url);
try {
  const manifest = JSON.parse(await readFile(new URL('fonts/manifest.json', root), 'utf8'));
  for (const font of manifest.fonts) {
    const content = await readFile(new URL(`fonts/${font.file}`, root));
    if (content.subarray(0, 4).toString('ascii') !== 'wOF2') {
      throw new Error(`${font.file} is not a valid WOFF2 font`);
    }
    if (createHash('sha256').update(content).digest('hex') !== font.woff2_sha256) {
      throw new Error(`${font.file} differs from the bundled font manifest`);
    }
  }
  await Promise.all(
    ['nom-na-tong-MIT.txt', 'hanamin-license.txt'].map((file) =>
      readFile(new URL(`licenses/${file}`, root)),
    ),
  );
  console.log(
    `Nôm web fonts verified: ${manifest.fonts.length} files, ${manifest.combined_codepoints} codepoints.`,
  );
} catch (error) {
  console.error(`Nôm font assets are missing or invalid: ${error.message}`);
  console.error(
    'Restore frontend/public/fonts/ and licenses/, or run py frontend/scripts/setup_fonts.py.',
  );
  process.exitCode = 1;
}
