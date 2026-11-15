import type { OpenPostRequest } from './api.gen'

type Assert<T extends true> = T
type Rejects<T> = T extends OpenPostRequest ? false : true

export type OpenPostRequestChecks = [
  Assert<{} extends OpenPostRequest ? true : false>,
  Assert<Rejects<number>>,
  Assert<Rejects<string>>,
  Assert<Rejects<boolean>>,
  Assert<Rejects<null>>,
  Assert<Rejects<undefined>>,
  Assert<Rejects<[]>>,
  Assert<Rejects<{ reveal: boolean }>>,
]
