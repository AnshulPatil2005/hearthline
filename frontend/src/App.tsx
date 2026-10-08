import { lazy, Suspense } from 'react'
import { Route, Routes } from 'react-router'
import Aid from './pages/Aid'
import CommandCenter from './pages/CommandCenter'
import ComingSoon from './pages/ComingSoon'
import ContractorPortal from './pages/ContractorPortal'
import HouseholdHome from './pages/HouseholdHome'
import Inventory from './pages/Inventory'
import Login from './pages/Login'
import Money from './pages/Money'
import Rebuild from './pages/Rebuild'
import RegistryManage from './pages/RegistryManage'
import RegistryPublic from './pages/RegistryPublic'
import ReviewCase from './pages/ReviewCase'
import ReviewQueue from './pages/ReviewQueue'
import { HomeRedirect, RequireAuth } from './routes'

// Bryntum components are large; load them only when a reviewer opens those pages.
const ReviewCalendar = lazy(() => import('./pages/ReviewCalendar'))
const ReviewBoard = lazy(() => import('./pages/ReviewBoard'))
const STAFF = ['reviewer', 'supervisor', 'org_admin'] as const
const loading = <div className="h-96 animate-pulse rounded-xl bg-sunken" />

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
        path="/aid"
        element={
          <RequireAuth role="household">
            <Aid />
          </RequireAuth>
        }
      />
      <Route
        path="/rebuild"
        element={
          <RequireAuth role="household" wide>
            <Rebuild />
          </RequireAuth>
        }
      />
      <Route
        path="/contractor"
        element={
          <RequireAuth role="contractor" wide>
            <ContractorPortal />
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
        path="/review"
        element={
          <RequireAuth role={['reviewer', 'supervisor', 'org_admin']} wide>
            <ReviewQueue />
          </RequireAuth>
        }
      />
      <Route
        path="/review/calendar"
        element={
          <RequireAuth role={[...STAFF]} wide>
            <Suspense fallback={loading}>
              <ReviewCalendar />
            </Suspense>
          </RequireAuth>
        }
      />
      <Route
        path="/review/board"
        element={
          <RequireAuth role={[...STAFF]} wide>
            <Suspense fallback={loading}>
              <ReviewBoard />
            </Suspense>
          </RequireAuth>
        }
      />
      <Route
        path="/command"
        element={
          <RequireAuth role={['org_admin', 'supervisor']} wide>
            <CommandCenter />
          </RequireAuth>
        }
      />
      <Route
        path="/review/cases/:id"
        element={
          <RequireAuth role={['reviewer', 'supervisor', 'org_admin']} wide>
            <ReviewCase />
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
