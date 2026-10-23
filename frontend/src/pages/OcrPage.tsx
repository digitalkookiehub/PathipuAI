import { useCallback, useEffect, useState } from 'react'
import {
  Accordion,
  AccordionButton,
  AccordionIcon,
  AccordionItem,
  AccordionPanel,
  Alert,
  AlertIcon,
  Box,
  Button,
  Checkbox,
  Flex,
  FormControl,
  FormHelperText,
  FormLabel,
  Heading,
  NumberInput,
  NumberInputField,
  Progress,
  Select,
  SimpleGrid,
  Spinner,
  Stat,
  StatLabel,
  StatNumber,
  Text,
  useToast,
} from '@chakra-ui/react'
import { Link as RouterLink, useParams } from 'react-router-dom'
import { api } from '../api'
import { BookStatusBadge } from '../components/StatusBadge'
import { errorMessage, useAsync } from '../hooks/useAsync'
import type { OcrEngine, OcrStatus } from '../types'

const POLL_MS = 1500

export default function OcrPage() {
  const bookId = Number(useParams().bookId)
  const toast = useToast()
  const loadBook = useCallback(() => api.book(bookId), [bookId])
  const { data: book, error: bookError, reload: reloadBook } = useAsync(loadBook)

  const [status, setStatus] = useState<OcrStatus | null>(null)
  const [firstPage, setFirstPage] = useState(1)
  const [lastPage, setLastPage] = useState(3)
  const [readAll, setReadAll] = useState(false)
  const [discard, setDiscard] = useState(false)
  const [engine, setEngine] = useState<OcrEngine>('tesseract')
  const [busy, setBusy] = useState(false)

  const refreshStatus = useCallback(async () => {
    try {
      setStatus(await api.ocrStatus(bookId))
    } catch (err) {
      toast({ title: errorMessage(err), status: 'error', id: 'status-error' })
    }
  }, [bookId, toast])

  useEffect(() => {
    void refreshStatus()
  }, [refreshStatus])

  const running = status?.running ?? false
  useEffect(() => {
    if (!running) return
    const timer = window.setInterval(() => void refreshStatus(), POLL_MS)
    return () => window.clearInterval(timer)
  }, [running, refreshStatus])

  const wasRunning = useWasRunning(running)
  useEffect(() => {
    if (wasRunning) reloadBook()
  }, [wasRunning, reloadBook])

  useEffect(() => {
    if (book !== null) setLastPage(Math.min(3, book.page_count))
  }, [book])

  const act = async (action: () => Promise<unknown>) => {
    setBusy(true)
    try {
      await action()
      await refreshStatus()
    } catch (err) {
      toast({ title: errorMessage(err), status: 'error' })
    } finally {
      setBusy(false)
    }
  }

  if (bookError !== null) {
    return (
      <Alert status="error">
        <AlertIcon />
        {bookError}
      </Alert>
    )
  }
  if (book === null || status === null) return <Spinner />

  const counts = status.page_counts
  const engineStatus = status.engines[engine]
  const done = counts.done ?? 0
  const failed = counts.failed ?? 0
  const waiting = (counts.not_started ?? 0) + (counts.processing ?? 0)
  const job = status.job
  const jobDone = job ? job.completed + job.failed : 0
  const range = readAll ? [null, null] : [firstPage, lastPage]

  return (
    <Box maxW="900px">
      <Flex justify="space-between" align="start" mb={4} gap={3}>
        <Box>
          <Heading size="lg" fontFamily="tamil">
            {book.title}
          </Heading>
          <Text color="gray.600">
            {book.source_language_name} · {book.page_count} pages
          </Text>
        </Box>
        <BookStatusBadge status={book.status} label={book.status_label} />
      </Flex>

      {!engineStatus.ready && (
        <Alert status="error" mb={4}>
          <AlertIcon />
          {engineStatus.message}
        </Alert>
      )}
      {status.error !== null && (
        <Alert status="warning" mb={4}>
          <AlertIcon />
          {status.error}
        </Alert>
      )}

      <SimpleGrid columns={4} spacing={3} mb={5}>
        <Stat bg="white" borderWidth="1px" borderRadius="md" p={3}>
          <StatLabel>Read</StatLabel>
          <StatNumber>{done}</StatNumber>
        </Stat>
        <Stat bg="white" borderWidth="1px" borderRadius="md" p={3}>
          <StatLabel>Waiting</StatLabel>
          <StatNumber>{waiting}</StatNumber>
        </Stat>
        <Stat bg="white" borderWidth="1px" borderRadius="md" p={3}>
          <StatLabel>Failed</StatLabel>
          <StatNumber color={failed > 0 ? 'red.500' : undefined}>{failed}</StatNumber>
        </Stat>
        <Stat bg="white" borderWidth="1px" borderRadius="md" p={3}>
          <StatLabel>Total</StatLabel>
          <StatNumber>{book.page_count}</StatNumber>
        </Stat>
      </SimpleGrid>

      {running && job !== null && (
        <Box mb={5}>
          <Text mb={1}>
            Reading pages… {jobDone} of {job.total}
          </Text>
          <Progress value={job.total > 0 ? (jobDone / job.total) * 100 : 0} borderRadius="md" hasStripe isAnimated />
        </Box>
      )}

      <Box bg="white" borderWidth="1px" borderRadius="lg" p={5} mb={5}>
        <Heading size="sm" mb={1}>
          Start or continue reading
        </Heading>
        <Text color="gray.600" fontSize="sm" mb={3}>
          Tip: to test the quality, read just the first few pages. Pages that are already read are never repeated.
        </Text>
        <FormControl maxW="520px" mb={4}>
          <FormLabel>Reading method</FormLabel>
          <Select value={engine} onChange={(e) => setEngine(e.target.value as OcrEngine)}>
            <option value="tesseract">Fast (about 3 seconds a page)</option>
            <option value="careful">Careful, much more accurate (about 1 minute a page)</option>
          </Select>
          <FormHelperText>
            {engine === 'careful'
              ? 'Best for hard pages such as phone photos. The first run downloads about 270 MB and takes a few minutes to start.'
              : 'Good for clean scans. Switch to Careful for pages that read badly.'}
          </FormHelperText>
        </FormControl>
        <Flex gap={4} wrap="wrap" align="end">
          <FormControl w="120px" isDisabled={readAll}>
            <FormLabel>From page</FormLabel>
            <NumberInput min={1} max={book.page_count} value={firstPage} onChange={(_, n) => setFirstPage(n || 1)}>
              <NumberInputField />
            </NumberInput>
          </FormControl>
          <FormControl w="120px" isDisabled={readAll}>
            <FormLabel>To page</FormLabel>
            <NumberInput min={1} max={book.page_count} value={lastPage} onChange={(_, n) => setLastPage(n || 1)}>
              <NumberInputField />
            </NumberInput>
          </FormControl>
          <Checkbox isChecked={readAll} onChange={(e) => setReadAll(e.target.checked)}>
            Read all remaining pages
          </Checkbox>
        </Flex>
        <Flex gap={3} mt={4} wrap="wrap">
          <Button
            colorScheme="blue"
            isDisabled={running || !engineStatus.ready}
            isLoading={busy}
            onClick={() => act(() => api.startOcr(bookId, range[0], range[1], false, engine))}
          >
            Start / continue reading
          </Button>
          <Button
            variant="outline"
            isDisabled={running || failed === 0 || !engineStatus.ready}
            onClick={() => act(() => api.startOcr(bookId, null, null, true, engine))}
          >
            Retry failed pages
          </Button>
          <Button as={RouterLink} to={`/books/${bookId}/review`} variant="ghost" ml="auto" isDisabled={done === 0}>
            Check and correct the text →
          </Button>
        </Flex>
      </Box>

      <Accordion allowToggle>
        <AccordionItem bg="white" borderWidth="1px" borderRadius="lg">
          <AccordionButton>
            <Box flex="1" textAlign="left" fontWeight={600}>
              Read pages again (replaces the earlier reading)
            </Box>
            <AccordionIcon />
          </AccordionButton>
          <AccordionPanel>
            <Text fontSize="sm" color="gray.600" mb={3}>
              Uses the “From page” and “To page” above. Pages you have corrected or approved are protected unless you
              tick the box below.
            </Text>
            <Checkbox isChecked={discard} onChange={(e) => setDiscard(e.target.checked)} mb={3}>
              Discard my corrections and approvals on these pages
            </Checkbox>
            <Box>
              <Button
                colorScheme="orange"
                isDisabled={running || !engineStatus.ready || readAll}
                onClick={() => act(() => api.reread(bookId, firstPage, lastPage, discard, engine))}
              >
                Read these pages again
              </Button>
            </Box>
          </AccordionPanel>
        </AccordionItem>
      </Accordion>
    </Box>
  )
}

/** True for one render after a running job has finished. */
function useWasRunning(running: boolean): boolean {
  const [previous, setPrevious] = useState(running)
  useEffect(() => setPrevious(running), [running])
  return previous && !running
}
