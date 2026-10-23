import { useCallback, useEffect, useState } from 'react'
import {
  Alert,
  AlertIcon,
  Badge,
  Box,
  Button,
  Heading,
  HStack,
  Spinner,
  Table,
  TableContainer,
  Tbody,
  Td,
  Text,
  Th,
  Thead,
  Tr,
  useToast,
} from '@chakra-ui/react'
import { api } from '../api'
import type { Account, AccountStatus } from '../api'
import { useAuth } from '../authState'
import { errorMessage } from '../hooks/useAsync'

const STATUS_BADGE: Record<AccountStatus, { label: string; color: string }> = {
  pending: { label: 'Waiting for approval', color: 'orange' },
  active: { label: 'Active', color: 'green' },
  disabled: { label: 'Disabled', color: 'gray' },
}

export default function AccountsPage() {
  const { status } = useAuth()
  const toast = useToast()
  const [accounts, setAccounts] = useState<Account[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<number | null>(null)

  const load = useCallback(async () => {
    try {
      setAccounts(await api.accounts())
      setError(null)
    } catch (err) {
      setError(errorMessage(err))
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  const act = async (account: Account, action: () => Promise<unknown>, done: string) => {
    setBusyId(account.id)
    try {
      await action()
      toast({ title: done, status: 'success' })
      await load()
    } catch (err) {
      toast({ title: errorMessage(err), status: 'error' })
    } finally {
      setBusyId(null)
    }
  }

  const waiting = accounts?.filter((a) => a.status === 'pending').length ?? 0

  return (
    <Box>
      <Heading size="lg" mb={2}>
        Accounts
      </Heading>
      <Text color="gray.600" mb={5}>
        Everyone with an active account can see and change every book. Approve only people you know.
      </Text>
      {waiting > 0 && (
        <Alert status="warning" mb={4}>
          <AlertIcon />
          {waiting} account{waiting === 1 ? ' is' : 's are'} waiting for your approval.
        </Alert>
      )}
      {error !== null && (
        <Alert status="error" mb={4}>
          <AlertIcon />
          {error}
        </Alert>
      )}
      {accounts === null && error === null && <Spinner />}
      {accounts !== null && (
        <TableContainer bg="white" borderWidth="1px" borderRadius="lg">
          <Table size="sm">
            <Thead>
              <Tr>
                <Th>Username</Th>
                <Th>Email</Th>
                <Th>Status</Th>
                <Th>Role</Th>
                <Th>Created</Th>
                <Th textAlign="right">Actions</Th>
              </Tr>
            </Thead>
            <Tbody>
              {accounts.map((account) => {
                const me = account.username === status?.username
                const busy = busyId === account.id
                const badge = STATUS_BADGE[account.status]
                return (
                  <Tr key={account.id}>
                    <Td fontWeight={600}>
                      {account.username}
                      {me && (
                        <Text as="span" color="gray.500" fontWeight={400}>
                          {' '}
                          (you)
                        </Text>
                      )}
                    </Td>
                    <Td>{account.email ?? '—'}</Td>
                    <Td>
                      <Badge colorScheme={badge.color}>{badge.label}</Badge>
                    </Td>
                    <Td>{account.is_admin ? 'Owner' : 'User'}</Td>
                    <Td>{account.created_at.slice(0, 10)}</Td>
                    <Td>
                      <HStack justify="flex-end" spacing={2}>
                        {account.status !== 'active' && (
                          <Button
                            size="xs"
                            colorScheme="green"
                            isLoading={busy}
                            onClick={() =>
                              void act(account, () => api.approveAccount(account.id), `${account.username} can sign in now.`)
                            }
                          >
                            {account.status === 'pending' ? 'Approve' : 'Enable'}
                          </Button>
                        )}
                        {!me && account.status === 'active' && (
                          <Button
                            size="xs"
                            variant="outline"
                            isDisabled={busy}
                            onClick={() =>
                              void act(account, () => api.disableAccount(account.id), `${account.username} was disabled.`)
                            }
                          >
                            Disable
                          </Button>
                        )}
                        {!me && account.status === 'active' && (
                          <Button
                            size="xs"
                            variant="ghost"
                            isDisabled={busy}
                            onClick={() =>
                              void act(
                                account,
                                () => api.setOwner(account.id, !account.is_admin),
                                account.is_admin
                                  ? `${account.username} is a normal user now.`
                                  : `${account.username} is an owner now.`,
                              )
                            }
                          >
                            {account.is_admin ? 'Make user' : 'Make owner'}
                          </Button>
                        )}
                        {!me && (
                          <Button
                            size="xs"
                            colorScheme="red"
                            variant="ghost"
                            isDisabled={busy}
                            onClick={() =>
                              void act(account, () => api.removeAccount(account.id), `${account.username} was removed.`)
                            }
                          >
                            {account.status === 'pending' ? 'Reject' : 'Remove'}
                          </Button>
                        )}
                      </HStack>
                    </Td>
                  </Tr>
                )
              })}
            </Tbody>
          </Table>
        </TableContainer>
      )}
    </Box>
  )
}
