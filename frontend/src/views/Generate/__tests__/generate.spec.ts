// Экран генерации на мок-API (MSW в Node): показатели 1 и 4 карточки T11, а также поля формы,
// примерная цена, отправка multipart и показ ошибки генерации.
import { File as NodeFile } from 'node:buffer'
import { http, HttpResponse } from 'msw'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { VueWrapper } from '@vue/test-utils'
import { server } from '@/mocks/node'
import { db, saveSession } from '@/mocks/db'
import { mountApp, settle } from '@/__tests__/helpers'
import { resetBatches } from '../tracker'

const DESIGNER_ID = 2

// В jsdom FormData и File свои, а fetch — из Node (undici): multipart с jsdom-файлом undici не читает,
// а openapi-fetch не узнаёт FormData из Node. В браузере этого нет, поэтому только в тестах
// createGeneration отправляет ту же форму, переложенную в FormData/File из Node, напрямую через fetch.
vi.mock('@/api/client', async (importOriginal) => {
  const mod = await importOriginal<typeof import('@/api/client')>()
  return {
    ...mod,
    createGeneration: async (fd: FormData) => {
      const response = await fetch(`${location.origin}/api/generations`, { method: 'POST', body: await toNodeForm(fd) })
      const body: unknown = await response.json().catch(() => undefined)
      return mod.unwrap(Promise.resolve(response.ok ? { data: body as never, response } : { error: body, response }))
    },
  }
})

async function toNodeForm(fd: FormData): Promise<FormData> {
  const empty = '--b\r\nContent-Disposition: form-data; name="x"\r\n\r\n1\r\n--b--\r\n'
  const sample = await new Response(empty, { headers: { 'content-type': 'multipart/form-data; boundary=b' } }).formData()
  const NodeFormData = sample.constructor as typeof FormData
  const out = new NodeFormData()
  for (const [key, value] of fd.entries()) {
    if (typeof value === 'string') {
      out.append(key, value)
    } else {
      const buf = await new Promise<ArrayBuffer>((resolve) => {
        const reader = new FileReader()
        reader.onload = () => resolve(reader.result as ArrayBuffer)
        reader.readAsArrayBuffer(value)
      })
      out.append(key, new NodeFile([new Uint8Array(buf)], value.name, { type: value.type }) as unknown as File, value.name)
    }
  }
  return out
}

/** Все POST /api/generations, которые дошли до мок-API, с разобранным multipart. */
let posts: FormData[] = []

beforeEach(() => {
  saveSession(DESIGNER_ID)
  resetBatches()
  posts = []
  server.use(
    http.post('*/api/generations', async ({ request }) => {
      posts.push(await request.clone().formData())
      // без return — запрос идёт дальше в обычный обработчик мока
    }),
  )
})

let current: VueWrapper | null = null
afterEach(() => {
  current?.unmount()
  current = null
})

async function open(path = '/generate') {
  const res = await mountApp(path)
  current = res.wrapper
  return res
}

/** Маленький PNG; `size` подменяет размер, чтобы не создавать в тесте файлы по 20 МБ (такие не отправляются). */
function png(name: string, size?: number): File {
  const f = new File([new Uint8Array(8)], name, { type: 'image/png' })
  if (size !== undefined) Object.defineProperty(f, 'size', { value: size })
  return f
}

async function chooseFiles(wrapper: VueWrapper, files: File[]) {
  const input = wrapper.find('[data-testid="file-input"]')
  Object.defineProperty(input.element, 'files', { value: files, configurable: true })
  await input.trigger('change')
  await settle()
}

async function submit(wrapper: VueWrapper) {
  await wrapper.find('[data-testid="generate-form"]').trigger('submit')
  // ждём конца отправки: кнопка снова «Сгенерировать»
  await vi.waitFor(() => expect(wrapper.find('button[type="submit"]').text()).toBe('Сгенерировать'))
  await settle()
}

const select = (w: VueWrapper, id: string) => w.find(`#${id}`).element as HTMLSelectElement

