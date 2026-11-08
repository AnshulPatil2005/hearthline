import QRCode from 'qrcode'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { cardUrl, codeFrom } from '../reopen'

/** The card's link as a QR code. The business scans it at the counter; the buyer can open it to check the balance. */
export function GiftCardQr({ code, size = 180 }: { code: string; size?: number }) {
  const { t } = useTranslation()
  const [src, setSrc] = useState<string | null>(null)
  useEffect(() => {
    QRCode.toDataURL(cardUrl(code), { width: size * 2, margin: 1, errorCorrectionLevel: 'M' })
      .then(setSrc)
      .catch(() => setSrc(null))
  }, [code, size])
  return src ? (
    <img
      src={src}
      width={size}
      height={size}
      alt={t('reopen.card.qrAlt', { code })}
      className="rounded-lg bg-white p-2"
    />
  ) : (
    <div style={{ width: size, height: size }} className="animate-pulse rounded-lg bg-sunken" />
  )
}

type Detector = { detect(source: HTMLVideoElement): Promise<{ rawValue: string }[]> }
declare global {
  interface Window {
    BarcodeDetector?: new (options: { formats: string[] }) => Detector
  }
}

/** Reads a gift card QR code with the camera (Chrome, Edge and Android). Elsewhere the code is typed in. */
export function QrScanner({ onCode }: { onCode: (code: string) => void }) {
  const { t } = useTranslation()
  const video = useRef<HTMLVideoElement>(null)
  const [scanning, setScanning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const supported = typeof window !== 'undefined' && 'BarcodeDetector' in window

  useEffect(() => {
    if (!scanning) return
    let stream: MediaStream | null = null
    let frame = 0
    let stopped = false
    const detector = new window.BarcodeDetector!({ formats: ['qr_code'] })
    navigator.mediaDevices
      .getUserMedia({ video: { facingMode: 'environment' } })
      .then(async (s) => {
        stream = s
        if (!video.current || stopped) {
          s.getTracks().forEach((track) => track.stop()) // stopped while the permission prompt was open
          return
        }
        video.current.srcObject = s
        await video.current.play()
        const tick = async () => {
          if (stopped || !video.current) return
          const found = await detector.detect(video.current).catch(() => [])
          if (found[0]) {
            const value = found[0].rawValue
            onCode(codeFrom(value))
            setScanning(false)
            return
          }
          frame = requestAnimationFrame(tick)
        }
        frame = requestAnimationFrame(tick)
      })
      .catch(() => {
        setError(t('reopen.redeem.noCamera'))
        setScanning(false)
      })
    return () => {
      stopped = true
      cancelAnimationFrame(frame)
      stream?.getTracks().forEach((track) => track.stop())
    }
  }, [scanning, onCode, t])

  if (!supported) return null
  return (
    <div className="space-y-2">
      {scanning ? (
        <>
          <video ref={video} muted playsInline className="aspect-video w-full max-w-sm rounded-lg bg-black" />
          <button onClick={() => setScanning(false)} className="text-sm text-ink-soft hover:text-ink">
            {t('reopen.redeem.stopScan')}
          </button>
        </>
      ) : (
        <button
          onClick={() => {
            setError(null)
            setScanning(true)
          }}
          className="rounded-lg border border-line px-3 py-1.5 text-sm hover:bg-sunken"
        >
          {t('reopen.redeem.scan')}
        </button>
      )}
      {error && <p className="text-sm text-danger">{error}</p>}
    </div>
  )
}
