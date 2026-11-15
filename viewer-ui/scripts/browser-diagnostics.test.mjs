import assert from 'node:assert/strict'
import { test } from 'node:test'

import { browserMetadata } from '../e2e/browser-diagnostics.ts'

/** @returns {Parameters<typeof browserMetadata>[0]} */
function browserWithGraphics() {
  return {
    version: () => '153.0.8010.12',
    newBrowserCDPSession: async () => ({
      send: async () => ({
        commandLine:
          '/private/profile/browser --headless --use-angle=swiftshader-webgl --proxy-server=https://user:secret@example.test --user-data-dir=/private/profile --use-gl=secret --disable-gpu=secret',
        gpu: {
          devices: [
            {
              vendorId: 65535,
              deviceId: 65535,
              vendorString: 'Google',
              deviceString: 'SwiftShader',
              driverVendor: 'SwANGLE',
              driverVersion: '5.0.0',
              unrelated: { credential: 'secret' },
            },
          ],
          auxAttributes: {
            displayType: 'ANGLE_SWIFTSHADER',
            inProcessGpu: false,
            targetCpuBits: 64,
            glVendor: { credential: 'secret' },
            secret: 'secret',
          },
          featureStatus: {
            gpu_compositing: 'disabled_software',
            webgl: ['secret'],
            arbitrary: 'secret',
          },
        },
      }),
      detach: async () => {},
    }),
  }
}

await test('browser diagnostics retain renderer evidence while omitting credentials and unrelated fields', async () => {
  const result = await browserMetadata(browserWithGraphics(), 'chromium')
  assert.equal(result.graphics.status, 'available')
  assert.ok('launchFlags' in result.graphics)
  assert.deepEqual(result.graphics.launchFlags, ['--headless', '--use-angle=swiftshader-webgl'])
  assert.deepEqual(result.graphics.attributes, {
    displayType: 'ANGLE_SWIFTSHADER',
    inProcessGpu: false,
    targetCpuBits: 64,
  })
  assert.deepEqual(result.graphics.features, { gpu_compositing: 'disabled_software' })
  assert.equal(result.graphics.devices[0]?.driverVendor, 'SwANGLE')
  assert.equal(result.graphics.sessionDetached, true)
  assert.ok(result.runtime.logicalCpuCount > 0)
  assert.doesNotMatch(JSON.stringify(result), /secret|private\/profile|example\.test/)
})

await test('Firefox records its version without attempting Chromium GPU APIs', async () => {
  const result = await browserMetadata(
    {
      version: () => '155.0',
      newBrowserCDPSession: () => {
        throw new Error('Chromium API must not run for Firefox')
      },
    },
    'firefox',
  )
  assert.deepEqual(result.browser, { name: 'firefox', version: '155.0' })
  assert.deepEqual(result.graphics, {
    status: 'unavailable',
    reason: 'unsupported-browser',
    sessionDetached: null,
  })
})

await test('failed GPU collection releases its session without retaining raw protocol errors', async () => {
  let detached = false
  const result = await browserMetadata(
    {
      version: () => '153.0.8010.12',
      newBrowserCDPSession: async () => ({
        send: () => {
          throw new Error('Protocol failure: https://user:secret@example.test')
        },
        detach: async () => {
          detached = true
        },
      }),
    },
    'chromium',
  )
  assert.equal(detached, true)
  assert.deepEqual(result.graphics, {
    status: 'unavailable',
    reason: 'cdp-request-failed',
    sessionDetached: true,
  })
  assert.doesNotMatch(JSON.stringify(result), /secret|example\.test/)
})

await test('unavailable CDP sessions produce an explicit diagnostic status', async () => {
  const result = await browserMetadata(
    {
      version: () => '153.0.8010.12',
      newBrowserCDPSession: async () => {
        throw new Error('private connection details')
      },
    },
    'chromium',
  )
  assert.deepEqual(result.graphics, {
    status: 'unavailable',
    reason: 'cdp-request-failed',
    sessionDetached: null,
  })
  assert.doesNotMatch(JSON.stringify(result), /private connection/)
})

await test('session detach failure is visible without discarding collected graphics metadata', async () => {
  const browser = browserWithGraphics()
  const session = await browser.newBrowserCDPSession()
  session.detach = async () => {
    throw new Error('private connection details')
  }
  browser.newBrowserCDPSession = async () => session
  const result = await browserMetadata(browser, 'chromium')
  assert.equal(result.graphics.status, 'available')
  assert.equal(result.graphics.sessionDetached, false)
  assert.doesNotMatch(JSON.stringify(result), /private connection/)
})