describe('экран генерации: проверки перед отправкой (показатель 1)', () => {
  it('пустой промпт не отправляется', async () => {
    const { wrapper } = await open()
    await wrapper.find('#gen-prompt').setValue('   ')
    await submit(wrapper)
    expect(wrapper.find('[data-testid="form-error"]').text()).toBe('Введите промпт')
    expect(posts).toHaveLength(0)
  })

  it('промпт длиннее 4000 символов не отправляется, счётчик подсвечен', async () => {
    const { wrapper } = await open()
    await wrapper.find('#gen-prompt').setValue('а'.repeat(4001))
    expect(wrapper.find('[data-testid="prompt-counter"]').text()).toBe('4001 / 4000')
    expect(wrapper.find('[data-testid="prompt-counter"]').classes()).toContain('over')
    await submit(wrapper)
    expect(wrapper.find('[data-testid="form-error"]').text()).toBe('Промпт длиннее 4000 символов')
    expect(posts).toHaveLength(0)
  })

  it('промпт ровно 4000 символов отправляется', async () => {
    const { wrapper } = await open()
    await wrapper.find('#gen-prompt').setValue('а'.repeat(4000))
    await submit(wrapper)
    expect(posts).toHaveLength(1)
    expect(wrapper.find('[data-testid="form-error"]').exists()).toBe(false)
  })

  it('11-й файл отклоняется с сообщением', async () => {
    const { wrapper } = await open()
    await chooseFiles(wrapper, Array.from({ length: 10 }, (_, i) => png(`ref-${i + 1}.png`)))
    expect(wrapper.findAll('[data-testid="ref-item"]')).toHaveLength(10)
    expect(wrapper.find('[data-testid="ref-error"]').exists()).toBe(false)

    await chooseFiles(wrapper, [png('ref-11.png')])
    expect(wrapper.findAll('[data-testid="ref-item"]')).toHaveLength(10)
    expect(wrapper.find('[data-testid="ref-error"]').text()).toContain('не больше 10 референсов')
  })

  it('11-й за один выбор: первые 10 приняты, лишний отклонён', async () => {
    const { wrapper } = await open()
    await chooseFiles(wrapper, Array.from({ length: 11 }, (_, i) => png(`r${i}.png`)))
    expect(wrapper.findAll('[data-testid="ref-item"]')).toHaveLength(10)
    expect(wrapper.findAll('[data-testid="ref-error"]')).toHaveLength(1)
  })

  it('файл больше 20 МБ отклоняется с сообщением', async () => {
    const { wrapper } = await open()
    await chooseFiles(wrapper, [png('big.png', 20 * 1024 * 1024 + 1), png('ok.png', 20 * 1024 * 1024)])
    expect(wrapper.findAll('[data-testid="ref-item"]')).toHaveLength(1)
    expect(wrapper.find('[data-testid="ref-error"]').text()).toBe('«big.png» больше 20 МБ')
  })

  it('не картинка отклоняется', async () => {
    const { wrapper } = await open()
    await chooseFiles(wrapper, [new File(['x'], 'doc.pdf', { type: 'application/pdf' })])
    expect(wrapper.findAll('[data-testid="ref-item"]')).toHaveLength(0)
    expect(wrapper.find('[data-testid="ref-error"]').text()).toContain('PNG, JPEG и WebP')
  })

  it('референс можно убрать', async () => {
    const { wrapper } = await open()
    await chooseFiles(wrapper, [png('a.png'), png('b.png')])
    await wrapper.find('[data-testid="ref-item"] button').trigger('click')
    expect(wrapper.findAll('[data-testid="ref-item"]').map((r) => r.text())).toEqual([expect.stringContaining('b.png')])
  })
})

