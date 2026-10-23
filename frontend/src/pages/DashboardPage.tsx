import { useCallback, useRef, useState } from 'react'
import {
  AlertDialog,
  AlertDialogBody,
  AlertDialogContent,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogOverlay,
  Alert,
  AlertIcon,
  Box,
  Button,
  Flex,
  Heading,
  SimpleGrid,
  Spinner,
  Text,
  useToast,
} from '@chakra-ui/react'
import { Link as RouterLink } from 'react-router-dom'
import { api } from '../api'
import { BookStatusBadge } from '../components/StatusBadge'
import { errorMessage, useAsync } from '../hooks/useAsync'
import type { Book } from '../types'

export default function DashboardPage() {
  const load = useCallback(() => api.books(), [])
  const { data: books, error, loading, reload } = useAsync(load)
  const [toDelete, setToDelete] = useState<Book | null>(null)
  const cancelRef = useRef<HTMLButtonElement>(null)
  const toast = useToast()

  const confirmDelete = async () => {
    if (toDelete === null) return
    try {
      await api.deleteBook(toDelete.id)
      toast({ title: 'The book was deleted.', status: 'success' })
      reload()
    } catch (err) {
      toast({ title: errorMessage(err), status: 'error' })
    } finally {
      setToDelete(null)
    }
  }

  if (loading && books === null) return <Spinner />
  if (error !== null) {
    return (
      <Alert status="error">
        <AlertIcon />
        {error}
      </Alert>
    )
  }

  return (
    <Box>
      <Flex justify="space-between" align="center" mb={5}>
        <Heading size="lg">My books</Heading>
        <Button as={RouterLink} to="/books/new" colorScheme="blue">
          Add a book
        </Button>
      </Flex>

      {books !== null && books.length === 0 && (
        <Alert status="info">
          <AlertIcon />
          You have no books yet. Click “Add a book” to upload your first scanned PDF.
        </Alert>
      )}

      <SimpleGrid columns={{ base: 1, md: 2, xl: 3 }} spacing={5}>
        {books?.map((book) => (
          <Box key={book.id} bg="white" borderWidth="1px" borderRadius="lg" p={5}>
            <Flex justify="space-between" align="start" gap={3}>
              <Heading size="md" fontFamily="tamil">
                {book.title}
              </Heading>
              <BookStatusBadge status={book.status} label={book.status_label} />
            </Flex>
            <Text color="gray.600" mt={1}>
              {book.author || 'Unknown author'} · {book.source_language_name} · {book.page_count} pages
            </Text>
            <Flex mt={4} gap={2} wrap="wrap">
              <Button as={RouterLink} to={`/books/${book.id}/ocr`} size="sm" colorScheme="blue">
                Read pages
              </Button>
              <Button as={RouterLink} to={`/books/${book.id}/review`} size="sm" variant="outline">
                Check and correct
              </Button>
              <Button size="sm" variant="ghost" colorScheme="red" onClick={() => setToDelete(book)}>
                Delete
              </Button>
            </Flex>
          </Box>
        ))}
      </SimpleGrid>

      <AlertDialog isOpen={toDelete !== null} leastDestructiveRef={cancelRef} onClose={() => setToDelete(null)}>
        <AlertDialogOverlay>
          <AlertDialogContent>
            <AlertDialogHeader>Delete this book?</AlertDialogHeader>
            <AlertDialogBody>
              “{toDelete?.title}” and all of its pages, corrections and files will be removed. This cannot be undone.
            </AlertDialogBody>
            <AlertDialogFooter>
              <Button ref={cancelRef} onClick={() => setToDelete(null)}>
                Keep it
              </Button>
              <Button colorScheme="red" ml={3} onClick={confirmDelete}>
                Yes, delete it
              </Button>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialogOverlay>
      </AlertDialog>
    </Box>
  )
}
