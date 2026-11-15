import { availableParallelism, cpus, release } from 'node:os'

type DiagnosticValue = string | number | boolean

type GraphicsDevice = {
  vendorId: number
  deviceId: number
  vendorString: string
  deviceString: string
  driverVendor: string
  driverVersion: string
}

type SystemInformation = {
  commandLine: string
  gpu: {
    devices: GraphicsDevice[]
    auxAttributes?: Record<string, unknown>
    featureStatus?: Record<string, unknown>
  }
}

type MetadataSession = {
  send(method: 'SystemInfo.getInfo'): Promise<SystemInformation>
  detach(): Promise<void>
}

type MetadataBrowser = {
  version(): string
  newBrowserCDPSession(): Promise<MetadataSession>
}

type GraphicsDiagnostics = {
  sessionDetached: boolean | null
} & (
  | {
      status: 'available'
      devices: GraphicsDevice[]
      attributes: Record<string, DiagnosticValue>
      features: Record<string, DiagnosticValue>
      launchFlags: string[]
    }
  | { status: 'unavailable'; reason: 'unsupported-browser' | 'cdp-request-failed' }
)

type BrowserMetadata = {
  browser: { name: string; version: string }
  runtime: {
    platform: string
    architecture: string
    osRelease: string
    nodeVersion: string
    logicalCpuCount: number
    availableParallelism: number
  }
  graphics: GraphicsDiagnostics
}

const GRAPHICS_ATTRIBUTES = [
  'displayType',
  'glImplementationParts',
  'glRenderer',
  'glVendor',
  'glVersion',
  'skiaBackendType',
  'targetCpuBits',
  'inProcessGpu',
] as const

const GRAPHICS_FEATURES = [
  '2d_canvas',
  'gpu_compositing',
  'rasterization',
  'multiple_raster_threads',
  'opengl',
  'video_decode',
  'video_encode',
  'webgl',
  'webgpu',
  'skia_graphite',
] as const

const LAUNCH_FLAGS = new Set([
  '--headless',
  '--headless=new',
  '--headless=old',
  '--disable-gpu',
  '--disable-gpu-compositing',
  '--disable-software-rasterizer',
  '--enable-unsafe-swiftshader',
  '--no-sandbox',
  '--disable-dev-shm-usage',
  '--disable-renderer-backgrounding',
  '--disable-background-timer-throttling',
  '--disable-backgrounding-occluded-windows',
  '--hide-scrollbars',
  '--force-color-profile=srgb',
  '--use-gl=angle',
  '--use-gl=egl',
  '--use-gl=desktop',
  '--use-gl=swiftshader',
  '--use-gl=disabled',
  '--use-angle=default',
  '--use-angle=metal',
  '--use-angle=gl',
  '--use-angle=vulkan',
  '--use-angle=d3d11',
  '--use-angle=swiftshader',
  '--use-angle=swiftshader-webgl',
])

function selectedValues(
  values: Record<string, unknown> | undefined,
  keys: readonly string[],
): Record<string, DiagnosticValue> {
  return Object.fromEntries(
    keys.flatMap((key) => {
      const value = values?.[key]
      if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean')
        return [[key, value]]
      return []
    }),
  )
}

async function chromiumGraphics(browser: MetadataBrowser): Promise<GraphicsDiagnostics> {
  let session: MetadataSession | undefined
  let diagnostics: GraphicsDiagnostics
  try {
    session = await browser.newBrowserCDPSession()
    const { commandLine, gpu } = await session.send('SystemInfo.getInfo')
    diagnostics = {
      status: 'available',
      sessionDetached: false,
      devices: gpu.devices.map((device) => ({
        vendorId: device.vendorId,
        deviceId: device.deviceId,
        vendorString: device.vendorString,
        deviceString: device.deviceString,
        driverVendor: device.driverVendor,
        driverVersion: device.driverVersion,
      })),
      attributes: selectedValues(gpu.auxAttributes, GRAPHICS_ATTRIBUTES),
      features: selectedValues(gpu.featureStatus, GRAPHICS_FEATURES),
      launchFlags: [...new Set(commandLine.split(/\s+/).filter((flag) => LAUNCH_FLAGS.has(flag)))],
    }
  } catch {
    // Protocol errors can include launch options; only the failure category is retained.
    diagnostics = { status: 'unavailable', reason: 'cdp-request-failed', sessionDetached: null }
  }
  if (session) {
    try {
      await session.detach()
      diagnostics.sessionDetached = true
    } catch {
      diagnostics.sessionDetached = false
    }
  }
  return diagnostics
}

export async function browserMetadata(
  browser: MetadataBrowser,
  browserName: string,
): Promise<BrowserMetadata> {
  return {
    browser: { name: browserName, version: browser.version() },
    runtime: {
      platform: process.platform,
      architecture: process.arch,
      osRelease: release(),
      nodeVersion: process.version,
      logicalCpuCount: cpus().length,
      availableParallelism: availableParallelism(),
    },
    graphics:
      browserName === 'chromium'
        ? await chromiumGraphics(browser)
        : {
            status: 'unavailable',
            reason: 'unsupported-browser',
            sessionDetached: null,
          },
  }
}
