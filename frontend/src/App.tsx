import { lazy, Suspense } from 'react'
import { Route, Routes } from 'react-router'
import { WakingNotice } from './components/WakingNotice'
import Login from './pages/Login'
import { HomeRedirect, RequireAuth } from './routes'

// Pages load on demand: a donor opening a registry link shouldn't download AG Grid or Bryntum.
const Aid = lazy(() => import('./pages/Aid'))
const Books = lazy(() => import('./pages/Books'))
const BusinessesReview = lazy(() => import('./pages/BusinessesReview'))
const ClaimView = lazy(() => import('./pages/ClaimView'))
const ConnectPayPalReturn = lazy(() => import('./pages/ConnectPayPalReturn'))
const Disputes = lazy(() => import('./pages/Disputes'))
const Legal = lazy(() => import('./pages/Legal'))
const BusinessHome = lazy(() => import('./pages/BusinessHome'))
const CommandCenter = lazy(() => import('./pages/CommandCenter'))
const ComingSoon = lazy(() => import('./pages/ComingSoon'))
const ContractorPortal = lazy(() => import('./pages/ContractorPortal'))
const GiftCardView = lazy(() => import('./pages/GiftCardView'))
const Giving = lazy(() => import('./pages/Giving'))
const HouseholdHome = lazy(() => import('./pages/HouseholdHome'))
const Insurance = lazy(() => import('./pages/Insurance'))
const Inventory = lazy(() => import('./pages/Inventory'))
const Money = lazy(() => import('./pages/Money'))
const PaymentReturn = lazy(() => import('./pages/PaymentReturn'))
const PriceWatch = lazy(() => import('./pages/PriceWatch'))
const Rebuild = lazy(() => import('./pages/Rebuild'))
const RegistryManage = lazy(() => import('./pages/RegistryManage'))
const RegistryPublic = lazy(() => import('./pages/RegistryPublic'))
const ReopenPublic = lazy(() => import('./pages/ReopenPublic'))
const ReviewCase = lazy(() => import('./pages/ReviewCase'))
const ReviewQueue = lazy(() => import('./pages/ReviewQueue'))
const ReviewCalendar = lazy(() => import('./pages/ReviewCalendar'))
const ReviewBoard = lazy(() => import('./pages/ReviewBoard'))
const CrewSchedule = lazy(() => import('./pages/CrewSchedule'))
const STAFF = ['reviewer', 'supervisor', 'org_admin'] as const
const loading = <div className="h-96 animate-pulse rounded-xl bg-sunken" />

export default function App() {
  return (
    <>
      <WakingNotice />
      <Suspense fallback={<div className="min-h-svh" />}>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/r/:slug" element={<RegistryPublic />} />
          <Route path="/reopen/:slug" element={<ReopenPublic />} />
          <Route path="/card/:code" element={<GiftCardView />} />
          <Route path="/price-watch" element={<PriceWatch />} />
          <Route path="/paid" element={<PaymentReturn />} />
          <Route path="/claim/:token" element={<ClaimView />} />
          <Route path="/privacy" element={<Legal doc="privacy" />} />
          <Route path="/terms" element={<Legal doc="terms" />} />
          <Route
            path="/connect/paypal"
            element={
              <RequireAuth role={['household', 'contractor', 'business']}>
                <ConnectPayPalReturn />
              </RequireAuth>
            }
          />
          <Route
            path="/giving"
            element={
              <RequireAuth role="donor" wide>
                <Giving />
              </RequireAuth>
            }
          />
          <Route
            path="/business"
            element={
              <RequireAuth role="business" wide>
                <BusinessHome />
              </RequireAuth>
            }
          />
          <Route
            path="/command/books"
            element={
              <RequireAuth role={['org_admin', 'supervisor']} wide>
                <Books />
              </RequireAuth>
            }
          />
          <Route
            path="/command/disputes"
            element={
              <RequireAuth role={['org_admin', 'supervisor']} wide>
                <Disputes />
              </RequireAuth>
            }
          />
          <Route
            path="/command/businesses"
            element={
              <RequireAuth role={['org_admin', 'supervisor']} wide>
                <BusinessesReview />
              </RequireAuth>
            }
          />
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
            path="/insurance"
            element={
              <RequireAuth role="household">
                <Insurance />
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
            path="/command/crews"
            element={
              <RequireAuth role={['org_admin', 'supervisor']} wide>
                <Suspense fallback={loading}>
                  <CrewSchedule />
                </Suspense>
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
      </Suspense>
    </>
  )
}
