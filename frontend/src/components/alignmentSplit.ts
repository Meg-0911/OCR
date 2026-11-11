type SplitSide = 'source' | 'target';

export function splitAlignmentText(
  source: string,
  target: string,
  side: SplitSide | undefined,
  position: number | undefined,
): { source: [string, string]; target: [string, string] } | null {
  if (!side || position === undefined) return null;

  const normalize = (text: string) => text.replace(/\s+/gu, ' ').trim();
  const sourceCharacters = Array.from(source);
  const sourceGlyphPositions = sourceCharacters.flatMap((character, index) =>
    /[\p{Script=Han}\p{Co}]|□/u.test(character) ? [index] : [],
  );
  const targetWords = [...target.matchAll(/\S+/gu)]
    .filter((match) => /[\p{L}\p{N}]/u.test(match[0]))
    .map((match) => ({
      text: match[0],
      end: Array.from(target.slice(0, (match.index || 0) + match[0].length)).length,
    }));
  if (sourceGlyphPositions.length < 2 || targetWords.length < 2) return null;

  let sourceCut: number;
  let targetCut: number;
  if (side === 'source') {
    if (position <= 0 || position >= sourceCharacters.length) return null;
    sourceCut = position;
    const glyphsBeforeCut = sourceGlyphPositions.filter((glyphPosition) => glyphPosition < position).length;
    if (!glyphsBeforeCut || glyphsBeforeCut >= sourceGlyphPositions.length) return null;
    const wordsBeforeCut = Math.min(glyphsBeforeCut, targetWords.length - 1);
    targetCut = targetWords[wordsBeforeCut - 1].end;
  } else {
    const boundaries = targetWords.slice(0, -1).map((word) => word.end);
    targetCut = boundaries.reduce((nearest, boundary) =>
      Math.abs(boundary - position) < Math.abs(nearest - position) ? boundary : nearest,
    boundaries[0]);
    if (targetCut <= 0 || targetCut >= Array.from(target).length) return null;
    const wordsBeforeCut = targetWords.findIndex((word) => word.end === targetCut) + 1;
    if (!wordsBeforeCut || wordsBeforeCut >= sourceGlyphPositions.length) return null;
    sourceCut = sourceGlyphPositions[wordsBeforeCut - 1] + 1;
  }

  const sourceParts: [string, string] = [
    normalize(sourceCharacters.slice(0, sourceCut).join('')),
    normalize(sourceCharacters.slice(sourceCut).join('')),
  ];
  const targetCharacters = Array.from(target);
  const targetParts: [string, string] = [
    normalize(targetCharacters.slice(0, targetCut).join('')),
    normalize(targetCharacters.slice(targetCut).join('')),
  ];
  if (sourceParts.some((part) => !part) || targetParts.some((part) => !part)) return null;
  return { source: sourceParts, target: targetParts };
}
