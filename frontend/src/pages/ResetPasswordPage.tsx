import { useState } from 'react'
import type { FormEvent } from 'react'
import { Alert, AlertIcon, Button, FormControl, FormHelperText, FormLabel, Input, Link, Stack } from '@chakra-ui/react'
import { Link as RouterLink, useSearchParams } from 'react-router-dom'
import { api } from '../api'
import { useAuth } from '../authState'
import AuthCard from '../components/AuthCard'
import { errorMessage } from '../hooks/useAsync'

export default function ResetPasswordPage() {
  const { refresh } = useAuth()
  const [params] = useSearchParams()
  const token = params.get('token') ?? ''
  const [password, setPassword] = useState('')
  const [repeat, setRepeat] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState(false)
  const [busy, setBusy] = useState(false)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (password !== repeat) return setError('The two passwords are not the same.')
    setBusy(true)
    setError(null)
    try {
      await api.resetPassword(token, password)
      setPassword('')
      setRepeat('')
      setDone(true)
      await refresh() // every browser was signed out, this one too
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  if (token === '') {
    return (
      <AuthCard title="Choose a new password" intro="This link is not complete.">
        <Alert status="warning">
          <AlertIcon />
          Please open the link from the email again, or ask for a new one.
        </Alert>
      </AuthCard>
    )
  }

  if (done) {
    return (
      <AuthCard title="Password changed" intro="You can sign in with your new password now." backLink={false}>
        <Button as={RouterLink} to="/" colorScheme="blue" w="100%">
          Sign in
        </Button>
      </AuthCard>
    )
  }

  return (
    <AuthCard title="Choose a new password" intro="After this, every browser signed in to your account is signed out.">
      <form onSubmit={submit}>
        <Stack spacing={4}>
          <FormControl isRequired>
            <FormLabel>New password</FormLabel>
            <Input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="new-password"
              autoFocus
            />
            <FormHelperText>At least 10 characters.</FormHelperText>
          </FormControl>
          <FormControl isRequired>
            <FormLabel>New password again</FormLabel>
            <Input type="password" value={repeat} onChange={(e) => setRepeat(e.target.value)} autoComplete="new-password" />
          </FormControl>
          {error !== null && (
            <Alert status="error">
              <AlertIcon />
              {error}{' '}
              {error.includes('expired') && (
                <Link as={RouterLink} to="/forgot-password" ml={1} fontWeight={600}>
                  Ask for a new link
                </Link>
              )}
            </Alert>
          )}
          <Button type="submit" colorScheme="blue" isLoading={busy} loadingText="Saving…">
            Save the new password
          </Button>
        </Stack>
      </form>
    </AuthCard>
  )
}
