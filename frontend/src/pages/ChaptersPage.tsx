import { useCallback, useEffect, useState } from 'react'
import {
  Alert,
  AlertIcon,
  Badge,
  Box,
  Button,
  Flex,
  FormControl,
  FormLabel,
  Heading,
  Input,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalHeader,
  ModalOverlay,
  NumberInput,
  NumberInputField,
  Spinner,
  Stack,
  Text,
  useDisclosure,
  useToast,
} from '@chakra-ui/react'
import { useParams } from 'react-router-dom'
import { api } from '../api'
import { ReviewStatusBadge } from '../components/StatusBadge'
import { errorMessage, useAsync } from '../hooks/useAsync'
import type { Chapter, ChapterPageText, ChaptersResponse } from '../types'

function rangeText(ranges: [number, number][]): string {
  return ranges.map(([from, to]) => (from === to ? `${from}` : `${from}–${to}`)).join(', ')
}

interface ChapterCardProps {
  bookId: number
  chapter: Chapter
  isFirst: boolean
  isLast: boolean
  pageCount: number
  onChange: (result: ChaptersResponse) => void
  onMove: (direction: -1 | 1) => void
  onPreview: () => void
}

function ChapterCard({ bookId, chapter, isFirst, isLast, pageCount, onChange, onMove, onPreview }: ChapterCardProps) {
  const toast = useToast()
  const [title, setTitle] = useState(chapter.title)
  const [heading, setHeading] = useState(chapter.heading)
  const [start, setStart] = useState(chapter.start_page)
  const [end, setEnd] = useState(chapter.end_page)

  useEffect(() => {
    setTitle(chapter.title)
    setHeading(chapter.heading)
    setStart(chapter.start_page)
    setEnd(chapter.end_page)
  }, [chapter])

  const dirty =
    title !== chapter.title || heading !== chapter.heading || start !== chapter.start_page || end !== chapter.end_page

  const save = async () => {
    try {
      onChange(await api.updateChapter(bookId, chapter.id, { title, heading, start_page: start, end_page: end }))
      toast({ title: 'Chapter saved.', status: 'success', duration: 1500 })
    } catch (err) {
      toast({ title: errorMessage(err), status: 'error' })
    }
  }

  const remove = async () => {
    if (!window.confirm(`Delete the chapter “${chapter.title}”? Its pages stay in the book.`)) return
    try {
      onChange(await api.deleteChapter(bookId, chapter.id))
    } catch (err) {
      toast({ title: errorMessage(err), status: 'error' })
    }
  }

  const allApproved = chapter.approved_pages === chapter.page_count

  return (
    <Box bg="white" borderWidth="1px" borderRadius="lg" p={4}>
      <Flex justify="space-between" align="center" mb={3} wrap="wrap" gap={2}>
        <Text fontWeight={600}>Chapter {chapter.order_index}</Text>
        <Badge colorScheme={allApproved ? 'green' : chapter.approved_pages > 0 ? 'purple' : 'gray'}>
          {chapter.approved_pages} of {chapter.page_count} pages approved
        </Badge>
      </Flex>
      <Stack spacing={3}>
        <Flex gap={3} wrap="wrap">
          <FormControl flex="2" minW="220px">
            <FormLabel>Chapter title</FormLabel>
            <Input value={title} onChange={(e) => setTitle(e.target.value)} fontFamily="tamil" />
          </FormControl>
          <FormControl flex="2" minW="220px">
            <FormLabel>Heading in the book (optional)</FormLabel>
            <Input value={heading} onChange={(e) => setHeading(e.target.value)} fontFamily="tamil" />
          </FormControl>
          <FormControl w="110px">
            <FormLabel>From page</FormLabel>
            <NumberInput min={1} max={pageCount} value={start} onChange={(_, n) => setStart(n || 1)}>
              <NumberInputField />
            </NumberInput>
          </FormControl>
          <FormControl w="110px">
            <FormLabel>To page</FormLabel>
            <NumberInput min={1} max={pageCount} value={end} onChange={(_, n) => setEnd(n || 1)}>
              <NumberInputField />
            </NumberInput>
          </FormControl>
        </Flex>
        <Flex gap={2} wrap="wrap">
          <Button size="sm" colorScheme="blue" onClick={() => void save()} isDisabled={!dirty}>
            Save
          </Button>
          <Button size="sm" variant="outline" onClick={onPreview}>
            Preview text
          </Button>
          <Button size="sm" variant="outline" as="a" href={api.chapterExportUrl(bookId, chapter.id, false)}>
            Download
          </Button>
          <Button size="sm" variant="ghost" onClick={() => onMove(-1)} isDisabled={isFirst} aria-label="Move up">
            ▲ Up
          </Button>
          <Button size="sm" variant="ghost" onClick={() => onMove(1)} isDisabled={isLast} aria-label="Move down">
            ▼ Down
          </Button>
          <Button size="sm" variant="ghost" colorScheme="red" ml="auto" onClick={() => void remove()}>
            Delete
          </Button>
        </Flex>
      </Stack>
    </Box>
  )
}

