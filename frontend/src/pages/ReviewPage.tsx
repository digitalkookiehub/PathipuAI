import { useCallback, useEffect, useMemo, useState } from 'react'
import type { KeyboardEvent } from 'react'
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
  FormLabel,
  Heading,
  Image,
  Input,
  NumberInput,
  NumberInputField,
  Progress,
  SimpleGrid,
  Spinner,
  Stat,
  StatHelpText,
  StatLabel,
  StatNumber,
  Text,
  Switch,
  Textarea,
  useToast,
  VStack,
} from '@chakra-ui/react'
import { Link as RouterLink, useParams, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { ReviewStatusBadge } from '../components/StatusBadge'
import { errorMessage, useAsync } from '../hooks/useAsync'
import type { OcrStatus, PageDetail, PageSummary, SearchHit } from '../types'
import { buildLexicon, convertText, convertWord } from '../tanglish'
import type { Lexicon } from '../tanglish'

const ENGINE_LABELS: Record<string, string> = { tesseract: 'Fast', careful: 'Careful' }
// Typing one of these after a word of English letters turns that word into Tamil.
const TANGLISH_TRIGGERS = new Set([' ', 'Enter', ',', '.', ';', ':', '?', '!', ')', '"', "'", '-'])
const TANGLISH_SETTING = 'pathippu.tanglish'

function readTanglishSetting(): boolean {
  try {
    return window.localStorage.getItem(TANGLISH_SETTING) !== '0'
  } catch {
    return true
  }
}

const CHIP_COLORS: Record<string, string> = { pending: 'gray', corrected: 'purple', approved: 'green' }

export default function ReviewPage() {
  const bookId = Number(useParams().bookId)
  const [searchParams, setSearchParams] = useSearchParams()
  const toast = useToast()

  const loadBook = useCallback(() => api.book(bookId), [bookId])
  const { data: book, error: bookError } = useAsync(loadBook)

  const [pages, setPages] = useState<PageSummary[]>([])
  const [status, setStatus] = useState<OcrStatus | null>(null)
  const [detail, setDetail] = useState<PageDetail | null>(null)
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const [query, setQuery] = useState('')
  const [hits, setHits] = useState<SearchHit[] | null>(null)
  const [approvedOnly, setApprovedOnly] = useState(false)
  const [bulkFrom, setBulkFrom] = useState(1)
  const [bulkTo, setBulkTo] = useState(1)
  const [tanglish, setTanglish] = useState(readTanglishSetting)
  const [lexicon, setLexicon] = useState<Lexicon | undefined>(undefined)

  const pageNumber = Math.max(1, Number(searchParams.get('page')) || 1)

  useEffect(() => {
    if (book !== null) setBulkTo(book.page_count)
  }, [book])
  const pageCount = book?.page_count ?? 1
  const dirty = detail !== null && draft !== detail.text
  const lastBookPage = book?.page_count ?? 1

  const refreshOverview = useCallback(async () => {
    const [list, ocrStatus] = await Promise.all([api.pages(bookId), api.ocrStatus(bookId)])
    setPages(list)
    setStatus(ocrStatus)
  }, [bookId])

  useEffect(() => {
    refreshOverview().catch((err: unknown) => toast({ title: errorMessage(err), status: 'error' }))
  }, [refreshOverview, toast])

  useEffect(() => {
    let cancelled = false
    setDetail(null)
    api
      .page(bookId, pageNumber)
      .then((result) => {
        if (cancelled) return
        setDetail(result)
        setDraft(result.text)
      })
      .catch((err: unknown) => {
        if (!cancelled) toast({ title: errorMessage(err), status: 'error' })
      })
    return () => {
      cancelled = true
    }
  }, [bookId, pageNumber, toast])

  const apply = (result: PageDetail) => {
    setDetail(result)
    setDraft(result.text)
  }

  /** Save any unsaved edits (never approves) before moving elsewhere. */
  const saveIfDirty = async (): Promise<boolean> => {
    if (!dirty || detail === null) return true
    try {
      apply(await api.saveText(bookId, detail.page_number, draft))
      return true
    } catch (err) {
      toast({ title: errorMessage(err), status: 'error' })
      return false
    }
  }

  const goTo = async (target: number) => {
    const clamped = Math.min(Math.max(target, 1), pageCount)
    if (clamped === pageNumber) return
    if (!(await saveIfDirty())) return
    setSearchParams({ page: String(clamped) })
    void refreshOverview()
  }

  const run = async (action: () => Promise<PageDetail>, success: string, then?: () => void) => {
    setBusy(true)
    try {
      apply(await action())
      toast({ title: success, status: 'success', duration: 1500 })
      await refreshOverview()
      then?.()
    } catch (err) {
      toast({ title: errorMessage(err), status: 'error' })
    } finally {
      setBusy(false)
    }
  }

  const save = () => run(() => api.saveText(bookId, pageNumber, draft), 'Saved.')
  const saveAndApprove = () =>
    run(
      async () => {
        await api.saveText(bookId, pageNumber, draft)
        return api.approve(bookId, pageNumber)
      },
      `Page ${pageNumber} approved.`,
      () => {
        if (pageNumber < pageCount) setSearchParams({ page: String(pageNumber + 1) })
      },
    )
  const restore = () => run(() => api.restore(bookId, pageNumber), 'Went back to the original text.')

  const doSearch = async () => {
    if (query.trim() === '') return setHits(null)
    try {
      setHits(await api.search(bookId, query))
    } catch (err) {
      toast({ title: errorMessage(err), status: 'error' })
    }
  }

  const approveMany = async (first: number, last: number) => {
    const message = `Approve pages ${first} to ${last} without checking each one? Pages that have not been read are skipped.`
    if (!window.confirm(message)) return
    if (!(await saveIfDirty())) return
    setBusy(true)
    try {
      const result = await api.approveMany(bookId, first, last)
      const pagesWord = result.approved === 1 ? 'page' : 'pages'
      const unread = result.unread > 0 ? ` ${result.unread} not read yet.` : ''
      toast({ title: `${result.approved} ${pagesWord} approved.${unread}`, status: 'success' })
      await refreshOverview()
      apply(await api.page(bookId, pageNumber))
    } catch (err) {
      toast({ title: errorMessage(err), status: 'error' })
    } finally {
      setBusy(false)
    }
  }

  const isTamil = book?.source_language === 'ta'

  useEffect(() => {
    if (!isTamil) return
    api
      .lexicon(bookId)
      .then((result) => setLexicon(buildLexicon(result.words)))
      .catch(() => {
        // Without the word list, typing still works with the spelling rules alone.
      })
  }, [bookId, isTamil])

  const saveTanglish = (enabled: boolean) => {
    setTanglish(enabled)
    try {
      window.localStorage.setItem(TANGLISH_SETTING, enabled ? '1' : '0')
    } catch {
      // The choice just is not remembered.
    }
  }

  /** After a space, comma, Enter... turn the English-letter word just typed into Tamil (undoable with Ctrl+Z). */
  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (!isTamil || !tanglish || event.nativeEvent.isComposing || event.ctrlKey || event.metaKey || event.altKey) return
    if (!TANGLISH_TRIGGERS.has(event.key)) return
    const area = event.currentTarget
    if (area.selectionStart !== area.selectionEnd) return
    const caret = area.selectionStart
    const match = /([A-Za-z]{2,})$/.exec(area.value.slice(0, caret))
    if (match === null) return
    const start = caret - match[1].length
    if (start > 0 && /[A-Za-z0-9]/.test(area.value.charAt(start - 1))) return // part of a longer code such as abc12def
    event.preventDefault()
    area.setSelectionRange(start, caret)
    const typed = event.key === 'Enter' ? '\n' : event.key
    document.execCommand('insertText', false, convertWord(match[1], lexicon) + typed)
  }

  const imageUrl = useMemo(
    () =>
      detail?.has_image
        ? api.pageImageUrl(bookId, detail.page_number, `${detail.ocr_confidence ?? 0}-${detail.ocr_text.length}`)
        : null,
    [bookId, detail],
  )

  if (bookError !== null) {
    return (
      <Alert status="error">
        <AlertIcon />
        {bookError}
      </Alert>
    )
  }
  if (book === null || status === null) return <Spinner />

  const counts = status.review_counts
  const read = (status.page_counts.done ?? 0) as number
  if (read === 0) {
    return (
      <Alert status="info">
        <AlertIcon />
        No pages have been read yet.
        <Button as={RouterLink} to={`/books/${bookId}/ocr`} size="sm" ml={3}>
          Read pages
        </Button>
      </Alert>
    )
  }

  return (
    <Box>
      <Flex justify="space-between" align="start" mb={3} wrap="wrap" gap={3}>
        <Box>
          <Heading size="lg" fontFamily="tamil">
            {book.title}
          </Heading>
          <Text color="gray.600">Check and correct the text</Text>
        </Box>
        <Button as={RouterLink} to={`/books/${bookId}/ocr`} variant="outline" size="sm">
          ← Read pages
        </Button>
      </Flex>

      <SimpleGrid columns={{ base: 2, md: 5 }} spacing={3} mb={3}>
        <Stat bg="white" borderWidth="1px" borderRadius="md" p={3}>
          <StatLabel>Pages read</StatLabel>
          <StatNumber>
            {read} / {book.page_count}
          </StatNumber>
        </Stat>
        <Stat bg="white" borderWidth="1px" borderRadius="md" p={3}>
          <StatLabel>Not checked yet</StatLabel>
          <StatNumber>{counts.pending}</StatNumber>
        </Stat>
        <Stat bg="white" borderWidth="1px" borderRadius="md" p={3}>
          <StatLabel>Awaiting approval</StatLabel>
          <StatNumber>{counts.corrected}</StatNumber>
        </Stat>
        <Stat bg="white" borderWidth="1px" borderRadius="md" p={3}>
          <StatLabel>Approved</StatLabel>
          <StatNumber>{counts.approved}</StatNumber>
        </Stat>
        <Stat bg="white" borderWidth="1px" borderRadius="md" p={3}>
          <StatLabel>OCR accuracy</StatLabel>
          <StatNumber>
            {status.accuracy.error_rate === null ? '—' : `${Math.round((1 - status.accuracy.error_rate) * 100)}%`}
          </StatNumber>
          <StatHelpText mb={0}>
            {status.accuracy.pages === 0
              ? 'Shown once you approve pages'
              : `measured on ${status.accuracy.pages} approved page${status.accuracy.pages === 1 ? '' : 's'}`}
          </StatHelpText>
          {Object.entries(status.accuracy.by_engine).length > 1 &&
            Object.entries(status.accuracy.by_engine).map(([name, acc]) => (
              <Text key={name} fontSize="xs" color="gray.600">
                {ENGINE_LABELS[name] ?? name}:{' '}
                {acc.error_rate === null ? '—' : `${Math.round((1 - acc.error_rate) * 100)}%`} ({acc.pages})
              </Text>
            ))}
        </Stat>
      </SimpleGrid>
      <Progress value={(counts.approved / book.page_count) * 100} colorScheme="green" borderRadius="md" mb={3} />

      <Flex wrap="wrap" gap={1} mb={4} maxH="96px" overflowY="auto" aria-label="Pages">
        {pages.map((p) => (
          <Button
            key={p.page_number}
            size="xs"
            minW="34px"
            colorScheme={CHIP_COLORS[p.review_status]}
            variant={p.page_number === pageNumber ? 'solid' : p.ocr_status === 'done' ? 'outline' : 'ghost'}
            isDisabled={p.ocr_status !== 'done'}
            onClick={() => void goTo(p.page_number)}
          >
            {p.page_number}
          </Button>
        ))}
      </Flex>

      <Accordion allowToggle mb={4}>
        <AccordionItem bg="white" borderWidth="1px" borderRadius="md">
          <AccordionButton>
            <Box flex="1" textAlign="left">
              Search the book or download the text
            </Box>
            <AccordionIcon />
          </AccordionButton>
          <AccordionPanel>
            <Flex gap={2} mb={3}>
              <Input
                placeholder="Find words in the book"
                value={query}
                fontFamily="tamil"
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => e.key === 'Enter' && void doSearch()}
              />
              <Button onClick={() => void doSearch()}>Search</Button>
            </Flex>
            {hits !== null && hits.length === 0 && <Text>Nothing found.</Text>}
            <VStack align="stretch" spacing={1} mb={3}>
              {hits?.map((hit) => (
                <Button
                  key={hit.page_number}
                  variant="ghost"
                  justifyContent="start"
                  fontFamily="tamil"
                  fontWeight={400}
                  onClick={() => void goTo(hit.page_number)}
                >
                  Page {hit.page_number}: …{hit.snippet}…
                </Button>
              ))}
            </VStack>
            <Flex gap={4} align="center">
              <Checkbox isChecked={approvedOnly} onChange={(e) => setApprovedOnly(e.target.checked)}>
                Only approved pages
              </Checkbox>
              <Button as="a" href={api.exportUrl(bookId, approvedOnly)} size="sm">
                Download corrected text (.txt)
              </Button>
            </Flex>
          </AccordionPanel>
        </AccordionItem>
        <AccordionItem bg="white" borderWidth="1px" borderRadius="md" mt={2}>
          <AccordionButton>
            <Box flex="1" textAlign="left">
              Approve many pages at once
            </Box>
            <AccordionIcon />
          </AccordionButton>
          <AccordionPanel>
            <Text fontSize="sm" color="gray.600" mb={3}>
              Use this after you have checked the pages. Pages are only approved when you press a button here; your
              corrections are kept, and pages that have not been read are skipped.
            </Text>
            <Flex gap={4} wrap="wrap" align="end">
              <FormControl w="120px">
                <FormLabel>From page</FormLabel>
                <NumberInput min={1} max={lastBookPage} value={bulkFrom} onChange={(_, n) => setBulkFrom(n || 1)}>
                  <NumberInputField />
                </NumberInput>
              </FormControl>
              <FormControl w="120px">
                <FormLabel>To page</FormLabel>
                <NumberInput min={1} max={lastBookPage} value={bulkTo} onChange={(_, n) => setBulkTo(n || 1)}>
                  <NumberInputField />
                </NumberInput>
              </FormControl>
              <Button colorScheme="green" isLoading={busy} onClick={() => void approveMany(bulkFrom, bulkTo)}>
                Approve these pages
              </Button>
              <Button variant="outline" isLoading={busy} onClick={() => void approveMany(1, lastBookPage)}>
                Approve all pages
              </Button>
            </Flex>
          </AccordionPanel>
        </AccordionItem>
      </Accordion>

      <Flex align="center" gap={3} mb={3} wrap="wrap">
        <Button size="sm" onClick={() => void goTo(pageNumber - 1)} isDisabled={pageNumber <= 1}>
          ◀ Previous
        </Button>
        <Text fontWeight={600}>
          Page {pageNumber} of {pageCount}
        </Text>
        <Button size="sm" onClick={() => void goTo(pageNumber + 1)} isDisabled={pageNumber >= pageCount}>
          Next ▶
        </Button>
        {detail !== null && <ReviewStatusBadge status={detail.review_status} />}
        {dirty && <Text color="orange.600">You have unsaved changes</Text>}
      </Flex>

      {detail === null ? (
        <Spinner />
      ) : detail.ocr_status !== 'done' ? (
        <Alert status="warning">
          <AlertIcon />
          Page {pageNumber} has not been read yet. Go to “Read pages” to read it.
        </Alert>
      ) : (
        <SimpleGrid columns={{ base: 1, lg: 2 }} spacing={5} alignItems="start">
          <Box bg="white" borderWidth="1px" borderRadius="lg" p={2} maxH="80vh" overflow="auto">
            {imageUrl !== null ? (
              <Image src={imageUrl} alt={`Scanned page ${pageNumber}`} w="100%" />
            ) : (
              <Text p={4}>The page image is missing.</Text>
            )}
          </Box>
          <Box maxW="794px" w="100%" mx="auto">
            {isTamil && (
              <Flex align="center" gap={3} mb={2} wrap="wrap">
                <FormControl display="flex" alignItems="center" w="auto">
                  <Switch id="tanglish" isChecked={tanglish} onChange={(e) => saveTanglish(e.target.checked)} mr={2} />
                  <FormLabel htmlFor="tanglish" mb={0}>
                    Type Tamil with English letters
                  </FormLabel>
                </FormControl>
                <Button size="xs" variant="outline" onClick={() => setDraft(convertText(draft, lexicon))}>
                  Convert the English words on this page now
                </Button>
                <Text fontSize="sm" color="gray.600" w="100%">
                  Type <b>vanakkam</b> and press space: வணக்கம். The spellings used in your book are preferred. A capital
                  letter in the middle of a word means that exact letter (N = ண, L = ள, R = ற). Ctrl+Z undoes a
                  conversion.
                </Text>
              </Flex>
            )}
            {/* A4 sheet (210 x 297 mm): margins are percentages of the width so it scales with the screen. */}
            <Flex
              direction="column"
              bg="white"
              boxShadow="lg"
              borderWidth="1px"
              borderColor="gray.300"
              aspectRatio="210 / 297"
              px="10%"
              py="9%"
            >
              <Textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={handleKeyDown}
                flex="1"
                minH={0}
                p={0}
                border="none"
                resize="none"
                bg="transparent"
                fontFamily="tamil"
                fontSize="clamp(15px, 1.45vw, 20px)"
                lineHeight="2"
                spellCheck={false}
                _focusVisible={{ boxShadow: 'none' }}
                aria-label="Text of the page"
              />
            </Flex>
            {detail.ocr_confidence !== null && (
              <Text fontSize="sm" color="gray.600" mt={1}>
                {ENGINE_LABELS[detail.ocr_engine ?? 'tesseract'] ?? 'Fast'} reading · OCR confidence {Math.round(detail.ocr_confidence)}% (only a hint, always check the text yourself)
              </Text>
            )}
            <Flex gap={3} mt={3} wrap="wrap">
              <Button onClick={save} isLoading={busy} isDisabled={!dirty}>
                Save
              </Button>
              <Button colorScheme="green" onClick={saveAndApprove} isLoading={busy}>
                Save and approve
              </Button>
              <Button
                variant="outline"
                onClick={restore}
                isDisabled={busy || (detail.corrected_text === null && detail.review_status === 'pending')}
              >
                Back to original
              </Button>
            </Flex>
            {detail.review_status === 'approved' && (
              <Alert status="success" mt={3}>
                <AlertIcon />
                This page is approved. If you change the text, it will need approval again.
              </Alert>
            )}
            {detail.corrected_text !== null && (
              <Accordion allowToggle mt={3}>
                <AccordionItem borderWidth="1px" borderRadius="md" bg="white">
                  <AccordionButton>
                    <Box flex="1" textAlign="left">
                      Show the original OCR text
                    </Box>
                    <AccordionIcon />
                  </AccordionButton>
                  <AccordionPanel>
                    <Text whiteSpace="pre-wrap" fontFamily="tamil" fontSize="18px" lineHeight="2">
                      {detail.ocr_text}
                    </Text>
                  </AccordionPanel>
                </AccordionItem>
              </Accordion>
            )}
          </Box>
        </SimpleGrid>
      )}
    </Box>
  )
}
