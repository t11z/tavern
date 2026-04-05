import { useEffect, useState } from 'react'

type Breakpoint = 'mobile' | 'tablet' | 'desktop'

interface BreakpointState {
  isMobile: boolean
  isTablet: boolean
  isDesktop: boolean
  bp: Breakpoint
}

function classify(width: number): Breakpoint {
  if (width < 640) return 'mobile'
  if (width < 1024) return 'tablet'
  return 'desktop'
}

export function useBreakpoint(): BreakpointState {
  const [bp, setBp] = useState<Breakpoint>(() => classify(window.innerWidth))

  useEffect(() => {
    const handler = () => setBp(classify(window.innerWidth))
    window.addEventListener('resize', handler)
    return () => window.removeEventListener('resize', handler)
  }, [])

  return {
    isMobile: bp === 'mobile',
    isTablet: bp === 'tablet',
    isDesktop: bp === 'desktop',
    bp,
  }
}
