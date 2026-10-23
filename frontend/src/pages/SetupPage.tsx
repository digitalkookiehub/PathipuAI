import { useState } from 'react'
import type { FormEvent } from 'react'
import {
  Alert,
  AlertIcon,
  Box,
  Button,
  Center,
  FormControl,
  FormHelperText,
  FormLabel,
  Heading,
  Input,
  Stack,
  Text,
} from '@chakra-ui/react'
import { api } from '../api'
import { useAuth } from '../authState'
import { errorMessage } from '../hooks/useAsync'

export default function SetupPage() {
  const { refresh } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [repeat, setRepeat] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (password !== repeat) return setError('The two passwords are not the same.')
    setBusy(true)
    setError(null)
    try {
      await api.setup(username, password)
      setPassword('')
      setRepeat('')
      await refresh()
    } catch (err) {
      setError(errorMessage(err))
      setBusy(false)
    }
  }

  return (
    <Center minH="100vh" px={4}>
      <Box bg="white" borderWidth="1px" borderRadius="lg" p={8} w="100%" maxW="460px">
        <Heading size="lg" color="blue.700" mb={1}>
          Welcome to PathippuAI
        </Heading>
        <Text color="gray.600" mb={5}>
          Create your account. Your books are private: only people who sign in can see them.
        </Text>
        <form onSubmit={submit}>
          <Stack spacing={4}>
            <FormControl isRequired>
              <FormLabel>Username</FormLabel>
              <Input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" autoFocus />
              <FormHelperText>3–64 letters, digits or . _ @ -</FormHelperText>
            </FormControl>
            <FormControl isRequired>
              <FormLabel>Password</FormLabel>
              <Input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="new-password"
              />
              <FormHelperText>At least 10 characters. A few words together make a strong password.</FormHelperText>
            </FormControl>
            <FormControl isRequired>
              <FormLabel>Type the password again</FormLabel>
              <Input
                type="password"
                value={repeat}
                onChange={(e) => setRepeat(e.target.value)}
                autoComplete="new-password"
              />
            </FormControl>
            {error !== null && (
              <Alert status="error">
                <AlertIcon />
                {error}
              </Alert>
            )}
            <Button type="submit" colorScheme="blue" isLoading={busy} loadingText="Creating…">
              Create my account
            </Button>
          </Stack>
        </form>
        <Text fontSize="sm" color="gray.500" mt={5}>
          This step only works on the computer that runs PathippuAI. On a server, create the first account with{' '}
          <code>python -m scripts.create_user YOUR-NAME</code>.
        </Text>
      </Box>
    </Center>
  )
}
