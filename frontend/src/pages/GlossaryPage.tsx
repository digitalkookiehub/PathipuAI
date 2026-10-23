import { useCallback, useEffect, useState } from 'react'
import {
  Alert,
  AlertIcon,
  Badge,
  Box,
  Button,
  Checkbox,
  Flex,
  FormControl,
  FormHelperText,
  FormLabel,
  Heading,
  Input,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalOverlay,
  SimpleGrid,
  Spinner,
  Stack,
  Text,
  Textarea,
  useDisclosure,
  useToast,
} from '@chakra-ui/react'
import { useParams } from 'react-router-dom'
import { api } from '../api'
import { errorMessage, useAsync } from '../hooks/useAsync'
import type { GlossaryTerm, GlossaryTermInput, Language } from '../types'

const EMPTY: GlossaryTermInput = {
  source_term: '',
  explanation: '',
  author_notes: '',
  keep_unchanged: false,
  translations: {},
}

interface TermFormProps {
  isOpen: boolean
  onClose: () => void
  editing: GlossaryTerm | null
  targetLanguages: Language[]
  onSave: (input: GlossaryTermInput) => Promise<void>
}

function TermForm({ isOpen, onClose, editing, targetLanguages, onSave }: TermFormProps) {
  const [form, setForm] = useState<GlossaryTermInput>(EMPTY)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (isOpen) setForm(editing === null ? EMPTY : { ...editing })
  }, [isOpen, editing])

  const submit = async () => {
    setSaving(true)
    try {
      await onSave(form)
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal isOpen={isOpen} onClose={onClose} size="2xl" scrollBehavior="inside">
      <ModalOverlay />
      <ModalContent>
        <ModalHeader>{editing === null ? 'Add a term' : 'Edit the term'}</ModalHeader>
        <ModalCloseButton />
        <ModalBody>
          <Stack spacing={4}>
            <FormControl isRequired>
              <FormLabel>Term (as written in the book)</FormLabel>
              <Input
                value={form.source_term}
                onChange={(e) => setForm({ ...form, source_term: e.target.value })}
                fontFamily="tamil"
                fontSize="18px"
              />
            </FormControl>
            <Checkbox
              isChecked={form.keep_unchanged}
              onChange={(e) => setForm({ ...form, keep_unchanged: e.target.checked })}
            >
              Keep this term unchanged in every translation (for example a mantra or a sacred name)
            </Checkbox>
            <FormControl>
              <FormLabel>What it means (optional)</FormLabel>
              <Textarea
                value={form.explanation}
                onChange={(e) => setForm({ ...form, explanation: e.target.value })}
                fontFamily="tamil"
              />
            </FormControl>
            <FormControl>
              <FormLabel>Your notes (optional)</FormLabel>
              <Textarea
                value={form.author_notes}
                onChange={(e) => setForm({ ...form, author_notes: e.target.value })}
                fontFamily="tamil"
              />
            </FormControl>
            <Box>
              <Heading size="xs" mb={2}>
                Preferred wording in each language (optional)
              </Heading>
              <SimpleGrid columns={{ base: 1, md: 2 }} spacing={3}>
                {targetLanguages.map((language) => (
                  <FormControl key={language.code}>
                    <FormLabel>{language.name}</FormLabel>
                    <Input
                      value={form.translations[language.code] ?? ''}
                      onChange={(e) =>
                        setForm({ ...form, translations: { ...form.translations, [language.code]: e.target.value } })
                      }
                      fontFamily="tamil"
                    />
                  </FormControl>
                ))}
              </SimpleGrid>
              <FormHelperText>Leave a language empty to let the translation decide.</FormHelperText>
            </Box>
          </Stack>
        </ModalBody>
        <ModalFooter>
          <Button variant="ghost" mr={3} onClick={onClose}>
            Cancel
          </Button>
          <Button colorScheme="blue" onClick={() => void submit()} isLoading={saving}>
            Save term
          </Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  )
}

