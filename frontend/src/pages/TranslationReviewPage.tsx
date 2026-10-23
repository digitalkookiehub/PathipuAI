import { useCallback, useEffect, useState } from 'react'
import {
  Accordion,
  AccordionButton,
  AccordionIcon,
  AccordionItem,
  AccordionPanel,
  Alert,
  AlertDescription,
  AlertIcon,
  Badge,
  Box,
  Button,
  Flex,
  FormControl,
  FormLabel,
  Heading,
  Progress,
  Select,
  SimpleGrid,
  Spinner,
  Text,
  Textarea,
  useToast,
} from '@chakra-ui/react'
import { Link as RouterLink, useParams, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { errorMessage, useAsync } from '../hooks/useAsync'
import type { Language, TranslationChunk, TranslationOverview } from '../types'

const STATUS_LABELS: Record<string, string> = {
  not_started: 'Not translated',
  processing: 'Translating',
  awaiting_approval: 'Awaiting approval',
  approved: 'Approved',
  failed: 'Failed',
}
const STATUS_COLORS: Record<string, string> = {
  not_started: 'gray',
  processing: 'blue',
  awaiting_approval: 'purple',
  approved: 'green',
  failed: 'red',
}

function textOf(chunk: TranslationChunk): string {
  return chunk.edited_text ?? chunk.translated_text ?? ''
}

/** A sheet of paper in A4 proportions (210 x 297 mm); margins are percentages so it scales with the screen. */
function Sheet({ children }: { children: React.ReactNode }) {
  return (
    <Flex
      direction="column"
      bg="white"
      boxShadow="lg"
      borderWidth="1px"
      borderColor="gray.300"
      aspectRatio="210 / 297"
      px="9%"
      py="8%"
    >
      {children}
    </Flex>
  )
}

export default function TranslationReviewPage() {
  const bookId = Number(useParams().bookId)
  const [params, setParams] = useSearchParams()
  const toast = useToast()

  const loadBook = useCallback(() => api.book(bookId), [bookId])
  const { data: book, error: bookError } = useAsync(loadBook)
  const [overview, setOverview] = useState<TranslationOverview | null>(null)
  const [languages, setLanguages] = useState<Language[]>([])
  const [chunks, setChunks] = useState<TranslationChunk[] | null>(null)
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)

  const chapterId = Number(params.get('chapter')) || null
  const language = params.get('lang')
  const requested = Math.max(0, Number(params.get('part')) || 0)

  const refreshOverview = useCallback(async () => {
    setOverview(await api.translation(bookId))
  }, [bookId])

  useEffect(() => {
    refreshOverview().catch((err: unknown) => toast({ title: errorMessage(err), status: 'error' }))
    api
      .targets(bookId)
      .then((result) => setLanguages(result.available))
      .catch((err: unknown) => toast({ title: errorMessage(err), status: 'error' }))
  }, [bookId, refreshOverview, toast])

  // Pick a sensible chapter and language to start with.
  useEffect(() => {
    if (overview === null || (chapterId !== null && language !== null)) return
    for (const chapter of overview.chapters) {
      const code = overview.targets.find((c) => (chapter.languages[c]?.translated ?? 0) > 0)
      if (code !== undefined) {
        setParams({ chapter: String(chapter.id), lang: code }, { replace: true })
        return
      }
    }
  }, [overview, chapterId, language, setParams])

  useEffect(() => {
    if (chapterId === null || language === null) return
    let cancelled = false
    setChunks(null)
    api
      .translationChunks(bookId, chapterId, language)
      .then((result) => {
        if (!cancelled) setChunks(result)
      })
      .catch((err: unknown) => {
        if (!cancelled) toast({ title: errorMessage(err), status: 'error' })
      })
    return () => {
      cancelled = true
    }
  }, [bookId, chapterId, language, toast])

  const position = chunks === null ? 0 : Math.min(requested, Math.max(chunks.length - 1, 0))
  const current = chunks !== null && chunks.length > 0 ? chunks[position] : null
  const savedText = current === null ? '' : textOf(current)
  const dirty = current !== null && draft !== savedText
  const editable = current !== null && ['awaiting_approval', 'approved'].includes(current.status)

  useEffect(() => {
    setDraft(savedText)
  }, [savedText, chapterId, language, position])

  const replaceChunk = (updated: TranslationChunk) =>
    setChunks((list) => list?.map((c) => (c.chunk_index === updated.chunk_index ? updated : c)) ?? null)

  /** Save unsaved edits (never approves) before moving elsewhere. */
  const saveIfDirty = async (): Promise<boolean> => {
    if (!dirty || current === null || chapterId === null || language === null) return true
    try {
      replaceChunk(await api.editChunk(bookId, chapterId, language, current.chunk_index, draft))
      await refreshOverview()
      return true
    } catch (err) {
      toast({ title: errorMessage(err), status: 'error' })
      return false
    }
  }

  const goTo = async (target: number) => {
    if (chunks === null || target < 0 || target >= chunks.length || target === position) return
    if (!(await saveIfDirty())) return
    const next = new URLSearchParams(params)
    next.set('part', String(target))
    setParams(next)
  }

  const run = async (action: () => Promise<TranslationChunk>, success: string, after?: () => void) => {
    setBusy(true)
    try {
      replaceChunk(await action())
      toast({ title: success, status: 'success', duration: 1500 })
      await refreshOverview()
      after?.()
    } catch (err) {
      toast({ title: errorMessage(err), status: 'error' })
    } finally {
      setBusy(false)
    }
  }

  const save = () => {
    if (current === null || chapterId === null || language === null) return
    void run(() => api.editChunk(bookId, chapterId, language, current.chunk_index, draft), 'Saved.')
  }

  const saveAndApprove = () => {
    if (current === null || chapterId === null || language === null) return
    void run(
      async () => {
        if (dirty) await api.editChunk(bookId, chapterId, language, current.chunk_index, draft)
        return api.approveChunk(bookId, chapterId, language, current.chunk_index)
      },
      'Approved.',
      () => {
        if (chunks !== null && position + 1 < chunks.length) {
          const next = new URLSearchParams(params)
          next.set('part', String(position + 1))
          setParams(next)
        }
      },
    )
  }

  const restore = () => {
    if (current === null || chapterId === null || language === null) return
    void run(() => api.restoreChunk(bookId, chapterId, language, current.chunk_index), 'Back to the machine translation.')
  }

  const approveAll = async () => {
    if (chapterId === null || language === null) return
    if (!window.confirm('Approve every part of this chapter that can be approved, without reading each one?')) return
    if (!(await saveIfDirty())) return
    setBusy(true)
    try {
      const result = await api.approveAllChunks(bookId, chapterId, language)
      const skipped = result.skipped > 0 ? ` ${result.skipped} could not be approved (placeholder, changed or failed).` : ''
      toast({ title: `${result.approved} part(s) approved.${skipped}`, status: result.skipped > 0 ? 'warning' : 'success' })
      setChunks(await api.translationChunks(bookId, chapterId, language))
      await refreshOverview()
    } catch (err) {
      toast({ title: errorMessage(err), status: 'error' })
    } finally {
      setBusy(false)
    }
  }

  const choose = async (nextChapter: number | null, nextLanguage: string | null) => {
    if (!(await saveIfDirty())) return
    const next = new URLSearchParams()
    if (nextChapter !== null) next.set('chapter', String(nextChapter))
    if (nextLanguage !== null) next.set('lang', nextLanguage)
    setParams(next)
  }

  if (bookError !== null) {
    return (
      <Alert status="error">
        <AlertIcon />
        {bookError}
      </Alert>
    )
  }
  if (book === null || overview === null) return <Spinner />

  const translatedChapters = overview.chapters.filter((chapter) =>
    Object.values(chapter.languages).some((l) => l.translated > 0),
  )
  if (translatedChapters.length === 0) {
    return (
      <Alert status="info">
        <AlertIcon />
        <AlertDescription>
          Nothing has been translated yet. Translate a chapter first.
          <Button as={RouterLink} to={`/books/${bookId}/translate`} size="sm" ml={3}>
            Go to Translate
          </Button>
        </AlertDescription>
      </Alert>
    )
  }

  const chapter = overview.chapters.find((c) => c.id === chapterId)
  const progress = chapter !== undefined && language !== null ? chapter.languages[language] : undefined
  const languageName = (code: string): string => languages.find((l) => l.code === code)?.name ?? code
  const canApprove =
    current !== null &&
    editable &&
    current.provider !== 'mock' &&
    !current.outdated &&
    !current.untranslated &&
    (dirty ? draft.trim() !== '' : true)

  return (
    <Box>
      <Heading size="lg" mb={1} fontFamily="tamil">
        {book.title}
      </Heading>
      <Text color="gray.600" mb={4}>
        Read the translation next to the Tamil, correct it, then approve it. Only approved translations are published.
      </Text>

      <Flex gap={4} wrap="wrap" mb={3} align="end">
        <FormControl maxW="320px">
          <FormLabel>Chapter</FormLabel>
          <Select
            value={chapterId ?? ''}
            onChange={(e) => void choose(Number(e.target.value), language)}
            fontFamily="tamil"
          >
            {translatedChapters.map((c) => (
              <option key={c.id} value={c.id}>
                {c.order_index}. {c.title}
              </option>
            ))}
          </Select>
        </FormControl>
        <FormControl maxW="220px">
          <FormLabel>Language</FormLabel>
          <Select value={language ?? ''} onChange={(e) => void choose(chapterId, e.target.value)}>
            {overview.targets.map((code) => (
              <option key={code} value={code}>
                {languageName(code)}
              </option>
            ))}
          </Select>
        </FormControl>
        {progress !== undefined && progress.total > 0 && (
          <Box flex="1" minW="220px">
            <Text fontSize="sm" mb={1}>
              {progress.approved} of {progress.total} parts approved
            </Text>
            <Progress value={(progress.approved / progress.total) * 100} colorScheme="green" borderRadius="md" />
          </Box>
        )}
        <Button variant="outline" onClick={() => void approveAll()} isLoading={busy} isDisabled={current === null}>
          Approve all parts of this chapter
        </Button>
      </Flex>

      {chunks === null && <Spinner />}
      {chunks !== null && chunks.length === 0 && (
        <Alert status="info">
          <AlertIcon />
          This chapter has not been translated into {language !== null ? languageName(language) : 'this language'} yet.
        </Alert>
      )}

      {chunks !== null && chunks.length > 0 && current !== null && (
        <>
          <Flex wrap="wrap" gap={1} mb={3} aria-label="Parts">
            {chunks.map((c, index) => (
              <Button
                key={c.chunk_index}
                size="xs"
                minW="34px"
                colorScheme={STATUS_COLORS[c.status] ?? 'gray'}
                variant={index === position ? 'solid' : 'outline'}
                onClick={() => void goTo(index)}
              >
                {index === 0 ? 'H' : index}
              </Button>
            ))}
          </Flex>

          <Flex align="center" gap={3} mb={3} wrap="wrap">
            <Button size="sm" onClick={() => void goTo(position - 1)} isDisabled={position === 0}>
              ◀ Previous
            </Button>
            <Text fontWeight={600}>
              {position === 0 ? 'Chapter heading' : `Part ${position}`} of {chunks.length - 1}
            </Text>
            <Button size="sm" onClick={() => void goTo(position + 1)} isDisabled={position >= chunks.length - 1}>
              Next ▶
            </Button>
            <Badge colorScheme={STATUS_COLORS[current.status] ?? 'gray'}>
              {STATUS_LABELS[current.status] ?? current.status}
            </Badge>
            {dirty && <Text color="orange.600">You have unsaved changes</Text>}
          </Flex>

          {current.provider === 'mock' && (
            <Alert status="warning" mb={3}>
              <AlertIcon />
              <AlertDescription>
                This is test-mode placeholder text, not a translation. Translate the chapter again with the real
                provider; placeholders cannot be approved.
              </AlertDescription>
            </Alert>
          )}
          {current.untranslated && (
            <Alert status="error" mb={3}>
              <AlertIcon />
              <AlertDescription>
                This part is not in {language !== null ? languageName(language) : 'the chosen language'}: it came back
                untranslated (still in the original language). It cannot be approved. Click “Translate again” on the
                Translate tab, or write the translation yourself.
              </AlertDescription>
            </Alert>
          )}
          {current.outdated && (
            <Alert status="warning" mb={3}>
              <AlertIcon />
              <AlertDescription>
                The Tamil text changed after this part was translated. Translate the chapter again before approving.
              </AlertDescription>
            </Alert>
          )}
          {current.status === 'failed' && (
            <Alert status="error" mb={3}>
              <AlertIcon />
              <AlertDescription>{current.error ?? 'This part could not be translated.'}</AlertDescription>
            </Alert>
          )}
          {current.notes !== null && (
            <Alert status="warning" mb={3}>
              <AlertIcon />
              <AlertDescription>
                Glossary check: {current.notes}
              </AlertDescription>
            </Alert>
          )}

          <SimpleGrid columns={{ base: 1, lg: 2 }} spacing={5} alignItems="start">
            <Box maxW="794px" w="100%" mx="auto">
              <Text fontSize="sm" color="gray.600" mb={1}>
                Tamil (approved)
              </Text>
              <Sheet>
                <Text whiteSpace="pre-wrap" overflowY="auto" fontFamily="tamil" fontSize="clamp(14px, 1.3vw, 18px)" lineHeight="2">
                  {current.source_text}
                </Text>
              </Sheet>
            </Box>
            <Box maxW="794px" w="100%" mx="auto">
              <Text fontSize="sm" color="gray.600" mb={1}>
                {language !== null ? languageName(language) : 'Translation'} (you can edit this)
              </Text>
              <Sheet>
                <Textarea
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  flex="1"
                  minH={0}
                  p={0}
                  border="none"
                  resize="none"
                  bg="transparent"
                  fontFamily="indic"
                  fontSize="clamp(14px, 1.3vw, 18px)"
                  lineHeight="2"
                  spellCheck={false}
                  isDisabled={!editable}
                  aria-label="Translation"
                  _focusVisible={{ boxShadow: 'none' }}
                />
              </Sheet>
              <Flex gap={3} mt={3} wrap="wrap">
                <Button onClick={save} isLoading={busy} isDisabled={!dirty || !editable}>
                  Save
                </Button>
                <Button colorScheme="green" onClick={saveAndApprove} isLoading={busy} isDisabled={!canApprove}>
                  Save and approve
                </Button>
                <Button
                  variant="outline"
                  onClick={restore}
                  isDisabled={busy || !editable || (current.edited_text === null && current.status !== 'approved')}
                >
                  Back to the machine translation
                </Button>
              </Flex>
              {current.status === 'approved' && (
                <Alert status="success" mt={3}>
                  <AlertIcon />
                  This part is approved. If you change it, it will need approval again.
                </Alert>
              )}
              {current.edited_text !== null && current.translated_text !== null && (
                <Accordion allowToggle mt={3}>
                  <AccordionItem borderWidth="1px" borderRadius="md" bg="white">
                    <AccordionButton>
                      <Box flex="1" textAlign="left">
                        Show the original machine translation
                      </Box>
                      <AccordionIcon />
                    </AccordionButton>
                    <AccordionPanel>
                      <Text whiteSpace="pre-wrap" fontFamily="indic" fontSize="17px" lineHeight="2">
                        {current.translated_text}
                      </Text>
                    </AccordionPanel>
                  </AccordionItem>
                </Accordion>
              )}
            </Box>
          </SimpleGrid>
        </>
      )}
    </Box>
  )
}
