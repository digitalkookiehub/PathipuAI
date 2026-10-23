import { Center, Spinner } from '@chakra-ui/react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { useAuth } from './authState'
import BookLayout from './components/BookLayout'
import Layout from './components/Layout'
import AccountsPage from './pages/AccountsPage'
import AddBookPage from './pages/AddBookPage'
import ChaptersPage from './pages/ChaptersPage'
import DashboardPage from './pages/DashboardPage'
import ForgotPasswordPage from './pages/ForgotPasswordPage'
import GlossaryPage from './pages/GlossaryPage'
import LoginPage from './pages/LoginPage'
import OcrPage from './pages/OcrPage'
import PublishPage from './pages/PublishPage'
import RegisterPage from './pages/RegisterPage'
import ResetPasswordPage from './pages/ResetPasswordPage'
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
  if (status.auth_required && !status.authenticated) {
    if (status.setup_required) return <SetupPage />
    return (
      <Routes>
        <Route path="register" element={<RegisterPage />} />
        <Route path="forgot-password" element={<ForgotPasswordPage />} />
        <Route path="reset-password" element={<ResetPasswordPage />} />
        <Route path="*" element={<LoginPage />} />
      </Routes>
    )
  }
  return (
    <Routes>
      <Route path="reset-password" element={<ResetPasswordPage />} />
      <Route path="register" element={<Navigate to="/" replace />} />
      <Route path="forgot-password" element={<Navigate to="/" replace />} />
      <Route element={<Layout />}>
        <Route index element={<DashboardPage />} />
        <Route path="books/new" element={<AddBookPage />} />
        {status.is_admin && <Route path="accounts" element={<AccountsPage />} />}
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