export default function GlossaryPage() {
  const bookId = Number(useParams().bookId)
  const toast = useToast()
  const loadBook = useCallback(() => api.book(bookId), [bookId])
  const { data: book, error: bookError } = useAsync(loadBook)
  const loadLanguages = useCallback(() => api.languages(), [])
  const { data: languages } = useAsync(loadLanguages)
  const loadTerms = useCallback(() => api.glossary(bookId), [bookId])
  const { data: terms, error: termsError, reload } = useAsync(loadTerms)

  const [editing, setEditing] = useState<GlossaryTerm | null>(null)
  const { isOpen, onOpen, onClose } = useDisclosure()

  const failure = bookError ?? termsError
  if (failure !== null) {
    return (
      <Alert status="error">
        <AlertIcon />
        {failure}
      </Alert>
    )
  }
  if (book === null || terms === null) return <Spinner />

  const names = new Map((languages ?? []).map((language) => [language.code, language.name]))
  const targetLanguages = (languages ?? []).filter((language) => language.code !== book.source_language)

  const openForm = (term: GlossaryTerm | null) => {
    setEditing(term)
    onOpen()
  }

  const save = async (input: GlossaryTermInput) => {
    try {
      if (editing === null) await api.addTerm(bookId, input)
      else await api.updateTerm(bookId, editing.id, input)
      toast({ title: 'Term saved.', status: 'success', duration: 1500 })
      onClose()
      reload()
    } catch (err) {
      toast({ title: errorMessage(err), status: 'error' })
    }
  }

  const remove = async (term: GlossaryTerm) => {
    if (!window.confirm(`Remove “${term.source_term}” from the glossary?`)) return
    try {
      await api.deleteTerm(bookId, term.id)
      reload()
    } catch (err) {
      toast({ title: errorMessage(err), status: 'error' })
    }
  }

  return (
    <Box maxW="1000px">
      <Flex justify="space-between" align="start" mb={4} gap={3} wrap="wrap">
        <Box>
          <Heading size="lg" fontFamily="tamil">
            {book.title}
          </Heading>
          <Text color="gray.600">
            Terms that must be translated the way you want, or not translated at all. The translation step follows
            this list.
          </Text>
        </Box>
        <Button colorScheme="blue" onClick={() => openForm(null)}>
          Add a term
        </Button>
      </Flex>

      {terms.length === 0 && (
        <Alert status="info">
          <AlertIcon />
          No terms yet. Add mantras, sacred names, Sanskrit words and other terms you want handled with care.
        </Alert>
      )}

      <Stack spacing={3}>
        {terms.map((term) => (
          <Box key={term.id} bg="white" borderWidth="1px" borderRadius="lg" p={4}>
            <Flex justify="space-between" align="start" gap={3} wrap="wrap">
              <Box>
                <Heading size="md" fontFamily="tamil">
                  {term.source_term}
                </Heading>
                {term.keep_unchanged && (
                  <Badge colorScheme="orange" mt={1}>
                    Keep unchanged
                  </Badge>
                )}
              </Box>
              <Flex gap={2}>
                <Button size="sm" variant="outline" onClick={() => openForm(term)}>
                  Edit
                </Button>
                <Button size="sm" variant="ghost" colorScheme="red" onClick={() => void remove(term)}>
                  Remove
                </Button>
              </Flex>
            </Flex>
            {term.explanation !== '' && (
              <Text mt={2} fontFamily="tamil">
                {term.explanation}
              </Text>
            )}
            {Object.keys(term.translations).length > 0 && (
              <Flex mt={2} gap={4} wrap="wrap">
                {Object.entries(term.translations).map(([code, value]) => (
                  <Text key={code} fontSize="sm">
                    <Text as="span" color="gray.600">
                      {names.get(code) ?? code}:
                    </Text>{' '}
                    <Text as="span" fontFamily="tamil">
                      {value}
                    </Text>
                  </Text>
                ))}
              </Flex>
            )}
            {term.author_notes !== '' && (
              <Text mt={2} fontSize="sm" color="gray.600" fontFamily="tamil">
                Note: {term.author_notes}
              </Text>
            )}
          </Box>
        ))}
      </Stack>

      <TermForm isOpen={isOpen} onClose={onClose} editing={editing} targetLanguages={targetLanguages} onSave={save} />
    </Box>
  )
}
