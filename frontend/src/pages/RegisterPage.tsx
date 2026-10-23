import { useState } from 'react'
import type { FormEvent } from 'react'
import { Alert, AlertIcon, Button, FormControl, FormHelperText, FormLabel, Input, Stack } from '@chakra-ui/react'
import { api } from '../api'
import AuthCard from '../components/AuthCard'
import { errorMessage } from '../hooks/useAsync'

export default function RegisterPage() {
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [repeat, setRepeat] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (password !== repeat) return setError('The two passwords are not the same.')
    setBusy(true)
    setError(null)
    try {
      const answer = await api.register({ username, email, password })
      setDone(answer.message)
      setPassword('')
      setRepeat('')
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  if (done !== null) {
    return (
      <AuthCard title="Account created" intro="Welcome to PathippuAI.">
        <Alert status="success">
          <AlertIcon />
          {done}
        </Alert>
      </AuthCard>
    )
  }

  return (
    <AuthCard title="Create an account" intro="Choose a username and password. You can sign in straight away.">
      <form onSubmit={submit}>
        <Stack spacing={4}>
          <FormControl isRequired>
            <FormLabel>Username</FormLabel>
            <Input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" autoFocus />
            <FormHelperText>3–64 letters, digits or . _ @ -</FormHelperText>
          </FormControl>
          <FormControl isRequired>
            <FormLabel>Email</FormLabel>
            <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" />
            <FormHelperText>Used only to send you a link if you forget your password.</FormHelperText>
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
            <Input type="password" value={repeat} onChange={(e) => setRepeat(e.target.value)} autoComplete="new-password" />
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
    </AuthCard>
  )
}