describe('экран генерации: поля формы и цена', () => {
  it('поля и значения по умолчанию из GET /api/models', async () => {
    const { wrapper } = await open()
    expect(select(wrapper, 'gen-model').value).toBe('gpt-image-2.5-sunburst')
    expect(select(wrapper, 'gen-quality').value).toBe('high')
    expect(select(wrapper, 'gen-format').value).toBe('jpeg')
    expect([...select(wrapper, 'gen-format').options].map((o) => o.text)).toEqual(['JPEG', 'PNG', 'WebP'])
    expect([...select(wrapper, 'gen-n').options].map((o) => o.value)).toEqual(['1', '2', '3', '4'])
    expect(wrapper.find('[data-testid="fidelity"]').exists()).toBe(true)
    expect((wrapper.find('#gen-fidelity').element as HTMLInputElement).checked).toBe(true)
    expect((wrapper.find('#gen-shared').element as HTMLInputElement).checked).toBe(true)
    expect(wrapper.find('[data-testid="mock-mode"]').exists()).toBe(true)
  })

  it('примерная цена = запасная цена × число вариантов', async () => {
    const { wrapper } = await open()
    expect(wrapper.find('[data-testid="price"]').text()).toBe('≈ 0,17\u00a0USD') // 167000 × 1
    await wrapper.find('#gen-n').setValue('3')
    expect(wrapper.find('[data-testid="price"]').text()).toBe('≈ 0,50\u00a0USD') // 167000 × 3
    await wrapper.find('#gen-quality').setValue('low')
    expect(wrapper.find('[data-testid="price"]').text()).toBe('≈ 0,03\u00a0USD') // 11000 × 3
  })

  it('модель без input_fidelity прячет переключатель, лишние варианты и форматы', async () => {
    const { wrapper } = await open()
    await wrapper.find('#gen-n').setValue('4')
    await wrapper.find('#gen-format').setValue('webp')
    await wrapper.find('#gen-model').setValue('gpt-image-1-mini')
    await settle()
    expect(wrapper.find('[data-testid="fidelity"]').exists()).toBe(false)
    expect([...select(wrapper, 'gen-n').options].map((o) => o.value)).toEqual(['1', '2'])
    expect(select(wrapper, 'gen-n').value).toBe('2')
    expect(select(wrapper, 'gen-format').value).toBe('jpeg')
    // «high» есть и у этой модели — качество сохраняется
    expect(select(wrapper, 'gen-quality').value).toBe('high')
    expect(wrapper.find('[data-testid="price"]').text()).toBe('≈ 0,07\u00a0USD') // 36000 × 2
  })

  it('запуск отправляет multipart с настройками и файлами и показывает варианты рядом', async () => {
    const { wrapper } = await open()
    await wrapper.find('#gen-prompt').setValue('Кресло с принтом')
    await wrapper.find('#gen-n').setValue('2')
    await wrapper.find('#gen-format').setValue('png')
    await wrapper.find('#gen-fidelity').setValue(false)
    await wrapper.find('#gen-shared').setValue(false)
    await chooseFiles(wrapper, [png('fabric.png')])
    await submit(wrapper)

    expect(posts).toHaveLength(1)
    const fd = posts[0]!
    expect(fd.get('prompt')).toBe('Кресло с принтом')
    expect(fd.get('model')).toBe('gpt-image-2.5-sunburst')
    expect(fd.get('quality')).toBe('high')
    expect(fd.get('n')).toBe('2')
    expect(fd.get('output_format')).toBe('png')
    expect(fd.get('input_fidelity')).toBe('low')
    expect(fd.get('shared')).toBe('false')
    expect((fd.getAll('files')[0] as File).name).toBe('fabric.png')
    expect(fd.getAll('source_ids')).toEqual([])

    const batch = wrapper.find('[data-testid="batch"]')
    expect(batch.findAll('[data-testid="variant"]')).toHaveLength(2)
    expect(batch.findAll('[data-testid="status"]').map((s) => s.text())).toEqual(['В очереди', 'В очереди'])
  })

  it('без референсов input_fidelity не отправляется', async () => {
    const { wrapper } = await open()
    await wrapper.find('#gen-prompt').setValue('Гостиная')
    await submit(wrapper)
    expect(posts[0]!.has('input_fidelity')).toBe(false)
  })

  it('ошибка сервера при запуске показывается текстом', async () => {
    server.use(
      http.post('*/api/generations', () =>
        HttpResponse.json({ detail: 'дневной бюджет сервиса исчерпан, обратитесь к администратору' }, { status: 429 }),
      ),
    )
    const { wrapper } = await open()
    await wrapper.find('#gen-prompt').setValue('Гостиная')
    await submit(wrapper)
    expect(wrapper.find('[data-testid="form-error"]').text()).toContain('дневной бюджет сервиса исчерпан')
  })

  it('генерация в статусе error показывает текст ошибки', async () => {
    server.use(
      http.get('*/api/generations/:id', ({ params }) => {
        const g = db.generations.find((x) => x.id === Number(params.id))!
        return HttpResponse.json({ ...g, status: 'error', error: 'Запрос отклонён модерацией OpenAI' })
      }),
    )
    const { wrapper } = await open()
    await wrapper.find('#gen-prompt').setValue('Гостиная')
    await submit(wrapper)
    await settle()
    expect(wrapper.find('[data-testid="status"]').text()).toBe('Ошибка')
    expect(wrapper.find('[data-testid="variant-error"]').text()).toBe('Запрос отклонён модерацией OpenAI')
  })
})

