import type { Page } from '@playwright/test'

type Color = { red: number; green: number; blue: number; alpha: number }
type ContrastReading = { title: string; ratio: number }

export async function mediaContrast(page: Page): Promise<ContrastReading[]> {
  return page.evaluate(() => {
    const context = document.createElement('canvas').getContext('2d', { willReadFrequently: true })!
    const color = (css: string): Color => {
      context.clearRect(0, 0, 1, 1)
      context.fillStyle = css
      context.fillRect(0, 0, 1, 1)
      const pixel = context.getImageData(0, 0, 1, 1).data
      return { red: pixel[0]!, green: pixel[1]!, blue: pixel[2]!, alpha: pixel[3]! / 255 }
    }
    const blend = (front: Color, back: Color): Color => ({
      red: front.red * front.alpha + back.red * (1 - front.alpha),
      green: front.green * front.alpha + back.green * (1 - front.alpha),
      blue: front.blue * front.alpha + back.blue * (1 - front.alpha),
      alpha: 1,
    })
    const background = (element: Element): Color => {
      const chain: Element[] = []
      for (let current: Element | null = element; current; current = current.parentElement)
        chain.unshift(current)
      return chain.reduce(
        (back, current) => blend(color(getComputedStyle(current).backgroundColor), back),
        color('white'),
      )
    }
    const luminance = (value: Color): number => {
      const linear = (channel: number): number => {
        const fraction = channel / 255
        return fraction <= 0.04045 ? fraction / 12.92 : ((fraction + 0.055) / 1.055) ** 2.4
      }
      return linear(value.red) * 0.2126 + linear(value.green) * 0.7152 + linear(value.blue) * 0.0722
    }
    const ratio = (text: Color, back: Color): number => {
      const first = luminance(text)
      const second = luminance(back)
      return (Math.max(first, second) + 0.05) / (Math.min(first, second) + 0.05)
    }
    const readings: ContrastReading[] = []
    for (const title of document.querySelectorAll(
      '[data-file-list] [data-media-id] [title], [data-audio-list] [data-media-id] [title]',
    )) {
      if (!title.textContent?.trim()) continue
      const back = background(title)
      readings.push({
        title: title.textContent.trim(),
        ratio: ratio(blend(color(getComputedStyle(title).color), back), back),
      })
    }
    for (const tile of document.querySelectorAll('button[data-media-id][aria-label^="Play "]')) {
      const title = tile.querySelector('.line-clamp-2')
      const image = tile.querySelector('img')
      if (!title || !image) continue
      let alpha = 1
      for (
        let current: Element | null = image;
        current && current !== tile;
        current = current.parentElement
      )
        alpha *= Number(getComputedStyle(current).opacity)
      const back = blend({ ...color('white'), alpha }, background(tile))
      readings.push({
        title: title.textContent ?? '',
        ratio: ratio(color(getComputedStyle(title).color), back),
      })
    }
    return readings
  })
}
