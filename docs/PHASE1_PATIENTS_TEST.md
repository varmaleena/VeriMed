# Patients slice

The owner approved a two-day AWS HealthLake test window, then recreation for recording.
This store contains AWS's Synthea preload and uses customer-managed KMS encryption.
Integrated NLP is disabled for this read-only patient view.
The current window expires November 20, 2026 at 18:34:54 IST (13:04:54 UTC); the teardown schedule is enabled.

1. Sign in at http://localhost:3000/login and choose Patients in the left navigation.
2. Expect live FHIR records with patient tokens, birth years, sex and source record identifiers.
3. At the table footer, expect ‹ 1–20 ›. The previous arrow is disabled on the first page. Choose the next arrow and verify the records change and the range becomes 21–40.
4. Choose the previous arrow to return to 1–20. Check both arrows with keyboard navigation. While loading, both are disabled; a failed read retains the current page and displays an error. Refresh starts from the first page. A total appears only when the live FHIR search supplies one.
5. Open Worklist and verify that its real encounter list still loads.
6. Sign out and open /patients. Expect a redirect to /login.
7. After the displayed test-window expiry, expect an inline closed-window message.

Names and direct patient identifiers from the FHIR payload are omitted from the response.
Tokens are derived from the cell tenant identifier and the FHIR resource identifier.
The API's IAM identity is limited to searching the configured datastore.
Its KMS decrypt/describe permissions are restricted to that datastore's encryption key and calls through HealthLake in the same account, as required by [AWS's encryption documentation](https://docs.aws.amazon.com/healthlake/latest/devguide/encryption-at-rest.html).
When deploying, supply `FHIR_KMS_KEY_ARN` and preserve `VERIMED_FHIR_EXPIRES_AT` as an ISO 8601 UTC string. PowerShell JSON date conversion must not localize this environment variable.
The direct Lambda live test verifies real FHIR reads, pagination and Verified Permissions denial. The human browser test additionally verifies the Cognito session path.

The expiry is displayed in IST. EventBridge Scheduler is configured to delete only CellFhirDemo using CloudFormation's stored execution role. The scheduled deletion is a future action and must be checked after the window ends.
The application checks the same expiry and returns HTTP 410 after it.
To recreate for recording, deploy a fresh CellFhirDemo with a new expiry and update the API's FHIR configuration from its outputs.
