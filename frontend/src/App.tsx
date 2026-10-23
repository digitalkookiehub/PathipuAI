import { Center, Spinner } from '@chakra-ui/react'
import { Route, Routes } from 'react-router-dom'
import { useAuth } from './authState'
import BookLayout from './components/BookLayout'
import Layout from './components/Layout'
import AddBookPage from './pages/AddBookPage'
import ChaptersPage from './pages/ChaptersPage'
import DashboardPage from './pages/DashboardPage'
import GlossaryPage from './pages/GlossaryPage'
import LoginPage from './pages/LoginPage'
import OcrPage from './pages/OcrPage'
import PublishPage from './pages/PublishPage'
import ReviewPage from './pages/ReviewPage'
import SetupPage from './pages/SetupPage'
import TranslationPage from './pages/TranslationPage'
import TranslationReviewPage from './pages/TranslationReviewPage'

export default function App() {
  const { status } = useAuth()
  if (status === null) {
    return (
      <Center minH="100vh">
        <Spinner />
      </Center>
    )
  }
  if (status.auth_required && !status.authenticated) return status.setup_required ? <SetupPage /> : <LoginPage />
  return (
    <Routes>
      <Route element={<Layout />}>
        <Route index element={<DashboardPage />} />
        <Route path="books/new" element={<AddBookPage />} />
        <Route path="books/:bookId" element={<BookLayout />}>
          <Route path="ocr" element={<OcrPage />} />
          <Route path="review" element={<ReviewPage />} />
          <Route path="chapters" element={<ChaptersPage />} />
          <Route path="glossary" element={<GlossaryPage />} />
          <Route path="translate" element={<TranslationPage />} />
          <Route path="translation-review" element={<TranslationReviewPage />} />
          <Route path="publish" element={<PublishPage />} />
        </Route>
      </Route>
    </Routes>
  )
}
