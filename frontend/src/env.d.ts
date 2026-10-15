interface ImportMetaEnv {
  /** Base URL of the TaleBoard API, eg:- https://xxxx.execute-api.eu-west-2.amazonaws.com */
  readonly VITE_API_URL: string
  /** Shared API key, sent as X-API-Key. Ends up in the built bundle by design -- a cost guard, not a secret */
  readonly VITE_API_KEY: string
}