describe('экран генерации: «Повторить» и «Править дальше» (показатель 4)', () => {
  function tuneSeed() {
    const g = db.generations.find((x) => x.id === 2)!
    Object.assign(g, {
      prompt: 'Уменьшить рюши на шторах',
      model: 'gpt-image-1-mini',
      quality: 'low',
      size: '1536x1024',
      output_format: 'png',
      input_fidelity: null,
      shared: false,
    })
  }

  it('?repeat=ID восстанавливает промпт и параметры прошлой работы', async () => {
    tuneSeed()
    const { wrapper, router } = await open('/generate?repeat=2')
    expect((wrapper.find('#gen-prompt').element as HTMLTextAreaElement).value).toBe('Уменьшить рюши на шторах')
    expect(select(wrapper, 'gen-model').value).toBe('gpt-image-1-mini')
    expect(select(wrapper, 'gen-quality').value).toBe('low')
    expect(select(wrapper, 'gen-size').value).toBe('1536x1024')
    expect(select(wrapper, 'gen-format').value).toBe('png')
    expect((wrapper.find('#gen-shared').element as HTMLInputElement).checked).toBe(false)
    expect(wrapper.find('[data-testid="fidelity"]').exists()).toBe(false)
    // параметр убран из адреса, чтобы обновление страницы не затирало правки
    expect(router.currentRoute.value.query).toEqual({})
  })

  it('кнопка «Повторить» у готового результата восстанавливает промпт и параметры', async () => {
    // опрос сразу отвечает «готово», чтобы не ждать таймингов мока
    server.use(
      http.get('*/api/generations/:id', ({ params }) => {
        const g = db.generations.find((x) => x.id === Number(params.id))!
        return HttpResponse.json({ ...g, status: 'done' })
      }),
    )
    const { wrapper } = await open()
    await wrapper.find('#gen-prompt').setValue('Первый промпт')
    await wrapper.find('#gen-quality').setValue('medium')
    await wrapper.find('#gen-size').setValue('1024x1536')
    await wrapper.find('#gen-format').setValue('webp')
    await submit(wrapper)
    expect(wrapper.find('[data-testid="status"]').text()).toBe('Готово')

    await wrapper.find('#gen-prompt').setValue('Другое')
    await wrapper.find('#gen-quality').setValue('low')
    await wrapper.find('#gen-size').setValue('auto')
    await wrapper.find('#gen-format').setValue('jpeg')
    await wrapper.find('[data-testid="repeat"]').trigger('click')
    expect((wrapper.find('#gen-prompt').element as HTMLTextAreaElement).value).toBe('Первый промпт')
    expect(select(wrapper, 'gen-quality').value).toBe('medium')
    expect(select(wrapper, 'gen-size').value).toBe('1024x1536')
    expect(select(wrapper, 'gen-format').value).toBe('webp')
  })

  it('«Править дальше» у результата кладёт его в референсы', async () => {
    server.use(
      http.get('*/api/generations/:id', ({ params }) => {
        const g = db.generations.find((x) => x.id === Number(params.id))!
        return HttpResponse.json({ ...g, status: 'done' })
      }),
    )
    const { wrapper } = await open()
    await wrapper.find('#gen-prompt').setValue('Первый')
    await submit(wrapper)
    await wrapper.find('[data-testid="edit-further"]').trigger('click')
    expect(wrapper.findAll('[data-testid="ref-item"]')).toHaveLength(1)
    await submit(wrapper)
    expect(posts[1]!.getAll('source_ids')).toEqual(['4'])
    expect(posts[1]!.get('parent_id')).toBe('4')
  })

  it('?ref=ID кладёт работу в референсы, запуск отправляет source_ids и parent_id', async () => {
    const { wrapper } = await open('/generate?ref=1')
    expect(wrapper.findAll('[data-testid="ref-item"]')).toHaveLength(1)
    expect(wrapper.find('[data-testid="parent-note"]').text()).toContain('№1')
    await wrapper.find('#gen-prompt').setValue('Сделать стены светлее')
    await submit(wrapper)
    expect(posts[0]!.getAll('source_ids')).toEqual(['1'])
    expect(posts[0]!.get('parent_id')).toBe('1')
    expect(posts[0]!.get('input_fidelity')).toBe('high')
  })

  it('выбор из галереи добавляет работу без parent_id', async () => {
    const { wrapper } = await open()
    const btn = wrapper.findAll('button').find((b) => b.text() === 'Из галереи')!
    await btn.trigger('click')
    await settle()
    await wrapper.findAll('[data-testid="picker-item"]')[0]!.trigger('click')
    await wrapper.find('#gen-prompt').setValue('Новый вариант')
    await submit(wrapper)
    expect(posts[0]!.getAll('source_ids')).toHaveLength(1)
    expect(posts[0]!.has('parent_id')).toBe(false)
  })
})
