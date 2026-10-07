import { Route, Routes } from 'react-router'
import ComingSoon from './pages/ComingSoon'
import HouseholdHome from './pages/HouseholdHome'
import Login from './pages/Login'
import { HomeRedirect, RequireAuth } from './routes'

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/home"
        element={
          <RequireAuth role="household">
            <HouseholdHome />
          </RequireAuth>
        }
      />
      <Route
        path="/workspace"
        element={
          <RequireAuth>
            <ComingSoon />
          </RequireAuth>
        }
      />
      <Route path="*" element={<HomeRedirect />} />
    </Routes>
  )
}
