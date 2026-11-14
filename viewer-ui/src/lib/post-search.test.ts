/// <reference types="node" />
import { DatabaseSync } from 'node:sqlite'
import { describe, expect, it } from 'vitest'

import { findHits, markHits, searchWords, unmarkHits } from '@/lib/post-search'

function matched(text: string, query: string): string[] {
  return findHits(text, searchWords(query)).map((range) => text.slice(range.start, range.end))
}

describe('post search', () => {
  it.each([
    { text: 'ςσΣ', query: 'σ', matches: ['ςσΣ'] },
    { text: 'σςΣ', query: 'ς', matches: ['σςΣ'] },
    { text: 'ſearch search', query: 'search', matches: ['ſearch', 'search'] },
    { text: 'search', query: 'ſearch', matches: ['search'] },
    { text: 'µmicro μmicro', query: 'μ', matches: ['µmicro', 'μmicro'] },
    { text: 'ϐeta βeta', query: 'β', matches: ['ϐeta', 'βeta'] },
    { text: 'ϑeta θeta', query: 'θ', matches: ['ϑeta', 'θeta'] },
    { text: 'ϕi φi', query: 'φ', matches: ['ϕi', 'φi'] },
    { text: 'ϖi πi', query: 'π', matches: ['ϖi', 'πi'] },
    { text: 'ϰappa κappa', query: 'κ', matches: ['ϰappa', 'κappa'] },
    { text: 'ϱho ρho', query: 'ρ', matches: ['ϱho', 'ρho'] },
    { text: 'ϵpsilon εpsilon', query: 'ε', matches: ['ϵpsilon', 'εpsilon'] },
    { text: 'ẛearch ṡearch search', query: 'search', matches: ['ẛearch', 'ṡearch', 'search'] },
    { text: 'ιota ιota', query: 'ι', matches: ['ιota', 'ιota'] },
    { text: 'ßeta sseta', query: 'ss', matches: ['sseta'] },
    { text: 'ıota iota', query: 'i', matches: ['iota'] },
    { text: 'йод иод', query: 'и', matches: ['иод'] },
    { text: 'ﬃle ffile', query: 'ffi', matches: ['ffile'] },
    { text: 'ｆｉｌｅ file', query: 'file', matches: ['file'] },
  ])('matches the SQLite unicode61 oracle for $text / $query', ({ text, query, matches }) => {
    const database = new DatabaseSync(':memory:')
    try {
      database.exec(
        "CREATE VIRTUAL TABLE documents USING fts5(text, tokenize='unicode61 remove_diacritics 2')",
      )
      database.prepare('INSERT INTO documents(text) VALUES (?)').run(text)
      const result = database
        .prepare(
          "SELECT highlight(documents, 0, '[hit]', '[/hit]') AS marked FROM documents WHERE documents MATCH ?",
        )
        .get(`"${query}"*`)
      const marked = result?.marked
      expect(typeof marked).toBe('string')
      const sqliteMatches = String(marked).matchAll(/\[hit\]([\s\S]*?)\[\/hit\]/g)
      expect([...sqliteMatches].map((match) => match[1])).toEqual(matches)
      expect(matched(text, query)).toEqual(matches)
    } finally {
      database.close()
    }
  })
  it('matches literal whole-word prefixes with case, yo and Latin accent folding', () => {
    expect(matched('Всё о Caféine и шейдерах', 'все CAFE шейд')).toEqual([
      'Всё',
      'Caféine',
      'шейдерах',
    ])
    expect(matched('Мой и мои уроки', 'мои')).toEqual(['мои'])
    expect(matched('Café Cafe\u0301 CAFÉ', 'cafe\u0301')).toEqual(['Café', 'Cafe\u0301', 'CAFÉ'])
    expect(matched('Мо\u0301й урок', 'мой')).toEqual(['Мо\u0301й'])
  })

  it('uses separators and distinct prefix terms instead of interpreting query operators', () => {
    expect(searchWords('___ "Alpha_beta"* OR café CAFÉ')).toEqual(['alpha', 'beta', 'or', 'cafe'])
    expect(searchWords('...!?*"\u0301')).toEqual([])
    expect(searchWords('alpha\u034fbeta')).toEqual(['alpha', 'beta'])
    expect(searchWords('alpha\u20ddbeta')).toEqual(['alpha', 'beta'])
    expect(matched('Alpha_beta@Gamma', 'alpha beta gamma')).toEqual(['Alpha', 'beta', 'Gamma'])
    expect(matched('alphabet unrelated betatron', 'alpha\u093fbeta')).toEqual([
      'alphabet',
      'betatron',
    ])
  })

  it('keeps UTF-16 offsets and private-use tokens intact', () => {
    expect(matched('😀 café 𐐀bc \ue000lesson', 'cafe 𐐨 \ue000les')).toEqual([
      'café',
      '𐐀bc',
      '\ue000lesson',
    ])
  })

  it('marks a word across inline elements without joining neighboring blocks', () => {
    const root = document.createElement('div')
    root.innerHTML =
      '<p>Sha<strong>der</strong>s and <a href="/a/w/p/id">shader</a></p><p>sha</p><p>ders</p>'
    const link = root.querySelector('a')
    const strong = root.querySelector('strong')
    const hits = markHits(root, searchWords('shader'))
    expect(hits.map((hit) => hit.marks.map((mark) => mark.textContent).join(''))).toEqual([
      'Shaders',
      'shader',
    ])
    expect(hits[0].marks).toHaveLength(3)
    expect(root.querySelector('a')).toBe(link)
    expect(root.querySelector('strong')).toBe(strong)
    unmarkHits(root)
    expect(root.innerHTML).toBe(
      '<p>Sha<strong>der</strong>s and <a href="/a/w/p/id">shader</a></p><p>sha</p><p>ders</p>',
    )
  })

  it('skips generated labels and player fallback while including retained attachment titles', () => {
    const root = document.createElement('div')
    root.innerHTML =
      '<section class="removed-media"><h2 data-page-generated="true">shader</h2><p class="removed-media-note" data-page-generated="true">shader</p><a class="attachment"><span class="attachment-name">shader.zip</span></a><video>shader</video><audio>shader</audio><div class="resume-note">shader</div><button>shader</button></section>'
    const video = root.querySelector('video')
    expect(markHits(root, searchWords('shader'))).toHaveLength(1)
    expect(root.querySelector('mark')?.parentElement).toHaveClass('attachment-name')
    unmarkHits(root)
    expect(root.querySelector('video')).toBe(video)
    expect(root.querySelector('mark')).toBeNull()
  })

  it('replaces only its own marks on repeated searches', () => {
    const root = document.createElement('div')
    root.innerHTML = '<p>alpha alpha beta <mark>authored</mark></p>'
    expect(markHits(root, searchWords('alpha'))).toHaveLength(2)
    expect(markHits(root, searchWords('beta'))).toHaveLength(1)
    unmarkHits(root)
    expect(root.innerHTML).toBe('<p>alpha alpha beta <mark>authored</mark></p>')
  })
})
