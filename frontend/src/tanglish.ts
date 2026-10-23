/**
 * Typing aid: turns Tamil written with English letters ("Tanglish") into Tamil script.
 *
 * Tanglish is ambiguous (n can be ந, ன or ண; t can be ட or த), so conversion has two steps:
 *  1. `transliterate` converts letters by simple phonetic rules.
 *  2. `convertWord` then looks the result up in a word list built from the book itself, so a word the book really
 *     uses gets its correct spelling (vanakkam -> வணக்கம் instead of வனக்கம்).
 * A capital letter inside a word (vaNakkam) always means "exactly this letter", and skips the word list.
 */

const PULLI = '்'

type Consonant = { kind: 'consonant'; letters: string[] }
type Vowel = { kind: 'vowel'; independent: string; sign: string }
type Raw = { kind: 'raw'; text: string }
type Token = Consonant | Vowel | Raw

const VOWELS: Record<string, [string, string]> = {
  aa: ['ஆ', 'ா'],
  A: ['ஆ', 'ா'],
  a: ['அ', ''],
  ee: ['ஈ', 'ீ'],
  ii: ['ஈ', 'ீ'],
  I: ['ஈ', 'ீ'],
  i: ['இ', 'ி'],
  oo: ['ஊ', 'ூ'],
  uu: ['ஊ', 'ூ'],
  U: ['ஊ', 'ூ'],
  u: ['உ', 'ு'],
  ai: ['ஐ', 'ை'],
  ae: ['ஏ', 'ே'],
  E: ['ஏ', 'ே'],
  e: ['எ', 'ெ'],
  au: ['ஔ', 'ௌ'],
  ow: ['ஔ', 'ௌ'],
  oa: ['ஓ', 'ோ'],
  O: ['ஓ', 'ோ'],
  o: ['ஒ', 'ொ'],
}

// Consonant spellings; clusters such as "nth" give several letters that join with a pulli.
const CONSONANTS: Record<string, string[]> = {
  ksh: ['க', 'ஷ'],
  ndr: ['ன', 'ற'],
  ndh: ['ந', 'த'],
  nth: ['ந', 'த'],
  ttr: ['ற', 'ற'],
  chh: ['ச'],
  ch: ['ச'],
  sh: ['ஷ'],
  zh: ['ழ'],
  th: ['த'],
  dh: ['த'],
  kh: ['க'],
  gh: ['க'],
  bh: ['ப'],
  ph: ['ப'],
  nd: ['ந', 'த'],
  nt: ['ந', 'த'],
  nr: ['ன', 'ற'],
  k: ['க'],
  g: ['க'],
  c: ['ச'],
  s: ['ச'],
  S: ['ஸ'],
  j: ['ஜ'],
  t: ['ட'],
  T: ['ட'],
  d: ['ட'],
  D: ['ட'],
  N: ['ண'],
  p: ['ப'],
  b: ['ப'],
  m: ['ம'],
  y: ['ய'],
  r: ['ர'],
  R: ['ற'],
  l: ['ல'],
  L: ['ள'],
  v: ['வ'],
  w: ['வ'],
  z: ['ழ'],
  h: ['ஹ'],
  f: ['ப'],
}

// Longest spelling first, so "nth" wins over "n" + "t" + "h".
const SPELLINGS: [string, Token][] = [
  ...Object.entries(VOWELS).map(([letters, [independent, sign]]): [string, Token] => [
    letters,
    { kind: 'vowel', independent, sign },
  ]),
  ...Object.entries(CONSONANTS).map(([letters, tamil]): [string, Token] => [letters, { kind: 'consonant', letters: tamil }]),
].sort((a, b) => b[0].length - a[0].length)

const VOWEL_LETTERS = /[aeiouAEIOU]/
const SRI = /^(shri|shree|sri|sree)/i

function tokenize(word: string): Token[] {
  const tokens: Token[] = []
  let i = 0
  const initial = SRI.exec(word)
  if (initial) {
    tokens.push({ kind: 'raw', text: 'ஸ்ரீ' })
    i = initial[0].length
  }
  while (i < word.length) {
    const rest = word.slice(i)
    // "ng" and "nj" before a vowel in the middle of a word are ங்க / ஞ்ச (thangam, panju).
    const nasal = /^(ng|nj)(?=[aeiouAEIOU])/.exec(rest)
    if (nasal && i > 0) {
      tokens.push({ kind: 'consonant', letters: nasal[1] === 'ng' ? ['ங', 'க'] : ['ஞ', 'ச'] })
      i += 2
      continue
    }
    if (/^(ng|nj)/.test(rest) && !VOWEL_LETTERS.test(rest[2] ?? '')) {
      tokens.push({ kind: 'consonant', letters: [rest[1] === 'g' ? 'ங' : 'ஞ'] })
      i += 2
      continue
    }
    const hit = SPELLINGS.find(([letters]) => rest.startsWith(letters))
    if (hit) {
      tokens.push(hit[1])
      i += hit[0].length
      continue
    }
    if (rest[0] === 'n') {
      // A lone n: ந at the start of a word, ன elsewhere (clusters such as "nd" and "nth" were matched above).
      tokens.push({ kind: 'consonant', letters: [i === 0 ? 'ந' : 'ன'] })
      i += 1
      continue
    }
    tokens.push({ kind: 'raw', text: rest[0] })
    i += 1
  }
  return tokens
}

