import { useState } from 'react'
import type { FormEvent } from 'react'
import { Alert, AlertIcon, Button, FormControl, FormLabel, Input, Stack } from '@chakra-ui/react'
import { api } from '../api'
import { useAuth } from '../authState'
import AuthCard from '../components/AuthCard'
import { errorMessage } from '../hooks/useAsync'

export default function ForgotPasswordPage() {
  const { status } = useAuth()
  const [email, setEmail] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [done, setDone] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      setDone((await api.forgotPassword(email)).message)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  if (status !== null && !status.reset_available) {
    return (
      <AuthCard title="Forgot password" intro="Email is not set up on this server yet.">
        <Alert status="info">
          <AlertIcon />
          Please ask the owner to set a new password for you.
        </Alert>
      </AuthCard>
    )
  }

  return (
    <AuthCard title="Forgot password" intro="Enter the email address of your account. We will send you a link.">
      {done !== null ? (
        <Alert status="success">
          <AlertIcon />
          {done}
        </Alert>
      ) : (
        <form onSubmit={submit}>
          <Stack spacing={4}>
            <FormControl isRequired>
              <FormLabel>Email</FormLabel>
              <Input type="email" value={email} onChange={(e) => setEmail(e.target.value)} autoComplete="email" autoFocus />
            </FormControl>
            {error !== null && (
              <Alert status="error">
                <AlertIcon />
                {error}
              </Alert>
            )}
            <Button type="submit" colorScheme="blue" isLoading={busy} loadingText="Sending…">
              Send the link
            </Button>
          </Stack>
        </form>
      )}
    </AuthCard>
  )
}
