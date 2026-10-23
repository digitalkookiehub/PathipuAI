import { Box, Button, Flex } from '@chakra-ui/react'
import { NavLink, Outlet, useParams } from 'react-router-dom'

const TABS = [
  { path: 'ocr', label: '1. Read pages' },
  { path: 'review', label: '2. Check and correct' },
  { path: 'chapters', label: '3. Chapters' },
  { path: 'glossary', label: '4. Glossary' },
  { path: 'translate', label: '5. Translate' },
  { path: 'translation-review', label: '6. Review translations' },
  { path: 'publish', label: '7. Publish' },
]

/** Shows the steps of one book as tabs above whichever step is open. */
export default function BookLayout() {
  const { bookId } = useParams()
  return (
    <Box>
      <Flex gap={2} mb={5} wrap="wrap" aria-label="Book steps">
        {TABS.map((tab) => (
          <Button
            key={tab.path}
            as={NavLink}
            to={`/books/${bookId}/${tab.path}`}
            size="sm"
            variant="outline"
            _activeLink={{ bg: 'blue.600', color: 'white', borderColor: 'blue.600' }}
          >
            {tab.label}
          </Button>
        ))}
      </Flex>
      <Outlet />
    </Box>
  )
}
