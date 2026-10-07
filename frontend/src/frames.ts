/** Splits a walkthrough video into evenly spaced JPEG frames on the user's device, so only
 *  still images are uploaded (small, and the server needs no video tooling). */
export async function extractFrames(file: File, maxFrames: number, maxEdge = 1600): Promise<File[]> {
  const url = URL.createObjectURL(file)
  const video = document.createElement('video')
  video.muted = true
  video.playsInline = true
  video.preload = 'auto'
  video.src = url
  try {
    await new Promise<void>((resolve, reject) => {
      video.onloadeddata = () => resolve()
      video.onerror = () => reject(new Error('This video format cannot be read in this browser'))
    })
    const count = Math.max(1, Math.min(maxFrames, Math.floor(video.duration / 2)))
    const scale = Math.min(1, maxEdge / Math.max(video.videoWidth, video.videoHeight))
    const canvas = document.createElement('canvas')
    canvas.width = Math.round(video.videoWidth * scale)
    canvas.height = Math.round(video.videoHeight * scale)
    const ctx = canvas.getContext('2d')!
    const frames: File[] = []
    for (let i = 0; i < count; i++) {
      video.currentTime = ((i + 0.5) * video.duration) / count
      await new Promise((resolve) => (video.onseeked = resolve))
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height)
      const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/jpeg', 0.85))
      if (blob) frames.push(new File([blob], `${file.name}-frame-${i + 1}.jpg`, { type: 'image/jpeg' }))
    }
    return frames
  } finally {
    URL.revokeObjectURL(url)
  }
}
