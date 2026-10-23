import { useState } from 'react'
import type { FormEvent } from 'react'
import {
  Alert,
  AlertIcon,
  Box,
  Button,
  Center,
  Flex,
  FormControl,
  FormLabel,
  Heading,
  Input,
  Link,
  Stack,
  Text,
} from '@chakra-ui/react'
import { Link as RouterLink } from 'react-router-dom'
import { api } from '../api'
import { useAuth } from '../authState'
import { errorMessage } from '../hooks/useAsync'

export default function LoginPage() {
  const { refresh } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api.login(username, password)
      setPassword('')
      await refresh()
    } catch (err) {
      setError(errorMessage(err))
      setBusy(false)
    }
  }

  return (
    <Center minH="100vh" px={4}>
      <Box bg="white" borderWidth="1px" borderRadius="lg" p={8} w="100%" maxW="420px">
        <Heading size="lg" color="blue.700" mb={1}>
          PathippuAI
        </Heading>
        <Text color="gray.600" mb={5}>
          Please sign in to open your books.
        </Text>
        <form onSubmit={submit}>
          <Stack spacing={4}>
            <FormControl isRequired>
              <FormLabel>Username</FormLabel>
              <Input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" autoFocus />
            </FormControl>
            <FormControl isRequired>
              <FormLabel>Password</FormLabel>
              <Input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="current-password"
              />
            </FormControl>
            {error !== null && (
              <Alert status="error">
                <AlertIcon />
                {error}
              </Alert>
            )}
            <Button type="submit" colorScheme="blue" isLoading={busy} loadingText="Signing in…">
              Sign in
            </Button>
          </Stack>
        </form>
        <Flex justify="space-between" mt={5} fontSize="sm">
          <Link as={RouterLink} to="/forgot-password" color="blue.600">
            Forgot password?
          </Link>
          <Link as={RouterLink} to="/register" color="blue.600">
            Create an account
          </Link>
        </Flex>
      </Box>
    </Center>
  )
}
