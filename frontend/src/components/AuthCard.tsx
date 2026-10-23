import type { ReactNode } from 'react'
import { Box, Center, Heading, Link, Text } from '@chakra-ui/react'
import { Link as RouterLink } from 'react-router-dom'

interface Props {
  title: string
  intro: string
  children: ReactNode
  /** show "Back to sign in" under the card */
  backLink?: boolean
}

/** The centred card used by the sign-in, sign-up and password pages. */
export default function AuthCard({ title, intro, children, backLink = true }: Props) {
  return (
    <Center minH="100vh" px={4}>
      <Box bg="white" borderWidth="1px" borderRadius="lg" p={8} w="100%" maxW="460px">
        <Heading size="lg" color="blue.700" mb={1}>
          {title}
        </Heading>
        <Text color="gray.600" mb={5}>
          {intro}
        </Text>
        {children}
        {backLink && (
          <Text fontSize="sm" mt={5}>
            <Link as={RouterLink} to="/" color="blue.600">
              ← Back to sign in
            </Link>
          </Text>
        )}
      </Box>
    </Center>
  )
}
