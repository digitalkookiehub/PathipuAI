import { describe, expect, it } from 'vitest'
import { buildLexicon, convertText, convertWord, tamilKey, transliterate } from './tanglish'

describe('transliterate', () => {
  it.each([
    ['naan', 'நான்'],
    ['nandri', 'நன்றி'],
    ['thangam', 'தங்கம்'],
    ['singam', 'சிங்கம்'],
    ['baabaa', 'பாபா'],
    ['amma', 'அம்ம'],
    ['ammaa', 'அம்மா'],
    ['ennai', 'என்னை'],
    ['thamizh', 'தமிழ்'],
    ['mel', 'மெல்'],
    ['kadavul', 'கடவுல்'],
    ['guru', 'குரு'],
    ['sri', 'ஸ்ரீ'],
    ['panju', 'பஞ்சு'],
    ['vaNakkam', 'வணக்கம்'],
    ['aanmeegam', 'ஆன்மீகம்'],
  ])('%s -> %s', (latin, tamil) => {
    expect(transliterate(latin)).toBe(tamil)
  })

  it('keeps characters it does not know', () => {
    expect(transliterate('om1')).toBe('ஒம்1')
  })
})

describe('tamilKey', () => {
  it('ignores the letters Tanglish cannot tell apart', () => {
    expect(tamilKey('வணக்கம்')).toBe(tamilKey('வனக்கம்'))
    expect(tamilKey('தமிழ்')).toBe(tamilKey('டமில்'))
    expect(tamilKey('பாபா')).toBe('papa')
    expect(tamilKey('வணக்கம்')).not.toBe(tamilKey('வணக்கமும்'))
  })
})

describe('convertWord with the book word list', () => {
  const lexicon = buildLexicon([
    ['வணக்கம்', 12],
    ['தமிழ்', 30],
    ['நன்றி', 5],
    ['சாயி', 4],
    ['ஸாயி', 40],
  ])

  it('uses the spelling the book uses', () => {
    expect(convertWord('vanakkam', lexicon)).toBe('வணக்கம்')
    expect(convertWord('tamil', lexicon)).toBe('தமிழ்')
    expect(convertWord('Nandri', lexicon)).toBe('நன்றி')
  })

  it('prefers the most used of two spellings', () => {
    expect(convertWord('saayi', lexicon)).toBe('ஸாயி')
  })

  it('falls back to the rules for words the book does not have', () => {
    expect(convertWord('thangam', lexicon)).toBe('தங்கம்')
    expect(convertWord('thangam')).toBe('தங்கம்')
  })

  it('treats an inner capital as an exact choice', () => {
    expect(convertWord('vanaKkam', lexicon)).toBe(transliterate('vanaKkam'))
  })
})

describe('convertText', () => {
  it('converts only runs of Latin letters', () => {
    expect(convertText('naan 12 baabaa, அவர் a', buildLexicon([]))).toBe('நான் 12 பாபா, அவர் a')
  })
})
