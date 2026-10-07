import { Route, Routes } from 'react-router'
import ComingSoon from './pages/ComingSoon'
import HouseholdHome from './pages/HouseholdHome'
import Inventory from './pages/Inventory'
import Login from './pages/Login'
import Money from './pages/Money'
import RegistryManage from './pages/RegistryManage'
import RegistryPublic from './pages/RegistryPublic'
import { HomeRedirect, RequireAuth } from './routes'

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/r/:slug" element={<RegistryPublic />} />
      <Route
        path="/registry"
        element={
          <RequireAuth role="household">
            <RegistryManage />
          </RequireAuth>
        }
      />
      <Route
        path="/home"
        element={
          <RequireAuth role="household">
            <HouseholdHome />
          </RequireAuth>
        }
      />
      <Route
        path="/inventory"
        element={
          <RequireAuth role="household" wide>
            <Inventory />
          </RequireAuth>
        }
      />
      <Route
        path="/money"
        element={
          <RequireAuth role="household" wide>
            <Money />
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
