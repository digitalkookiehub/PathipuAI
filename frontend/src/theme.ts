import '@fontsource/noto-sans-tamil/400.css'
import '@fontsource/noto-sans-tamil/600.css'
import '@fontsource/noto-sans-telugu/400.css'
import '@fontsource/noto-sans-kannada/400.css'
import '@fontsource/noto-sans-malayalam/400.css'
import '@fontsource/noto-sans-devanagari/400.css'
import { extendTheme } from '@chakra-ui/react'

// Noto Sans Tamil is bundled (open font licence) so Tamil is clear on every computer.
// Translated text can be in any of the supported scripts; the browser picks the matching font per character.
const indicFont = `'Noto Sans Telugu', 'Noto Sans Kannada', 'Noto Sans Malayalam', 'Noto Sans Devanagari', 'Noto Sans Tamil', sans-serif`
const tamilFont = "'Noto Sans Tamil', 'Latha', 'Nirmala UI', sans-serif"

export const theme = extendTheme({
  fonts: {
    body: `system-ui, 'Segoe UI', ${tamilFont}`,
    heading: `system-ui, 'Segoe UI', ${tamilFont}`,
    tamil: tamilFont,
    indic: indicFont,
  },
  styles: {
    global: {
      body: { bg: 'gray.50' },
    },
  },
})
