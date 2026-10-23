import { useCallback, useState } from 'react'
import type { FormEvent } from 'react'
import {
  Alert,
  AlertIcon,
  Box,
  Button,
  FormControl,
  FormHelperText,
  FormLabel,
  Heading,
  Input,
  Select,
  Stack,
  Textarea,
} from '@chakra-ui/react'
import { useNavigate } from 'react-router-dom'
import { api } from '../api'
import { errorMessage, useAsync } from '../hooks/useAsync'

export default function AddBookPage() {
  const navigate = useNavigate()
  const loadLanguages = useCallback(() => api.languages(), [])
  const { data: languages } = useAsync(loadLanguages)

  const [title, setTitle] = useState('')
  const [author, setAuthor] = useState('')
  const [description, setDescription] = useState('')
  const [sourceLanguage, setSourceLanguage] = useState('ta')
  const [publicationDetails, setPublicationDetails] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (title.trim() === '') return setError('Please enter the book title.')
    if (file === null) return setError('Please choose your scanned PDF.')
    setSaving(true)
    setError(null)
    try {
      const book = await api.addBook({ title, author, description, sourceLanguage, publicationDetails, file })
      navigate(`/books/${book.id}/ocr`)
    } catch (err) {
      setError(errorMessage(err))
      setSaving(false)
    }
  }

  return (
    <Box maxW="720px" bg="white" borderWidth="1px" borderRadius="lg" p={6}>
      <Heading size="lg" mb={5}>
        Add a book
      </Heading>
      <form onSubmit={submit}>
        <Stack spacing={4}>
          <FormControl isRequired>
            <FormLabel>Book title</FormLabel>
            <Input value={title} onChange={(e) => setTitle(e.target.value)} fontFamily="tamil" />
          </FormControl>
          <FormControl>
            <FormLabel>Author name</FormLabel>
            <Input value={author} onChange={(e) => setAuthor(e.target.value)} fontFamily="tamil" />
          </FormControl>
          <FormControl>
            <FormLabel>Language of the book</FormLabel>
            <Select value={sourceLanguage} onChange={(e) => setSourceLanguage(e.target.value)}>
              {languages?.map((language) => (
                <option key={language.code} value={language.code}>
                  {language.name}
                </option>
              )) ?? <option value="ta">Tamil</option>}
            </Select>
          </FormControl>
          <FormControl>
            <FormLabel>Description (optional)</FormLabel>
            <Textarea value={description} onChange={(e) => setDescription(e.target.value)} fontFamily="tamil" />
          </FormControl>
          <FormControl>
            <FormLabel>Publication details (optional)</FormLabel>
            <Textarea
              value={publicationDetails}
              onChange={(e) => setPublicationDetails(e.target.value)}
              fontFamily="tamil"
            />
          </FormControl>
          <FormControl isRequired>
            <FormLabel>Scanned PDF</FormLabel>
            <Input
              type="file"
              accept="application/pdf,.pdf"
              p={1}
              onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            />
            <FormHelperText>A scanned PDF made with Adobe Scan works well.</FormHelperText>
          </FormControl>
          {error !== null && (
            <Alert status="error">
              <AlertIcon />
              {error}
            </Alert>
          )}
          <Button type="submit" colorScheme="blue" isLoading={saving} loadingText="Saving your book…">
            Save book
          </Button>
        </Stack>
      </form>
    </Box>
  )
}
