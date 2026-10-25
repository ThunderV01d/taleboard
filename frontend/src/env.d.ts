interface ImportMetaEnv {
  /** Base URL of the TaleBoard API, eg:- https://xxxx.execute-api.eu-west-2.amazonaws.com */
  readonly VITE_API_URL: string
  /** Cognito user pool ID, eg:- eu-west-2_AbCdEf123 (the stack's UserPoolId output) */
  readonly VITE_COGNITO_USER_POOL_ID: string
  /** Cognito app client ID (the stack's UserPoolClientId output) */
  readonly VITE_COGNITO_CLIENT_ID: string
  /** Cognito's domain, without https:// (the stack's AuthDomain output), eg:- name.auth.eu-west-2.amazoncognito.com */
  readonly VITE_COGNITO_DOMAIN: string
}