export default function ChaptersPage() {
  const bookId = Number(useParams().bookId)
  const toast = useToast()
  const loadBook = useCallback(() => api.book(bookId), [bookId])
  const { data: book, error: bookError } = useAsync(loadBook)
  const loadChapters = useCallback(() => api.chapters(bookId), [bookId])
  const { data: loaded, error: chaptersError } = useAsync(loadChapters)

  const [state, setState] = useState<ChaptersResponse | null>(null)
  const [title, setTitle] = useState('')
  const [heading, setHeading] = useState('')
  const [start, setStart] = useState(1)
  const [end, setEnd] = useState(1)
  const [preview, setPreview] = useState<{ chapter: Chapter; pages: ChapterPageText[] } | null>(null)
  const { isOpen, onOpen, onClose } = useDisclosure()

  useEffect(() => {
    if (loaded !== null) setState(loaded)
  }, [loaded])

  // Suggest the first page that is not in any chapter yet.
  useEffect(() => {
    if (state === null) return
    const next = state.unassigned[0]
    if (next) {
      setStart(next[0])
      setEnd(next[1])
    }
  }, [state])

  const add = async () => {
    try {
      setState(await api.addChapter(bookId, { title, heading, start_page: start, end_page: end }))
      setTitle('')
      setHeading('')
      toast({ title: 'Chapter added.', status: 'success', duration: 1500 })
    } catch (err) {
      toast({ title: errorMessage(err), status: 'error' })
    }
  }

  const move = async (index: number, direction: -1 | 1) => {
    if (state === null) return
    const reordered = [...state.chapters]
    const [moved] = reordered.splice(index, 1)
    reordered.splice(index + direction, 0, moved)
    try {
      setState(await api.reorderChapters(bookId, reordered))
    } catch (err) {
      toast({ title: errorMessage(err), status: 'error' })
    }
  }

  const openPreview = async (chapter: Chapter) => {
    try {
      setPreview({ chapter, pages: await api.chapterText(bookId, chapter.id) })
      onOpen()
    } catch (err) {
      toast({ title: errorMessage(err), status: 'error' })
    }
  }

  const failure = bookError ?? chaptersError
  if (failure !== null) {
    return (
      <Alert status="error">
        <AlertIcon />
        {failure}
      </Alert>
    )
  }
  if (book === null || state === null) return <Spinner />

  return (
    <Box maxW="1000px">
      <Heading size="lg" mb={1} fontFamily="tamil">
        {book.title}
      </Heading>
      <Text color="gray.600" mb={4}>
        Group the pages into chapters. Translation works one chapter at a time.
      </Text>

      {state.unassigned.length > 0 ? (
        <Alert status="warning" mb={4}>
          <AlertIcon />
          Pages not in any chapter yet: {rangeText(state.unassigned)}
        </Alert>
      ) : (
        <Alert status="success" mb={4}>
          <AlertIcon />
          Every page belongs to a chapter.
        </Alert>
      )}

      <Box bg="white" borderWidth="1px" borderRadius="lg" p={4} mb={5}>
        <Heading size="sm" mb={3}>
          Add a chapter
        </Heading>
        <Flex gap={3} wrap="wrap" align="end">
          <FormControl flex="2" minW="220px">
            <FormLabel>Chapter title</FormLabel>
            <Input value={title} onChange={(e) => setTitle(e.target.value)} fontFamily="tamil" />
          </FormControl>
          <FormControl flex="2" minW="220px">
            <FormLabel>Heading in the book (optional)</FormLabel>
            <Input value={heading} onChange={(e) => setHeading(e.target.value)} fontFamily="tamil" />
          </FormControl>
          <FormControl w="110px">
            <FormLabel>From page</FormLabel>
            <NumberInput min={1} max={book.page_count} value={start} onChange={(_, n) => setStart(n || 1)}>
              <NumberInputField />
            </NumberInput>
          </FormControl>
          <FormControl w="110px">
            <FormLabel>To page</FormLabel>
            <NumberInput min={1} max={book.page_count} value={end} onChange={(_, n) => setEnd(n || 1)}>
              <NumberInputField />
            </NumberInput>
          </FormControl>
          <Button colorScheme="blue" onClick={() => void add()}>
            Add chapter
          </Button>
        </Flex>
      </Box>

      <Stack spacing={4}>
        {state.chapters.map((chapter, index) => (
          <ChapterCard
            key={chapter.id}
            bookId={bookId}
            chapter={chapter}
            pageCount={book.page_count}
            isFirst={index === 0}
            isLast={index === state.chapters.length - 1}
            onChange={setState}
            onMove={(direction) => void move(index, direction)}
            onPreview={() => void openPreview(chapter)}
          />
        ))}
      </Stack>

      <Modal isOpen={isOpen} onClose={onClose} size="3xl" scrollBehavior="inside">
        <ModalOverlay />
        <ModalContent>
          <ModalHeader fontFamily="tamil">{preview?.chapter.heading || preview?.chapter.title}</ModalHeader>
          <ModalCloseButton />
          <ModalBody pb={6}>
            {preview !== null && preview.pages.length === 0 && <Text>None of this chapter’s pages have been read yet.</Text>}
            {preview?.pages.map((page) => (
              <Box key={page.page_number} mb={5}>
                <Flex align="center" gap={2} mb={1}>
                  <Text fontWeight={600} color="gray.600">
                    Page {page.page_number}
                  </Text>
                  <ReviewStatusBadge status={page.review_status} />
                </Flex>
                <Text whiteSpace="pre-wrap" fontFamily="tamil" fontSize="20px" lineHeight="2">
                  {page.text}
                </Text>
              </Box>
            ))}
          </ModalBody>
        </ModalContent>
      </Modal>
    </Box>
  )
}
