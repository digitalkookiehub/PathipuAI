import { Box, Button, Container, Flex, Heading, Link, Spacer, Text, useDisclosure } from '@chakra-ui/react'
import { NavLink, Outlet } from 'react-router-dom'
import { useAuth } from '../authState'
import ChangePasswordModal from './ChangePasswordModal'

const navLinkStyle = { fontWeight: 600, px: 3, py: 2, borderRadius: 'md', _hover: { bg: 'blue.50' } }

export default function Layout() {
  const { status, signOut } = useAuth()
  const password = useDisclosure()
  const showAccount = status?.auth_required === true && status.authenticated

  return (
    <Box minH="100vh">
      <Box as="header" bg="white" borderBottomWidth="1px" py={3}>
        <Container maxW="1500px">
          <Flex align="center" gap={6}>
            <Heading size="md" color="blue.700">
              PathippuAI
            </Heading>
            <Link as={NavLink} to="/" end {...navLinkStyle} _activeLink={{ bg: 'blue.100' }}>
              My books
            </Link>
            <Link as={NavLink} to="/books/new" {...navLinkStyle} _activeLink={{ bg: 'blue.100' }}>
              Add a book
            </Link>
            {status?.is_admin === true && status.auth_required && (
              <Link as={NavLink} to="/accounts" {...navLinkStyle} _activeLink={{ bg: 'blue.100' }}>
                Accounts
              </Link>
            )}
            <Spacer />
            {showAccount && (
              <Flex align="center" gap={3}>
                <Text fontSize="sm" color="gray.600">
                  {status?.username}
                </Text>
                <Button size="sm" variant="ghost" onClick={password.onOpen}>
                  Change password
                </Button>
                <Button size="sm" variant="outline" onClick={() => void signOut()}>
                  Sign out
                </Button>
              </Flex>
            )}
          </Flex>
        </Container>
      </Box>
      <Container maxW="1500px" py={6}>
        <Outlet />
      </Container>
      <ChangePasswordModal isOpen={password.isOpen} onClose={password.onClose} />
    </Box>
  )
}