/** Convert one Latin word to Tamil by phonetic rules only. */
export function transliterate(word: string): string {
  let output = ''
  let pending: string | null = null // a consonant waiting to learn which vowel follows it
  const flush = (withPulli: boolean) => {
    if (pending !== null) output += pending + (withPulli ? PULLI : '')
    pending = null
  }
  for (const token of tokenize(word)) {
    if (token.kind === 'consonant') {
      for (const letter of token.letters) {
        flush(true) // a consonant followed by another consonant takes a pulli
        pending = letter
      }
    } else if (token.kind === 'vowel') {
      if (pending !== null) {
        output += pending + token.sign
        pending = null
      } else {
        output += token.independent
      }
    } else {
      flush(true)
      output += token.text
    }
  }
  flush(true)
  return output
}

// --- word list matching -----------------------------------------------------------------------------------------

const CONSONANT_KEY: Record<string, string> = {
  க: 'k', ங: 'k', ச: 's', ஞ: 'n', ட: 't', ண: 'n', த: 't', ந: 'n', ப: 'p', ம: 'm', ய: 'y', ர: 'r', ல: 'l',
  வ: 'v', ழ: 'l', ள: 'l', ற: 'r', ன: 'n', ஜ: 'j', ஷ: 's', ஸ: 's', ஹ: 'h',
}
const VOWEL_KEY: Record<string, string> = {
  அ: 'a', ஆ: 'a', இ: 'i', ஈ: 'i', உ: 'u', ஊ: 'u', எ: 'e', ஏ: 'e', ஐ: 'ai', ஒ: 'o', ஓ: 'o', ஔ: 'au',
}
const SIGN_KEY: Record<string, string> = {
  'ா': 'a', 'ி': 'i', 'ீ': 'i', 'ு': 'u', 'ூ': 'u', 'ெ': 'e', 'ே': 'e', 'ை': 'ai', 'ொ': 'o', 'ோ': 'o', 'ௌ': 'au',
}

/**
 * A spelling-insensitive fingerprint of a Tamil word. Letters that Tanglish cannot tell apart (ந ன ண, ட த, ல ள ழ,
 * ர ற, long and short vowels) give the same key, so "vanakkam" and "வணக்கம்" match.
 */
export function tamilKey(word: string): string {
  let key = ''
  const chars = Array.from(word)
  for (let i = 0; i < chars.length; i++) {
    const char = chars[i]
    const consonant = CONSONANT_KEY[char]
    if (consonant !== undefined) {
      const next = chars[i + 1]
      if (next === PULLI) {
        key += consonant
        i += 1
      } else if (next !== undefined && SIGN_KEY[next] !== undefined) {
        key += consonant + SIGN_KEY[next]
        i += 1
      } else {
        key += consonant + 'a'
      }
    } else if (VOWEL_KEY[char] !== undefined) {
      key += VOWEL_KEY[char]
    }
  }
  return key
}

export type Lexicon = Map<string, string>

/** Build a word list from [word, score] pairs (best first): each key maps to the most used spelling. */
export function buildLexicon(entries: [string, number][]): Lexicon {
  const lexicon: Lexicon = new Map()
  for (const [word] of [...entries].sort((a, b) => b[1] - a[1])) {
    const key = tamilKey(word)
    if (key !== '' && !lexicon.has(key)) lexicon.set(key, word)
  }
  return lexicon
}

/** Convert one Latin word, preferring the spelling the book itself uses. */
export function convertWord(word: string, lexicon?: Lexicon): string {
  const explicit = /[A-Z]/.test(word.slice(1)) // an inner capital means "exactly this letter"
  const tamil = transliterate(word.charAt(0).toLowerCase() + word.slice(1))
  if (!explicit && lexicon !== undefined) {
    const known = lexicon.get(tamilKey(tamil))
    if (known !== undefined) return known
  }
  return tamil
}

/** Convert every run of two or more Latin letters in a text (used for the "convert all" button). */
export function convertText(text: string, lexicon?: Lexicon): string {
  return text.replace(/[A-Za-z]{2,}/g, (word) => convertWord(word, lexicon))
}
