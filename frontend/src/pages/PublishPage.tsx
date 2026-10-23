import { useCallback, useEffect, useState } from 'react'
import {
  Alert,
  AlertDescription,
  AlertIcon,
  Badge,
  Box,
  Button,
  Checkbox,
  Flex,
  Heading,
  Radio,
  RadioGroup,
  Select,
  Spinner,
  Stack,
  Text,
  useToast,
} from '@chakra-ui/react'
import { Link as RouterLink, useParams } from 'react-router-dom'
import { api } from '../api'
import { errorMessage, useAsync } from '../hooks/useAsync'
import type { ExportItem, ExportKind, Language, PublishStatus } from '../types'

const POLL_MS = 1500

function formatSize(bytes: number | null): string {
  if (bytes === null) return ''
  return bytes > 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(bytes / 1024))} KB`
}

export default function PublishPage() {
  const bookId = Number(useParams().bookId)
  const toast = useToast()
  const loadBook = useCallback(() => api.book(bookId), [bookId])
  const { data: book, error: bookError } = useAsync(loadBook)

  const [status, setStatus] = useState<PublishStatus | null>(null)
  const [items, setItems] = useState<ExportItem[]>([])
  const [languages, setLanguages] = useState<Language[]>([])
  const [kind, setKind] = useState<ExportKind>('source')
  const [language, setLanguage] = useState('')
  const [toc, setToc] = useState(true)
  const [pageRefs, setPageRefs] = useState(false)
  const [numbered, setNumbered] = useState(true)
  const [creating, setCreating] = useState(false)

  const refresh = useCallback(async () => {
    try {
      const [state, list] = await Promise.all([api.publishing(bookId), api.exports(bookId)])
      setStatus(state)
      setItems(list)
    } catch (err) {
      toast({ title: errorMessage(err), status: 'error', id: 'publish-error' })
    }
  }, [bookId, toast])

  useEffect(() => {
    void refresh()
    api
      .languages()
      .then(setLanguages)
      .catch((err: unknown) => toast({ title: errorMessage(err), status: 'error' }))
  }, [refresh, toast])

  const busy = items.some((item) => item.status === 'processing') || (status?.running ?? false)
  useEffect(() => {
    if (!busy) return
    const timer = window.setInterval(() => void refresh(), POLL_MS)
    return () => window.clearInterval(timer)
  }, [busy, refresh])

  // Keep a sensible language selected.
  useEffect(() => {
    if (status !== null && (language === '' || !status.targets.includes(language))) setLanguage(status.targets[0] ?? '')
  }, [status, language])

  const name = (code: string): string => languages.find((l) => l.code === code)?.name ?? code

  const create = async (sample: boolean) => {
    if (status === null) return
    setCreating(true)
    try {
      const chosen = kind === 'target' || kind === 'bilingual' ? [language] : kind === 'multilingual' ? status.targets : []
      await api.createExport(bookId, {
        kind,
        languages: chosen,
        toc,
        page_references: kind === 'source' ? pageRefs : false,
        sample,
        numbered_paragraphs: numbered,
      })
      toast({ title: sample ? 'Creating the sample…' : 'Creating the PDF…', status: 'info', duration: 2000 })
      await refresh()
    } catch (err) {
      toast({ title: errorMessage(err), status: 'error', duration: 12000, isClosable: true })
    } finally {
      setCreating(false)
    }
  }

  const remove = async (item: ExportItem) => {
    if (!window.confirm('Delete this PDF? The book itself is not affected.')) return
    try {
      await api.deleteExport(bookId, item.id)
      await refresh()
    } catch (err) {
      toast({ title: errorMessage(err), status: 'error' })
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

  const selected = (): { ready: boolean; problems: string[] } => {
    const source = status.source
    const target = status.languages[language]
    if (kind === 'source') return source
    if (kind === 'target') return target ?? { ready: false, problems: ['Choose a language on the Translate tab first.'] }
    if (kind === 'bilingual') {
      if (target === undefined) return { ready: false, problems: ['Choose a language on the Translate tab first.'] }
      return { ready: source.ready && target.ready, problems: [...source.problems, ...target.problems] }
    }
    const all = status.targets.map((code) => status.languages[code])
    if (all.length === 0) return { ready: false, problems: ['Choose languages on the Translate tab first.'] }
    return {
      ready: source.ready && all.every((l) => l.ready),
      problems: [...source.problems, ...all.flatMap((l) => l.problems)],
    }
  }
  const readiness = selected()
  const needsLanguage = kind === 'target' || kind === 'bilingual'

  const label = (item: ExportItem): string => {
    const langs = item.languages.map(name).join(', ')
    const base: Record<ExportKind, string> = {
      source: 'Tamil book',
      target: `${langs} translation`,
      bilingual: `Tamil and ${langs}`,
      multilingual: `Tamil and ${langs}`,
    }
    return base[item.kind]
  }

  return (
    <Box maxW="900px">
      <Heading size="lg" mb={1} fontFamily="tamil">
        {book.title}
      </Heading>
      <Text color="gray.600" mb={4}>
        Make PDFs of the book. Only approved text is ever published; nothing unreviewed can slip in.
      </Text>

      {status.unassigned.length > 0 && (
        <Alert status="warning" mb={4}>
          <AlertIcon />
          <AlertDescription>
            Pages {status.unassigned.map(([a, b]) => (a === b ? a : `${a}–${b}`)).join(', ')} are not in any chapter, so
            they are not published. Add them to a chapter on the Chapters tab.
          </AlertDescription>
        </Alert>
      )}

      <Box bg="white" borderWidth="1px" borderRadius="lg" p={5} mb={5}>
        <Heading size="sm" mb={3}>
          What do you want to publish?
        </Heading>
        <RadioGroup value={kind} onChange={(value) => setKind(value as ExportKind)}>
          <Stack spacing={3}>
            <Radio value="source">The Tamil book</Radio>
            <Radio value="target">One translation on its own</Radio>
            <Radio value="bilingual">Tamil and one translation together (Tamil first, translation below)</Radio>
            <Radio value="multilingual">Tamil and all chosen languages together</Radio>
          </Stack>
        </RadioGroup>

        {needsLanguage && (
          <Flex mt={4} align="center" gap={3}>
            <Text>Language:</Text>
            <Select maxW="260px" value={language} onChange={(e) => setLanguage(e.target.value)}>
              {status.targets.map((code) => (
                <option key={code} value={code}>
                  {name(code)}
                </option>
              ))}
            </Select>
          </Flex>
        )}
        {kind === 'multilingual' && status.targets.length > 0 && (
          <Text mt={3} fontSize="sm" color="gray.600">
            Includes: Tamil, {status.targets.map(name).join(', ')}
          </Text>
        )}

        <Stack mt={4} spacing={2}>
          <Checkbox isChecked={toc} onChange={(e) => setToc(e.target.checked)}>
            Include a contents page
          </Checkbox>
          <Checkbox isChecked={numbered} onChange={(e) => setNumbered(e.target.checked)}>
            Start a new paragraph at each numbered item (1. 2. 3. or அ) ஆ) இ))
          </Checkbox>
          {kind === 'source' && (
            <Checkbox isChecked={pageRefs} onChange={(e) => setPageRefs(e.target.checked)}>
              Show the original scanned page numbers in small grey text
            </Checkbox>
          )}
        </Stack>

        {readiness.ready ? (
          <Alert status="success" mt={4}>
            <AlertIcon />
            Everything for this is approved and ready.
          </Alert>
        ) : (
          <Alert status="warning" mt={4} alignItems="start">
            <AlertIcon />
            <Box>
              <AlertDescription>
                <Text fontWeight={600}>Not ready yet. Only approved text is published:</Text>
                <Box as="ul" pl={5} mt={1}>
                  {readiness.problems.slice(0, 8).map((problem) => (
                    <li key={problem}>{problem}</li>
                  ))}
                  {readiness.problems.length > 8 && <li>… and {readiness.problems.length - 8} more</li>}
                </Box>
                <Flex gap={3} mt={2} wrap="wrap">
                  <Button as={RouterLink} to={`/books/${bookId}/review`} size="xs" variant="outline">
                    Check and correct pages
                  </Button>
                  <Button as={RouterLink} to={`/books/${bookId}/translate`} size="xs" variant="outline">
                    Translate
                  </Button>
                  <Button as={RouterLink} to={`/books/${bookId}/translation-review`} size="xs" variant="outline">
                    Review translations
                  </Button>
                </Flex>
              </AlertDescription>
            </Box>
          </Alert>
        )}

        <Flex gap={3} mt={4} wrap="wrap">
          <Button
            variant="outline"
            onClick={() => void create(true)}
            isLoading={creating}
            isDisabled={busy || (!readiness.ready && !sampleCanRun(status, kind, language))}
          >
            Preview a sample first
          </Button>
          <Button
            colorScheme="blue"
            onClick={() => void create(false)}
            isLoading={creating}
            isDisabled={busy || !readiness.ready || (needsLanguage && language === '')}
          >
            Create the PDF
          </Button>
        </Flex>
        <Text fontSize="sm" color="gray.600" mt={2}>
          A sample has only the cover, the first chapter&apos;s heading and a few paragraphs, so you can check the look
          and the fonts quickly. A whole book can take a minute or two.
        </Text>
      </Box>

      <Heading size="sm" mb={3}>
        Your PDFs
      </Heading>
      {items.length === 0 && <Text color="gray.600">No PDFs yet.</Text>}
      <Stack spacing={3}>
        {items.map((item) => (
          <Flex key={item.id} bg="white" borderWidth="1px" borderRadius="lg" p={4} align="center" gap={3} wrap="wrap">
            <Box flex="1" minW="220px">
              <Flex gap={2} align="center" wrap="wrap">
                <Text fontWeight={600}>{label(item)}</Text>
                {item.sample && <Badge colorScheme="orange">Sample</Badge>}
                {item.status === 'processing' && (
                  <Badge colorScheme="blue">
                    <Spinner size="xs" mr={1} />
                    Creating…
                  </Badge>
                )}
                {item.status === 'failed' && <Badge colorScheme="red">Failed</Badge>}
              </Flex>
              <Text fontSize="sm" color="gray.600">
                {item.created_at}
                {item.page_count !== null ? ` · ${item.page_count} pages` : ''}
                {item.size_bytes !== null ? ` · ${formatSize(item.size_bytes)}` : ''}
                {!item.toc && item.status === 'done' ? ' · no contents page' : ''}
              </Text>
              {item.error !== null && (
                <Text fontSize="sm" color="red.600">
                  {item.error}
                </Text>
              )}
            </Box>
            {item.status === 'done' && (
              <>
                <Button
                  as="a"
                  href={api.exportFileUrl(bookId, item.id, false)}
                  target="_blank"
                  rel="noreferrer"
                  size="sm"
                  colorScheme="blue"
                >
                  Open
                </Button>
                <Button as="a" href={api.exportFileUrl(bookId, item.id, true)} size="sm" variant="outline">
                  Download
                </Button>
              </>
            )}
            <Button size="sm" variant="ghost" colorScheme="red" onClick={() => void remove(item)} isDisabled={item.status === 'processing'}>
              Delete
            </Button>
          </Flex>
        ))}
      </Stack>
    </Box>
  )
}

/** A sample only needs the first chapter, so it may be possible even when the whole book is not ready. */
function sampleCanRun(status: PublishStatus, kind: ExportKind, language: string): boolean {
  if (status.chapters === 0) return false
  const sourceNeeded = kind !== 'target'
  const codes = kind === 'multilingual' ? status.targets : language === '' ? [] : [language]
  if (kind !== 'source' && codes.length === 0) return false
  // The server decides; the button stays available when the problems are not only about the first chapter.
  return sourceNeeded || codes.length > 0
}
