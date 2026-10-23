import { useState } from 'react'
import type { FormEvent } from 'react'
import {
  Alert,
  AlertIcon,
  Button,
  FormControl,
  FormHelperText,
  FormLabel,
  Input,
  Modal,
  ModalBody,
  ModalCloseButton,
  ModalContent,
  ModalFooter,
  ModalHeader,
  ModalOverlay,
  Stack,
  useToast,
} from '@chakra-ui/react'
import { api } from '../api'
import { errorMessage } from '../hooks/useAsync'

interface Props {
  isOpen: boolean
  onClose: () => void
}

export default function ChangePasswordModal({ isOpen, onClose }: Props) {
  const toast = useToast()
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [repeat, setRepeat] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const close = () => {
    setCurrent('')
    setNext('')
    setRepeat('')
    setError(null)
    onClose()
  }

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (next !== repeat) return setError('The two new passwords are not the same.')
    setBusy(true)
    setError(null)
    try {
      await api.changePassword(current, next)
      toast({ title: 'Your password was changed. Other browsers were signed out.', status: 'success' })
      close()
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Modal isOpen={isOpen} onClose={close}>
      <ModalOverlay />
      <ModalContent as="form" onSubmit={submit}>
        <ModalHeader>Change password</ModalHeader>
        <ModalCloseButton />
        <ModalBody>
          <Stack spacing={4}>
            <FormControl isRequired>
              <FormLabel>Current password</FormLabel>
              <Input type="password" value={current} onChange={(e) => setCurrent(e.target.value)} autoComplete="current-password" />
            </FormControl>
            <FormControl isRequired>
              <FormLabel>New password</FormLabel>
              <Input type="password" value={next} onChange={(e) => setNext(e.target.value)} autoComplete="new-password" />
              <FormHelperText>At least 10 characters.</FormHelperText>
            </FormControl>
            <FormControl isRequired>
              <FormLabel>New password again</FormLabel>
              <Input type="password" value={repeat} onChange={(e) => setRepeat(e.target.value)} autoComplete="new-password" />
            </FormControl>
            {error !== null && (
              <Alert status="error">
                <AlertIcon />
                {error}
              </Alert>
            )}
          </Stack>
        </ModalBody>
        <ModalFooter>
          <Button variant="ghost" mr={3} onClick={close}>
            Cancel
          </Button>
          <Button type="submit" colorScheme="blue" isLoading={busy}>
            Change password
          </Button>
        </ModalFooter>
      </ModalContent>
    </Modal>
  )
}
