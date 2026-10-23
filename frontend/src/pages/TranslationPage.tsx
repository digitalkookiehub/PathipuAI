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
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalHeader,
  ModalOverlay,
  Progress,
  SimpleGrid,
  Spinner,
  Stack,
  Text,
  useDisclosure,
  useToast,
} from '@chakra-ui/react'
import { Link as RouterLink, useParams } from 'react-router-dom'
import { api, ApiError } from '../api'
import { errorMessage, useAsync } from '../hooks/useAsync'
import type {
  ChapterProgress,
  LanguageProgress,
  TargetsResponse,
  TranslationChunk,
  TranslationOverview,
  TranslationStatus,
} from '../types'

const POLL_MS = 1500

const STATUS_LABELS: Record<TranslationStatus, string> = {
  not_started: 'Not started',
  in_progress: 'In progress',
  awaiting_approval: 'Awaiting approval',
  approved: 'Approved',
  failed: 'Failed',
}

const STATUS_COLORS: Record<TranslationStatus, string> = {
  not_started: 'gray',
  in_progress: 'blue',
  awaiting_approval: 'purple',
  approved: 'green',
  failed: 'red',
}

/** The button label for a chapter in one language, or null when there is nothing left to translate. */
function actionLabel(progress: LanguageProgress): string | null {
  if (progress.status === 'failed') return 'Retry the failed parts'
  if (progress.status === 'in_progress') return 'Continue translating'
  if (progress.status === 'not_started') return 'Translate'
  if (progress.outdated || progress.test_output || progress.untranslated > 0) return 'Translate again'
  return null
}

function LanguageCell({ name, progress }: { name: string; progress: LanguageProgress }) {
  return (
    <Box borderWidth="1px" borderRadius="md" p={3} bg="gray.50">
      <Flex justify="space-between" align="center" gap={2} wrap="wrap">
        <Text fontWeight={600}>{name}</Text>
        <Badge colorScheme={STATUS_COLORS[progress.status]}>{STATUS_LABELS[progress.status]}</Badge>
      </Flex>
      {progress.total > 0 && (
        <Text fontSize="sm" color="gray.600" mt={1}>
          {progress.translated} of {progress.total} parts translated · {progress.approved} approved
        </Text>
      )}
      {progress.untranslated > 0 && (
        <Text fontSize="sm" color="red.600" mt={1}>
          {progress.untranslated} part{progress.untranslated === 1 ? '' : 's'} came back in the wrong language (not
          translated). Click “Translate again”.
        </Text>
      )}
      {progress.test_output && (
        <Badge colorScheme="orange" mt={1} whiteSpace="normal">
          Test placeholders, not a real translation
        </Badge>
      )}
      {progress.outdated && (
        <Badge colorScheme="orange" mt={1}>
          Source text changed
        </Badge>
      )}
      {progress.notes > 0 && (
        <Text fontSize="sm" color="orange.600" mt={1}>
          {progress.notes} part{progress.notes === 1 ? '' : 's'} need a glossary check
        </Text>
      )}
      {progress.status === 'failed' && progress.error !== null && (
        <Text fontSize="sm" color="red.600" mt={1}>
          {progress.error}
        </Text>
      )}
    </Box>
  )
}

export default function TranslationPage() {
  const bookId = Number(useParams().bookId)
  const toast = useToast()
  const loadBook = useCallback(() => api.book(bookId), [bookId])
  const { data: book, error: bookError } = useAsync(loadBook)

  const [overview, setOverview] = useState<TranslationOverview | null>(null)
  const [targets, setTargets] = useState<TargetsResponse | null>(null)
  const [selected, setSelected] = useState<string[]>([])
  const [saving, setSaving] = useState(false)
  const [starting, setStarting] = useState(false)
  const [activeTask, setActiveTask] = useState<string | null>(null)
  const [preview, setPreview] = useState<{
    chapter: ChapterProgress
    language: string
    chunks: TranslationChunk[]
  } | null>(null)
  const { isOpen, onOpen, onClose } = useDisclosure()

  const refresh = useCallback(async () => {
    try {
      setOverview(await api.translation(bookId))
    } catch (err) {
      toast({ title: errorMessage(err), status: 'error', id: 'translation-error' })
    }
  }, [bookId, toast])

  useEffect(() => {
    void refresh()
    api
      .targets(bookId)
      .then((result) => {
        setTargets(result)
        setSelected(result.selected)
      })
      .catch((err: unknown) => toast({ title: errorMessage(err), status: 'error' }))
  }, [bookId, refresh, toast])

  const running = overview?.running ?? false
  useEffect(() => {
    if (!running) return
    const timer = window.setInterval(() => void refresh(), POLL_MS)
    return () => window.clearInterval(timer)
  }, [running, refresh])

  const languageName = (code: string): string => targets?.available.find((l) => l.code === code)?.name ?? code

  const toggle = (code: string, checked: boolean) =>
    setSelected((current) => (checked ? [...current, code] : current.filter((c) => c !== code)))

  const saveTargets = async () => {
    setSaving(true)
    try {
      const result = await api.setTargets(bookId, selected)
      setTargets(result)
      setSelected(result.selected)
      toast({ title: 'Languages saved.', status: 'success', duration: 1500 })
      await refresh()
    } catch (err) {
      toast({ title: errorMessage(err), status: 'error' })
    } finally {
      setSaving(false)
    }
  }

  /** Translate exactly one chapter into exactly one language. */
  const start = async (chapter: ChapterProgress, code: string, overwrite = false): Promise<void> => {
    setStarting(true)
    try {
      const result = await api.startTranslation(bookId, [chapter.id], [code], overwrite)
      if (result.status === 'nothing_to_do') {
        toast({ title: 'This is already translated. Nothing to do.', status: 'info' })
      } else {
        setActiveTask(`“${chapter.title}” into ${languageName(code)}`)
        toast({ title: `Translation started (${result.chunks} parts).`, status: 'success' })
      }
      await refresh()
    } catch (err) {
      if (err instanceof ApiError && err.status === 409 && !overwrite) {
        if (window.confirm(`${err.message}

Do you want to replace them?`)) {
          setStarting(false)
          return start(chapter, code, true)
        }
      } else {
        toast({ title: errorMessage(err), status: 'error' })
      }
    } finally {
      setStarting(false)
    }
  }

  const openPreview = async (chapter: ChapterProgress, language: string) => {
    try {
      setPreview({ chapter, language, chunks: await api.translationChunks(bookId, chapter.id, language) })
      onOpen()
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
  if (book === null || overview === null || targets === null) return <Spinner />

  const job = overview.job
  const jobDone = job ? job.completed + job.failed : 0
  const provider = overview.provider
  const savedSame = selected.length === targets.selected.length && selected.every((c) => targets.selected.includes(c))
  const hasTestOutput = overview.chapters.some((chapter) =>
    Object.values(chapter.languages).some((language) => language.test_output),
  )

  return (
    <Box maxW="1000px">
      <Heading size="lg" mb={1} fontFamily="tamil">
        {book.title}
      </Heading>
      <Text color="gray.600" mb={4}>
        Translate the approved text, chapter by chapter. Only approved pages are ever translated.
      </Text>

      {provider.is_test ? (
        <Alert status="warning" mb={4}>
          <AlertIcon />
          <AlertDescription>{provider.message}</AlertDescription>
        </Alert>
      ) : (
        !provider.ready && (
          <Alert status="error" mb={4}>
            <AlertIcon />
            <AlertDescription>{provider.message}</AlertDescription>
          </Alert>
        )
      )}
      {provider.ready && !provider.is_test && (
        <Text fontSize="sm" color="gray.600" mb={4}>
          Translating with {provider.label}.
        </Text>
      )}
      {provider.ready && !provider.is_test && hasTestOutput && (
        <Alert status="info" mb={4}>
          <AlertIcon />
          <AlertDescription>
            Some results below are test placeholders from test mode. Click “Translate again” on that language to
            replace them with real translations.
          </AlertDescription>
        </Alert>
      )}
      {overview.error !== null && (
        <Alert status="error" mb={4}>
          <AlertIcon />
          <AlertDescription>{overview.error}</AlertDescription>
        </Alert>
      )}

      <Box bg="white" borderWidth="1px" borderRadius="lg" p={4} mb={5}>
        <Heading size="sm" mb={3}>
          Translate into
        </Heading>
        <Flex gap={5} wrap="wrap" mb={3}>
          {targets.available.map((language) => (
            <Checkbox
              key={language.code}
              isChecked={selected.includes(language.code)}
              onChange={(e) => toggle(language.code, e.target.checked)}
            >
              {language.name}
            </Checkbox>
          ))}
        </Flex>
        <Button size="sm" colorScheme="blue" onClick={() => void saveTargets()} isLoading={saving} isDisabled={savedSame}>
          Save languages
        </Button>
      </Box>

      {running && job !== null && (
        <Box mb={5}>
          <Text mb={1}>
            Translating{activeTask !== null ? ` ${activeTask}` : ''}… {jobDone} of {job.total} parts
          </Text>
          <Progress value={job.total > 0 ? (jobDone / job.total) * 100 : 0} borderRadius="md" hasStripe isAnimated />
        </Box>
      )}

      <Heading size="sm" mb={1}>
        Chapters
      </Heading>
      <Text fontSize="sm" color="gray.600" mb={3}>
        Translate one chapter into one language at a time. Nothing is translated until you click its button.
      </Text>

      {overview.chapters.length === 0 && (
        <Alert status="info">
          <AlertIcon />
          Create chapters first (step 3). Translation works one chapter at a time.
        </Alert>
      )}
      {overview.targets.length === 0 && overview.chapters.length > 0 && (
        <Alert status="info" mb={3}>
          <AlertIcon />
          Choose at least one language above and save it.
        </Alert>
      )}

      <Stack spacing={4}>
        {overview.chapters.map((chapter) => (
          <Box key={chapter.id} bg="white" borderWidth="1px" borderRadius="lg" p={4}>
            <Flex justify="space-between" align="start" gap={3} wrap="wrap" mb={2}>
              <Box>
                <Heading size="sm" fontFamily="tamil">
                  {chapter.order_index}. {chapter.title}
                </Heading>
                <Text fontSize="sm" color="gray.600">
                  {chapter.approved_pages} of {chapter.page_count} pages approved
                </Text>
              </Box>
              {chapter.ready ? (
                <Badge colorScheme="green">Ready to translate</Badge>
              ) : (
                <Badge colorScheme="orange">
                  Approve pages {chapter.missing_pages.join(', ')}
                  {chapter.missing_pages.length >= 12 ? ' …' : ''} first
                </Badge>
              )}
            </Flex>
            {overview.targets.length > 0 && (
              <SimpleGrid columns={{ base: 1, md: 2 }} spacing={3}>
                {overview.targets.map((code) => {
                  const progress = chapter.languages[code]
                  return (
                    <Box key={code}>
                      <LanguageCell name={languageName(code)} progress={progress} />
                      {chapter.ready && actionLabel(progress) !== null && (
                        <Button
                          size="sm"
                          mt={2}
                          colorScheme="blue"
                          onClick={() => void start(chapter, code)}
                          isLoading={starting}
                          isDisabled={running || !provider.ready}
                        >
                          {actionLabel(progress)}
                        </Button>
                      )}
                      {progress.total > 0 && progress.translated > 0 && (
                        <Flex gap={4} mt={1}>
                          <Button
                            as={RouterLink}
                            to={`/books/${bookId}/translation-review?chapter=${chapter.id}&lang=${code}`}
                            size="xs"
                            variant="link"
                            colorScheme="blue"
                          >
                            Review and approve →
                          </Button>
                          <Button size="xs" variant="link" onClick={() => void openPreview(chapter, code)}>
                            Quick look
                          </Button>
                        </Flex>
                      )}
                    </Box>
                  )
                })}
              </SimpleGrid>
            )}
          </Box>
        ))}
      </Stack>

      <Modal isOpen={isOpen} onClose={onClose} size="4xl" scrollBehavior="inside">
        <ModalOverlay />
        <ModalContent>
          <ModalHeader>
            {preview?.chapter.title} · {preview !== null ? languageName(preview.language) : ''}
          </ModalHeader>
          <ModalCloseButton />
          <ModalBody pb={6}>
            {preview?.chunks.map((chunk) => (
              <Box key={chunk.chunk_index} mb={5}>
                {chunk.notes !== null && (
                  <Alert status="warning" mb={2}>
                    <AlertIcon />
                    <AlertDescription>{chunk.notes}</AlertDescription>
                  </Alert>
                )}
                {chunk.provider === 'mock' && (
                  <Badge colorScheme="orange" mb={1}>
                    Test placeholder
                  </Badge>
                )}
                <Text whiteSpace="pre-wrap" fontFamily="indic" fontSize="19px" lineHeight="2">
                  {chunk.edited_text ?? chunk.translated_text ?? '(not translated yet)'}
                </Text>
                <Text whiteSpace="pre-wrap" fontFamily="tamil" fontSize="14px" color="gray.500" mt={2}>
                  {chunk.source_text}
                </Text>
              </Box>
            ))}
          </ModalBody>
        </ModalContent>
      </Modal>
    </Box>
  )
}
